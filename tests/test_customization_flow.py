import importlib.util
import json
from copy import deepcopy
from pathlib import Path
import uuid
import pytest
from psycopg.types.json import Jsonb
from app.customization import select_variant, issue_quote, check_quote
from app.db import UnitOfWork
from app.protocol import PublicOrderCreateRequest
from app.services.errors import ServiceError
from app.services.public_orders import PublicOrderService
from app.settings import Settings
from test_postgres_integration import postgres_database, insert_terminal

ROOT = Path(__file__).resolve().parents[2] / 'coffee-terminal-simulator'
spec = importlib.util.spec_from_file_location('terminal_compiler', ROOT / 'coffee-terminal/customization.py')
compiler = importlib.util.module_from_spec(spec); spec.loader.exec_module(compiler)


def recipe():
    return json.loads((ROOT / 'config/instances/coffee-bot-003/recipes/iced-vanilla-latte.json').read_text())


@pytest.fixture
def custom_case(postgres_database):
    db = postgres_database; r = recipe(); v = compiler.variants(r)
    product = dict(recipeId=r['recipeId'], version=r['version'], skuCode=r['skuCode'], name=r['name'],
                   priceMinor=2300, available=True, maxServings=1, materialRequirements=v[-1]['materialRequirements'],
                   optionSchema=r['optionSchema'], customizationVariants=v)
    inventory = {'inventoryVersion':1,'materials':[{'materialId':mid,'available':amount} for mid,amount in compiler.variants(r)[-1]['materialRequirements'].items()]}
    with db.connect() as c:
        tid = insert_terminal(c)
        c.execute("update terminal set lifecycle_status='ACTIVE',connection_status='online',last_heartbeat_at=now() where id=%s",(tid,))
        for kind, value in [('capabilities', {'products':[product]}),('inventory', inventory)]:
            c.execute('insert into terminal_snapshot(terminal_id,snapshot_type,payload_json) values(%s,%s,%s)',(tid,kind,Jsonb(value)))
    settings = Settings.model_construct(admin_token='test-secret',public_payment_mode='TEST_FREE')
    service = PublicOrderService(UnitOfWork(db),settings,request_dispatch=lambda *args:None,payment_provider=lambda _:None)
    return db,service,tid,r


def payload(r, **options):
    return PublicOrderCreateRequest(recipeId=r['recipeId'], recipeVersion=r['version'],paymentMode='TEST_FREE',customization=options)


def test_quote_freeze_dispatch_and_idempotency(custom_case):
    db,service,tid,r=custom_case
    request=payload(r,sugar='NONE',ice='NONE',milk='NONE')
    quote=service.quote('test-device',request)
    assert quote['available']
    assert all(mid not in quote['product']['materialRequirements'] for mid in ('milk','ice','vanilla-syrup'))
    request.quoteId=quote['quoteId']
    created=service.create('test-device',request,'custom-key')
    assert created['product']['customization']=={'sugar':'NONE','ice':'NONE','milk':'NONE'}
    assert service.create('test-device',request,'custom-key')['duplicate']
    with pytest.raises(ServiceError) as error:
        service.create('test-device',payload(r,sugar='EXTRA'),'custom-key')
    assert error.value.status_code==409
    from app.services.production import ProductionService
    with db.connect() as c:
        ProductionService(service.settings,payment_provider=lambda _:None).dispatch_next_order(c,tid)
        command=c.execute("select payload_json from terminal_command where terminal_id=%s",(tid,)).fetchone()['payload_json']
        assert command['customization']==created['product']['customization']
        assert command['compiledRecipeDigest']==compiler.compile_recipe(r, command['customization'])['compiledRecipeDigest']


def test_price_change_expiry_and_tampering_require_new_quote(custom_case):
    db,service,tid,r=custom_case; request=payload(r)
    quote=service.quote('test-device',request);request.quoteId=quote['quoteId']
    with db.connect() as c:
        c.execute("update terminal_snapshot set payload_json=jsonb_set(payload_json,'{products,0,priceMinor}','2500') where terminal_id=%s and snapshot_type='capabilities'",(tid,))
    with pytest.raises(ServiceError) as error:service.create('test-device',request,'changed-price')
    assert error.value.detail['code']=='QUOTE_CHANGED'
    for token in [quote['quoteId']+'x',issue_quote('secret','test-device',quote['product'],'TEST_FREE',expires=1)]:
        with pytest.raises(ServiceError):check_quote(token,'secret','test-device',quote['product'],'TEST_FREE')


def test_customization_without_quote_and_unsupported_options_rejected(custom_case):
    _,service,_,r=custom_case
    with pytest.raises(ServiceError):service.create('test-device',payload(r),'no-quote')
    from pydantic import ValidationError
    with pytest.raises(ValidationError):payload(r, milk='EXTRA')


def test_no_milk_variant_remains_available_with_no_milk_stock(custom_case):
    db,service,tid,r=custom_case
    with db.connect() as c:
        c.execute("update terminal_snapshot set payload_json=jsonb_set(payload_json,'{materials}',(select jsonb_agg(case when m->>'materialId'='milk' then jsonb_set(m,'{available}','0') else m end) from jsonb_array_elements(payload_json->'materials') m)) where terminal_id=%s and snapshot_type='inventory'",(tid,))
    assert service.menu('test-device')['products'][0]['available']
    assert service.quote('test-device',payload(r,milk='NONE'))['available']
    assert not service.quote('test-device',payload(r,milk='STANDARD'))['available']


