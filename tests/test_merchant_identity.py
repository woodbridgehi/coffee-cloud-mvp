from __future__ import annotations

import json
import os
import re
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.types.json import Jsonb

from app.database import Database
from app.merchant.provision import provision_role
from app.merchant.router import create_router
from app.merchant.security import MerchantError, cipher, hash_password, verify_password
from app.merchant.service import MerchantService
from app.settings import Settings


PASSWORD = 'test-customer-password-2026'


@pytest.fixture
def merchant():
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('TEST_DATABASE_URL required for tenant isolation tests')
    suffix = uuid.uuid4().hex
    schema, role = 'merchant_test_'+suffix, 'merchant_role_'+suffix
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('create schema {}').format(sql.Identifier(schema)))
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query)); query['options'] = '-csearch_path='+schema
    scoped_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ''))
    database = Database(scoped_url, min_size=1, max_size=4)
    database.initialize()
    with database.connect() as c:
        provision_role(c, role)
    settings = Settings(_env_file=None, DATABASE_URL=scoped_url, ADMIN_TOKEN='test-admin-'+'x'*32,
                        MERCHANT_ENABLED=True, MERCHANT_RUNTIME_ROLE=role,
                        MERCHANT_ENCRYPTION_KEY=Fernet.generate_key().decode(),
                        MERCHANT_SMTP_HOST='test-mail.invalid', MERCHANT_MAIL_FROM='no-reply@test.invalid',
                        PUBLIC_BASE_URL='https://testserver')
    service = MerchantService(database, settings)
    try:
        yield service
    finally:
        database.close()
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('drop schema {} cascade').format(sql.Identifier(schema)))
            c.execute(sql.SQL('drop role {}').format(sql.Identifier(role)))


def email_token(service, email):
    with service.database.connect() as c:
        row = c.execute('select encrypted_message from merchant_mail_outbox where recipient=%s order by created_at desc limit 1', (email,)).fetchone()
    body = json.loads(cipher(service.settings.merchant_encryption_key).decrypt(row['encrypted_message'].encode()))['body']
    return re.search(r'token=([^\s]+)', body).group(1)


def account(service, email='owner-a@test.invalid'):
    service.register({'email': email, 'password': PASSWORD, 'displayName': email, 'tenantName': email}, 'test-ip')
    service.verify_email({'token': email_token(service, email)})
    session, token = service.login({'email': email, 'password': PASSWORD}, 'test-ip')
    return session, token


def test_password_kdf_salts_and_rejects_invalid_passwords():
    first = hash_password(PASSWORD)
    second = hash_password(PASSWORD)
    assert first != second
    assert verify_password(PASSWORD, first)
    assert not verify_password('incorrect-but-long-password', first)
    assert not verify_password(None, first)
    with pytest.raises(MerchantError):
        hash_password('short')


def test_registration_does_not_authenticate_before_verification_and_token_is_single_use(merchant):
    email = 'verify@test.invalid'
    result = merchant.register({'email': email, 'password': PASSWORD, 'displayName': 'User', 'tenantName': 'Company'}, 'ip')
    assert result == {'status': 'VERIFICATION_PENDING'}
    assert 'token' not in json.dumps(result)
    with pytest.raises(MerchantError) as error:
        merchant.login({'email': email, 'password': PASSWORD}, 'ip')
    assert error.value.status == 401
    token = email_token(merchant, email)
    assert merchant.verify_email({'token': token})['status'] == 'VERIFIED'
    with pytest.raises(MerchantError):
        merchant.verify_email({'token': token})


def test_tenants_are_isolated_even_when_repository_forgets_where(merchant):
    a, at = account(merchant)
    b, bt = account(merchant, 'owner-b@test.invalid')
    ast = merchant.save_store(at, {'name': 'A'}, a['csrfToken'], 'test')
    merchant.save_store(bt, {'name': 'B'}, b['csrfToken'], 'test')
    assert [s['name'] for s in merchant.stores(at)] == ['A']
    with merchant.scoped(bt, 'stores.read') as (c, p):
        assert [r['name'] for r in c.execute('select * from merchant_store').fetchall()] == ['B']
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute('insert into merchant_store(tenant_id,name) values(%s,%s)', (uuid.UUID(a['tenant']['id']), 'Bad'))
    with pytest.raises(MerchantError) as error:
        merchant.save_store(bt, {'name': 'Hijack', 'version': 1}, b['csrfToken'], 'test', ast['id'])
    assert error.value.status == 404
    assert merchant.stores(at)[0]['name'] == 'A'


def test_runtime_has_no_auth_table_access_and_missing_context_is_closed(merchant):
    with merchant.database.connect() as c:
        c.execute(sql.SQL('set local role {}').format(sql.Identifier(merchant.settings.merchant_runtime_role)))
        assert c.execute('select * from merchant_store').fetchall() == []
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute('select password_hash from merchant_user')


