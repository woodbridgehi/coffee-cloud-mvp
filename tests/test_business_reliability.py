"""Real database coverage for retry identity and reconnect dispatch liveness."""
from copy import deepcopy
from datetime import timedelta
import logging
import os
import uuid

import pytest
from psycopg.types.json import Jsonb

from app.db import UnitOfWork
from app.protocol import canonical_digest, utc_now
from app.services.background_worker import BackgroundWorkerService
from app.services.commands import CommandService
from app.services.errors import ServiceError
from app.services.mqtt_gateway import MqttGatewayService
from app.services.production import ProductionService
from app.settings import Settings
from app.telemetry import TelemetryCache
from test_payment_consistency import postgres_database, insert_terminal, seed_paid_queued_order


def gateway(db, event=lambda *a: {"ok": True}, **kwargs):
    return MqttGatewayService(UnitOfWork(db), logger=logging.getLogger(__name__),
        heartbeat=lambda *a, **kw: {"ok": True}, event=event, task_ack=lambda *a: {},
        command_result=lambda *a: {}, request_dispatch=kwargs.pop("request_dispatch", lambda *a: None), **kwargs)


def envelope(device):
    return {"schema": "coffee.mqtt-envelope.v1", "deviceId": device, "type": "event",
            "messageId": "retry-event", "sentAt": "2026-09-17T00:00:00Z",
            "payload": {"deviceId": device, "eventId": "retry-event", "type": "task.succeeded",
                        "payload": {"taskId": "task-1", "taskRevision": 3}}}


def test_retry_identity_with_legacy_sql_row(postgres_database):
    db = postgres_database
    with db.connect() as c: insert_terminal(c)
    body = {"topic": "v1/devices/pay-device/up", "envelope": envelope("pay-device")}
    calls = []
    def event(*args):
        calls.append(args)
        if len(calls) == 1: raise RuntimeError("transient outage")
        return {"ok": True}
    service = gateway(db, event)
    with pytest.raises(RuntimeError): service.ingest(body)
    with db.connect() as c:
        row = c.execute("select * from mqtt_inbox").fetchone()
        assert row["status"] == "RETRY"
        assert row["payload_digest"].strip() == canonical_digest(body["envelope"])
    retry = deepcopy(body); retry["envelope"]["sentAt"] = "2026-09-17T00:00:01Z"
    assert service.ingest(retry)["ok"]
    assert service.ingest(body)["duplicate"]
    assert service.ingest(retry)["duplicate"]
    assert len(calls) == 2
    for field, value in (("taskId", "other-task"), ("taskRevision", 4)):
        conflict = deepcopy(retry); conflict["envelope"]["payload"]["payload"][field] = value
        with pytest.raises(ServiceError) as exc: service.ingest(conflict)
        assert exc.value.status_code == 409
    version = deepcopy(retry); version["envelope"]["schema"] = "coffee.mqtt-envelope.v2"
    with pytest.raises(ServiceError): service.ingest(version)


@pytest.mark.parametrize("redis_enabled", [False, True])
def test_presence_before_heartbeat_keeps_dispatch_until_state_ready(postgres_database, redis_enabled):
    db = postgres_database
    settings = Settings.model_construct(offline_threshold_seconds=60)
    production = ProductionService(settings, payment_provider=lambda _: None)
    device = f"reconnect-{uuid.uuid4().hex}"
    with db.connect() as c:
        tid = insert_terminal(c, device)
        c.execute("update terminal set lifecycle_status='ACTIVE',connection_status='offline',last_heartbeat_at=now()-interval '5 minutes',reported_status=%s where id=%s", (Jsonb({"deviceStatus": "IDLE"}), tid))
        seed_paid_queued_order(c, tid)
    cache = None
    if redis_enabled:
        if not os.getenv("TEST_REDIS_URL"): pytest.skip("isolated TEST_REDIS_URL required")
        cache = TelemetryCache(os.environ["TEST_REDIS_URL"], online_ttl_seconds=60, logger=logging.getLogger(__name__))
        cache.start()
    service = gateway(db, request_dispatch=production.request_dispatch, telemetry_cache=cache)
    worker = BackgroundWorkerService(UnitOfWork(db), settings, production=production, payment_provider=lambda _: None, telemetry_cache=cache)
    try:
        service.ingest({"topic": f"v1/devices/{device}/presence", "envelope": {"deviceId": device, "online": True}})
        assert worker.process_dispatch_batch(limit=1) == 1
        with db.connect() as c:
            assert c.execute("select status from terminal_dispatch_request where terminal_id=%s", (tid,)).fetchone()["status"] == "RETRY"
            assert c.execute("select count(*) as n from terminal_command").fetchone()["n"] == 0
        if cache:
            assert cache.heartbeat(device, tid, {"deviceStatus": "IDLE"})
            # Redis heartbeat alone must not permit dispatch before SQL flush.
            with db.connect() as c: c.execute("update terminal_dispatch_request set next_attempt_at=now()")
            worker.process_dispatch_batch(limit=1)
            assert worker.flush_telemetry_batch() >= 1
        else:
            with db.connect() as c: c.execute("update terminal set last_heartbeat_at=now() where id=%s", (tid,))
        with db.connect() as c: c.execute("update terminal_dispatch_request set next_attempt_at=now()")
        worker.process_dispatch_batch(limit=1)
        worker.process_dispatch_batch(limit=1)
        with db.connect() as c:
            assert c.execute("select count(*) as n from terminal_command").fetchone()["n"] == 1
            assert not c.execute("select * from terminal_dispatch_request").fetchone()
    finally:
        if cache: cache.close()


