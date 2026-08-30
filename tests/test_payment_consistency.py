"""A1 payment/refund correctness acceptance tests.

The DB-free part covers pure state rules; everything else runs against a real
isolated PostgreSQL schema (skipped without TEST_DATABASE_URL) because this
batch is precisely about transactions, refund budgets and lock ordering.
"""
from __future__ import annotations

import os
import threading
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg
import pytest
from fastapi import HTTPException
from psycopg import sql
from psycopg.types.json import Jsonb

from app.database import MIGRATIONS, SCHEMA_SQL, Database
from app.db import UnitOfWork
from app.payment_providers import MockPaymentProvider, ProviderResult
from app.payment_service import apply_paid_callback, callback_amount_minor, enqueue_outbox
from app.payment_state import decide_payment_transition, decide_refund_transition
from app.protocol import PaymentCreateRequest, RefundCreateRequest
from app.repositories import OrderRepository, PaymentRepository
from app.repositories import CommandRepository
from app.security import hash_token
from app.services.errors import ServiceError
from app.services.payments import PaymentApplicationService
from app.services.production import ProductionService
from app.services.public_orders import PublicOrderService
from app.services.refund_intents import BUDGET_REFUND_STATUSES, apply_refund_outcome, create_refund_intent
from app.settings import Settings


TOKEN = "test-order-access-token"


def order_token(order_id: uuid.UUID) -> str:
    return f"{TOKEN}:{order_id}"


