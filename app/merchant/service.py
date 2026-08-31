from __future__ import annotations

import json
import re
import secrets
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from psycopg import sql
from psycopg.types.json import Jsonb

from .security import MerchantError, PERMISSIONS, cipher, hash_password, token_hash, verify_password


def now():
    return datetime.now(timezone.utc)


def email_address(value: Any) -> str:
    value = str(value or '').strip().lower()
    if len(value) > 254 or not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', value):
        raise MerchantError(422, 'INVALID_EMAIL', '请输入有效邮箱', {'email': '邮箱格式不正确'})
    return value


def username(value: Any) -> str:
    if not isinstance(value, str):
        raise MerchantError(422, 'INVALID_USERNAME', '请输入用户名', {'username': '用户名必填'})
    value = value.strip().lower()
    if not re.fullmatch(r'[a-z][a-z0-9_.-]{2,31}', value):
        raise MerchantError(422, 'INVALID_USERNAME', '用户名须为3至32位，以字母开头，仅含英文字母、数字、点、下划线或连字符', {'username': '用户名格式不正确'})
    return value


def text_field(data: dict, field: str, limit: int = 160, default: str | None = None) -> str:
    value = data.get(field, default)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise MerchantError(422, 'INVALID_FIELD', '请检查输入', {field: f'必填，最长{limit}个字符'})
    return value.strip()


def identifier(value: Any) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        raise MerchantError(404, 'NOT_FOUND', '资源不存在或无访问权限') from None


