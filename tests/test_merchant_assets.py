import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.merchant.assets import MerchantAssets, LEGACY_TENANT
from app.merchant.orders import MerchantOrders
from app.merchant.security import MerchantError
from test_merchant_identity import merchant, account


def terminal(service):
    with service.database.connect() as c:
        return c.execute("insert into terminal(device_id,serial_number,lifecycle_status) values(%s,%s,'ACTIVE') returning *",
                         ('device-'+uuid.uuid4().hex,'serial-'+uuid.uuid4().hex)).fetchone()


def claim(service,session,token,device):
    assets=MerchantAssets(service)
    code=assets.issue_claim(device['id'])['claimCode']
    store=service.save_store(token,{'name':'Store'},session['csrfToken'],'test')
    data={'claimCode':code,'storeId':store['id'],'name':'Owned machine'}
    return assets.claim(token,data,session['csrfToken'],'claim-key','test'),data


def insert_order(service,device,status='READY'):
    order_id=uuid.uuid4()
    with service.database.connect() as c:
        c.execute("""insert into sales_order(id,order_no,terminal_id,access_token_hash,idempotency_key,request_digest,status,
            payment_mode,payment_status,currency,total_amount_minor,recipe_id,recipe_version,product_name,product_snapshot)
            values(%s,%s,%s,%s,%s,%s,%s,'TEST_FREE','NOT_REQUIRED','CNY',100,'coffee','v1','Coffee',%s)""",
            (order_id,'order-'+uuid.uuid4().hex,device['id'],uuid.uuid4().hex*2,str(uuid.uuid4()),'f'*64,status,Jsonb({})))
    return order_id


def test_claim_is_single_use_idempotent_and_does_not_transfer_old_orders(merchant):
    session,token=account(merchant)
    device=terminal(merchant)
    historical=insert_order(merchant,device)
    owned,data=claim(merchant,session,token,device)
    assets=MerchantAssets(merchant)
    assert assets.claim(token,data,session['csrfToken'],'claim-key','test') == owned
    assert assets.devices(token,{},owned['id'])['name']=='Owned machine'
    with merchant.database.connect() as c:
        assert c.execute('select tenant_id from sales_order where id=%s',(historical,)).fetchone()['tenant_id']==LEGACY_TENANT
        assert c.execute('select count(*) as n from merchant_device_ownership where terminal_id=%s and valid_until is null',(device['id'],)).fetchone()['n']==1
    b,bt=account(merchant,'owner-b@test.invalid')
    with pytest.raises(MerchantError):assets.claim(bt,data,b['csrfToken'],'steal','test')
    with pytest.raises(MerchantError) as error:assets.devices(bt,{},owned['id'])
    assert error.value.status==404


def test_order_ownership_is_frozen_and_foreign_orders_are_hidden(merchant):
    a,at=account(merchant); b,bt=account(merchant,'owner-b@test.invalid')
    device=terminal(merchant);owned,_=claim(merchant,a,at,device)
    order_id=insert_order(merchant,device)
    orders=MerchantOrders(merchant)
    assert orders.orders(at,{},str(order_id))['deviceNameSnapshot']=='Owned machine'
    with pytest.raises(MerchantError):orders.orders(bt,{},str(order_id))
    with merchant.database.connect() as c:
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute('update sales_order set tenant_id=%s where id=%s',(uuid.UUID(b['tenant']['id']),order_id))


def test_transfer_freezes_orders_requires_recipient_and_can_be_cancelled(merchant):
    a,at=account(merchant);b,bt=account(merchant,'owner-b@test.invalid')
    device=terminal(merchant);owned,_=claim(merchant,a,at,device)
    assets=MerchantAssets(merchant)
    transfer=assets.transfer(at,owned['id'],{'targetTenantReference':b['tenant']['id'],'reason':'Transfer','ownershipVersion':owned['ownershipVersion']},a['csrfToken'],'transfer-key','test')
    assert transfer['status']=='PENDING_RECIPIENT'
    with pytest.raises(psycopg.errors.CheckViolation):insert_order(merchant,device,'CREATED')
    with pytest.raises(MerchantError):assets.transfer_action(at,transfer['id'],{'version':1},a['csrfToken'],'test','accept')
    accepted=assets.transfer_action(bt,transfer['id'],{'version':1},b['csrfToken'],'test','accept')
    assert accepted['status']=='PENDING_PLATFORM'
    assert assets.transfer_action(at,transfer['id'],{'version':2},a['csrfToken'],'test','cancel')['status']=='CANCELLED'
    assert insert_order(merchant,device)


def test_busy_device_transfer_and_archiving_populated_store_are_rejected(merchant):
    a,at=account(merchant);b,bt=account(merchant,'owner-b@test.invalid')
    device=terminal(merchant);owned,_=claim(merchant,a,at,device)
    insert_order(merchant,device,'QUEUED')
    with pytest.raises(MerchantError) as error:
        MerchantAssets(merchant).transfer(at,owned['id'],{'targetTenantReference':b['tenant']['id'],'reason':'Transfer','ownershipVersion':owned['ownershipVersion']},a['csrfToken'],'transfer','test')
    assert error.value.code=='DEVICE_BUSY'
    store=merchant.stores(at)[0]
    assert store['deviceCount']==1
    with pytest.raises(MerchantError) as error:
        merchant.save_store(at,{'name':store['name'],'status':'ARCHIVED','version':1},a['csrfToken'],'test',store['id'])
    assert error.value.code=='STORE_HAS_DEVICES'
