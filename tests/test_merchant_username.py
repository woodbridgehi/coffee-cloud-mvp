import uuid

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.merchant.http import MerchantBoundary
from app.merchant.router import create_router
from app.merchant.security import MerchantError
from app.merchant.assets import MerchantAssets
from app.merchant.accounts import MerchantAccounts
from test_merchant_identity import merchant, account, PASSWORD


def enable_username(service):
    service.settings.merchant_registration_mode = 'USERNAME'
    service.settings.merchant_limited_release = True
    service.settings.merchant_smtp_host = None


def register(service, name='coffee.owner', **extra):
    return service.register({'username': name, 'password': PASSWORD,
                             'displayName': name, 'tenantName': 'Coffee company', **extra}, 'test-ip')


def test_username_registration_is_atomic_normalized_and_does_not_verify_email(merchant):
    enable_username(merchant)
    assert register(merchant, ' Coffee.Owner ', email='unverified@example.com', role='ADMIN', tenantId=str(uuid.uuid4())) == {'status': 'REGISTERED'}
    session, token = merchant.login({'username': 'COFFEE.OWNER', 'password': PASSWORD}, 'ip')
    assert session['user']['username'] == 'coffee.owner'
    assert session['user']['email'] is None
    assert 'devices.transfer' not in session['permissions']
    assert 'payments.manage' not in session['permissions']
    assert 'members.manage' in session['permissions']
    assert len(session['memberships']) == 1
    assert session['memberships'][0]['role'] == 'OWNER'
    with merchant.database.connect() as c:
        user = c.execute('select * from merchant_user').fetchone()
        assert user['verified_at'] is None and user['email'] is None
        assert c.execute('select count(*) as n from merchant_mail_outbox').fetchone()['n'] == 0
    with pytest.raises(MerchantError) as error:
        register(merchant, 'coffee.owner')
    assert error.value.code == 'USERNAME_TAKEN'
    assert merchant.members(token)[0]['username'] == 'coffee.owner'
    merchant.validate_runtime()


@pytest.mark.parametrize('name', ['', 'ab', '1owner', 'user@example.com', 'a b', '../admin', 'a'*33, None])
def test_username_invalid_input_cannot_create_an_account(merchant, name):
    enable_username(merchant)
    with pytest.raises(MerchantError) as error:
        register(merchant, name)
    assert error.value.code == 'INVALID_USERNAME'
    with merchant.database.connect() as c:
        assert c.execute('select count(*) as n from merchant_user').fetchone()['n'] == 0


def test_username_tenants_cannot_read_each_others_stores_and_cannot_bypass_feature_gates(merchant):
    enable_username(merchant)
    register(merchant, 'owner-a'); register(merchant, 'owner-b')
    a, at = merchant.login({'username': 'owner-a', 'password': PASSWORD}, 'ip')
    b, bt = merchant.login({'username': 'owner-b', 'password': PASSWORD}, 'ip')
    store = merchant.save_store(at, {'name': 'A private store'}, a['csrfToken'], 'test')
    assert merchant.stores(bt) == []
    with pytest.raises(MerchantError) as error:
        merchant.save_store(bt, {'name': 'Stolen', 'version': 1}, b['csrfToken'], 'test', store['id'])
    assert error.value.status == 404
    with pytest.raises(MerchantError) as error:
        MerchantAssets(merchant).transfer(at, '1', {}, a['csrfToken'], 'transfer-key', 'test')
    assert error.value.status == 403
    with pytest.raises(MerchantError) as error:
        MerchantAccounts(merchant).action(at, str(uuid.uuid4()), {}, a['csrfToken'], 'test', 'set-default')
    assert error.value.status == 403
    with pytest.raises(MerchantError) as error:
        merchant.invite(at, {'email': 'owner@elsewhere.com'}, a['csrfToken'], 'test')
    assert error.value.code == 'MAIL_UNAVAILABLE'


def test_existing_verified_email_login_keeps_working_after_username_mode_switch(merchant):
    original, _ = account(merchant)
    enable_username(merchant)
    session, _ = merchant.login({'username': original['user']['email'], 'password': PASSWORD}, 'ip')
    assert session['user']['id'] == original['user']['id']
    assert session['user']['username'] is None


def test_public_http_username_flow_cookie_csrf_logout_and_size_limit(merchant):
    enable_username(merchant)
    app = FastAPI()
    app.include_router(create_router(merchant))
    app.add_middleware(MerchantBoundary)
    @app.middleware('http')
    async def request_id(request: Request, call_next):
        request.state.request_id = 'test'
        return await call_next(request)
    @app.exception_handler(MerchantError)
    async def error_handler(request, error):
        return JSONResponse(status_code=error.status, content={'error': {'code': error.code}})
    with TestClient(app, base_url='https://testserver') as client:
        base = '/api/v1/merchant'
        config = client.get(base+'/auth/config')
        assert config.json()['data']['registrationMode'] == 'USERNAME'
        assert config.json()['data']['mailEnabled'] is False
        assert config.headers['cache-control'] == 'no-store'
        origin = {'Origin': 'https://testserver'}
        data = {'username': 'http.owner', 'password': PASSWORD, 'displayName': 'Owner', 'tenantName': 'My company'}
        assert client.post(base+'/auth/register', json=data).status_code == 403
        assert client.post(base+'/auth/register', json=data, headers=origin).json()['data']['status'] == 'REGISTERED'
        bad = client.post(base+'/auth/login', json={'username': 'http.owner', 'password': 'bad'}, headers=origin)
        assert bad.status_code == 401
        login = client.post(base+'/auth/login', json=data, headers=origin)
        assert login.status_code == 200
        assert all(flag in login.headers['set-cookie'] for flag in ['Secure', 'HttpOnly', 'SameSite=lax'])
        headers = {**origin, 'X-CSRF-Token': login.json()['data']['csrfToken']}
        assert client.get(base+'/session').status_code == 200
        assert client.post(base+'/stores', json={'name': 'Http Store'}, headers=headers).status_code == 200
        assert client.get(base+'/stores').json()['data'][0]['name'] == 'Http Store'
        assert client.post(base+'/auth/register', content=b'x'*65537, headers=origin).status_code == 413
        assert client.post(base+'/auth/logout', json={}, headers=headers).status_code == 200
        assert client.get(base+'/session').status_code == 401
