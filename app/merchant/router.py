from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, Body, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response

from .security import MerchantError
from .assets import MerchantAssets
from .orders import MerchantOrders
from .accounts import MerchantAccounts
from .costs import MerchantCosts
from .catalog import MerchantCatalog
from .reports import MerchantReports


def create_router(service):
    router = APIRouter(prefix='/api/v1/merchant', tags=['merchant'])
    settings = service.settings
    assets = MerchantAssets(service)
    orders = MerchantOrders(service)
    accounts = MerchantAccounts(service)
    costs = MerchantCosts(service)
    catalog = MerchantCatalog(service)
    reports = MerchantReports(service)
    cookie_name = '__Host-coffee_session' if settings.merchant_cookie_secure else 'coffee_session_dev'

    def token(request):
        return request.cookies.get(cookie_name)

    def remote(request):
        return request.client.host if request.client else 'unknown'

    def csrf(request):
        origin = request.headers.get('origin', '')
        expected = urlsplit(settings.public_base_url)
        if origin != f'{expected.scheme}://{expected.netloc}':
            raise MerchantError(403, 'ORIGIN_INVALID', '请求来源校验失败')
        if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
            raise MerchantError(415, 'JSON_REQUIRED', '请使用 JSON 请求')
        return request.headers.get('x-csrf-token', '')

    def result(data):
        return {'data': data}

    def listing(data):
        return {'data': data, 'meta': {'nextCursor': None, 'total': len(data)}}

    @router.get('/auth/config')
    def auth_config():
        return result(service.auth_config())

    @router.post('/auth/register')
    def register(request: Request, data: dict = Body(...)):
        csrf(request)
        return result(service.register(data, remote(request)))

    @router.post('/auth/verify-email')
    def verify(request: Request, data: dict = Body(...)):
        csrf(request)
        service.rate_limit('verify', remote(request))
        return result(service.verify_email(data))

    @router.post('/auth/login')
    def login(request: Request, data: dict = Body(...)):
        csrf(request)
        payload, value = service.login(data, remote(request))
        response = JSONResponse(jsonable_encoder(result(payload)))
        response.set_cookie(cookie_name, value, httponly=True, secure=settings.merchant_cookie_secure,
                            samesite='lax', path='/', max_age=settings.merchant_session_hours*3600)
        return response

    @router.get('/session')
    def session(request: Request):
        return result(service.session(token(request)))

    @router.post('/session/tenant')
    def switch(request: Request, data: dict = Body(...)):
        return result(service.switch_tenant(token(request), data, csrf(request)))

    @router.post('/auth/logout')
    def logout(request: Request):
        payload = service.logout(token(request), csrf(request))
        response = JSONResponse(result(payload))
        response.delete_cookie(cookie_name, path='/', secure=settings.merchant_cookie_secure, httponly=True, samesite='lax')
        return response

    @router.post('/auth/revoke-other-sessions')
    def revoke_others(request: Request):
        return result(service.logout(token(request), csrf(request), others=True))

    @router.post('/auth/reauthenticate')
    def reauthenticate(request: Request, data: dict = Body(...)):
        return result(service.reauthenticate(token(request), data, csrf(request), remote(request)))

    @router.post('/auth/forgot-password')
    def forgot(request: Request, data: dict = Body(...)):
        csrf(request)
        return result(service.forgot_password(data, remote(request)))

    @router.post('/auth/reset-password')
    def reset(request: Request, data: dict = Body(...)):
        csrf(request)
        return result(service.reset_password(data, remote(request)))

    @router.post('/auth/accept-invitation')
    def accept(request: Request, data: dict = Body(...)):
        return result(service.accept_invitation(token(request), data, remote(request), csrf(request)))

    @router.get('/stores')
    def stores(request: Request):
        return listing(service.stores(token(request)))

    @router.post('/stores')
    def create_store(request: Request, data: dict = Body(...)):
        return result(service.save_store(token(request), data, csrf(request), request.state.request_id))

    @router.patch('/stores/{store_id}')
    def update_store(store_id: str, request: Request, data: dict = Body(...)):
        return result(service.save_store(token(request), data, csrf(request), request.state.request_id, store_id))

    @router.get('/tenant')
    def tenant(request: Request):
        return result(service.tenant(token(request)))

    @router.patch('/tenant')
    def update_tenant(request: Request, data: dict = Body(...)):
        return result(service.tenant(token(request), data, csrf(request), request.state.request_id))

    @router.get('/members')
    def members(request: Request):
        return listing(service.members(token(request)))

    @router.patch('/members/{member_id}')
    def update_member(member_id: str, request: Request, data: dict = Body(...)):
        return result(service.update_member(token(request), member_id, data, csrf(request), request.state.request_id))

    @router.get('/invitations')
    def invitations(request: Request):
        return listing(service.invitations(token(request)))

    @router.post('/invitations')
    def invite(request: Request, data: dict = Body(...)):
        return result(service.invite(token(request), data, csrf(request), request.state.request_id))

    @router.post('/invitations/{invitation_id}/revoke')
    def revoke_invite(invitation_id: str, request: Request):
        return result(service.revoke_invitation(token(request), invitation_id, csrf(request), request.state.request_id))

    @router.get('/devices')
    def devices(request: Request):
        return listing(assets.devices(token(request), dict(request.query_params)))

    @router.post('/devices/claim')
    def claim(request: Request, data: dict = Body(...)):
        return result(assets.claim(token(request),data,csrf(request),request.headers.get('idempotency-key'),request.state.request_id))

    @router.get('/devices/{device_id}')
    def device(device_id: str, request: Request):
        return result(assets.devices(token(request),{},device_id))

    @router.patch('/devices/{device_id}')
    def update_device(device_id: str, request: Request, data: dict = Body(...)):
        return result(assets.update(token(request),device_id,data,csrf(request),request.state.request_id))

    @router.post('/devices/{device_id}/lifecycle')
    def lifecycle(device_id: str, request: Request, data: dict = Body(...)):
        return result(assets.update(token(request),device_id,data,csrf(request),request.state.request_id,lifecycle=True))

    @router.post('/devices/{device_id}/commands')
    def command(device_id: str, request: Request, data: dict = Body(...)):
        return result(assets.command(token(request),device_id,data,csrf(request),request.headers.get('idempotency-key'),request.state.request_id))

    @router.get('/devices/{device_id}/commands/{command_id}')
    def command_status(device_id: str, command_id: str, request: Request):
        return result(assets.command(token(request),device_id,{},None,None,request.state.request_id,command_id))

    @router.post('/devices/{device_id}/transfer-requests')
    def transfer(device_id: str, request: Request, data: dict = Body(...)):
        return result(assets.transfer(token(request),device_id,data,csrf(request),request.headers.get('idempotency-key'),request.state.request_id))

    @router.post('/devices/{device_id}/unbind-requests')
    def unbind(device_id: str, request: Request, data: dict = Body(...)):
        return result(assets.transfer(token(request),device_id,data,csrf(request),request.headers.get('idempotency-key') or 'unbind-'+str(data.get('ownershipVersion')),request.state.request_id,unbind=True))

    @router.get('/transfers')
    def transfers(request: Request):
        return listing(assets.transfers(token(request)))

    @router.post('/transfers/{transfer_id}/accept')
    def accept_transfer(transfer_id: str, request: Request, data: dict = Body(...)):
        return result(assets.transfer_action(token(request),transfer_id,data,csrf(request),request.state.request_id,'accept'))

    @router.post('/transfers/{transfer_id}/cancel')
    def cancel_transfer(transfer_id: str, request: Request, data: dict = Body(...)):
        return result(assets.transfer_action(token(request),transfer_id,data,csrf(request),request.state.request_id,'cancel'))

    @router.get('/orders')
    def order_list(request: Request):
        return orders.orders(token(request),dict(request.query_params))

    @router.get('/orders/{order_id}')
    def order_detail(order_id: str, request: Request):
        return result(orders.orders(token(request),{},order_id))

    @router.post('/orders/{order_id}/refunds')
    def refund(order_id: str, request: Request, data: dict = Body(...)):
        return result(orders.refund(token(request),order_id,data,csrf(request),request.headers.get('idempotency-key'),request.state.request_id))

    @router.get('/payment-accounts')
    def payment_accounts(request: Request):
        return listing(accounts.list(token(request)))

    @router.post('/payment-accounts')
    def create_account(request: Request, data: dict = Body(...)):
        return result(accounts.create(token(request),data,csrf(request),request.state.request_id))

    @router.post('/payment-accounts/{account_id}/{action}')
    def account_action(account_id: str, action: str, request: Request, data: dict = Body(...)):
        return result(accounts.action(token(request),account_id,data,csrf(request),request.state.request_id,action))

    @router.get('/materials')
    def materials(request: Request):
        return listing(costs.materials(token(request)))

    @router.post('/materials')
    def create_material(request: Request, data: dict = Body(...)):
        return result(costs.materials(token(request),data,csrf(request),request.state.request_id))

    @router.get('/purchases')
    def purchases(request: Request):
        return listing(costs.purchases(token(request),dict(request.query_params)))

    @router.post('/purchases')
    def create_purchase(request: Request, data: dict = Body(...)):
        return result(costs.save_purchase(token(request),data,csrf(request),request.headers.get('idempotency-key'),request.state.request_id))

    @router.patch('/purchases/{purchase_id}')
    def update_purchase(purchase_id: str, request: Request, data: dict = Body(...)):
        return result(costs.save_purchase(token(request),data,csrf(request),None,request.state.request_id,purchase_id))

    @router.post('/purchases/{purchase_id}/post')
    def post_purchase(purchase_id: str, request: Request, data: dict = Body(...)):
        return result(costs.post_purchase(token(request),purchase_id,data,csrf(request),request.state.request_id))

    @router.get('/inventory')
    def inventory(request: Request):
        return listing(costs.inventory(token(request),dict(request.query_params)))

    @router.get('/inventory/movements')
    def movements(request: Request):
        return listing(costs.inventory(token(request),dict(request.query_params),movements=True))

    @router.post('/inventory/movements')
    def create_movement(request: Request, data: dict = Body(...)):
        return result(costs.movement(token(request),data,csrf(request),request.headers.get('idempotency-key'),request.state.request_id))

    @router.get('/expenses')
    def expenses(request: Request):
        return listing(costs.expenses(token(request),dict(request.query_params)))

    @router.post('/expenses')
    def create_expense(request: Request, data: dict = Body(...)):
        return result(costs.create_expense(token(request),data,csrf(request),request.headers.get('idempotency-key'),request.state.request_id))

    @router.post('/expenses/{expense_id}/post')
    def post_expense(expense_id: str, request: Request, data: dict = Body(...)):
        return result(costs.expense_action(token(request),expense_id,data,csrf(request),request.state.request_id))

    @router.post('/expenses/{expense_id}/reversals')
    def reverse_expense(expense_id: str, request: Request, data: dict = Body(...)):
        return result(costs.expense_action(token(request),expense_id,data,csrf(request),request.state.request_id,reverse=True))

    @router.get('/prices')
    def prices(request: Request):
        return listing(catalog.prices(token(request),dict(request.query_params)))

    @router.post('/prices')
    def create_price(request: Request, data: dict = Body(...)):
        return result(catalog.prices(token(request),{},data,csrf(request),request.state.request_id))

    @router.get('/dashboard')
    def dashboard(request: Request):
        return result(reports.dashboard(token(request),dict(request.query_params)))

    @router.get('/reports/operating')
    def operating(request: Request):
        return result(reports.operating(token(request),dict(request.query_params)))

    @router.get('/reports/operating.csv')
    def operating_csv(request: Request):
        return Response(reports.csv(token(request),dict(request.query_params)),media_type='text/csv',
                        headers={'Content-Disposition':'attachment; filename="operating-report.csv"'})

    @router.get('/audit')
    def audit(request: Request):
        return reports.audit(token(request),dict(request.query_params))

    return router
