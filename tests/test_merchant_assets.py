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


def test_recovery_alert_covers_debug_task_and_clears_after_review(merchant):
    session,token=account(merchant)
    device=terminal(merchant);owned,_=claim(merchant,session,token,device)
    task='recovery-'+uuid.uuid4().hex
    recovery={'taskId':task,'taskKind':'DEBUG','detectedAt':'2026-09-12T00:00:00Z',
              'stepId':'lid','stepName':'封杯并出杯','reason':'制作中断，等待现场人工核验','reasonCode':'DEVICE_RESTARTED_OUTCOME_UNKNOWN'}
    with merchant.database.connect() as c:
        c.execute("update terminal set reported_status=%s,last_seen_at=now() where id=%s",
                  (Jsonb({'deviceStatus':'RECOVERING','currentTaskId':task,'recovery':recovery}),device['id']))
        c.execute("""insert into terminal_command(terminal_id,message_id,command_type,payload_json,status)
                  values(%s,%s,'MAKE_DRINK',%s,'UNKNOWN')""",
                  (device['id'],'cmd-'+uuid.uuid4().hex,Jsonb({'taskId':task,'orderId':'debug-test'})))
    assets=MerchantAssets(merchant)
    alert=assets.devices(token,{},owned['id'])['alerts'][0]
    assert alert['taskKind']=='DEBUG' and alert['stepName']=='封杯并出杯'
    assert alert['occurredAt']=='2026-09-12T00:00:00Z'
    assert len(assets.devices(token,{})[0]['alerts'])==1
    from app.merchant.reports import MerchantReports
    dashboard=MerchantReports(merchant).dashboard(token,{'from':'2026-09-12','to':'2026-09-13'})
    assert any(a.get('taskId')==task for a in dashboard['alerts'])
    other,other_token=account(merchant,'other-review@test.invalid')
    assert assets.devices(other_token,{})==[]
    with pytest.raises(MerchantError): assets.devices(other_token,{},owned['id'])
    with merchant.database.connect() as c:
        c.execute("update terminal_command set status='CANCELLED' where terminal_id=%s",(device['id'],))
        c.execute("update terminal set reported_status=%s where id=%s",(Jsonb({'deviceStatus':'IDLE','recovery':None}),device['id']))
    assert assets.devices(token,{},owned['id'])['alerts']==[]


def test_legacy_unknown_command_appears_without_new_heartbeat(merchant):
    session,token=account(merchant)
    device=terminal(merchant);owned,_=claim(merchant,session,token,device)
    task='legacy-'+uuid.uuid4().hex
    with merchant.database.connect() as c:
        command=c.execute("""insert into terminal_command(terminal_id,message_id,command_type,payload_json,status)
            values(%s,%s,'MAKE_DRINK',%s,'UNKNOWN') returning id""",
            (device['id'],'cmd-'+uuid.uuid4().hex,Jsonb({'taskId':task,'orderId':'debug-test'}))).fetchone()
        c.execute("""insert into terminal_command_transition(command_id,revision,to_status,actor,payload_json)
            values(%s,1,'UNKNOWN','device-event',%s)""",(command['id'],Jsonb({'occurredAt':'2026-09-11T12:00:00Z','payload':{'taskId':task,'orderId':'debug-test'}})))
    alert=MerchantAssets(merchant).devices(token,{},owned['id'])['alerts'][0]
    assert alert['taskKind']=='DEBUG' and alert['occurredAt']=='2026-09-11T12:00:00Z'
    assert alert['stepName']=='未记录'