class MerchantService:
    def __init__(self, database, settings):
        self.database, self.settings = database, settings
        self._dummy_hash: str | None = None

    def enabled(self):
        if not self.settings.merchant_enabled:
            raise MerchantError(503, 'NOT_CONFIGURED', '客户服务尚未开放')

    def mail_ready(self):
        self.enabled()
        if not self.auth_config()['mailEnabled']:
            raise MerchantError(503, 'MAIL_UNAVAILABLE', '邮件服务尚未配置，暂不能发送验证或邀请邮件')
        cipher(self.settings.merchant_encryption_key)

    def auth_config(self):
        self.enabled()
        return {'registrationMode': self.settings.merchant_registration_mode,
                'passwordMinLength': 15, 'passwordMaxLength': 128,
                'usernamePattern': '^[a-z][a-z0-9_.-]{2,31}$',
                'mailEnabled': bool(self.settings.merchant_smtp_host and self.settings.merchant_mail_from
                                    and not self.settings.merchant_limited_release),
                'limitedRelease': self.settings.merchant_limited_release}

    def permissions(self, role):
        permissions = set(PERMISSIONS[role])
        if self.settings.merchant_limited_release:
            permissions -= {'devices.transfer', 'payments.manage', 'commands.execute'}
        return permissions

    def validate_runtime(self):
        if not self.settings.merchant_enabled:
            return
        cipher(self.settings.merchant_encryption_key)
        with self.database.connect() as c:
            c.execute('select username from merchant_user limit 0')
            c.execute(sql.SQL('set local role {}').format(sql.Identifier(self.settings.merchant_runtime_role)))
            row = c.execute('''select rolsuper,rolbypassrls,
                (select pg_get_userbyid(relowner)=current_user from pg_class where oid='merchant_store'::regclass) as owns
                from pg_roles where rolname=current_user''').fetchone()
            if row['rolsuper'] or row['rolbypassrls'] or row['owns']:
                raise RuntimeError('Unsafe merchant database role')
            c.execute('select id from merchant_store limit 0')

    def rate_limit(self, action: str, remote: str, email: str = ''):
        self.enabled()
        # Independent committed transaction: failed login rollbacks must not
        # erase the counters. No proxy-supplied address is trusted here.
        buckets = [(f'{action}:ip:{remote}', 20), (f'{action}:global', 120)]
        if email:
            buckets.append((f'{action}:email:{email}', 10))
        exceeded = False
        with self.database.connect() as c:
            for key, limit in buckets:
                row = c.execute("""insert into merchant_rate_limit(key,hits) values(%s,1)
                    on conflict(key) do update set
                    hits=case when merchant_rate_limit.window_start < now()-interval '10 minutes'
                              then 1 else merchant_rate_limit.hits+1 end,
                    window_start=case when merchant_rate_limit.window_start < now()-interval '10 minutes'
                                      then now() else merchant_rate_limit.window_start end returning hits""",
                    (token_hash(key),)).fetchone()
                exceeded |= row['hits'] > limit
        if exceeded:
            raise MerchantError(429, 'RATE_LIMITED', '操作过于频繁，请10分钟后重试')

    def _action(self, c, purpose: str, user_id, recipient: str, payload: dict, *, days=1):
        token = secrets.token_urlsafe(32)
        action = c.execute("""insert into merchant_email_action(token_hash,user_id,purpose,payload,expires_at)
            values(%s,%s,%s,%s,%s) returning id,expires_at""",
            (token_hash(token), user_id, purpose, Jsonb(payload), now()+timedelta(days=days))).fetchone()
        view = {'VERIFY': 'verify', 'RESET': 'reset', 'INVITE': 'invite'}[purpose]
        url = self.settings.public_base_url.rstrip('/') + f'/assets/merchant.html#/{view}?token={token}'
        message = cipher(self.settings.merchant_encryption_key).encrypt(json.dumps({
            'subject': 'Coffee Cloud 账号确认',
            'body': f'请仅在您发起注册、找回密码或接受邀请时打开此链接：\n{url}\n链接仅可使用一次，请勿转发。',
        }, ensure_ascii=False).encode()).decode()
        c.execute('insert into merchant_mail_outbox(recipient,encrypted_message) values(%s,%s)', (recipient, message))
        return action

    def register(self, data: dict, remote: str):
        if self.settings.merchant_registration_mode == 'USERNAME':
            return self.register_username(data, remote)
        email = email_address(data.get('email'))
        self.rate_limit('register', remote, email)
        self.mail_ready()
        display = text_field(data, 'displayName')
        tenant_name = text_field(data, 'tenantName')
        password = hash_password(data.get('password', ''))
        with self.database.connect() as c:
            user = c.execute("""insert into merchant_user(email,display_name,password_hash)
                values(%s,%s,%s) on conflict(email) do nothing returning id""", (email, display, password)).fetchone()
            if user:
                self._action(c, 'VERIFY', user['id'], email, {'tenantName': tenant_name})
        return {'status': 'VERIFICATION_PENDING'}

    def register_username(self, data: dict, remote: str):
        name = username(data.get('username'))
        self.rate_limit('register', remote, name)
        display = text_field(data, 'displayName')
        tenant_name = text_field(data, 'tenantName')
        password = hash_password(data.get('password', ''))
        with self.database.connect() as c:
            user = c.execute('''insert into merchant_user(username,display_name,password_hash)
                values(%s,%s,%s) on conflict(username) do nothing returning id''', (name, display, password)).fetchone()
            if not user:
                raise MerchantError(409, 'USERNAME_TAKEN', '用户名已被使用，请更换', {'username': '用户名已被使用'})
            tenant = c.execute('insert into merchant_tenant(name) values(%s) returning id', (tenant_name,)).fetchone()
            c.execute("insert into merchant_member(tenant_id,user_id,role) values(%s,%s,'OWNER')", (tenant['id'], user['id']))
            self.audit(c, {'tenant_id': tenant['id'], 'user_id': user['id'], 'display_name': display},
                       'account.register', 'tenant', tenant_name, '')
        # Username credentials do not assert ownership of any email address.
        return {'status': 'REGISTERED'}

    def verify_email(self, data: dict):
        self.enabled()
        with self.database.connect() as c:
            action = self._consume_action(c, data.get('token'), 'VERIFY')
            user = c.execute('select * from merchant_user where id=%s for update', (action['user_id'],)).fetchone()
            if not user or user['verified_at']:
                raise MerchantError(409, 'TOKEN_INVALID', '链接无效或已经使用')
            tenant = c.execute('insert into merchant_tenant(name) values(%s) returning id',
                               (action['payload']['tenantName'],)).fetchone()
            c.execute("insert into merchant_member(tenant_id,user_id,role) values(%s,%s,'OWNER')", (tenant['id'], user['id']))
            c.execute('update merchant_user set verified_at=now() where id=%s', (user['id'],))
        return {'status': 'VERIFIED'}

    @staticmethod
    def _consume_action(c, token, purpose):
        if not isinstance(token, str) or len(token) > 128:
            raise MerchantError(409, 'TOKEN_INVALID', '链接无效或已过期')
        row = c.execute("""select * from merchant_email_action
            where token_hash=%s and purpose=%s and expires_at>now() and consumed_at is null for update""",
            (token_hash(token), purpose)).fetchone()
        if not row:
            raise MerchantError(409, 'TOKEN_INVALID', '链接无效或已过期')
        c.execute('update merchant_email_action set consumed_at=now() where id=%s', (row['id'],))
        return row

    def login(self, data: dict, remote: str):
        value = data.get('username') if 'username' in data else data.get('email')
        is_email = isinstance(value, str) and '@' in value
        name = email_address(value) if is_email else username(value)
        self.rate_limit('login', remote, name)
        with self.database.connect() as c:
            field = sql.Identifier('email' if is_email else 'username')
            user = c.execute(sql.SQL('select * from merchant_user where {}=%s').format(field), (name,)).fetchone()
        if self._dummy_hash is None:
            self._dummy_hash = hash_password('dummy-password-for-constant-work')
        valid = verify_password(data.get('password', ''), user['password_hash'] if user else self._dummy_hash)
        if not valid or not user or (not user['verified_at'] and not user['username']) or user['status'] != 'ACTIVE':
            raise MerchantError(401, 'LOGIN_FAILED', '用户名、密码或账号状态不正确')
        token = secrets.token_urlsafe(48)
        with self.database.connect() as c:
            # Serialize session issuance against password reset/account suspension.
            fresh = c.execute('select * from merchant_user where id=%s for update', (user['id'],)).fetchone()
            if fresh['password_hash'] != user['password_hash'] or fresh['status'] != 'ACTIVE':
                raise MerchantError(401, 'LOGIN_FAILED', '账号状态已改变，请重新登录')
            member = c.execute("""select m.* from merchant_member m join merchant_tenant t on t.id=m.tenant_id
                where m.user_id=%s and m.status='ACTIVE' and t.status='ACTIVE' order by m.created_at,m.id limit 1""",
                (user['id'],)).fetchone()
            if not member:
                raise MerchantError(403, 'NO_MEMBERSHIP', '当前没有可访问的组织')
            c.execute("""insert into merchant_session(token_hash,csrf_token,user_id,member_id,expires_at)
                values(%s,%s,%s,%s,%s)""", (token_hash(token), secrets.token_urlsafe(32), user['id'],
                member['id'], now()+timedelta(hours=self.settings.merchant_session_hours)))
            result = self._session_payload(c, self._principal(c, token))
        return result, token

    def _principal(self, c, token: str | None):
        self.enabled()
        if not token or len(token) > 128:
            raise MerchantError(401, 'SESSION_INVALID', '请先登录')
        row = c.execute("""select s.id as session_id,s.csrf_token,s.reauthenticated_at,u.id as user_id,
            u.email,u.username,u.display_name,m.id as member_id,m.tenant_id,m.role,m.store_scope,m.version as member_version,
            t.name as tenant_name,t.timezone,t.environment,t.version as tenant_version
            from merchant_session s join merchant_user u on u.id=s.user_id
            join merchant_member m on m.id=s.member_id and m.user_id=u.id
            join merchant_tenant t on t.id=m.tenant_id
            where s.token_hash=%s and s.expires_at>now() and s.revoked_at is null
            and u.status='ACTIVE' and (u.verified_at is not null or u.username is not null) and m.status='ACTIVE' and t.status='ACTIVE'
            for share of s,u,m,t""", (token_hash(token),)).fetchone()
        if not row:
            raise MerchantError(401, 'SESSION_INVALID', '登录已失效，请重新登录')
        return row

    def _session_payload(self, c, p):
        memberships = c.execute("""select m.id,m.tenant_id,m.role,t.name from merchant_member m
            join merchant_tenant t on t.id=m.tenant_id where m.user_id=%s
            and m.status='ACTIVE' and t.status='ACTIVE' order by t.name,m.id""", (p['user_id'],)).fetchall()
        return {'user': {'id': str(p['user_id']), 'email': p['email'], 'username': p['username'], 'displayName': p['display_name']},
                'tenant': {'id': str(p['tenant_id']), 'name': p['tenant_name'], 'timezone': p['timezone'], 'environment': p['environment']},
                'membershipId': str(p['member_id']),
                'memberships': [{'id': str(m['id']), 'tenantId': str(m['tenant_id']), 'tenantName': m['name'], 'role': m['role']} for m in memberships],
                'permissions': sorted(self.permissions(p['role'])), 'storeScope': p['store_scope'], 'csrfToken': p['csrf_token']}

    @contextmanager
    def identity(self, token, permission=None, *, csrf=None, sensitive=False):
        with self.database.connect() as c:
            # Acquire the tenant membership fence before any user/member/session
            # row locks. Membership writes are exclusive, other requests shared.
            hint = c.execute("""select m.tenant_id from merchant_session s join merchant_member m on m.id=s.member_id
                where s.token_hash=%s""", (token_hash(token or ''),)).fetchone()
            if hint:
                function = 'pg_advisory_xact_lock' if permission == 'members.manage' else 'pg_advisory_xact_lock_shared'
                c.execute(sql.SQL('select {}(hashtextextended(%s,0))').format(sql.Identifier(function)),
                          ('member:'+str(hint['tenant_id']),))
            p = self._principal(c, token)
            if hint and p['tenant_id'] != hint['tenant_id']:
                raise MerchantError(409, 'SESSION_CHANGED', '组织已切换，请刷新后重试')
            if permission and permission not in self.permissions(p['role']):
                raise MerchantError(403, 'FORBIDDEN', '当前角色无此操作权限')
            if csrf is not None and not secrets.compare_digest(p['csrf_token'], csrf):
                raise MerchantError(403, 'CSRF_INVALID', '请求校验失败，请刷新页面')
            if sensitive and p['reauthenticated_at'] < now()-timedelta(minutes=10):
                raise MerchantError(403, 'REAUTH_REQUIRED', '请重新验证身份后再操作')
            c.execute("select set_config('coffee.tenant_id',%s,true)", (str(p['tenant_id']),))
            c.execute("select set_config('coffee.store_scope',%s,true)", (json.dumps(p['store_scope']),))
            yield c, p

    @contextmanager
    def scoped(self, token, permission, *, csrf=None, sensitive=False):
        with self.identity(token, permission, csrf=csrf, sensitive=sensitive) as (c, p):
            c.execute(sql.SQL('set local role {}').format(sql.Identifier(self.settings.merchant_runtime_role)))
            role = c.execute("""select r.rolsuper,r.rolbypassrls,
                (select pg_get_userbyid(relowner)=current_user from pg_class where oid='merchant_store'::regclass) as owns
                from pg_roles r where r.rolname=current_user""").fetchone()
            if role['rolsuper'] or role['rolbypassrls'] or role['owns']:
                raise MerchantError(503, 'UNSAFE_DATABASE_ROLE', '客户数据库权限配置尚未完成')
            c.execute("select set_config('coffee.tenant_id',%s,true)", (str(p['tenant_id']),))
            c.execute("select set_config('coffee.store_scope',%s,true)", (json.dumps(p['store_scope']),))
            yield c, p

    def session(self, token):
        with self.identity(token) as (c, p):
            return self._session_payload(c, p)

    def switch_tenant(self, token, data, csrf):
        with self.identity(token, csrf=csrf) as (c, p):
            member = c.execute("""select m.id from merchant_member m join merchant_tenant t on t.id=m.tenant_id
                where m.id=%s and m.user_id=%s and m.status='ACTIVE' and t.status='ACTIVE'""",
                (identifier(data.get('membershipId')), p['user_id'])).fetchone()
            if not member:
                raise MerchantError(404, 'NOT_FOUND', '组织不存在或无访问权限')
            c.execute('update merchant_session set member_id=%s,csrf_token=%s where id=%s',
                      (member['id'], secrets.token_urlsafe(32), p['session_id']))
            return self._session_payload(c, self._principal(c, token))

    def logout(self, token, csrf, *, others=False):
        with self.identity(token, csrf=csrf) as (c, p):
            if others:
                result = c.execute('update merchant_session set revoked_at=now() where user_id=%s and id<>%s and revoked_at is null',
                                   (p['user_id'], p['session_id']))
                return {'revokedCount': result.rowcount}
            c.execute('update merchant_session set revoked_at=now() where id=%s', (p['session_id'],))
        return {'status': 'SIGNED_OUT'}

    def reauthenticate(self, token, data, csrf, remote):
        self.rate_limit('reauthenticate', remote)
        with self.identity(token, csrf=csrf) as (c, p):
            row = c.execute('select password_hash from merchant_user where id=%s', (p['user_id'],)).fetchone()
            if not verify_password(data.get('password', ''), row['password_hash']):
                raise MerchantError(403, 'PASSWORD_INVALID', '密码不正确')
            c.execute('update merchant_session set reauthenticated_at=now() where id=%s', (p['session_id'],))
        return {'validUntil': (now()+timedelta(minutes=10)).isoformat()}

    def forgot_password(self, data, remote):
        email = email_address(data.get('email'))
        self.rate_limit('forgot', remote, email)
        self.mail_ready()
        with self.database.connect() as c:
            user = c.execute("select id from merchant_user where email=%s and status='ACTIVE' and verified_at is not null", (email,)).fetchone()
            if user:
                self._action(c, 'RESET', user['id'], email, {}, days=1/24)
        return {'status': 'ACCEPTED'}

    def reset_password(self, data, remote):
        self.rate_limit('reset', remote)
        password = hash_password(data.get('password', ''))
        with self.database.connect() as c:
            action = self._consume_action(c, data.get('token'), 'RESET')
            c.execute('update merchant_user set password_hash=%s where id=%s', (password, action['user_id']))
            c.execute('update merchant_session set revoked_at=now() where user_id=%s and revoked_at is null', (action['user_id'],))
        return {'status': 'UPDATED'}

    @staticmethod
    def check_version(row, data):
        if type(data.get('version')) is not int or row['version'] != data['version']:
            raise MerchantError(409, 'VERSION_CONFLICT', '数据已改变，请重新读取后操作')

    @staticmethod
    def store_allowed(p, store_id):
        scope = p['store_scope']
        return scope['mode'] == 'ALL' or str(store_id) in scope['storeIds']

    @staticmethod
    def audit(c, p, action, resource, label, request_id):
        c.execute("select set_config('coffee.tenant_id',%s,true)", (str(p['tenant_id']),))
        c.execute("""insert into merchant_audit(tenant_id,actor_id,actor_name,action,resource_type,resource_label,request_id)
            values(%s,%s,%s,%s,%s,%s,%s)""", (p['tenant_id'], p['user_id'], p['display_name'], action, resource, label, request_id))

    def stores(self, token):
        with self.scoped(token, 'stores.read') as (c, p):
            rows = c.execute('''select s.*,(select count(*) from terminal t where t.tenant_id=s.tenant_id
                and t.merchant_store_id=s.id and t.lifecycle_status<>'RETIRED') as device_count
                from merchant_store s where s.tenant_id=%s order by s.created_at,s.id''', (p['tenant_id'],)).fetchall()
            return [self._store(r) for r in rows if self.store_allowed(p, r['id'])]

    @staticmethod
    def _store(r):
        return {'id': str(r['id']), 'name': r['name'], 'address': r['address'], 'status': r['status'], 'version': r['version'], 'deviceCount': int(r.get('device_count', 0))}

    def save_store(self, token, data, csrf, request_id, store_id=None):
        name = text_field(data, 'name')
        address = data.get('address', '')
        if not isinstance(address, str) or len(address) > 500:
            raise MerchantError(422, 'INVALID_ADDRESS', '地址最长500个字符')
        with self.scoped(token, 'stores.manage', csrf=csrf) as (c, p):
            if store_id:
                current = c.execute('select * from merchant_store where id=%s and tenant_id=%s for update', (identifier(store_id), p['tenant_id'])).fetchone()
                if not current:
                    raise MerchantError(404, 'NOT_FOUND', '门店不存在或无访问权限')
                self.check_version(current, data)
                status = data.get('status', current['status'])
                if status not in ('ACTIVE', 'ARCHIVED'):
                    raise MerchantError(422, 'INVALID_STATUS', '无效门店状态')
                if status == 'ARCHIVED' and c.execute("select 1 from terminal where tenant_id=%s and merchant_store_id=%s and lifecycle_status<>'RETIRED' limit 1", (p['tenant_id'], current['id'])).fetchone():
                    raise MerchantError(409, 'STORE_HAS_DEVICES', '门店仍有绑定设备，请先处理设备归属')
                row = c.execute('update merchant_store set name=%s,address=%s,status=%s,version=version+1 where id=%s returning *',
                                (name, address, status, current['id'])).fetchone()
            else:
                row = c.execute('insert into merchant_store(tenant_id,name,address) values(%s,%s,%s) returning *', (p['tenant_id'], name, address)).fetchone()
            self.audit(c, p, 'store.update' if store_id else 'store.create', 'store', name, request_id)
            return self._store(row)

    def tenant(self, token, data=None, csrf=None, request_id=''):
        with self.identity(token, 'tenant.manage' if data is not None else None, csrf=csrf) as (c, p):
            if data is not None:
                self.check_version({'version': p['tenant_version']}, data)
                tz = data.get('timezone', p['timezone'])
                try:
                    ZoneInfo(tz)
                except (ZoneInfoNotFoundError, ValueError, TypeError):
                    raise MerchantError(422, 'INVALID_TIMEZONE', '无效时区') from None
                # Timezone changes require an explicit accounting migration.
                if tz != p['timezone']:
                    raise MerchantError(409, 'TIMEZONE_LOCKED', '时区变更需要平台确认账期迁移')
                c.execute('update merchant_tenant set name=%s,version=version+1 where id=%s', (text_field(data, 'name'), p['tenant_id']))
                self.audit(c, p, 'tenant.update', 'tenant', text_field(data, 'name'), request_id)
            row = c.execute('select * from merchant_tenant where id=%s', (p['tenant_id'],)).fetchone()
            return {'id': str(row['id']), 'name': row['name'], 'timezone': row['timezone'], 'environment': row['environment'], 'version': row['version']}

    def members(self, token):
        with self.identity(token, 'members.read') as (c, p):
            rows = c.execute("""select m.*,u.email,u.username,u.display_name from merchant_member m
                join merchant_user u on u.id=m.user_id where m.tenant_id=%s order by m.created_at,m.id""", (p['tenant_id'],)).fetchall()
            return [self._member(r) for r in rows]

    @staticmethod
    def _member(r):
        return {'id': str(r['id']), 'email': r['email'], 'username': r['username'], 'displayName': r['display_name'],
                'role': r['role'], 'status': r['status'], 'storeScope': r['store_scope'], 'version': r['version']}

    def _scope(self, c, p, data):
        scope = data.get('storeScope', {'mode': 'SELECTED', 'storeIds': []})
        if not isinstance(scope, dict) or scope.get('mode') not in ('ALL', 'SELECTED') or not isinstance(scope.get('storeIds'), list):
            raise MerchantError(422, 'INVALID_SCOPE', '请选择有效的门店权限范围')
        ids = [identifier(x) for x in scope['storeIds']]
        c.execute("select set_config('coffee.tenant_id',%s,true)", (str(p['tenant_id']),))
        if ids:
            found = c.execute('select id from merchant_store where tenant_id=%s and id=any(%s)', (p['tenant_id'], ids)).fetchall()
            if set(ids) != {r['id'] for r in found}:
                raise MerchantError(404, 'NOT_FOUND', '门店不存在或无访问权限')
        return {'mode': scope['mode'], 'storeIds': [str(x) for x in ids] if scope['mode'] == 'SELECTED' else []}

    def update_member(self, token, member_id, data, csrf, request_id):
        with self.identity(token, 'members.manage', csrf=csrf, sensitive=True) as (c, p):
            row = c.execute("""select m.*,u.email,u.username,u.display_name from merchant_member m join merchant_user u on u.id=m.user_id
                where m.tenant_id=%s and m.id=%s for update of m""", (p['tenant_id'], identifier(member_id))).fetchone()
            if not row:
                raise MerchantError(404, 'NOT_FOUND', '成员不存在或无访问权限')
            self.check_version(row, data)
            role, status = data.get('role', row['role']), data.get('status', row['status'])
            if role not in PERMISSIONS or status not in ('ACTIVE', 'SUSPENDED'):
                raise MerchantError(422, 'INVALID_ROLE', '角色或状态无效')
            owners = c.execute("select count(*) as n from merchant_member where tenant_id=%s and role='OWNER' and status='ACTIVE'", (p['tenant_id'],)).fetchone()['n']
            if row['role'] == 'OWNER' and row['status'] == 'ACTIVE' and (role != 'OWNER' or status != 'ACTIVE') and owners <= 1:
                raise MerchantError(409, 'LAST_OWNER', '不能停用或降级最后一位组织所有者')
            scope = self._scope(c, p, data) if 'storeScope' in data else row['store_scope']
            c.execute('update merchant_member set role=%s,status=%s,store_scope=%s,version=version+1 where id=%s',
                      (role, status, Jsonb(scope), row['id']))
            c.execute('update merchant_session set revoked_at=now() where member_id=%s and revoked_at is null', (row['id'],))
            self.audit(c, p, 'member.update', 'member', row['username'] or row['email'], request_id)
            return self._member({**row, 'role': role, 'status': status, 'store_scope': scope, 'version': row['version']+1})

    def invitations(self, token):
        with self.identity(token, 'members.read') as (c, p):
            rows = c.execute('select * from merchant_invitation where tenant_id=%s order by created_at desc,id', (p['tenant_id'],)).fetchall()
            return [{'id': str(r['id']), 'email': r['email'], 'role': r['role'],
                     'status': 'EXPIRED' if r['status'] == 'PENDING' and r['expires_at'] < now() else r['status'],
                     'expiresAt': r['expires_at'].isoformat(), 'deliveryStatus': 'QUEUED'} for r in rows]

    def invite(self, token, data, csrf, request_id):
        self.mail_ready()
        email = email_address(data.get('email'))
        role = data.get('role')
        if role not in PERMISSIONS:
            raise MerchantError(422, 'INVALID_ROLE', '无效角色')
        with self.identity(token, 'members.manage', csrf=csrf, sensitive=True) as (c, p):
            scope = self._scope(c, p, data)
            c.execute("select pg_advisory_xact_lock(hashtextextended(%s,0))", ('invite:'+str(p['tenant_id'])+email,))
            c.execute("update merchant_invitation set status='REVOKED' where tenant_id=%s and email=%s and status='PENDING' and expires_at<=now()", (p['tenant_id'], email))
            if c.execute("select 1 from merchant_invitation where tenant_id=%s and email=%s and status='PENDING'", (p['tenant_id'], email)).fetchone():
                raise MerchantError(409, 'INVITATION_EXISTS', '已有有效邀请')
            invite_id = uuid.uuid4()
            action = self._action(c, 'INVITE', None, email, {'invitationId': str(invite_id)}, days=3)
            c.execute("""insert into merchant_invitation(id,tenant_id,email,role,store_scope,action_id,expires_at)
                values(%s,%s,%s,%s,%s,%s,%s)""", (invite_id, p['tenant_id'], email, role, Jsonb(scope), action['id'], action['expires_at']))
            self.audit(c, p, 'invitation.create', 'invitation', email, request_id)
            return {'id': str(invite_id), 'status': 'PENDING', 'deliveryStatus': 'QUEUED', 'expiresAt': action['expires_at'].isoformat()}

    def revoke_invitation(self, token, invitation_id, csrf, request_id):
        with self.identity(token, 'members.manage', csrf=csrf) as (c, p):
            row = c.execute("""update merchant_invitation set status='REVOKED'
                where id=%s and tenant_id=%s and status='PENDING' returning *""", (identifier(invitation_id), p['tenant_id'])).fetchone()
            if not row:
                raise MerchantError(404, 'NOT_FOUND', '邀请不存在或无访问权限')
            c.execute('update merchant_email_action set consumed_at=now() where id=%s', (row['action_id'],))
            self.audit(c, p, 'invitation.revoke', 'invitation', row['email'], request_id)
        return {'status': 'REVOKED'}

    def accept_invitation(self, token, data, remote, csrf=None):
        self.rate_limit('accept-invite', remote)
        with self.database.connect() as c:
            action = self._consume_action(c, data.get('token'), 'INVITE')
            inv = c.execute("select * from merchant_invitation where action_id=%s and status='PENDING' and expires_at>now() for update", (action['id'],)).fetchone()
            if not inv:
                raise MerchantError(409, 'TOKEN_INVALID', '邀请已失效')
            tenant = c.execute("select id from merchant_tenant where id=%s and status='ACTIVE'", (inv['tenant_id'],)).fetchone()
            if not tenant:
                raise MerchantError(409, 'TOKEN_INVALID', '邀请已失效')
            user = c.execute('select * from merchant_user where email=%s for update', (inv['email'],)).fetchone()
            if user:
                p = self._principal(c, token)
                if p['user_id'] != user['id'] or not csrf or not secrets.compare_digest(p['csrf_token'], csrf):
                    raise MerchantError(403, 'INVITATION_ACCOUNT_MISMATCH', '请使用受邀邮箱对应账号登录后接受邀请')
            else:
                user = c.execute("""insert into merchant_user(email,display_name,password_hash,verified_at)
                    values(%s,%s,%s,now()) returning *""", (inv['email'], text_field(data, 'displayName'), hash_password(data.get('password', '')))).fetchone()
            inserted = c.execute("""insert into merchant_member(tenant_id,user_id,role,store_scope)
                values(%s,%s,%s,%s) on conflict(tenant_id,user_id) do nothing returning id""",
                (inv['tenant_id'], user['id'], inv['role'], Jsonb(inv['store_scope']))).fetchone()
            if not inserted:
                raise MerchantError(409, 'ALREADY_MEMBER', '您已经是该组织成员，请由所有者调整权限')
            c.execute("update merchant_invitation set status='ACCEPTED' where id=%s", (inv['id'],))
        return {'status': 'ACCEPTED'}