def test_session_switch_rejects_other_user_membership_and_logout_revokes(merchant):
    a, at = account(merchant)
    b, bt = account(merchant, 'owner-b@test.invalid')
    with pytest.raises(MerchantError) as error:
        merchant.switch_tenant(at, {'membershipId': b['membershipId']}, a['csrfToken'])
    assert error.value.status == 404
    merchant.logout(at, a['csrfToken'])
    with pytest.raises(MerchantError) as error:
        merchant.session(at)
    assert error.value.status == 401


def test_invitation_operator_scope_last_owner_and_revocation(merchant):
    owner, token = account(merchant)
    store = merchant.save_store(token, {'name': 'Selected store'}, owner['csrfToken'], 'test')
    merchant.invite(token, {'email': 'operator@test.invalid', 'role': 'OPERATOR',
                           'storeScope': {'mode': 'SELECTED', 'storeIds': [store['id']]}}, owner['csrfToken'], 'test')
    invite_token = email_token(merchant, 'operator@test.invalid')
    merchant.accept_invitation(None, {'token': invite_token, 'displayName': 'Operator', 'password': PASSWORD}, 'ip')
    operator, ot = merchant.login({'email': 'operator@test.invalid', 'password': PASSWORD}, 'ip')
    assert 'payments.manage' not in operator['permissions']
    assert len(merchant.stores(ot)) == 1
    with pytest.raises(MerchantError) as error:
        merchant.save_store(ot, {'name': 'Forbidden'}, operator['csrfToken'], 'test')
    assert error.value.status == 403
    with pytest.raises(MerchantError) as error:
        merchant.update_member(token, owner['membershipId'], {'role': 'FINANCE', 'version': 1}, owner['csrfToken'], 'test')
    assert error.value.code == 'LAST_OWNER'
    merchant.update_member(token, operator['membershipId'], {'status': 'SUSPENDED', 'version': 1}, owner['csrfToken'], 'test')
    with pytest.raises(MerchantError):
        merchant.session(ot)


def test_password_reset_revokes_existing_sessions_and_consumes_token(merchant):
    session, token = account(merchant)
    merchant.forgot_password({'email': session['user']['email']}, 'ip')
    reset = email_token(merchant, session['user']['email'])
    assert merchant.reset_password({'token': reset, 'password': 'a-new-secure-password-2026'}, 'ip')['status'] == 'UPDATED'
    with pytest.raises(MerchantError):
        merchant.session(token)
    with pytest.raises(MerchantError):
        merchant.reset_password({'token': reset, 'password': 'a-new-secure-password-2026'}, 'ip')


def test_http_cookie_origin_csrf_and_admin_token_separation(merchant):
    app = FastAPI()
    app.include_router(create_router(merchant))
    @app.middleware('http')
    async def request_id(request: Request, call_next):
        request.state.request_id = 'test'
        return await call_next(request)
    @app.exception_handler(MerchantError)
    async def error_handler(request, error):
        return JSONResponse(status_code=error.status, content={'error': {'code': error.code}})
    account(merchant)
    with TestClient(app, base_url='https://testserver') as client:
        assert client.get('/api/v1/merchant/session', headers={'Authorization': 'Bearer '+merchant.settings.admin_token}).status_code == 401
        login = client.post('/api/v1/merchant/auth/login', json={'email': 'owner-a@test.invalid', 'password': PASSWORD}, headers={'Origin': 'https://testserver'})
        assert login.status_code == 200
        assert 'HttpOnly' in login.headers['set-cookie'] and 'Secure' in login.headers['set-cookie']
        csrf = login.json()['data']['csrfToken']
        assert client.post('/api/v1/merchant/stores', json={'name': 'X'}, headers={'Origin': 'https://evil.invalid', 'X-CSRF-Token': csrf}).status_code == 403
        assert client.post('/api/v1/merchant/stores', json={'name': 'X'}, headers={'Origin': 'https://testserver'}).status_code == 403
        assert client.post('/api/v1/merchant/stores', json={'name': 'X'}, headers={'Origin': 'https://testserver', 'X-CSRF-Token': csrf}).status_code == 200


def test_mail_unconfigured_fails_before_creating_user(merchant):
    merchant.settings.merchant_smtp_host = None
    with pytest.raises(MerchantError) as error:
        merchant.register({'email': 'no-mail@test.invalid', 'password': PASSWORD, 'displayName': 'N', 'tenantName': 'N'}, 'ip')
    assert error.value.code == 'MAIL_UNAVAILABLE'
    with merchant.database.connect() as c:
        assert c.execute('select count(*) as n from merchant_user').fetchone()['n'] == 0
