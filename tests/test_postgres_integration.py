from __future__ import annotations

import json
import os
import uuid
import asyncio
import logging
from contextlib import contextmanager
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from app.database import Database
from app.repositories.dispatch import DispatchRepository
from app.repositories.telemetry import TelemetryRepository
from app.db import UnitOfWork
from app.live_progress import progress_key
from app.order_events import OrderEventBroker
from app.order_stream import order_stream
from app.security import hash_token
from app.services.public_orders import PublicOrderService
from app.settings import Settings
from app.telemetry import TelemetryCache


pytestmark = pytest.mark.postgres


def schema_url(database_url: str, schema: str) -> str:
    parsed = urlsplit(database_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["options"] = f"-csearch_path={schema}"
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


@pytest.fixture()
def postgres_database():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    schema = f"coffee_test_{uuid.uuid4().hex}"
    with psycopg.connect(database_url, autocommit=True) as admin:
        admin.execute(sql.SQL("create schema {}").format(sql.Identifier(schema)))
    database = Database(schema_url(database_url, schema), min_size=1, max_size=3)
    try:
        database.initialize(run_migrations=True)
        yield database
    finally:
        database.close()
        with psycopg.connect(database_url, autocommit=True) as admin:
            admin.execute(sql.SQL("drop schema {} cascade").format(sql.Identifier(schema)))


def insert_terminal(connection, device_id: str = "test-device") -> int:
    return connection.execute(
        "insert into terminal(device_id,serial_number) values(%s,%s) returning id",
        (device_id, f"serial-{uuid.uuid4()}"),
    ).fetchone()["id"]


def test_real_postgres_telemetry_batch_and_dispatch_recovery(postgres_database: Database) -> None:
    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection)
        TelemetryRepository(connection).apply_snapshots([(
            "test-device",
            {
                "terminalId": str(terminal_id),
                "connectionStatus": "online",
                "lastSeenAt": "2026-08-30T00:00:00Z",
                "progressPayload": json.dumps({
                    "type": "task.progress",
                    "payload": {
                        "taskId": "missing-job-is-valid", "taskRevision": 3,
                        "overallProgress": 0.5, "stepProgress": 0.25,
                    },
                }),
            },
        )])
        DispatchRepository(connection).enqueue(terminal_id, "initial")

    with postgres_database.connect() as connection:
        claimed = DispatchRepository(connection).claim("worker-a")
        assert claimed is not None
        original_revision = claimed["revision"]

    with postgres_database.connect() as connection:
        DispatchRepository(connection).enqueue(terminal_id, "newer-event")

    with postgres_database.connect() as connection:
        DispatchRepository(connection).complete(terminal_id, original_revision)
        current = connection.execute(
            "select status,revision from terminal_dispatch_request where terminal_id=%s", (terminal_id,)
        ).fetchone()
        assert current == {"status": "PENDING", "revision": original_revision + 1}


def test_order_mutation_emits_transactional_notification(postgres_database: Database) -> None:
    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection, "notify-device")
        order_id = uuid.uuid4()
        connection.execute(
            """insert into sales_order(
                   id,order_no,terminal_id,access_token_hash,idempotency_key,request_digest,status,
                   payment_mode,payment_status,currency,total_amount_minor,recipe_id,recipe_version,
                   product_name,product_snapshot)
                 values(%s,%s,%s,%s,%s,%s,'QUEUED','TEST_FREE','NOT_REQUIRED','CNY',100,
                        'coffee','v1','Coffee',%s)""",
            (
                order_id, f"ORDER-{uuid.uuid4().hex[:8]}", terminal_id, "a" * 64,
                str(uuid.uuid4()), "b" * 64, Jsonb({"recipeId": "coffee"}),
            ),
        )

    with psycopg.connect(postgres_database.database_url, autocommit=True) as listener:
        listener.execute("listen coffee_order_updates")
        with postgres_database.connect() as connection:
            connection.execute("update sales_order set status='DISPATCHED' where id=%s", (order_id,))
        notifications = list(listener.notifies(timeout=2, stop_after=1))

    assert [notification.payload for notification in notifications] == [str(order_id)]