def test_debug_command_carries_deadline_and_task_target(postgres_database):
    db = postgres_database
    with db.connect() as c:
        tid = insert_terminal(c)
        c.execute("update terminal set reported_status=%s where id=%s", (Jsonb({"currentTaskId": "task-old"}), tid))
    service = CommandService(UnitOfWork(db), lease_seconds=30, transition_command=lambda *a: None)
    result = service.create_debug_command({"id": tid, "device_id": "pay-device"}, "pause")
    assert result["command"]["taskId"] == "task-old"
    assert result["command"]["expiresAt"]
    with db.connect() as c:
        row = c.execute("select * from terminal_command").fetchone()
        assert utc_now() < row["expires_at"] < utc_now() + timedelta(minutes=6)


def test_inbox_recovery_without_new_broker_delivery(postgres_database):
    db = postgres_database
    with db.connect() as c: insert_terminal(c)
    calls = []
    def event(*args):
        calls.append(args)
        if len(calls) == 1: raise RuntimeError("business unavailable")
        return {"ok": True}
    service = gateway(db, event)
    with pytest.raises(RuntimeError):
        service.ingest({"topic": "v1/devices/pay-device/up", "envelope": envelope("pay-device")})
    assert service.recover_pending() == 0
    with db.connect() as c: c.execute("update mqtt_inbox set next_recovery_at=now()")
    assert service.recover_pending() == 1
    assert service.recover_pending() == 0
    with db.connect() as c:
        row = c.execute("select * from mqtt_inbox").fetchone()
        assert row["status"] == "PROCESSED"
        assert row["recovery_attempts"] == 1
    assert len(calls) == 2


def test_recovery_claim_is_exclusive_and_crash_lease_can_expire(postgres_database):
    from app.repositories.mqtt_gateway import MqttGatewayRepository
    db = postgres_database
    with db.connect() as c:
        insert_terminal(c)
        body = envelope("pay-device")
        MqttGatewayRepository(c).insert_inbox(("pay-device", "v1/devices/pay-device/up", "retry-event", "event", None, None, 3, canonical_digest(body), body))
        c.execute("update mqtt_inbox set next_recovery_at=now()")
    with db.connect() as c:
        assert len(MqttGatewayRepository(c).claim_recovery(1)) == 1
        with db.connect() as other:
            assert MqttGatewayRepository(other).claim_recovery(1) == []
    with db.connect() as c: c.execute("update mqtt_inbox set next_recovery_at=now()")
    assert gateway(db).recover_pending() == 1


from test_production_consistency import production_case, snapshot


def test_business_committed_before_inbox_result_is_recovered_idempotently(production_case):
    db, production, messages, identity, order_id, command = production_case
    calls = []
    def commit_then_fail(device, event, terminal):
        result = messages.event(device, event, terminal)
        calls.append(result)
        if len(calls) == 1: raise RuntimeError("lost response after business commit")
        return result
    service = gateway(db, commit_then_fail)
    body = envelope(identity["device_id"])
    body["payload"]["payload"] = {"taskId": command["taskId"], "taskRevision": 3}
    with pytest.raises(RuntimeError):
        service.ingest({"topic": f"v1/devices/{identity['device_id']}/up", "envelope": body})
    before = snapshot(production_case)
    assert before["order_status"] == "READY"
    with db.connect() as c: c.execute("update mqtt_inbox set next_recovery_at=now()")
    service.recover_pending()
    after = snapshot(production_case)
    assert after["revision"] == before["revision"]
    assert after["refunds"] == 0
    assert len(calls) == 2