def schema_url(database_url: str, schema: str) -> str:
    parsed = urlsplit(database_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["options"] = f"-csearch_path={schema}"
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


class RecordingProvider(MockPaymentProvider):
    """Mock channel that records close/refund calls for race assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.close_calls: list[str] = []
        self.refund_calls: list[str] = []
        self.refund_status = "REFUNDED"

    def close_payment(self, merchant_no: str) -> ProviderResult:
        self.close_calls.append(merchant_no)
        return super().close_payment(merchant_no)

    def refund(self, request) -> ProviderResult:
        self.refund_calls.append(request.merchant_refund_no)
        if self.refund_status == "FAILED":
            return ProviderResult("FAILED", raw={"mock": "permanent refund failure"})
        return super().refund(request)


def payment_settings(**overrides) -> Settings:
    values = {
        "payment_default_provider": "mock",
        "allow_mock_payment": True,
        "public_base_url": "http://payments.test",
        "payment_reconcile_seconds": 30,
        "payment_pending_ttl_seconds": 900,
    }
    values.update(overrides)
    return Settings.model_construct(**values)


def insert_terminal(connection, device_id: str = "pay-device") -> int:
    return connection.execute(
        "insert into terminal(device_id,serial_number) values(%s,%s) returning id",
        (device_id, f"serial-{uuid.uuid4()}"),
    ).fetchone()["id"]


def insert_order(
    connection, terminal_id: int, *, status: str = "CREATED", payment_status: str = "NOT_STARTED",
    total_minor: int = 1000, payment_mode: str = "ONLINE",
) -> uuid.UUID:
    order_id = uuid.uuid4()
    token = order_token(order_id)
    connection.execute(
        """insert into sales_order(id,order_no,terminal_id,access_token_hash,idempotency_key,
               request_digest,status,payment_mode,payment_status,currency,total_amount_minor,
               recipe_id,recipe_version,product_name,product_snapshot)
             values(%s,%s,%s,%s,%s,%s,%s,%s,%s,'CNY',%s,'coffee','v1','Coffee',%s)""",
        (order_id, f"ORDER-{uuid.uuid4().hex[:8]}", terminal_id, hash_token(token),
         str(uuid.uuid4()), "d" * 64, status, payment_mode, payment_status, total_minor,
         Jsonb({"recipeId": "coffee"})),
    )
    return order_id


def insert_payment(
    connection, order_id: uuid.UUID, *, status: str = "PENDING", amount_minor: int = 1000,
    provider: str = "mock", paid: bool = False,
) -> dict:
    payment_id = uuid.uuid4()
    merchant_no = f"C{uuid.uuid4().hex[:16].upper()}"
    row = connection.execute(
        """insert into payment(id,order_id,provider,merchant_payment_no,idempotency_key,
               request_digest,status,amount_minor,currency,subject)
             values(%s,%s,%s,%s,%s,%s,%s,%s,'CNY','Coffee') returning *""",
        (payment_id, order_id, provider, merchant_no, str(uuid.uuid4()), "d" * 64,
         status, amount_minor),
    ).fetchone()
    if paid:
        connection.execute("update payment set paid_at=now() where id=%s", (payment_id,))
    return row


def seed_paid_queued_order(connection, terminal_id: int, *, total_minor: int = 1000):
    """Order with money received, primary payment recorded and a queued job."""
    order_id = insert_order(
        connection, terminal_id, status="QUEUED", payment_status="PAID", total_minor=total_minor
    )
    payment = insert_payment(connection, order_id, status="PAID", amount_minor=total_minor, paid=True)
    connection.execute(
        "update sales_order set paid_payment_id=%s where id=%s", (payment["id"], order_id)
    )
    connection.execute(
        """insert into production_job(id,task_id,order_id,terminal_id,status)
             values(%s,%s,%s,%s,'QUEUED')""",
        (uuid.uuid4(), f"task-{uuid.uuid4().hex[:8]}", order_id, terminal_id),
    )
    return order_id, payment


def seed_command(connection, terminal_id: int, order_id: uuid.UUID, *, delivered: bool):
    job = connection.execute(
        "select id from production_job where order_id=%s", (order_id,)
    ).fetchone()
    message_id = f"cmd-{uuid.uuid4()}"
    # The real entry state for the expiry path: a CREATED command whose
    # delivery deadline is already exceeded, not a pre-terminalized EXPIRED row.
    row = connection.execute(
        """insert into terminal_command(terminal_id,message_id,command_type,payload_json,status,
               expires_at,delivered_at)
             values(%s,%s,'MAKE_DRINK',%s,'CREATED',now()-interval '1 minute',%s) returning *""",
        (terminal_id, message_id, Jsonb({"messageId": message_id}), "now()" if delivered else None),
    ).fetchone()
    connection.execute(
        "update production_job set command_id=%s,status='DISPATCHED' where id=%s", (row["id"], job["id"])
    )
    connection.execute("update sales_order set status='DISPATCHED' where id=%s", (order_id,))
    return row


def paid_callback_values(payment: dict, provider_trade_no: str = "") -> dict:
    return {
        "merchant_payment_no": payment["merchant_payment_no"],
        "amount_minor": str(payment["amount_minor"]),
        "provider_trade_no": provider_trade_no or f"trade-{uuid.uuid4().hex[:8]}",
    }


def apply_succeeded(database, refund_id) -> None:
    with database.connect() as connection:
        apply_refund_outcome(connection, refund_id=refund_id, target="SUCCEEDED", actor="test")


class FakeCursor:
    def __init__(self, row=None) -> None:
        self.row = row

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, row=None) -> None:
        self.row = row
        self.calls: list[str] = []

    def execute(self, statement: str, params=None):
        self.calls.append(statement)
        return FakeCursor(self.row)


def test_refunding_payment_never_rewrites_paid_state() -> None:
    # REFUNDING -> PAID is legal ONLY on the refund settlement path (every
    # in-flight refund failed, nothing succeeded); replayed payment callbacks
    # never take it (apply_paid_callback treats them as duplicates).
    assert decide_payment_transition("REFUNDING", "PAID").allowed is True
    assert decide_payment_transition("PARTIALLY_REFUNDED", "PAID").allowed is False
    assert decide_payment_transition("REFUNDED", "PAID").allowed is False
    assert decide_payment_transition("PAID", "REFUNDING").allowed
    assert decide_refund_transition("SUCCEEDED", "PROCESSING").allowed is False
    assert decide_refund_transition("FAILED", "PROCESSING").allowed is False
    assert decide_refund_transition("REQUESTED", "FAILED").allowed


def test_callback_amount_parsing_is_exact_decimal() -> None:
    assert callback_amount_minor({"amount_minor": "1000"}) == 1000
    assert callback_amount_minor({"amount_minor": 1050}) == 1050
    assert callback_amount_minor({"total_amount": "10.00"}) == 1000
    assert callback_amount_minor({"total_amount": "10.5"}) == 1050
    assert callback_amount_minor({}) is None
    for invalid in (
        {"amount_minor": "10.5"},
        {"total_amount": "0.001"},
        {"amount_minor": "-5"},
        {"amount_minor": "NaN"},
        {"amount_minor": "abc"},
        {"total_amount": "1,000"},
        {"total_amount": "bad", "amount_minor": "1000"},
    ):
        with pytest.raises(HTTPException):
            callback_amount_minor(invalid)


def test_joined_order_projection_locks_only_the_order_row() -> None:
    connection = FakeConnection()
    OrderRepository(connection).find_with_terminal(uuid.uuid4(), for_update=True)
    assert connection.calls[0].endswith("for update of o")
    assert "for update of t" not in connection.calls[0]


def test_public_projection_prefers_primary_payment_sql() -> None:
    connection = FakeConnection()
    OrderRepository(connection).public_view(uuid.uuid4())
    assert "(o.paid_payment_id is not distinct from p.id) desc" in connection.calls[0]


@pytest.fixture()
def postgres_database():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    schema = f"coffee_a1_{uuid.uuid4().hex}"
    with psycopg.connect(database_url, autocommit=True) as admin:
        admin.execute(sql.SQL("create schema {}").format(sql.Identifier(schema)))
    database = Database(schema_url(database_url, schema), min_size=1, max_size=6)
    try:
        database.initialize(run_migrations=True)
        yield database
    finally:
        database.close()
        with psycopg.connect(database_url, autocommit=True) as admin:
            admin.execute(sql.SQL("drop schema {} cascade").format(sql.Identifier(schema)))


@pytest.fixture()
def half_migrated_database():
    """A schema stopped at migration 9, for verifying migration 10 compatibility."""
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    schema = f"coffee_a1_mig_{uuid.uuid4().hex}"
    with psycopg.connect(database_url, autocommit=True) as admin:
        admin.execute(sql.SQL("create schema {}").format(sql.Identifier(schema)))
    database = Database(schema_url(database_url, schema), min_size=1, max_size=3)
    try:
        database.pool.open(wait=True)
        with database.connect() as connection:
            connection.execute("select pg_advisory_xact_lock(hashtext('coffee-cloud-schema-migration'))")
            connection.execute(SCHEMA_SQL)
            for version, name, statement in MIGRATIONS:
                if version >= 10:
                    continue
                connection.execute(statement)
                connection.execute(
                    "insert into schema_migration(version,name) values(%s,%s)", (version, name)
                )
        yield database
    finally:
        database.close()
        with psycopg.connect(database_url, autocommit=True) as admin:
            admin.execute(sql.SQL("drop schema {} cascade").format(sql.Identifier(schema)))


def test_paid_queued_cancel_creates_one_refund_intent_and_repeat_cancel_is_idempotent(
    postgres_database,
) -> None:
    provider = RecordingProvider()
    service = PublicOrderService(
        UnitOfWork(postgres_database), Settings.model_construct(),
        request_dispatch=lambda *_: None, payment_provider=lambda *_: provider,
    )
    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection)
        order_id, payment = seed_paid_queued_order(connection, terminal_id)

    token = order_token(order_id)
    first = service.cancel(order_id, token)
    assert first["status"] == "CANCELLED"
    assert first["paymentStatus"] == "REFUNDING"

    with postgres_database.connect() as connection:
        orders = OrderRepository(connection)
        payments = PaymentRepository(connection)
        order = orders.find(order_id)
        assert order["status"] == "CANCELLED"
        assert order["payment_status"] == "REFUNDING"
        assert orders.job(order_id)["status"] == "CANCELLED"
        current = payments.find(payment["id"])
        assert current["status"] == "REFUNDING"
        refunds = connection.execute(
            "select * from refund where payment_id=%s", (payment["id"],)
        ).fetchall()
        assert len(refunds) == 1
        assert refunds[0]["status"] == "REQUESTED"
        assert refunds[0]["amount_minor"] == 1000
        assert refunds[0]["next_attempt_at"] is not None
    assert provider.close_calls == []  # the primary paid intent is never closed

    second = service.cancel(order_id, token)
    assert second["status"] == "CANCELLED"
    with postgres_database.connect() as connection:
        count = connection.execute(
            "select count(*) as c from refund where payment_id=%s", (payment["id"],)
        ).fetchone()["c"]
        assert count == 1


def test_unpaid_cancel_closes_every_open_intent_and_never_refunds(postgres_database) -> None:
    provider = RecordingProvider()
    service = PublicOrderService(
        UnitOfWork(postgres_database), Settings.model_construct(),
        request_dispatch=lambda *_: None, payment_provider=lambda *_: provider,
    )
    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection)
        order_id = insert_order(connection, terminal_id, status="AWAITING_PAYMENT")
        first = insert_payment(connection, order_id, status="CREATED")
        second = insert_payment(connection, order_id, status="PENDING")

    result = service.cancel(order_id, order_token(order_id))
    assert result["status"] == "CANCELLED"
    assert sorted(provider.close_calls) == sorted(
        [first["merchant_payment_no"], second["merchant_payment_no"]]
    )

    with postgres_database.connect() as connection:
        statuses = connection.execute(
            "select status from payment where order_id=%s order by created_at", (order_id,)
        ).fetchall()
        assert [row["status"] for row in statuses] == ["CLOSED", "CLOSED"]
        order = OrderRepository(connection).find(order_id)
        assert order["payment_status"] == "CLOSED"
        assert connection.execute("select count(*) as c from refund").fetchone()["c"] == 0


def test_command_expire_refunds_only_when_definitely_not_delivered(postgres_database) -> None:
    production = ProductionService(payment_settings(), payment_provider=lambda *_: RecordingProvider())
    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection, "expire-clean")
        order_id, payment = seed_paid_queued_order(connection, terminal_id)
        command = seed_command(connection, terminal_id, order_id, delivered=False)

        production.expire_order_for_command(connection, command)

        order = OrderRepository(connection).find(order_id)
        assert order["status"] == "EXPIRED"
        refunds = connection.execute(
            "select * from refund where payment_id=%s", (payment["id"],)
        ).fetchall()
        assert len(refunds) == 1 and refunds[0]["amount_minor"] == 1000

    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection, "expire-unknown")
        order_id, payment = seed_paid_queued_order(connection, terminal_id)
        command = seed_command(connection, terminal_id, order_id, delivered=True)

        production.expire_order_for_command(connection, command)

        orders = OrderRepository(connection)
        order = orders.find(order_id)
        assert order["status"] == "HOLD"
        job = orders.job(order_id)
        assert job["status"] == "HOLD" and job["manual_review_required"] is True
        assert connection.execute(
            "select count(*) as c from refund where payment_id=%s", (payment["id"],)
        ).fetchone()["c"] == 0


def test_payment_create_reuses_active_intent_and_rejects_provider_switch(postgres_database) -> None:
    provider = RecordingProvider()
    service = PaymentApplicationService(
        UnitOfWork(postgres_database), payment_settings(),
        provider_factory=lambda *_: provider, mock_provider=provider,
    )
    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection)
        order_id = insert_order(connection, terminal_id)
        cancelled_id = insert_order(
            connection, terminal_id, status="CANCELLED", payment_status="CLOSED"
        )

    token = order_token(order_id)
    first = service.create(order_id, PaymentCreateRequest(), token, "key-a")
    assert first["status"] == "PENDING" and first["duplicate"] is False

    reused = service.create(order_id, PaymentCreateRequest(), token, "key-b")
    assert reused["paymentId"] == first["paymentId"]
    assert reused["duplicate"] is True
    with postgres_database.connect() as connection:
        count = connection.execute(
            "select count(*) as c from payment where order_id=%s", (order_id,)
        ).fetchone()["c"]
        assert count == 1  # no second merchant payment for the same order

    with pytest.raises(ServiceError) as conflict:
        service.create(order_id, PaymentCreateRequest(provider="alipay"), token, "key-c")
    assert "provider" in str(conflict.value.detail)

    with pytest.raises(ServiceError) as dead:
        service.create(cancelled_id, PaymentCreateRequest(), order_token(cancelled_id), "key-d")
    assert dead.value.status_code == 409


@pytest.mark.parametrize("dead_status", ["CANCELLED", "EXPIRED", "FAILED"])
def test_late_paid_callback_on_dead_order_refunds_and_never_revives(
    postgres_database, dead_status
) -> None:
    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection)
        order_id = insert_order(connection, terminal_id, status=dead_status)
        payment = insert_payment(connection, order_id, status="CLOSED")

        values = paid_callback_values(payment)
        updated, duplicate = apply_paid_callback(
            connection, provider="mock", event_id="late-1", values=values
        )
        assert duplicate is False
        order = OrderRepository(connection).find(order_id)
        assert order["status"] == dead_status  # never revived
        assert order["paid_payment_id"] == payment["id"]
        assert order["payment_status"] == "REFUNDING"
        assert updated["status"] == "REFUNDING"
        assert updated["paid_at"] is not None  # the money fact is recorded
        refunds = connection.execute(
            "select * from refund where payment_id=%s", (payment["id"],)
        ).fetchall()
        assert len(refunds) == 1 and refunds[0]["amount_minor"] == 1000
        assert connection.execute(
            "select count(*) as c from business_outbox where event_type='payment.paid'"
        ).fetchone()["c"] == 0  # late money never queues production
        assert connection.execute(
            "select count(*) as c from production_job where order_id=%s", (order_id,)
        ).fetchone()["c"] == 0

        replay, replay_duplicate = apply_paid_callback(
            connection, provider="mock", event_id="late-2", values=values
        )
        assert replay_duplicate is True
        assert replay["status"] == "REFUNDING"  # never written back to PAID
        assert connection.execute(
            "select count(*) as c from refund where payment_id=%s", (payment["id"],)
        ).fetchone()["c"] == 1
        assert connection.execute(
            "select count(*) as c from payment_callback_inbox where payment_id=%s",
            (payment["id"],),
        ).fetchone()["c"] == 2


def test_extra_payment_is_refunded_without_touching_primary_projection(postgres_database) -> None:
    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection)
        order_id, primary = seed_paid_queued_order(connection, terminal_id)
        extra = insert_payment(connection, order_id, status="PENDING")

        updated, duplicate = apply_paid_callback(
            connection, provider="mock", event_id="extra-1", values=paid_callback_values(extra)
        )
        assert duplicate is False
        assert updated["status"] == "REFUNDING"
        order = OrderRepository(connection).find(order_id)
        assert order["paid_payment_id"] == primary["id"]  # primary stays the first payment
        assert order["payment_status"] == "PAID"  # order projection untouched
        assert PaymentRepository(connection).find(primary["id"])["status"] == "PAID"
        assert connection.execute(
            "select count(*) as c from business_outbox where event_type='payment.paid'"
        ).fetchone()["c"] == 0  # extra money never dispatches a second job
        refund = connection.execute(
            "select * from refund where payment_id=%s", (extra["id"],)
        ).fetchone()
        assert refund["amount_minor"] == 1000

        settled = apply_refund_outcome(
            connection, refund_id=refund["id"], target="SUCCEEDED", actor="test"
        )
        assert settled["status"] == "SUCCEEDED"
        assert PaymentRepository(connection).find(extra["id"])["status"] == "REFUNDED"
        order = OrderRepository(connection).find(order_id)
        assert order["payment_status"] == "PAID"  # still untouched
        view = OrderRepository(connection).public_view(order_id)["payment_json"]
        assert view["id"] == str(primary["id"])  # public projection prefers the primary


def test_inflight_budget_blocks_second_partial_refund_and_unknown_occupies(postgres_database) -> None:
    with postgres_database.connect() as connection:
        orders = OrderRepository(connection)
        payments = PaymentRepository(connection)
        terminal_id = insert_terminal(connection)
        order_id, payment = seed_paid_queued_order(connection, terminal_id)
        orders.find(order_id, for_update=True)

        first = create_refund_intent(
            connection, payment_id=payment["id"], idempotency_key="r700",
            amount_minor=700, reason="partial",
        )
        assert first.created and first.refund["amount_minor"] == 700

        with pytest.raises(ServiceError) as over:
            create_refund_intent(
                connection, payment_id=payment["id"], idempotency_key="r700b",
                amount_minor=700, reason="over",
            )
        assert over.value.status_code == 409
        assert payments.refunded_total(payment["id"], statuses=BUDGET_REFUND_STATUSES) == 700

        apply_refund_outcome(
            connection, refund_id=first.refund["id"], target="UNKNOWN", actor="test"
        )
        assert payments.refunded_total(payment["id"], statuses=BUDGET_REFUND_STATUSES) == 700
        with pytest.raises(ServiceError):
            create_refund_intent(
                connection, payment_id=payment["id"], idempotency_key="r400",
                amount_minor=400, reason="still over",
            )
        tail = create_refund_intent(
            connection, payment_id=payment["id"], idempotency_key="r300",
            amount_minor=300, reason="remaining",
        )
        assert tail.created and tail.refund["amount_minor"] == 300


def test_manual_refund_api_only_schedules_and_defaults_to_remaining_budget(postgres_database) -> None:
    provider = RecordingProvider()
    service = PaymentApplicationService(
        UnitOfWork(postgres_database), payment_settings(),
        provider_factory=lambda *_: provider, mock_provider=provider,
    )
    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection)
        order_id, payment = seed_paid_queued_order(connection, terminal_id)
        connection.execute("update sales_order set status='FAILED' where id=%s", (order_id,))

    partial = service.refund(payment["id"], RefundCreateRequest(amountMinor=700), "manual-1")
    assert partial["status"] == "REQUESTED" and partial["duplicate"] is False
    assert provider.refund_calls == []  # the API never submits to the channel
    apply_succeeded(postgres_database, uuid.UUID(partial["refundId"]))

    with postgres_database.connect() as connection:
        orders = OrderRepository(connection)
        current = PaymentRepository(connection).find(payment["id"])
        assert current["status"] == "PARTIALLY_REFUNDED"
        order = orders.find(order_id)
        assert order["payment_status"] == "PARTIALLY_REFUNDED"

    remaining = service.refund(payment["id"], RefundCreateRequest(), "manual-2")
    assert remaining["status"] == "REQUESTED"
    assert provider.refund_calls == []
    apply_succeeded(postgres_database, uuid.UUID(remaining["refundId"]))

    with postgres_database.connect() as connection:
        orders = OrderRepository(connection)
        current = PaymentRepository(connection).find(payment["id"])
        order = orders.find(order_id)
        assert current["status"] == "REFUNDED"
        assert order["payment_status"] == "REFUNDED"
        assert order["status"] == "REFUNDED"  # failed order closed by full refund

    repeated = service.refund(payment["id"], RefundCreateRequest(), "manual-2")
    assert repeated["duplicate"] is True and repeated["status"] == "SUCCEEDED"
    with postgres_database.connect() as connection:
        total = connection.execute(
            "select count(*) as c from refund where payment_id=%s", (payment["id"],)
        ).fetchone()["c"]
        assert total == 2
    assert provider.refund_calls == []  # duplicates never resubmit either


def test_channel_permanent_failure_is_terminal_and_frees_budget(postgres_database) -> None:
    from app.services.background_worker import BackgroundWorkerService

    provider = RecordingProvider()
    provider.refund_status = "FAILED"
    worker = BackgroundWorkerService(
        UnitOfWork(postgres_database), payment_settings(),
        payment_provider=lambda *_: provider,
        production=ProductionService(payment_settings(), payment_provider=lambda *_: provider),
    )
    with postgres_database.connect() as connection:
        orders = OrderRepository(connection)
        terminal_id = insert_terminal(connection)
        order_id, payment = seed_paid_queued_order(connection, terminal_id)
        orders.find(order_id, for_update=True)
        intent = create_refund_intent(
            connection, payment_id=payment["id"], idempotency_key="fail-1", amount_minor=700,
            reason="will fail permanently",
        )

    assert worker.process_refund_batch() == 1
    with postgres_database.connect() as connection:
        refund = PaymentRepository(connection).find_refund(intent.refund["id"])
        assert refund["status"] == "FAILED"  # not endlessly PROCESSING
        assert refund["completed_at"] is not None

    assert worker.process_refund_batch() == 0  # FAILED is never claimed again
    assert len(provider.refund_calls) == 1

    with postgres_database.connect() as connection:
        orders = OrderRepository(connection)
        orders.find(order_id, for_update=True)
        retry = create_refund_intent(
            connection, payment_id=payment["id"], idempotency_key="fail-2",
            reason="retry after permanent failure",
        )
        assert retry.created and retry.refund["amount_minor"] == 1000  # budget was freed


def test_worker_submits_refund_once_and_settles_primary_projection(postgres_database) -> None:
    from app.services.background_worker import BackgroundWorkerService

    provider = RecordingProvider()
    worker = BackgroundWorkerService(
        UnitOfWork(postgres_database), payment_settings(),
        payment_provider=lambda *_: provider,
        production=ProductionService(payment_settings(), payment_provider=lambda *_: provider),
    )
    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection)
        order_id, payment = seed_paid_queued_order(connection, terminal_id)
        orders = OrderRepository(connection)
        orders.find(order_id, for_update=True)
        create_refund_intent(
            connection, payment_id=payment["id"], idempotency_key="auto-1", reason="full refund"
        )

    assert worker.process_refund_batch() == 1
    assert worker.process_refund_batch() == 0
    assert len(provider.refund_calls) == 1

    with postgres_database.connect() as connection:
        orders = OrderRepository(connection)
        payments = PaymentRepository(connection)
        assert payments.find(payment["id"])["status"] == "REFUNDED"
        order = orders.find(order_id)
        assert order["payment_status"] == "REFUNDED"
        refund = connection.execute(
            "select * from refund where payment_id=%s", (payment["id"],)
        ).fetchone()
        assert refund["status"] == "SUCCEEDED"


def test_concurrent_callbacks_and_refunds_respect_lock_order_and_budget(postgres_database) -> None:
    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection)
        order_id = insert_order(connection, terminal_id)
        payment = insert_payment(connection, order_id, status="PENDING")
        callback_values = paid_callback_values(payment)

    errors: list[Exception] = []

    def callback(event_id: str) -> None:
        try:
            with postgres_database.connect() as connection:
                apply_paid_callback(
                    connection, provider="mock", event_id=event_id,
                    values=callback_values,
                )
        except Exception as exc:  # pragma: no cover - only on failure
            errors.append(exc)

    threads = [threading.Thread(target=callback, args=(f"race-{index}",)) for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []

    with postgres_database.connect() as connection:
        current = PaymentRepository(connection).find(payment["id"])
        assert current["status"] == "PAID"
        assert connection.execute(
            "select count(*) as c from payment_callback_inbox where payment_id=%s",
            (payment["id"],),
        ).fetchone()["c"] == 4
        assert connection.execute(
            "select count(*) as c from business_outbox where event_type='payment.paid'"
        ).fetchone()["c"] == 1
        connection.execute(
            "update sales_order set paid_payment_id=%s where id=%s", (payment["id"], order_id)
        )

    outcomes: list[str] = []

    def refund_attempt(key: str) -> None:
        try:
            with postgres_database.connect() as connection:
                orders = OrderRepository(connection)
                orders.find(order_id, for_update=True)  # required financial lock order
                create_refund_intent(
                    connection, payment_id=payment["id"], idempotency_key=key,
                    amount_minor=700, reason="race",
                )
            outcomes.append("created")
        except ServiceError:
            outcomes.append("rejected")
        except Exception as exc:  # pragma: no cover - only on failure
            errors.append(exc)

    threads = [
        threading.Thread(target=refund_attempt, args=(f"race-refund-{index}",)) for index in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert sorted(outcomes) == ["created", "rejected"]

    with postgres_database.connect() as connection:
        frozen = PaymentRepository(connection).refunded_total(
            payment["id"], statuses=BUDGET_REFUND_STATUSES
        )
        assert frozen == 700  # two concurrent 700s cannot over-freeze a 1000 payment


def test_migration_backfills_primary_payment_from_earliest_paid_at(half_migrated_database) -> None:
    with half_migrated_database.connect() as connection:
        terminal_id = insert_terminal(connection)
        paid_order = insert_order(
            connection, terminal_id, status="REFUNDED", payment_status="REFUNDED"
        )
        older = connection.execute(
            """insert into payment(id,order_id,provider,merchant_payment_no,idempotency_key,
                   request_digest,status,amount_minor,currency,subject,paid_at)
                 values(%s,%s,'mock',%s,%s,%s,'REFUNDED',1000,'CNY','Coffee',now()-interval '2 hours')
                 returning *""",
            (uuid.uuid4(), paid_order, f"C{uuid.uuid4().hex[:8].upper()}", str(uuid.uuid4()), "d" * 64),
        ).fetchone()
        newer = connection.execute(
            """insert into payment(id,order_id,provider,merchant_payment_no,idempotency_key,
                   request_digest,status,amount_minor,currency,subject,paid_at)
                 values(%s,%s,'mock',%s,%s,%s,'REFUNDING',1000,'CNY','Coffee',now()-interval '1 hour')
                 returning *""",
            (uuid.uuid4(), paid_order, f"C{uuid.uuid4().hex[:8].upper()}", str(uuid.uuid4()), "d" * 64),
        ).fetchone()
        unpaid_order = insert_order(connection, terminal_id, status="AWAITING_PAYMENT")
        insert_payment(connection, unpaid_order, status="PENDING")
        assert connection.execute(
            """select count(*) as c from information_schema.columns
                where column_name='paid_payment_id' and table_schema=current_schema()"""
        ).fetchone()["c"] == 0  # column really does not exist yet

        migration = next(item for item in MIGRATIONS if item[0] == 10)
        connection.execute(migration[2])
        connection.execute(
            "insert into schema_migration(version,name) values(%s,%s)", (migration[0], migration[1])
        )

        rows = connection.execute(
            "select id,paid_payment_id from sales_order where id in (%s,%s)",
            (paid_order, unpaid_order),
        ).fetchall()
        by_order = {row["id"]: row["paid_payment_id"] for row in rows}
        assert by_order[paid_order] == older["id"]  # earliest paid_at wins, not the newest
        assert by_order[paid_order] != newer["id"]
        assert by_order[unpaid_order] is None


def test_paid_outbox_event_queues_the_order_once_and_only_for_primary(postgres_database) -> None:
    from app.services.background_worker import BackgroundWorkerService

    provider = RecordingProvider()
    worker = BackgroundWorkerService(
        UnitOfWork(postgres_database), payment_settings(),
        payment_provider=lambda *_: provider,
        production=ProductionService(payment_settings(), payment_provider=lambda *_: provider),
    )
    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection)
        order_id = insert_order(connection, terminal_id)
        payment = insert_payment(connection, order_id, status="PENDING")
        extra = insert_payment(connection, order_id, status="PENDING")

        apply_paid_callback(
            connection, provider="mock", event_id="outbox-1", values=paid_callback_values(payment)
        )
        # Simulate a legacy event claiming the extra intent funded the order.
        enqueue_outbox(
            connection, "payment.paid", "payment", str(extra["id"]),
            {"paymentId": str(extra["id"]), "orderId": str(order_id), "terminalId": terminal_id},
            f"payment:{extra['id']}:paid",
        )

    assert worker.process_business_outbox_batch() == 2

    with postgres_database.connect() as connection:
        orders = OrderRepository(connection)
        order = orders.find(order_id)
        assert order["status"] == "QUEUED"  # paid order queued exactly once
        assert order["paid_payment_id"] == payment["id"]
        jobs = connection.execute(
            "select * from production_job where order_id=%s", (order_id,)
        ).fetchall()
        assert len(jobs) == 1  # the extra payment event must not create a second job
        assert connection.execute(
            "select count(*) as c from terminal_dispatch_request where terminal_id=%s",
            (terminal_id,),
        ).fetchone()["c"] == 1


# ---------------------------------------------------------------------------
# A1 review follow-up: replayed callbacks, failed refund settlement, automatic
# refund budget on cancel, outbox-aware expiry, close_payment contracts.
# ---------------------------------------------------------------------------


class CloseResultProvider(RecordingProvider):
    """Channel whose close_payment returns a scripted outcome."""

    def __init__(self, close_result: ProviderResult) -> None:
        super().__init__()
        self.close_result = close_result

    def close_payment(self, merchant_no: str) -> ProviderResult:
        self.close_calls.append(merchant_no)
        return self.close_result


def seed_refunding_order(connection, terminal_id: int, *, order_status: str, order_payment_status: str, payment_status: str, refund_status: str | None):
    order_id = insert_order(
        connection, terminal_id, status=order_status, payment_status=order_payment_status
    )
    payment = insert_payment(connection, order_id, status=payment_status, paid=True)
    connection.execute(
        "update sales_order set paid_payment_id=%s where id=%s", (payment["id"], order_id)
    )
    if refund_status is not None:
        connection.execute(
            """insert into refund(id,payment_id,provider,merchant_refund_no,idempotency_key,
                   request_digest,status,amount_minor,reason)
                 values(%s,%s,'mock',%s,%s,%s,%s,1000,'test')""",
            (uuid.uuid4(), payment["id"], f"R{uuid.uuid4().hex[:12].upper()}",
             str(uuid.uuid4()), "d" * 64, refund_status),
        )
    return order_id, payment


@pytest.mark.parametrize(
    "order_status,order_payment_status,payment_status,refund_status",
    [
        ("READY", "REFUNDING", "REFUNDING", "PROCESSING"),
        ("READY", "REFUNDED", "REFUNDED", "SUCCEEDED"),
        ("FAILED", "REFUNDED", "REFUNDED", "SUCCEEDED"),
    ],
)
def test_replayed_paid_callback_with_new_event_id_never_regresses_refund_states(
    postgres_database, order_status, order_payment_status, payment_status, refund_status
) -> None:
    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection)
        order_id, payment = seed_refunding_order(
            connection, terminal_id,
            order_status=order_status, order_payment_status=order_payment_status,
            payment_status=payment_status, refund_status=refund_status,
        )
        values = paid_callback_values(payment)

        first, duplicate = apply_paid_callback(
            connection, provider="mock", event_id="replay-a", values=values
        )
        assert duplicate is True  # already recorded money: idempotent confirm only
        second, second_duplicate = apply_paid_callback(
            connection, provider="mock", event_id="replay-b", values=values
        )
        assert second_duplicate is True

        orders = OrderRepository(connection)
        order = orders.find(order_id)
        assert order["status"] == order_status
        assert order["payment_status"] == order_payment_status  # never back to PAID
        assert PaymentRepository(connection).find(payment["id"])["status"] == payment_status
        assert connection.execute(
            "select count(*) as c from business_outbox where event_type='payment.paid'"
        ).fetchone()["c"] == 0  # payment.paid is never enqueued twice
        assert connection.execute(
            "select count(*) as c from refund where payment_id=%s", (payment["id"],)
        ).fetchone()["c"] == 1


def test_all_refunds_failed_settles_back_to_paid_on_the_settlement_path(postgres_database) -> None:
    from app.services.background_worker import BackgroundWorkerService

    provider = RecordingProvider()
    provider.refund_status = "FAILED"
    worker = BackgroundWorkerService(
        UnitOfWork(postgres_database), payment_settings(),
        payment_provider=lambda *_: provider,
        production=ProductionService(payment_settings(), payment_provider=lambda *_: provider),
    )
    with postgres_database.connect() as connection:
        orders = OrderRepository(connection)
        terminal_id = insert_terminal(connection)
        order_id, payment = seed_paid_queued_order(connection, terminal_id)
        orders.find(order_id, for_update=True)
        create_refund_intent(
            connection, payment_id=payment["id"], idempotency_key="full-fail", reason="full refund"
        )

    assert worker.process_refund_batch() == 1
    with postgres_database.connect() as connection:
        orders = OrderRepository(connection)
        payments = PaymentRepository(connection)
        refund = payments.find_refund_idempotent(payment["id"], "full-fail")
        assert refund["status"] == "FAILED" and refund["completed_at"] is not None
        assert payments.find(payment["id"])["status"] == "PAID"  # settlement-only path
        order = orders.find(order_id)
        assert order["payment_status"] == "PAID" and order["status"] == "QUEUED"

        # A stale "still processing" channel result must not resurrect the refund.
        stale = apply_refund_outcome(
            connection, refund_id=refund["id"], target="PROCESSING", actor="test"
        )
        assert stale["status"] == "FAILED"


def test_partial_success_then_partial_failure_stays_partially_refunded(postgres_database) -> None:
    with postgres_database.connect() as connection:
        orders = OrderRepository(connection)
        terminal_id = insert_terminal(connection)
        order_id, payment = seed_paid_queued_order(connection, terminal_id)
        orders.find(order_id, for_update=True)
        ok = create_refund_intent(
            connection, payment_id=payment["id"], idempotency_key="part-ok", amount_minor=700,
            reason="partial",
        )
        apply_refund_outcome(connection, refund_id=ok.refund["id"], target="SUCCEEDED", actor="test")
        bad = create_refund_intent(
            connection, payment_id=payment["id"], idempotency_key="part-bad", amount_minor=300,
            reason="will fail",
        )
        apply_refund_outcome(connection, refund_id=bad.refund["id"], target="FAILED", actor="test")

        payments = PaymentRepository(connection)
        assert payments.find(payment["id"])["status"] == "PARTIALLY_REFUNDED"
        assert orders.find(order_id)["payment_status"] == "PARTIALLY_REFUNDED"


def test_cancel_succeeds_when_full_refund_is_already_in_flight(postgres_database) -> None:
    provider = RecordingProvider()
    service = PublicOrderService(
        UnitOfWork(postgres_database), Settings.model_construct(),
        request_dispatch=lambda *_: None, payment_provider=lambda *_: provider,
    )
    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection)
        order_id, payment = seed_refunding_order(
            connection, terminal_id,
            order_status="QUEUED", order_payment_status="REFUNDING",
            payment_status="REFUNDING", refund_status="PROCESSING",
        )

    result = service.cancel(order_id, order_token(order_id))
    assert result["status"] == "CANCELLED"  # not a 409 budget conflict
    with postgres_database.connect() as connection:
        assert connection.execute(
            "select count(*) as c from refund where payment_id=%s", (payment["id"],)
        ).fetchone()["c"] == 1  # no duplicate automatic intent


def seed_command_with_outbox(
    connection, terminal_id: int, order_id: uuid.UUID, *,
    outbox_status: str | None, attempt_count: int = 0, outbox_published: bool = False,
    delivered: bool = False,
) -> dict:
    message_id = f"cmd-{uuid.uuid4()}"
    row = connection.execute(
        """insert into terminal_command(terminal_id,message_id,command_type,payload_json,status,
               expires_at,published_at,delivered_at)
             values(%s,%s,'MAKE_DRINK',%s,'CREATED',now()-interval '1 minute',%s,%s) returning *""",
        (terminal_id, message_id, Jsonb({"messageId": message_id, "taskId": f"task-{message_id}"}),
         "now()" if outbox_published or delivered else None, "now()" if delivered else None),
    ).fetchone()
    if outbox_status is not None:
        connection.execute(
            """insert into command_outbox(id,command_id,terminal_id,topic,envelope_json,
                   status,attempt_count,published_at)
                 values(%s,%s,%s,'t/down',%s,%s,%s,%s)""",
            (uuid.uuid4(), row["id"], terminal_id, Jsonb({"messageId": message_id}),
             outbox_status, attempt_count, "now()" if outbox_published else None),
        )
    connection.execute(
        "update production_job set command_id=%s,status='DISPATCHED' where order_id=%s",
        (row["id"], order_id),
    )
    connection.execute(
        "update sales_order set status='DISPATCHED' where id=%s", (order_id,)
    )
    return row


def test_expire_holds_orders_when_outbox_was_claimed_or_attempted(postgres_database) -> None:
    production = ProductionService(payment_settings(), payment_provider=lambda *_: RecordingProvider())
    for name, outbox_status, attempts in (("publishing", "PUBLISHING", 0), ("retry", "RETRY", 1)):
        with postgres_database.connect() as connection:
            terminal_id = insert_terminal(connection, f"expire-{name}")
            order_id, payment = seed_paid_queued_order(connection, terminal_id)
            command = seed_command_with_outbox(
                connection, terminal_id, order_id,
                outbox_status=outbox_status, attempt_count=attempts,
            )

            verdict = production.expire_order_for_command(connection, command)

            assert verdict == "UNKNOWN"  # may have reached the broker already
            orders = OrderRepository(connection)
            assert orders.find(order_id)["status"] == "HOLD"
            assert orders.job(order_id)["manual_review_required"] is True
            assert connection.execute(
                "select count(*) as c from refund where payment_id=%s", (payment["id"],)
            ).fetchone()["c"] == 0  # never auto-refund an unknown outcome


def test_expire_terminalizes_outbox_and_refunds_when_never_claimed(postgres_database) -> None:
    production = ProductionService(payment_settings(), payment_provider=lambda *_: RecordingProvider())
    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection, "expire-pending")
        order_id, payment = seed_paid_queued_order(connection, terminal_id)
        command = seed_command_with_outbox(
            connection, terminal_id, order_id, outbox_status="PENDING"
        )

        verdict = production.expire_order_for_command(connection, command)

        assert verdict == "EXPIRED"
        assert OrderRepository(connection).find(order_id)["status"] == "EXPIRED"
        refunds = connection.execute(
            "select * from refund where payment_id=%s", (payment["id"],)
        ).fetchall()
        assert len(refunds) == 1 and refunds[0]["amount_minor"] == 1000
        outbox = connection.execute(
            "select * from command_outbox where command_id=%s", (command["id"],)
        ).fetchone()
        assert outbox["status"] == "EXPIRED"  # can never be published after the refund
        assert CommandRepository(connection).claim("gateway", 10, 30) == []


def test_claim_filters_terminal_commands(postgres_database) -> None:
    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection, "claim-filter")
        live = connection.execute(
            """insert into terminal_command(terminal_id,message_id,command_type,payload_json)
                 values(%s,%s,'MAKE_DRINK',%s) returning id""",
            (terminal_id, f"cmd-live-{uuid.uuid4()}", Jsonb({})),
        ).fetchone()
        expired = connection.execute(
            """insert into terminal_command(terminal_id,message_id,command_type,payload_json,status)
                 values(%s,%s,'MAKE_DRINK',%s,'EXPIRED') returning id""",
            (terminal_id, f"cmd-dead-{uuid.uuid4()}", Jsonb({})),
        ).fetchone()
        for row in (live, expired):
            connection.execute(
                """insert into command_outbox(id,command_id,terminal_id,topic,envelope_json)
                     values(%s,%s,%s,'t/down',%s)""",
                (uuid.uuid4(), row["id"], terminal_id, Jsonb({})),
            )

        claimed = CommandRepository(connection).claim("gateway", 10, 30)
        assert [row["command_id"] for row in claimed] == [live["id"]]


def test_claim_only_takes_future_deadline_deliverable_commands(postgres_database) -> None:
    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection, "claim-window")
        order_id, _ = seed_paid_queued_order(connection, terminal_id)
        repository = CommandRepository(connection)
        rows = {}
        for name, status, deadline in (
            ("future", "CREATED", "now()+interval '1 hour'"),
            ("unknown", "UNKNOWN", "now()+interval '1 hour'"),
            ("past", "CREATED", "now()-interval '1 minute'"),
        ):
            rows[name] = connection.execute(
                """insert into terminal_command(terminal_id,message_id,command_type,payload_json,
                       status,expires_at)
                     values(%s,%s,'MAKE_DRINK',%s,%s,""" + deadline + """) returning id""",
                (terminal_id, f"cmd-{name}-{uuid.uuid4()}", Jsonb({}), status),
            ).fetchone()
            repository.insert_outbox(rows[name]["id"], terminal_id, "t/down", {})

        claimed = repository.claim("gateway", 10, 30)

        # UNKNOWN must never re-drive physical production, a past deadline
        # belongs to the expiry scan, and only the live future command is taken.
        assert [row["command_id"] for row in claimed] == [rows["future"]["id"]]


def test_publish_confirmation_and_expiry_never_deadlock(postgres_database, monkeypatch) -> None:
    from app.services.background_worker import BackgroundWorkerService
    from app.services.command_state import transition_command
    from app.services.commands import CommandService
    from app.repositories.workers import WorkerRepository

    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection, "lock-order-publish")
        order_id, _ = seed_paid_queued_order(connection, terminal_id)
        seed_command_with_outbox(
            connection, terminal_id, order_id, outbox_status="PUBLISHING", attempt_count=1
        )
        outbox_id = connection.execute(
            "update command_outbox set locked_by='gw',locked_until=now()+interval '30 seconds' returning id"
        ).fetchone()["id"]

    # Deterministic interleaving: the publish confirmation holds the command and
    # outbox locks while the offline scan has already selected its candidates;
    # the scan must not block on or deadlock against the confirmation.
    outbox_locked, expiry_selected = threading.Event(), threading.Event()
    original_outbox = CommandRepository.outbox
    original_expired = WorkerRepository.expired_commands

    def observed_outbox(self, *args, **kwargs):
        row = original_outbox(self, *args, **kwargs)
        outbox_locked.set()
        assert expiry_selected.wait(10), "expiry scan never selected its candidates"
        return row

    def observed_expired(self, *args, **kwargs):
        rows = original_expired(self, *args, **kwargs)
        expiry_selected.set()
        return rows

    monkeypatch.setattr(CommandRepository, "outbox", observed_outbox)
    monkeypatch.setattr(WorkerRepository, "expired_commands", observed_expired)
    service = CommandService(UnitOfWork(postgres_database), lease_seconds=30,
        transition_command=transition_command)
    provider = RecordingProvider()
    worker = BackgroundWorkerService(UnitOfWork(postgres_database), payment_settings(),
        payment_provider=lambda *_: provider,
        production=ProductionService(payment_settings(), payment_provider=lambda *_: provider))
    errors: list[Exception] = []

    def guarded(operation):
        try:
            operation()
        except Exception as error:  # pragma: no cover - only on failure
            errors.append(error)

    publish_thread = threading.Thread(target=guarded, args=(lambda: service.published(outbox_id, "gw"),))
    expiry_thread = threading.Thread(target=guarded, args=(worker.offline_scan_once,))
    publish_thread.start()
    assert outbox_locked.wait(10)
    expiry_thread.start()
    publish_thread.join(30)
    expiry_thread.join(30)
    assert not publish_thread.is_alive() and not expiry_thread.is_alive()
    assert not errors, [f"{type(error).__name__}: {error}" for error in errors]


def test_expiry_recheck_never_overwrites_event_advanced_commands(postgres_database) -> None:
    from app.services.background_worker import BackgroundWorkerService
    from app.services.command_state import transition_command

    provider = RecordingProvider()
    worker = BackgroundWorkerService(
        UnitOfWork(postgres_database), payment_settings(),
        payment_provider=lambda *_: provider,
        production=ProductionService(payment_settings(), payment_provider=lambda *_: provider),
    )
    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection, "expire-event-race")
        order_id, payment = seed_paid_queued_order(connection, terminal_id)
        command = seed_command_with_outbox(
            connection, terminal_id, order_id, outbox_status="PENDING"
        )
        # The scan captures its read-only candidates...
        candidates = connection.execute(
            "select * from terminal_command where status='CREATED' and expires_at<=now()"
        ).fetchall()
        assert [row["id"] for row in candidates] == [command["id"]]
        # ...then a device event lands before per-command processing.
        commands = CommandRepository(connection)
        updated, _ = transition_command(
            connection, commands.by_db_id(command["id"]), "PUBLISHED", "device-event",
            reason="late event",
        )
        transition_command(connection, updated, "SUCCEEDED", "device-event", reason="late event")

    worker.offline_scan_once()

    with postgres_database.connect() as connection:
        final = connection.execute(
            "select status from terminal_command where id=%s", (command["id"],)
        ).fetchone()["status"]
        assert final == "SUCCEEDED"  # never regressed to EXPIRED from a stale snapshot
        assert OrderRepository(connection).find(order_id)["status"] != "EXPIRED"
        assert connection.execute(
            "select count(*) as c from refund where payment_id=%s", (payment["id"],)
        ).fetchone()["c"] == 0


def test_never_sent_refunded_command_is_invisible_to_pull_and_claim(postgres_database) -> None:
    from app.services.background_worker import BackgroundWorkerService
    from app.services.command_state import transition_command
    from app.services.device_messages import DeviceMessageService

    provider = RecordingProvider()
    production = ProductionService(payment_settings(), payment_provider=lambda *_: provider)
    worker = BackgroundWorkerService(
        UnitOfWork(postgres_database), payment_settings(),
        payment_provider=lambda *_: provider, production=production,
    )
    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection, "expire-invisible")
        order_id, payment = seed_paid_queued_order(connection, terminal_id)
        seed_command_with_outbox(connection, terminal_id, order_id, outbox_status="PENDING")

    worker.offline_scan_once()

    with postgres_database.connect() as connection:
        assert connection.execute(
            "select count(*) as c from refund where payment_id=%s", (payment["id"],)
        ).fetchone()["c"] == 1  # never sent: money released in the same transaction
        assert CommandRepository(connection).claim("gateway", 10, 30) == []
        device_id = connection.execute(
            "select device_id from terminal where id=%s", (terminal_id,)
        ).fetchone()["device_id"]
    service = DeviceMessageService(
        UnitOfWork(postgres_database),
        request_dispatch=lambda *args, **kwargs: None,
        transition_command=transition_command,
        expire_order_for_command=production.expire_order_for_command,
        reconcile_command_event=lambda *args, **kwargs: None,
        reconcile_order_event=lambda *args, **kwargs: None,
        reconcile_order_ack=lambda *args, **kwargs: None,
        order_url=lambda device: "",
    )
    assert service.commands({"id": terminal_id, "device_id": device_id}, "0", 50)["commands"] == []


def test_claim_and_expire_race_never_publishes_after_refund(postgres_database) -> None:
    from app.services.background_worker import BackgroundWorkerService

    provider = RecordingProvider()
    worker = BackgroundWorkerService(
        UnitOfWork(postgres_database), payment_settings(),
        payment_provider=lambda *_: provider,
        production=ProductionService(payment_settings(), payment_provider=lambda *_: provider),
    )
    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection, "expire-race")
        order_id, _payment = seed_paid_queued_order(connection, terminal_id)
        seed_command_with_outbox(connection, terminal_id, order_id, outbox_status="PENDING")

    errors: list[Exception] = []

    def expire() -> None:
        try:
            worker.offline_scan_once()
        except Exception as exc:  # pragma: no cover - only on failure
            errors.append(exc)

    def gateway_claim() -> None:
        try:
            for _ in range(20):
                with postgres_database.connect() as connection:
                    commands = CommandRepository(connection)
                    for row in commands.claim("gateway", 5, 30):
                        commands.mark_published(row["id"])
        except Exception as exc:  # pragma: no cover - only on failure
            errors.append(exc)

    threads = [threading.Thread(target=expire), threading.Thread(target=gateway_claim)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert errors == []

    with postgres_database.connect() as connection:
        order = OrderRepository(connection).find(order_id)
        command = connection.execute(
            "select * from terminal_command where terminal_id=%s", (terminal_id,)
        ).fetchone()
        outbox = connection.execute(
            "select * from command_outbox where command_id=%s", (command["id"],)
        ).fetchone()
        assert command["status"] in {"EXPIRED", "UNKNOWN"}
        if order["status"] == "EXPIRED":
            # Refunded orders must never end up with a published command.
            assert outbox["status"] != "PUBLISHED"
            assert outbox["status"] == "EXPIRED"


def test_close_result_paid_is_recorded_via_callback_compensation(postgres_database) -> None:
    provider = CloseResultProvider(ProviderResult("PAID", provider_trade_no=f"late-{uuid.uuid4().hex[:8]}"))
    service = PublicOrderService(
        UnitOfWork(postgres_database), Settings.model_construct(),
        request_dispatch=lambda *_: None, payment_provider=lambda *_: provider,
    )
    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection, "close-paid")
        order_id = insert_order(connection, terminal_id, status="AWAITING_PAYMENT")
        payment = insert_payment(connection, order_id, status="PENDING")

    result = service.cancel(order_id, order_token(order_id))
    assert result["status"] == "CANCELLED"
    with postgres_database.connect() as connection:
        orders = OrderRepository(connection)
        order = orders.find(order_id)
        assert order["payment_status"] == "REFUNDING"  # late money recorded and refunded
        assert order["paid_payment_id"] == payment["id"]
        current = PaymentRepository(connection).find(payment["id"])
        assert current["status"] == "REFUNDING" and current["paid_at"] is not None
        assert connection.execute(
            "select count(*) as c from refund where payment_id=%s", (payment["id"],)
        ).fetchone()["c"] == 1


def test_close_result_unknown_stays_pending_for_reconciliation(postgres_database) -> None:
    provider = CloseResultProvider(ProviderResult("UNKNOWN"))
    service = PublicOrderService(
        UnitOfWork(postgres_database), Settings.model_construct(),
        request_dispatch=lambda *_: None, payment_provider=lambda *_: provider,
    )
    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection, "close-unknown")
        order_id = insert_order(connection, terminal_id, status="AWAITING_PAYMENT")
        payment = insert_payment(connection, order_id, status="PENDING")

    service.cancel(order_id, order_token(order_id))
    with postgres_database.connect() as connection:
        current = PaymentRepository(connection).find(payment["id"])
        assert current["status"] == "PENDING"  # undecided; the worker owns it
        assert current["next_reconcile_at"] is not None
        order = OrderRepository(connection).find(order_id)
        assert order["payment_status"] != "CLOSED"


def test_close_visits_multiple_open_intents_in_stable_id_order(postgres_database) -> None:
    provider = CloseResultProvider(ProviderResult("CLOSED"))
    service = PublicOrderService(
        UnitOfWork(postgres_database), Settings.model_construct(),
        request_dispatch=lambda *_: None, payment_provider=lambda *_: provider,
    )
    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection, "close-order")
        order_id = insert_order(connection, terminal_id, status="AWAITING_PAYMENT")
        first = insert_payment(connection, order_id, status="CREATED")
        second = insert_payment(connection, order_id, status="PENDING")

    service.cancel(order_id, order_token(order_id))
    with postgres_database.connect() as connection:
        rows = connection.execute(
            "select merchant_payment_no,id from payment where order_id=%s order by created_at,id",
            (order_id,),
        ).fetchall()
        expected = [row["merchant_payment_no"] for row in rows if row["id"] in {first["id"], second["id"]}]
        assert provider.close_calls == expected  # stable created_at,id order


def test_conflicting_trade_no_and_missing_amount_are_rejected(postgres_database) -> None:
    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection)
        order_id, payment = seed_paid_queued_order(connection, terminal_id)
        values = paid_callback_values(payment)
        first, _ = apply_paid_callback(
            connection, provider="mock", event_id="trade-1", values=values
        )
        assert first["provider_trade_no"] == values["provider_trade_no"]

        # A different channel trade number must be rejected, never merged.
        with pytest.raises(HTTPException) as conflict:
            apply_paid_callback(
                connection, provider="mock", event_id="trade-2",
                values={**values, "provider_trade_no": "another-trade-no"},
            )
        assert conflict.value.status_code == 409
        current = PaymentRepository(connection).find(payment["id"])
        assert current["provider_trade_no"] == values["provider_trade_no"]

        # A paid fact without an amount must never confirm money.
        with pytest.raises(HTTPException) as missing:
            apply_paid_callback(
                connection, provider="mock", event_id="trade-3",
                values={"merchant_payment_no": payment["merchant_payment_no"]},
            )
        assert missing.value.status_code == 409


def test_paid_outbox_never_queues_terminal_or_refunding_orders(postgres_database) -> None:
    from app.services.background_worker import BackgroundWorkerService

    provider = RecordingProvider()
    worker = BackgroundWorkerService(
        UnitOfWork(postgres_database), payment_settings(),
        payment_provider=lambda *_: provider,
        production=ProductionService(payment_settings(), payment_provider=lambda *_: provider),
    )
    with postgres_database.connect() as connection:
        terminal_id = insert_terminal(connection, "outbox-dead")
        ready_order, ready_payment = seed_refunding_order(
            connection, terminal_id,
            order_status="READY", order_payment_status="PAID",
            payment_status="PAID", refund_status=None,
        )
        connection.execute("delete from production_job where order_id=%s", (ready_order,))
        enqueue_outbox(
            connection, "payment.paid", "payment", str(ready_payment["id"]),
            {"paymentId": str(ready_payment["id"]), "orderId": str(ready_order), "terminalId": terminal_id},
            f"payment:{ready_payment['id']}:paid",
        )

    assert worker.process_business_outbox_batch() == 1
    with postgres_database.connect() as connection:
        orders = OrderRepository(connection)
        assert orders.find(ready_order)["status"] == "READY"  # never re-queued
        assert connection.execute(
            "select count(*) as c from production_job where order_id=%s", (ready_order,)
        ).fetchone()["c"] == 0  # no production job for a terminal order