def test_real_dual_channel_sse_progress_no_sql_and_redis_reconnect(postgres_database: Database):
    redis_url = os.getenv("TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("TEST_REDIS_URL must point to an isolated disposable Redis (test kills Pub/Sub connections)")
    log = logging.getLogger("dual-sse-integration")
    device_id, task_id, order_id = f"test-{uuid.uuid4().hex}", f"task-{uuid.uuid4().hex}", uuid.uuid4()
    token = "test-order-access-token"
    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection, device_id)
        connection.execute(
            """insert into sales_order(id,order_no,terminal_id,access_token_hash,idempotency_key,
                   request_digest,status,payment_mode,payment_status,currency,total_amount_minor,
                   recipe_id,recipe_version,product_name,product_snapshot)
                 values(%s,%s,%s,%s,%s,%s,'MAKING','TEST_FREE','NOT_REQUIRED','CNY',100,
                        'coffee','v1','Coffee',%s)""",
            (order_id, str(order_id), terminal_id, hash_token(token), str(order_id), "b" * 64, Jsonb({})),
        )
        connection.execute(
            """insert into production_job(id,task_id,order_id,terminal_id,status,progress,last_device_revision)
                 values(%s,%s,%s,%s,'EXECUTING',0.1,1)""", (uuid.uuid4(), task_id, order_id, terminal_id),
        )

    class CountingUow(UnitOfWork):
        calls = 0

        @contextmanager
        def transaction(self):
            self.calls += 1
            with super().transaction() as connection:
                yield connection

    cache = TelemetryCache(redis_url, online_ttl_seconds=120, logger=log)
    cache.start()
    uow = CountingUow(postgres_database)
    service = PublicOrderService(uow, Settings.model_construct(), request_dispatch=lambda *_: None,
                                payment_provider=lambda *_: None, telemetry_cache=cache)
    brokers = [OrderEventBroker(postgres_database.database_url, redis_url=redis_url, logger=log) for _ in range(2)]
    for broker in brokers:
        broker.start()

    def report(revision, progress):
        assert cache.progress(device_id, terminal_id, {
            "deviceId": device_id, "type": "task.progress", "payload": {
                "taskId": task_id, "taskRevision": revision,
                "overallProgress": progress, "stepProgress": progress,
            },
        })

    def decode(frame):
        return json.loads(frame.split("data: ", 1)[1])

    async def scenario():
        for broker in brokers:
            assert await asyncio.to_thread(broker.postgres_connected.wait, 5)
            assert await asyncio.to_thread(broker.redis_connected.wait, 5)
        await asyncio.sleep(0.05)
        streams = [order_stream(broker, service, order_id, token) for broker in brokers]
        try:
            for stream in streams:
                assert decode(await anext(stream))["production"]["progress"] == 0.1
            baseline = uow.calls
            report(5, 0.8)
            report(3, 0.3)  # Delayed/out-of-order packet cannot replace revision 5.
            for stream in streams:
                frame = await asyncio.wait_for(anext(stream), 5)
                assert decode(frame)["production"]["progress"] == 0.8
            assert uow.calls == baseline
            assert cache.client.ttl(progress_key(device_id, task_id)) > 0
            with postgres_database.connect() as connection:
                row = connection.execute("select progress,last_device_revision from production_job where order_id=%s", (order_id,)).fetchone()
                assert row == {"progress": 0.1, "last_device_revision": 1}
            assert not cache.client.zscore(cache._dirty_key(), device_id)

            # Only run this against TEST_REDIS_URL, never production Redis.
            cache.client.client_kill_filter(_type="pubsub")
            report(6, 0.9)
            for stream in streams:
                frame = await asyncio.wait_for(anext(stream), 10)
                assert decode(frame)["production"]["progress"] == 0.9
            assert uow.calls == baseline  # Reconnect catch-up still does not query SQL.
            # Fresh browser gets latest Redis state without replaying history.
            fresh = order_stream(brokers[0], service, order_id, token)
            try:
                assert decode(await anext(fresh))["production"]["progress"] == 0.9
            finally:
                await fresh.aclose()
            with postgres_database.connect() as connection:
                connection.execute("update production_job set status='SUCCEEDED',progress=1,last_device_revision=7 where order_id=%s", (order_id,))
                connection.execute("update sales_order set status='READY' where id=%s", (order_id,))
            report(999, 0.2)  # Even a higher late progress revision cannot undo terminal state.
            for stream in streams:
                for _ in range(3):
                    final = decode(await asyncio.wait_for(anext(stream), 5))
                    if final["status"] == "READY":
                        break
                assert final["status"] == "READY" and final["production"]["progress"] == 1.0
                with pytest.raises(StopAsyncIteration):
                    await anext(stream)
        finally:
            for stream in streams:
                await stream.aclose()

    try:
        asyncio.run(scenario())
    finally:
        for broker in brokers:
            broker.stop()
        if cache.client:
            cache.client.delete(progress_key(device_id, task_id))
        cache.close()