def test_concurrent_custom_orders_compete_for_last_milk(custom_case):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    _,service,_,r=custom_case
    request=payload(r,sugar='NONE',ice='NONE',milk='STANDARD')
    request.quoteId=service.quote('test-device',request)['quoteId']
    barrier=Barrier(2)
    def create(key):
        barrier.wait()
        try:return service.create('test-device',request,key)
        except ServiceError as exc:return exc.status_code
    with ThreadPoolExecutor(2) as executor:results=list(executor.map(create,['race-a','race-b']))
    assert sum(isinstance(result,dict) for result in results)==1
    assert 409 in results


def test_online_order_keeps_quote_and_debug_default_is_compiled(custom_case):
    db,service,tid,r=custom_case
    service.settings.public_payment_mode='ONLINE'
    request=payload(r,milk='NONE');request.paymentMode='ONLINE'
    request.quoteId=service.quote('test-device',request)['quoteId']
    created=service.create('test-device',request,'online-custom')
    assert created['status']=='CREATED'
    assert created['product']['customization']['milk']=='NONE'
    assert created['totalAmountMinor']==2300
    from app.services.commands import CommandService
    commands=CommandService(UnitOfWork(db),lease_seconds=30,transition_command=lambda *a,**k:None)
    debug=commands.create_debug_order({'id':tid,'device_id':'test-device'},r['recipeId'])['command']
    assert debug['compiledRecipeDigest']==compiler.compile_recipe(r)['compiledRecipeDigest']
    assert all(value=='STANDARD' for value in debug['customization'].values())


def test_disabled_template_cannot_be_reenabled_by_selecting_no_milk(custom_case):
    db,service,tid,r=custom_case
    with db.connect() as c:
        c.execute("update terminal_snapshot set payload_json=jsonb_set(payload_json,'{products,0,enabled}','false') where terminal_id=%s and snapshot_type='capabilities'",(tid,))
    assert not service.menu('test-device')['products'][0]['available']
    assert not service.quote('test-device',payload(r,milk='NONE'))['available']


def test_latte_quote_to_terminal_execution_and_cloud_completion(custom_case, tmp_path):
    """Actual hot-latte recipe across quote, dispatch, isolated runtime and event reconciliation."""
    import subprocess, shutil
    from app.services.production import ProductionService
    from app.production_state import EVENT_TARGETS
    db,service,tid,_ = custom_case
    r=json.loads((ROOT/'config/instances/coffee-bot-003/recipes/latte.json').read_text())
    variants=compiler.variants(r)
    product=dict(recipeId=r['recipeId'],version=r['version'],skuCode=r['skuCode'],name=r['name'],
        priceMinor=1800,available=True,maxServings=10,materialRequirements=variants[-1]['materialRequirements'],
        optionSchema=r['optionSchema'],customizationVariants=variants)
    with db.connect() as c:
        c.execute("update terminal_snapshot set payload_json=%s where terminal_id=%s and snapshot_type='capabilities'",(Jsonb({'products':[product]}),tid))
        c.execute("update terminal_snapshot set payload_json=%s where terminal_id=%s and snapshot_type='inventory'",(Jsonb({'materials':[{'materialId':mid,'available':amount*10} for mid,amount in variants[-1]['materialRequirements'].items()]}),tid))
    request=payload(r,milk='STANDARD')
    request.quoteId=service.quote('test-device',request)['quoteId']
    created=service.create('test-device',request,'art-end-to-end')
    production=ProductionService(service.settings,payment_provider=lambda _:None)
    with db.connect() as c: command=production.dispatch_next_order(c,tid)
    shutil.copytree(ROOT/'config/instances/coffee-bot-003/recipes',tmp_path/'recipes')
    shutil.copy(ROOT/'config/instances/coffee-bot-003/materials.json',tmp_path/'materials.json')
    (tmp_path/'failures.json').write_text(json.dumps({'globalFailureRate':0,'profiles':{},'stepOverrides':{}}))
    terminal_python=ROOT/'.venv/bin/python'
    if not terminal_python.exists():pytest.skip('terminal runtime environment is required for cross-process acceptance')
    script="""
import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from backend import CoffeeDeviceRuntime
runtime=CoffeeDeviceRuntime({'deviceId':'test-device','storeId':'test','backend':{'mode':'local'},'localApi':{'enabled':False}},Path(sys.argv[2]))
try:
    with runtime.lock:
        accepted=runtime._accept_task(json.load(sys.stdin))
        assert accepted['ok'],accepted
        for _ in range(10):runtime._execution_tick(120)
        assert runtime.runtime['task']['state']=='SUCCEEDED'
        print(json.dumps(list(reversed(runtime.events))))
finally:runtime.close()
"""
    result=subprocess.run([str(terminal_python),'-c',script,str(ROOT/'coffee-terminal'),str(tmp_path)],
        input=json.dumps(command),capture_output=True,text=True,timeout=30,check=True)
    for e in json.loads(result.stdout):
        if e['type'] in EVENT_TARGETS or e['type']=='task.progress':
            with db.connect() as c:production.reconcile_device_event(c,tid,e,e['type'])
    with db.connect() as c:
        order=c.execute('select status,failure_code from sales_order where id=%s',(created['orderId'],)).fetchone()
        assert order=={'status':'READY','failure_code':None}
        job=c.execute('select step_durations from production_job where order_id=%s',(created['orderId'],)).fetchone()
        assert any(step['visual']['actions']==['latte-art'] for step in job['step_durations'])
