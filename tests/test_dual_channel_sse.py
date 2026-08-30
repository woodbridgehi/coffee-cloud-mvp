from __future__ import annotations

import asyncio
from copy import deepcopy
import logging
import uuid

import pytest

from app.live_progress import merge_progress, progress_key, validate_progress
from app.order_events import ORDER_CHANGED, PROGRESS_CHANGED, OrderEventBroker
from app.order_stream import order_stream
from app.protocol import DeviceEvent
from app.services.device_messages import DeviceMessageService
from app.services.production import ProductionService
from app.settings import Settings
from app.telemetry import TelemetryCache

LOG = logging.getLogger("test-dual-sse")


def event(revision=2, task_id="task-1", device_id="device-1", progress=0.5):
    return {"deviceId": device_id, "eventId": str(uuid.uuid4()), "type": "task.progress", "payload": {
        "taskId": task_id, "taskRevision": revision, "overallProgress": progress,
        "stepProgress": 0.2, "stepName": "Grinding",
    }}


def snapshot():
    return {"deviceId": "device-1", "status": "MAKING", "production": {
        "taskId": "task-1", "status": "EXECUTING", "deviceRevision": 1,
        "progress": 0.1, "overallProgress": 0.1, "stepProgress": 0.1,
        "currentStepName": "Starting",
    }}


def test_overlay_is_immutable_and_accepts_only_newer_matching_revision():
    original = snapshot()
    updated = merge_progress(original, event())
    assert original["production"]["progress"] == 0.1
    assert updated["production"]["progress"] == 0.5
    assert merge_progress(updated, event(revision=1)) is updated
    assert merge_progress(updated, event(revision=2, progress=0.2)) is updated
    assert merge_progress(original, event(task_id="another-task")) is original
    assert merge_progress(original, event(device_id="another-device")) is original


@pytest.mark.parametrize("order_status,job_status", [
    ("READY", "SUCCEEDED"), ("FAILED", "FAILED"), ("CANCELLED", "CANCELLED"),
    ("MAKING", "HOLD"), ("ACCEPTED", "ACCEPTED"),
])
def test_durable_state_wins_even_over_higher_progress_revision(order_status, job_status):
    durable = snapshot()
    durable["status"], durable["production"]["status"] = order_status, job_status
    assert merge_progress(durable, event(revision=999)) is durable


@pytest.mark.parametrize("field,value", [("taskRevision", None), ("taskRevision", -1),
                                         ("overallProgress", float("nan")), ("stepProgress", "broken")])
def test_invalid_progress_rejected(field, value):
    invalid = event()
    invalid["payload"][field] = value
    with pytest.raises(ValueError):
        validate_progress(invalid)


class RecordingRedis:
    def __init__(self):
        self.calls = []
        self.executions = 0

    def pipeline(self, **kwargs):
        return self

    def eval(self, *args):
        self.calls.append(args)

    def execute(self):
        self.executions += 1
        return [1] * len(self.calls)


def test_redis_batch_keeps_latest_revision_without_marking_sql_dirty():
    cache = TelemetryCache(None, online_ttl_seconds=120, logger=LOG)
    cache.client = RecordingRedis()
    with cache.batch():
        cache.progress("device-1", 7, event(revision=3))
        cache.progress("device-1", 7, event(revision=2))
        cache.progress("device-2", 8, event(device_id="device-2"))
    assert cache.client.executions == 1
    assert len(cache.client.calls) == 2
    assert cache.client.calls[0][2] == progress_key("device-1", "task-1")
    assert cache.client.calls[0][3] == 3


def test_http_progress_never_falls_back_to_sql_when_redis_absent():
    class ForbiddenUow:
        def transaction(self):
            raise AssertionError("progress must not open a SQL transaction")

    callback = lambda *args, **kwargs: None
    service = DeviceMessageService(ForbiddenUow(), request_dispatch=callback, transition_command=callback,
        expire_order_for_command=callback, reconcile_command_event=callback, reconcile_order_event=callback,
        reconcile_order_ack=callback, order_url=callback)
    result = service.event("device-1", DeviceEvent(**event()), {"id": 7})
    assert result["dropped"] is True


def test_old_progress_inbox_replay_cannot_write_sql():
    service = ProductionService(Settings.model_construct(), payment_provider=lambda *_: None)
    # object() has no execute(): even one SQL operation would fail this regression.
    assert service.reconcile_order_event(object(), 7, event(), "task.progress") == {"status": "EPHEMERAL_PROGRESS"}


def test_bounded_queue_preserves_database_flag_and_task_isolation():
    async def scenario():
        broker = OrderEventBroker("unused", logger=LOG)
        queue = broker.subscribe("order-1", asyncio.get_running_loop())
        broker.watch_progress(queue, "device-1", "task-1")
        broker._publish_progress(progress_key("device-1", "task-2"))
        await asyncio.sleep(0)
        assert queue.empty()
        broker._publish("order-1")
        for _ in range(10):
            broker._publish_progress(progress_key("device-1", "task-1"))
        await asyncio.sleep(0)
        assert queue.qsize() == 1
        assert queue.get_nowait() == ORDER_CHANGED | PROGRESS_CHANGED
        broker.unsubscribe("order-1", queue)
        assert not broker.progress_subscribers and not broker.progress_keys
    asyncio.run(scenario())


def test_sse_progress_does_not_query_sql_and_reconnect_reads_latest():
    async def scenario():
        broker = OrderEventBroker("unused", logger=LOG)
        order_id = uuid.uuid4()

        class Service:
            sql_reads = 0
            durable = snapshot()
            live = event()

            def get(self, *_args, **_kwargs):
                self.sql_reads += 1
                return deepcopy(self.durable)

            def with_live_progress(self, value):
                return merge_progress(value, self.live)

        service = Service()
        stream = order_stream(broker, service, order_id, "token")
        initial = await anext(stream)
        assert '"overallProgress":0.5' in initial
        service.live = event(revision=3, progress=0.8)
        broker._publish_progress(progress_key("device-1", "task-1"))
        update = await asyncio.wait_for(anext(stream), 1)
        assert '"overallProgress":0.8' in update
        assert service.sql_reads == 1
        # Redis listener reconnect refreshes cache, not PostgreSQL.
        broker._resync(PROGRESS_CHANGED)
        await asyncio.wait_for(anext(stream), 1)
        assert service.sql_reads == 1
        await stream.aclose()
        stream = order_stream(broker, service, order_id, "token")
        assert '"overallProgress":0.8' in await anext(stream)
        service.durable["status"] = "READY"
        service.durable["production"].update(status="SUCCEEDED", progress=1.0, overallProgress=1.0)
        broker._publish(str(order_id))
        broker._publish_progress(progress_key("device-1", "task-1"))
        final = await asyncio.wait_for(anext(stream), 1)
        assert '"status":"READY"' in final and '"overallProgress":1.0' in final
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        assert broker.subscriber_count() == 0
    asyncio.run(scenario())
