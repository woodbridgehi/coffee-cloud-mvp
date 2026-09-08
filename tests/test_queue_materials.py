from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from copy import deepcopy
import pytest

from psycopg.types.json import Jsonb

from app.material_commitments import apply_commitments
from app.db import UnitOfWork
from app.protocol import PublicOrderCreateRequest
from app.services.public_orders import PublicOrderService
from app.services.errors import ServiceError
from app.settings import Settings
from test_postgres_integration import postgres_database, insert_terminal
from test_production_consistency import production_case, event
from app.repositories.orders import OrderRepository


def test_shared_materials_and_unknown_legacy_commitments():
    menu = {'products': [{'remainingServings': 5, 'materialRequirements': {'milk': 100},
                         'available': True, 'unavailableReasons': []}]}
    inventory = {'materials': [{'materialId': 'milk', 'available': 150}]}
    committed = [{'product_snapshot': {'materialRequirements': {'milk': 100}}}]
    assert not apply_commitments(deepcopy(menu), inventory, committed)['salesEnabled']
    assert not apply_commitments(deepcopy(menu), inventory, [{'product_snapshot': {}}])['salesEnabled']
    assert apply_commitments(deepcopy(menu), inventory, [])['products'][0]['remainingServings'] == 1


def test_final_event_blocks_stale_inventory_until_matching_snapshot(production_case):
    event(production_case, 'task.succeeded', inventoryVersion=12)
    event(production_case, 'inventory.adjusted', inventoryVersion=8)
    db, _, _, identity, _, _ = production_case
    with db.connect() as c:
        required = OrderRepository(c).required_inventory_version(identity['id'])
        assert required == 12
    menu = {'products': [{'remainingServings': 1, 'available': True, 'unavailableReasons': []}]}
    assert not apply_commitments(deepcopy(menu), {'inventoryVersion': 11}, [], required)['salesEnabled']
    assert apply_commitments(deepcopy(menu), {'inventoryVersion': 12}, [], required)['salesEnabled']


@pytest.mark.parametrize('payment_mode', ['TEST_FREE', 'ONLINE'])
def test_concurrent_different_drinks_share_last_milk_and_cancel_releases(postgres_database, payment_mode):
    db = postgres_database
    with db.connect() as c:
        terminal_id = insert_terminal(c)
        c.execute("update terminal set lifecycle_status='ACTIVE',connection_status='online',last_heartbeat_at=now() where id=%s", (terminal_id,))
        products = [{'recipeId': name, 'version': 'v1', 'skuCode': name, 'name': name,
                     'available': True, 'maxServings': 1, 'materialRequirements': {'milk': 100}}
                    for name in ['latte', 'mocha']]
        for kind, payload in [('capabilities', {'products': products}),
                              ('inventory', {'materials': [{'materialId': 'milk', 'available': 100}]})]:
            c.execute('insert into terminal_snapshot(terminal_id,snapshot_type,payload_json) values(%s,%s,%s)',
                      (terminal_id, kind, Jsonb(payload)))
    service = PublicOrderService(UnitOfWork(db), Settings.model_construct(admin_token='test-secret', public_payment_mode=payment_mode),
                                 request_dispatch=lambda *args: None, payment_provider=lambda _: None)
    barrier = Barrier(2)
    def create(name):
        barrier.wait()
        try:
            return service.create('test-device', PublicOrderCreateRequest(recipeId=name, recipeVersion='v1', paymentMode=payment_mode), name)
        except ServiceError as exc:
            return exc.status_code
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(create, ['latte', 'mocha']))
    assert sum(isinstance(r, dict) for r in results) == 1
    assert 409 in results
    accepted = next(r for r in results if isinstance(r, dict))
    import uuid
    service.cancel(uuid.UUID(str(accepted['orderId'])), accepted['accessToken'])
    assert service.menu('test-device')['salesEnabled']


def test_unpaid_without_payment_expires_and_frees_commitment(postgres_database):
    from app.services.background_worker import BackgroundWorkerService
    from app.services.production import ProductionService
    import uuid
    settings = Settings.model_construct()
    with postgres_database.connect() as c:
        terminal_id = insert_terminal(c)
        order_id = uuid.uuid4()
        OrderRepository(c).insert(order_id=order_id, order_no='expiry-test', terminal_id=terminal_id,
            access_token_hash='a'*64, idempotency_key='expiry', request_digest='b'*64,
            order_status='CREATED', payment_mode='ONLINE', payment_status='NOT_STARTED',
            product={'currency':'CNY','priceMinor':100,'recipeId':'latte','recipeVersion':'v1',
                     'skuCode':'LATTE','name':'Latte','materialRequirements':{'milk':100}})
        c.execute("update sales_order set created_at=now()-interval '1 hour' where id=%s", (order_id,))
    worker = BackgroundWorkerService(UnitOfWork(postgres_database), settings, payment_provider=lambda _:None,
        production=ProductionService(settings,payment_provider=lambda _:None))
    worker.offline_scan_once()
    with postgres_database.connect() as c:
        assert OrderRepository(c).find(order_id)['status'] == 'EXPIRED'
        assert OrderRepository(c).material_commitments(terminal_id) == []
