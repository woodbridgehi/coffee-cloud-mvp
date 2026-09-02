from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timedelta

from psycopg.types.json import Jsonb

from ..protocol import canonical_digest, CommandCreateRequest
from ..repositories import CommandRepository
from ..services.commands import CommandService
from ..services.refund_intents import create_refund_intent
from ..services.errors import ServiceError
from .security import MerchantError, PERMISSIONS, token_hash
from .service import identifier, now, text_field


LEGACY_TENANT = uuid.UUID('00000000-0000-4000-8000-000000000001')


class MerchantAssets:
    def __init__(self, service):
        self.service = service

    def device(self, c, p, device_id, *, lock=False):
        # The UI treats IDs as opaque strings; only database integer asset IDs
        # are accepted here, never an arbitrary global terminal identifier.
        if not str(device_id).isdigit() or len(str(device_id)) > 18:
            raise MerchantError(404, 'NOT_FOUND', '设备不存在或无访问权限')
        row = c.execute('select * from terminal where id=%s and tenant_id=%s'+(' for update' if lock else ''),
                        (int(device_id), p['tenant_id'])).fetchone()
        if not row or not self.service.store_allowed(p, row['merchant_store_id']):
            raise MerchantError(404, 'NOT_FOUND', '设备不存在或无访问权限')
        return row

    def store(self, c, p, store_id):
        row = c.execute("select * from merchant_store where id=%s and tenant_id=%s and status='ACTIVE'",
                        (identifier(store_id), p['tenant_id'])).fetchone()
        if not row or not self.service.store_allowed(p, row['id']):
            raise MerchantError(404, 'NOT_FOUND', '门店不存在或无访问权限')
        return row

    def payload(self, c, p, row, detail=False):
        store = c.execute('select name from merchant_store where id=%s and tenant_id=%s', (row['merchant_store_id'], p['tenant_id'])).fetchone()
        online = row['last_seen_at'] is not None and row['last_seen_at'] > now()-timedelta(seconds=self.service.settings.offline_threshold_seconds)
        permissions = self.service.permissions(p['role'])
        actions = []
        if not row['ownership_frozen']:
            if 'devices.manage' in permissions:
                actions += ['RENAME','REASSIGN']
                if row['lifecycle_status'] == 'ACTIVE': actions += ['SUSPEND']
                if row['lifecycle_status'] == 'SUSPENDED': actions += ['RESUME', 'ARCHIVE']
            if 'devices.transfer' in permissions: actions += ['REQUEST_TRANSFER', 'REQUEST_UNBIND']
            if 'commands.execute' in permissions and online and row['lifecycle_status'] == 'ACTIVE': actions += ['COMMAND_RELOAD_CONFIG']
        result = {'id': str(row['id']), 'deviceId': row['device_id'], 'serialNumber': row['serial_number'],
                  'name': row.get('device_name') or row['device_id'], 'storeId': str(row['merchant_store_id']) if row['merchant_store_id'] else None,
                  'storeName': store['name'] if store else '未分配门店', 'lifecycle': 'ARCHIVED' if row['lifecycle_status']=='RETIRED' else row['lifecycle_status'],
                  'online': online, 'lastSeenAt': row['last_seen_at'], 'provisioningStatus': row.get('provisioning_status', 'LEGACY'),
                  'deviceIdentityKind': row.get('device_identity_kind'), 'ownershipVersion': row['ownership_version'],
                  'version': row['merchant_version'], 'allowedActions': actions}
        if detail:
            snapshots = {r['snapshot_type']: r['payload_json'] for r in c.execute('select snapshot_type,payload_json from terminal_snapshot where terminal_id=%s', (row['id'],)).fetchall()}
            job = c.execute("select task_id,status from production_job where terminal_id=%s and status in ('PENDING','DISPATCHED','ACCEPTED','EXECUTING','HOLD') order by created_at desc limit 1", (row['id'],)).fetchone()
            capability_snapshot = snapshots.get('capabilities', {})
            capabilities = capability_snapshot.get('products') or capability_snapshot.get('recipes') or []
            capabilities = [{**item, 'id': item.get('id') or item.get('recipeId'),
                             'estimatedSeconds': item.get('estimatedSeconds') or item.get('estimatedDurationSeconds')}
                            for item in capabilities]
            inventory = [{**item, 'availableQuantity': item.get('availableQuantity', item.get('available')),
                          'onHandQuantity': item.get('onHandQuantity', item.get('onHand')),
                          'reservedQuantity': item.get('reservedQuantity', item.get('reserved'))}
                         for item in snapshots.get('inventory', {}).get('materials', [])]
            result.update(capabilities=capabilities, inventory=inventory, alerts=[],
                          currentJob={'id': job['task_id'], 'status': job['status']} if job else None)
        return result

    def devices(self, token, params, device_id=None):
        # Authenticated identity connection is needed for detailed device
        # projections; every base row must first pass tenant+store authorization.
        with self.service.scoped(token, 'devices.read') as (c, p):
            if device_id:
                return self.payload(c, p, self.device(c, p, device_id), True)
            rows = c.execute('select * from terminal where tenant_id=%s order by id', (p['tenant_id'],)).fetchall()
            result = []
            for row in rows:
                if not self.service.store_allowed(p, row['merchant_store_id']): continue
                if params.get('storeId') and str(row['merchant_store_id']) != params['storeId']: continue
                status = 'RETIRED' if params.get('status')=='ARCHIVED' else params.get('status')
                if status and row['lifecycle_status'] != status: continue
                if params.get('q') and params['q'].lower() not in (' '.join(str(row.get(k) or '') for k in ('device_id','device_name','serial_number'))).lower(): continue
                result.append(self.payload(c, p, row))
            return result

    def idempotent(self, c, p, operation, key, data, fn):
        if not key or not isinstance(key, str) or len(key)>160:
            raise MerchantError(400, 'IDEMPOTENCY_REQUIRED', '需要有效的 Idempotency-Key')
        digest = canonical_digest(data)
        c.execute('select pg_advisory_xact_lock(hashtextextended(%s,0))', (str(p['tenant_id'])+operation+key,))
        row = c.execute('select * from merchant_operation where tenant_id=%s and operation=%s and key=%s', (p['tenant_id'], operation, key)).fetchone()
        if row:
            if row['digest'] != digest:
                raise MerchantError(409, 'IDEMPOTENCY_CONFLICT', '同一请求标识不能用于不同内容')
            return row['response']
        result = fn()
        from fastapi.encoders import jsonable_encoder
        result = jsonable_encoder(result)
        c.execute('insert into merchant_operation(tenant_id,operation,key,digest,response) values(%s,%s,%s,%s,%s)',
                  (p['tenant_id'], operation, key, digest, Jsonb(result)))
        return result

    @staticmethod
    def blocking(c, terminal_id):
        reasons = []
        if c.execute("""select 1 from sales_order where terminal_id=%s and
            (status in ('CREATED','AWAITING_PAYMENT','QUEUED','DISPATCHED','ACCEPTED','MAKING','HOLD')
             or payment_status in ('PENDING','REFUNDING')) limit 1""", (terminal_id,)).fetchone():
            reasons.append('存在待付款、在途制作或退款中的订单')
        if c.execute("select 1 from production_job where terminal_id=%s and (status='HOLD' or manual_review_required) limit 1", (terminal_id,)).fetchone():
            reasons.append('存在待人工确认的生产任务')
        if c.execute("select 1 from terminal_command where terminal_id=%s and status in ('CREATED','DELIVERING','ACKED','EXECUTING') limit 1", (terminal_id,)).fetchone():
            reasons.append('存在尚未完成的设备指令')
        return reasons

    def issue_claim(self, terminal_id):
        # Only called behind the separate platform access.manage dependency.
        code = secrets.token_urlsafe(32)
        with self.service.database.connect() as c:
            row = c.execute('select * from terminal where id=%s for update', (int(terminal_id),)).fetchone()
            if not row or row['tenant_id'] != LEGACY_TENANT:
                raise MerchantError(409, 'CLAIM_NOT_AVAILABLE', '仅未分配的出厂设备可以生成认领码')
            c.execute('update merchant_device_claim set expires_at=now() where terminal_id=%s and consumed_at is null', (row['id'],))
            expires = now()+timedelta(days=7)
            c.execute('insert into merchant_device_claim(terminal_id,code_hash,expires_at) values(%s,%s,%s)', (row['id'], token_hash(code), expires))
        return {'claimCode': code, 'expiresAt': expires, 'deviceId': row['device_id']}

    def claim(self, token, data, csrf, key, request_id):
        pairing = bool(data.get('pairingCode'))
        code = text_field(data, 'pairingCode' if pairing else 'claimCode', 128)
        with self.service.identity(token, 'devices.claim', csrf=csrf, sensitive=True) as (c, p):
            def execute():
                if pairing:
                    claim = c.execute("""select * from device_pairing_session
                        where pairing_code_hash=%s and status='PENDING' and expires_at>now() for update""", (token_hash(code),)).fetchone()
                    if not claim: raise MerchantError(409, 'PAIRING_INVALID', '配对码无效、已使用或已过期')
                else:
                    claim = c.execute('select * from merchant_device_claim where code_hash=%s and consumed_at is null and expires_at>now() for update', (token_hash(code),)).fetchone()
                    if not claim: raise MerchantError(409, 'CLAIM_INVALID', '认领码无效、已使用或已过期')
                device = c.execute('select * from terminal where id=%s for update', (claim['terminal_id'],)).fetchone()
                if device['tenant_id'] != LEGACY_TENANT or device['ownership_frozen'] or self.blocking(c, device['id']):
                    raise MerchantError(409, 'PAIRING_INVALID' if pairing else 'CLAIM_INVALID', '设备已分配或有未处理业务，请联系平台')
                store = self.store(c, p, data.get('storeId'))
                c.execute('update merchant_device_ownership set valid_until=now() where terminal_id=%s and valid_until is null', (device['id'],))
                row = c.execute("""update terminal set tenant_id=%s,merchant_store_id=%s,device_name=%s,
                    store_name=coalesce(store_name,%s),profile_source=coalesce(profile_source,%s),
                    profile_completed_at=coalesce(profile_completed_at,now()),
                    provisioning_status=case when %s then 'CLAIMED_PENDING_PROVISION' else provisioning_status end,
                    ownership_version=ownership_version+1,merchant_version=merchant_version+1,updated_at=now()
                    where id=%s returning *""",
                    (p['tenant_id'], store['id'], text_field(data, 'name'), store['name'],
                     'MERCHANT_PAIRING' if pairing else 'MERCHANT_CLAIM', pairing, device['id'])).fetchone()
                c.execute('insert into merchant_device_ownership(terminal_id,tenant_id,store_id,version) values(%s,%s,%s,%s)', (row['id'], p['tenant_id'], store['id'], row['ownership_version']))
                if pairing:
                    c.execute("""update device_pairing_session set status='CLAIMED',claimed_at=now()
                        where id=%s""", (claim['id'],))
                else:
                    c.execute('update merchant_device_claim set consumed_at=now(),consumed_by=%s where id=%s', (p['tenant_id'], claim['id']))
                self.service.audit(c,p,'device.pair' if pairing else 'device.claim','device',row['device_id'],request_id)
                return self.payload(c,p,row)
            return self.idempotent(c,p,'device.pair' if pairing else 'device.claim',key, data,execute)

    def update(self, token, device_id, data, csrf, request_id, *, lifecycle=False):
        with self.service.scoped(token, 'devices.manage', csrf=csrf, sensitive=lifecycle) as (c,p):
            row = self.device(c,p,device_id,lock=True)
            self.service.check_version({'version':row['merchant_version']},data)
            if row['ownership_frozen']: raise MerchantError(409,'DEVICE_FROZEN','设备正在办理归属变更')
            if lifecycle:
                action = data.get('action')
                status = {'SUSPEND':'SUSPENDED','RESUME':'ACTIVE','ARCHIVE':'RETIRED'}.get(action)
                allowed = self.payload(c,p,row)['allowedActions']
                if action not in allowed: raise MerchantError(409,'BAD_STATE','当前设备状态不允许此操作')
                text_field(data,'reason',500)
                if action == 'ARCHIVE' and self.blocking(c,row['id']): raise MerchantError(409,'DEVICE_BUSY','请先处理未完成业务')
                row = c.execute('update terminal set lifecycle_status=%s,merchant_version=merchant_version+1,updated_at=now() where id=%s returning *',(status,row['id'])).fetchone()
            else:
                store = self.store(c,p,data.get('storeId'))
                row = c.execute('update terminal set device_name=%s,merchant_store_id=%s,merchant_version=merchant_version+1,updated_at=now() where id=%s returning *',
                                (text_field(data,'name'),store['id'],row['id'])).fetchone()
            self.service.audit(c,p,'device.lifecycle' if lifecycle else 'device.update','device',row['device_id'],request_id)
            return self.payload(c,p,row)

    def command(self, token, device_id, data, csrf, key, request_id, command_id=None):
        with self.service.scoped(token, 'devices.read' if command_id else 'commands.execute',csrf=csrf) as (c,p):
            terminal = self.device(c,p,device_id,lock=not command_id)
            repository = CommandRepository(c)
            if command_id:
                row=repository.find(terminal['id'], command_id)
                if not row: raise MerchantError(404,'NOT_FOUND','指令不存在或无访问权限')
            else:
                if data.get('ownershipVersion') != terminal['ownership_version']: raise MerchantError(409,'VERSION_CONFLICT','设备归属已改变')
                if data.get('command') != 'RELOAD_CONFIG' or 'COMMAND_RELOAD_CONFIG' not in self.payload(c,p,terminal)['allowedActions']:
                    raise MerchantError(409,'COMMAND_NOT_ALLOWED','当前仅允许在线设备重载配置')
                def execute():
                    existing=repository.by_idempotency(terminal['id'], 'merchant:'+str(p['tenant_id'])+':'+str(key))
                    if existing: return {'id':existing['message_id'],'status':existing['status']}
                    message_id='cmd-'+str(uuid.uuid4());expires=now()+timedelta(minutes=5)
                    payload={'messageId':message_id,'type':'RELOAD_CONFIG','expiresAt':expires.isoformat()}
                    row=repository.insert(terminal_id=terminal['id'],message_id=message_id,command_type='RELOAD_CONFIG',payload=payload,
                        digest=canonical_digest(payload),expires_at=expires,idempotency_key='merchant:'+str(p['tenant_id'])+':'+str(key))
                    repository.insert_initial_transition(row['id'],'merchant-api','customer configuration reload',payload)
                    CommandService._enqueue_outbox(c,row,terminal)
                    self.service.audit(c,p,'command.create','device',terminal['device_id'],request_id)
                    return {'id':message_id,'status':'PENDING'}
                return self.idempotent(c,p,'command:'+str(device_id),key,data,execute)
            status={'CREATED':'PENDING','DELIVERING':'PENDING','ACKED':'PENDING','SUCCEEDED':'SUCCEEDED','EXECUTING':'EXECUTING'}.get(row['status'],row['status'])
            return {'id':row['message_id'],'status':status,'resultMessage':row['status']}

    def transfer(self, token, device_id, data, csrf, key, request_id, *, unbind=False):
        with self.service.identity(token,'devices.transfer',csrf=csrf,sensitive=True) as (c,p):
            def execute():
                device=self.device(c,p,device_id,lock=True)
                if data.get('ownershipVersion') != device['ownership_version']: raise MerchantError(409,'VERSION_CONFLICT','设备归属已改变')
                if device['ownership_frozen']: raise MerchantError(409,'DEVICE_FROZEN','已有归属变更申请')
                blocking=self.blocking(c,device['id'])
                if blocking: raise MerchantError(409,'DEVICE_BUSY','；'.join(blocking))
                target=None
                if not unbind:
                    target=identifier(data.get('targetTenantReference'))
                    if target==p['tenant_id'] or target==LEGACY_TENANT or not c.execute("select 1 from merchant_tenant where id=%s and status='ACTIVE'",(target,)).fetchone():
                        raise MerchantError(404,'NOT_FOUND','目标组织不存在或不可接收')
                row=c.execute("""insert into merchant_device_transfer(terminal_id,source_tenant_id,target_tenant_id,reason,status,ownership_version,previous_lifecycle)
                    values(%s,%s,%s,%s,%s,%s,%s) returning *""",(device['id'],p['tenant_id'],target,text_field(data,'reason',500),
                    'PENDING_PLATFORM' if unbind else 'PENDING_RECIPIENT',device['ownership_version'],device['lifecycle_status'])).fetchone()
                c.execute("update terminal set ownership_frozen=true,lifecycle_status='SUSPENDED',merchant_version=merchant_version+1 where id=%s",(device['id'],))
                self.service.audit(c,p,'device.unbind-request' if unbind else 'device.transfer-request','device',device['device_id'],request_id)
                return {'id':str(row['id']),'status':row['status'],'blockingReasons':[],'version':row['version']}
            return self.idempotent(c,p,'unbind:'+str(device_id) if unbind else 'transfer:'+str(device_id),key,data,execute)

    def transfers(self, token):
        with self.service.identity(token,'devices.transfer') as (c,p):
            rows=c.execute("""select x.*,d.device_id,d.device_name,source.name as source_name,target.name as target_name
                from merchant_device_transfer x join terminal d on d.id=x.terminal_id
                join merchant_tenant source on source.id=x.source_tenant_id left join merchant_tenant target on target.id=x.target_tenant_id
                where x.source_tenant_id=%s or x.target_tenant_id=%s order by x.created_at desc,x.id""",(p['tenant_id'],p['tenant_id'])).fetchall()
            return [{'id':str(r['id']),'deviceId':str(r['terminal_id']),'deviceName':r['device_name'] or r['device_id'],
                     'direction':'OUT' if r['source_tenant_id']==p['tenant_id'] else 'IN',
                     'counterpartName':r['target_name'] if r['source_tenant_id']==p['tenant_id'] else r['source_name'],
                     'status':r['status'],'blockingReasons':[],'reason':r['reason'],'createdAt':r['created_at'],'version':r['version']} for r in rows]

    def transfer_action(self, token, transfer_id, data, csrf, request_id, action):
        with self.service.identity(token,'devices.transfer',csrf=csrf,sensitive=True) as (c,p):
            row=c.execute('select * from merchant_device_transfer where id=%s and (source_tenant_id=%s or target_tenant_id=%s) for update',
                          (identifier(transfer_id),p['tenant_id'],p['tenant_id'])).fetchone()
            if not row: raise MerchantError(404,'NOT_FOUND','申请不存在或无访问权限')
            self.service.check_version(row,data)
            if action=='accept':
                if row['target_tenant_id']!=p['tenant_id'] or row['status']!='PENDING_RECIPIENT': raise MerchantError(409,'BAD_STATE','当前申请不能接收')
                target_store=self.store(c,p,data['storeId'])['id'] if data.get('storeId') else None
                c.execute("update merchant_device_transfer set status='PENDING_PLATFORM',target_store_id=%s,version=version+1 where id=%s",(target_store,row['id']))
                status='PENDING_PLATFORM'
            else:
                if row['source_tenant_id']!=p['tenant_id'] or row['status'] not in ('PENDING_RECIPIENT','PENDING_PLATFORM'): raise MerchantError(409,'BAD_STATE','当前申请不能取消')
                c.execute("update merchant_device_transfer set status='CANCELLED',version=version+1 where id=%s",(row['id'],))
                c.execute('update terminal set ownership_frozen=false,lifecycle_status=%s,merchant_version=merchant_version+1 where id=%s and ownership_version=%s',
                          (row['previous_lifecycle'],row['terminal_id'],row['ownership_version']))
                status='CANCELLED'
            self.service.audit(c,p,'transfer.'+action,'transfer',str(row['id']),request_id)
            return {'id':str(row['id']),'status':status,'version':row['version']+1}