def test_recovery_does_not_replay_stale_telemetry(postgres_database):
    from app.repositories.mqtt_gateway import MqttGatewayRepository
    db = postgres_database
    with db.connect() as c:
        insert_terminal(c)
        for kind in ("presence", "state", "heartbeat"):
            body = {"deviceId": "pay-device", "online": True, "deviceStatus": "IDLE"}
            MqttGatewayRepository(c).insert_inbox(("pay-device", f"v1/devices/pay-device/{kind}", kind, kind, None, None, None, canonical_digest(body), body))
        c.execute("update mqtt_inbox set next_recovery_at=now()")
    assert gateway(db).recover_pending() == 0
    with db.connect() as c:
        assert c.execute("select count(*) as n from mqtt_inbox where status='RECEIVED'").fetchone()["n"] == 3


def test_upgrade_repair_restores_lost_dispatch_without_external_event(postgres_database):
    db = postgres_database
    settings = Settings.model_construct(offline_threshold_seconds=60)
    production = ProductionService(settings, payment_provider=lambda _: None)
    worker = BackgroundWorkerService(UnitOfWork(db), settings, production=production, payment_provider=lambda _: None)
    with db.connect() as c:
        tid = insert_terminal(c)
        c.execute("update terminal set lifecycle_status='ACTIVE',connection_status='online',last_heartbeat_at=now(),reported_status=%s where id=%s", (Jsonb({"deviceStatus": "IDLE"}), tid))
        seed_paid_queued_order(c, tid)
    # This is the pre-upgrade orphan: ordinary dispatch cannot discover it.
    assert worker.process_dispatch_batch(limit=1) == 0
    assert worker.repair_missing_dispatch_requests() == 1
    assert worker.repair_missing_dispatch_requests() == 0
    assert worker.process_dispatch_batch(limit=1) == 1
    with db.connect() as c:
        assert c.execute("select count(*) as n from terminal_command").fetchone()["n"] == 1
    assert worker.repair_missing_dispatch_requests() == 0


def test_dispatch_repair_is_concurrent_and_preserves_existing_lease(postgres_database):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    db = postgres_database
    settings = Settings.model_construct()
    production = ProductionService(settings, payment_provider=lambda _: None)
    worker = BackgroundWorkerService(UnitOfWork(db), settings, production=production, payment_provider=lambda _: None)
    with db.connect() as c:
        tid = insert_terminal(c)
        seed_paid_queued_order(c, tid)
        seed_paid_queued_order(c, tid)
    barrier = Barrier(2)
    def repair():
        barrier.wait(5)
        return worker.repair_missing_dispatch_requests()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(repair) for _ in range(2)]
        assert sum(f.result(timeout=10) for f in futures) == 1
    with db.connect() as c:
        c.execute("update terminal_dispatch_request set status='PROCESSING',revision=7,locked_by='active-worker',locked_until=now()+interval '1 minute',attempt_count=4")
        before = c.execute("select * from terminal_dispatch_request").fetchone()
    assert worker.repair_missing_dispatch_requests() == 0
    with db.connect() as c:
        assert c.execute("select * from terminal_dispatch_request").fetchone() == before


@pytest.mark.parametrize("blocker", ["offline", "pickup", "hold"])
def test_repaired_dispatch_still_obeys_interlocks(production_case, blocker):
    from test_production_consistency import event
    db, production, _, identity, order_id, command = production_case
    if blocker == "pickup":
        event(production_case, "task.succeeded", pickupSlot={"state": "OCCUPIED", "revision": 1, "taskId": command["taskId"]})
    with db.connect() as c:
        if blocker == "hold":
            c.execute("update production_job set status='HOLD' where order_id=%s", (order_id,))
            c.execute("update sales_order set status='HOLD' where id=%s", (order_id,))
        elif blocker == "offline":
            c.execute("update terminal set connection_status='offline' where id=%s", (identity["id"],))
        seed_paid_queued_order(c, identity["id"])
        c.execute("delete from terminal_dispatch_request where terminal_id=%s", (identity["id"],))
    worker = BackgroundWorkerService(UnitOfWork(db), production.settings, production=production, payment_provider=lambda _: None)
    assert worker.repair_missing_dispatch_requests() == 1
    assert worker.process_dispatch_batch(limit=1) == 1
    with db.connect() as c:
        assert c.execute("select count(*) as n from terminal_command").fetchone()["n"] == 1
        assert c.execute("select status from terminal_dispatch_request").fetchone()["status"] == "RETRY"
