from app.repositories.pickup import PickupRepository
from app.repositories.orders import OrderRepository
from test_production_consistency import production_case, event, postgres_database
from test_payment_consistency import seed_paid_queued_order
from app.services.errors import ServiceError
import pytest


def test_pickup_blocks_dispatch_and_collection_releases_it(production_case):
    db, production, _, identity, order_id, command = production_case
    slot = {'state':'OCCUPIED','revision':1,'taskId':command['taskId']}
    event(production_case, 'task.succeeded', pickupSlot=slot)
    with db.connect() as c:
        next_order, _ = seed_paid_queued_order(c, identity['id'])
        assert PickupRepository(c).blocked(identity['id'])
        assert production.dispatch_next_order(c, identity['id']) is None
        assert OrderRepository(c).find(order_id)['pickup_required']
    event(production_case, 'pickup.collected', pickupSlot={**slot,'state':'EMPTY','revision':3})
    # Delayed older timeout cannot occupy the slot again.
    event(production_case, 'pickup.overdue', pickupSlot={**slot,'state':'NEEDS_CHECK','revision':2})
    with db.connect() as c:
        assert not PickupRepository(c).blocked(identity['id'])
        assert OrderRepository(c).find(order_id)['collected_at'] is not None
        dispatched = production.dispatch_next_order(c, identity['id'])
        assert dispatched['orderId'] == str(next_order)


def test_collection_before_completion_is_not_lost(production_case):
    db, _, _, identity, order_id, command = production_case
    slot = {'state':'EMPTY','revision':2,'taskId':command['taskId']}
    event(production_case, 'pickup.collected', pickupSlot=slot)
    event(production_case, 'task.succeeded', pickupSlot={**slot,'state':'OCCUPIED','revision':1})
    with db.connect() as c:
        assert not PickupRepository(c).blocked(identity['id'])
        order = OrderRepository(c).find(order_id)
        assert order['status'] == 'READY' and order['collected_at'] is not None


def test_conflicting_slot_revision_does_not_mark_order_collected(production_case):
    db, _, _, identity, order_id, command = production_case
    slot = {'state':'OCCUPIED','revision':1,'taskId':command['taskId']}
    event(production_case, 'task.succeeded', pickupSlot=slot)
    with pytest.raises(ServiceError) as error:
        event(production_case, 'pickup.collected', pickupSlot={**slot,'state':'EMPTY'})
    assert error.value.status_code == 409
    with db.connect() as c:
        assert OrderRepository(c).find(order_id)['collected_at'] is None
        assert PickupRepository(c).blocked(identity['id'])


def test_collection_dispatch_retries_when_idle_snapshot_arrives_late(production_case):
    from psycopg.types.json import Jsonb
    from app.db import UnitOfWork
    from app.services.background_worker import BackgroundWorkerService
    from app.settings import Settings
    db, production, _, identity, _, command = production_case
    slot = {'state':'OCCUPIED','revision':1,'taskId':command['taskId']}
    event(production_case, 'task.succeeded', pickupSlot=slot)
    event(production_case, 'pickup.collected', pickupSlot={**slot,'revision':2,'state':'EMPTY'})
    with db.connect() as c:
        next_order, _ = seed_paid_queued_order(c, identity['id'])
        c.execute('update terminal set reported_status=%s where id=%s',
                  (Jsonb({'deviceStatus':'BUSY','currentTaskState':'RUNNING'}),identity['id']))
    worker = BackgroundWorkerService(UnitOfWork(db),Settings.model_construct(),production=production,payment_provider=lambda _:None)
    worker.process_dispatch_batch(1)
    with db.connect() as c:
        assert c.execute('select status from terminal_dispatch_request where terminal_id=%s',(identity['id'],)).fetchone()['status']=='RETRY'
        c.execute("update terminal set reported_status='{}'::jsonb where id=%s",(identity['id'],))
        c.execute('update terminal_dispatch_request set next_attempt_at=now() where terminal_id=%s',(identity['id'],))
    worker.process_dispatch_batch(1)
    with db.connect() as c:
        assert OrderRepository(c).find(next_order)['status']=='DISPATCHED'
