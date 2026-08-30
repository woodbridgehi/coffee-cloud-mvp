"""Real PostgreSQL acceptance of the coordinated production state machine."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
import uuid

import pytest
from psycopg.types.json import Jsonb

from app.db import UnitOfWork
from app.protocol import CommandResult, DeviceEvent
from app.repositories import DeviceMessageRepository
from app.services.command_state import transition_command
from app.services.device_messages import DeviceMessageService
from app.services.errors import ServiceError
from app.services.production import ProductionService
from app.settings import Settings
from test_payment_consistency import (
    insert_terminal,
    postgres_database as postgres_database,
    seed_paid_queued_order,
)


@pytest.fixture
def production_case(postgres_database):
    db = postgres_database
    production = ProductionService(
        Settings.model_construct(), payment_provider=lambda _: None
    )
    service = DeviceMessageService(
        UnitOfWork(db),
        request_dispatch=production.request_dispatch,
        transition_command=transition_command,
        expire_order_for_command=production.expire_order_for_command,
        reconcile_command_event=production.reconcile_command_event,
        reconcile_order_event=production.reconcile_order_event,
        reconcile_order_ack=production.reconcile_order_ack,
        order_url=lambda _: "",
    )
    with db.connect() as connection:
        terminal_id = insert_terminal(connection)
        connection.execute(
            "update terminal set lifecycle_status='ACTIVE',last_heartbeat_at=now() where id=%s",
            (terminal_id,),
        )
        order_id, payment = seed_paid_queued_order(connection, terminal_id)
        command = production.dispatch_next_order(connection, terminal_id)
    return (
        db,
        production,
        service,
        {"id": terminal_id, "device_id": "pay-device"},
        order_id,
        command,
    )


def snapshot(case):
    db, _, _, _, order_id, _ = case
    with db.connect() as connection:
        return connection.execute(
            """select o.status as order_status,o.payment_status,j.status as job_status,
                 j.revision,j.last_device_revision,j.manual_review_required,j.hold_reason,
                 c.status as command_status,
                 (select count(*) from refund r join payment p on p.id=r.payment_id where p.order_id=o.id) as refunds
                 from sales_order o join production_job j on j.order_id=o.id
                 join terminal_command c on c.id=j.command_id where o.id=%s""",
            (order_id,),
        ).fetchone()


def event(case, kind, revision=1, **extra):
    _, _, service, identity, _, command = case
    return service.event(
        identity["device_id"],
        DeviceEvent(
            eventId=str(uuid.uuid4()),
            deviceId=identity["device_id"],
            type=kind,
            payload={"taskId": command["taskId"], "taskRevision": revision, **extra},
        ),
        identity,
    )


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("task.acknowledged", ("ACCEPTED", "ACCEPTED", "ACKED")),
        ("task.started", ("MAKING", "EXECUTING", "EXECUTING")),
        ("task.succeeded", ("READY", "SUCCEEDED", "SUCCEEDED")),
    ],
)
def test_authenticated_event_can_arrive_before_publish_receipt(
    production_case, kind, expected
):
    event(production_case, kind)
    row = snapshot(production_case)
    assert (row["order_status"], row["job_status"], row["command_status"]) == expected
    assert row["refunds"] == 0


@pytest.mark.parametrize(
    "final,late", [("task.succeeded", "task.started"), ("task.failed", "task.retry")]
)
def test_larger_revision_never_revives_a_final_task(production_case, final, late):
    event(production_case, final)
    before = snapshot(production_case)
    assert event(production_case, late, 999)["orderTransition"]["stale"]
    assert snapshot(production_case) == before


def test_equal_revision_conflicting_state_is_not_partially_applied(production_case):
    event(production_case, "task.acknowledged", 10)
    before = snapshot(production_case)
    result = event(production_case, "task.started", 10)
    assert result["orderTransition"]["reason"] == "REVISION_CONFLICT"
    assert snapshot(production_case) == before


@pytest.mark.parametrize(
    "prior", [None, "task.acknowledged", "task.started", "task.succeeded"]
)
def test_reject_ack_refunds_only_before_execution(production_case, prior):
    _, _, service, identity, _, command = production_case
    if prior:
        event(production_case, prior)
    before = snapshot(production_case)
    body = {"messageId": command["messageId"], "accepted": False}
    service.task_ack(identity, command["taskId"], body)
    row = snapshot(production_case)
    if prior in {None, "task.acknowledged"}:
        assert (
            row["order_status"],
            row["job_status"],
            row["command_status"],
            row["refunds"],
        ) == ("FAILED", "REJECTED", "REJECTED", 1)
    else:
        assert row == before
    service.task_ack(identity, command["taskId"], body)
    assert snapshot(production_case) == row


def test_control_command_cannot_steal_task_association(production_case):
    db, _, service, identity, _, command = production_case
    control_id = f"cancel-{uuid.uuid4()}"
    with db.connect() as connection:
        connection.execute(
            """insert into terminal_command(terminal_id,message_id,command_type,payload_json,status)
                 values(%s,%s,'CANCEL_TASK',%s,'CREATED')""",
            (identity["id"], control_id, Jsonb({"taskId": command["taskId"]})),
        )
    event(production_case, "task.started")
    with pytest.raises(ServiceError) as rejected:
        service.task_ack(
            identity, command["taskId"], {"messageId": control_id, "accepted": False}
        )
    assert rejected.value.status_code == 404
    assert snapshot(production_case)["command_status"] == "EXECUTING"
    with db.connect() as connection:
        assert (
            connection.execute(
                "select status from terminal_command where message_id=%s", (control_id,)
            ).fetchone()["status"]
            == "CREATED"
        )


@pytest.mark.parametrize(
    "waiting,resume",
    [("task.paused", "task.resumed"), ("task.retry_wait", "task.retry")],
)
def test_waiting_blocks_dispatch_and_does_not_refund(production_case, waiting, resume):
    db, production, _, identity, _, _ = production_case
    event(production_case, "task.started", 1)
    event(production_case, waiting, 2)
    row = snapshot(production_case)
    assert row["job_status"] in {"PAUSED", "RETRY_WAIT"}
    assert row["refunds"] == 0
    with db.connect() as connection:
        seed_paid_queued_order(connection, identity["id"])
        assert production.dispatch_next_order(connection, identity["id"]) is None
    event(production_case, "task.started", 3)
    assert snapshot(production_case) == row
    event(production_case, resume, 4)
    assert snapshot(production_case)["job_status"] == "EXECUTING"
    event(production_case, "task.succeeded", 5)
    assert snapshot(production_case)["refunds"] == 0


@pytest.mark.parametrize("waiting", ["task.paused", "task.retry_wait"])
def test_waiting_timeout_holds_instead_of_refunding(production_case, waiting):
    db, production, _, _, order_id, _ = production_case
    event(production_case, "task.started", 1)
    event(production_case, waiting, 2)
    with db.connect() as connection:
        job = connection.execute(
            "update production_job set updated_at=now()-interval '1 hour' where order_id=%s returning id",
            (order_id,),
        ).fetchone()
        production.hold_overdue_job(connection, order_id, job["id"])
    row = snapshot(production_case)
    assert (
        row["order_status"],
        row["job_status"],
        row["command_status"],
        row["refunds"],
    ) == ("HOLD", "HOLD", "UNKNOWN", 0)
    assert row["manual_review_required"]


def test_recovered_task_requires_final_evidence_and_clears_hold(production_case):
    event(production_case, "task.started", 1)
    event(production_case, "task.recovered", 2, state="PAUSED")
    before = snapshot(production_case)
    assert before["manual_review_required"]
    for revision, kind in enumerate(
        ["task.resumed", "task.started", "task.retry", "task.acknowledged"], 3
    ):
        event(production_case, kind, revision)
        assert snapshot(production_case) == before
    event(production_case, "task.cancelled", 10)
    final = snapshot(production_case)
    assert final["job_status"] == "CANCELLED" and final["refunds"] == 1
    assert not final["manual_review_required"] and final["hold_reason"] is None
    event(production_case, "task.cancelled", 11)
    assert snapshot(production_case) == final


@pytest.mark.parametrize("accepted", [None, "false", 0, 1, {}, []])
def test_ack_boolean_is_strict(production_case, accepted):
    _, _, service, identity, _, command = production_case
    with pytest.raises(ServiceError) as error:
        service.task_ack(
            identity,
            command["taskId"],
            {"messageId": command["messageId"], "accepted": accepted},
        )
    assert error.value.status_code == 422


@pytest.mark.parametrize(
    "extra",
    [
        {"taskRevision": True},
        {"taskRevision": -1},
        {"messageId": []},
        {"elapsedSeconds": "fast"},
        {"failure": "oops"},
    ],
)
def test_bad_event_body_rolls_back_inbox_and_states(production_case, extra):
    db, _, _, _, _, _ = production_case
    before = snapshot(production_case)
    with pytest.raises(ServiceError) as error:
        event(production_case, "task.started", **extra)
    assert error.value.status_code == 422
    assert snapshot(production_case) == before
    with db.connect() as connection:
        assert (
            connection.execute("select count(*) as n from terminal_event").fetchone()[
                "n"
            ]
            == 0
        )


def test_generic_command_result_cannot_bypass_production_coordinator(production_case):
    _, _, service, identity, _, command = production_case
    with pytest.raises(ServiceError) as error:
        service.command_result(
            identity, command["messageId"], CommandResult(status="SUCCEEDED")
        )
    assert error.value.status_code == 409
    assert snapshot(production_case)["command_status"] == "CREATED"


@pytest.mark.parametrize("conflict", [False, True])
def test_concurrent_duplicate_event_is_idempotent_or_conflict_not_500(
    production_case, monkeypatch, conflict
):
    db, _, service, identity, _, command = production_case
    original = DeviceMessageRepository.insert_event
    barrier = Barrier(2)

    def synchronized_insert(self, **kwargs):
        barrier.wait(timeout=5)
        return original(self, **kwargs)

    monkeypatch.setattr(DeviceMessageRepository, "insert_event", synchronized_insert)
    event_id = str(uuid.uuid4())

    def send(index):
        try:
            return service.event(
                identity["device_id"],
                DeviceEvent(
                    eventId=event_id,
                    deviceId=identity["device_id"],
                    type="task.succeeded",
                    payload={
                        "taskId": command["taskId"],
                        "taskRevision": index + 1 if conflict else 1,
                    },
                ),
                identity,
            )
        except ServiceError as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, [0, 1]))
    if conflict:
        assert results.count(409) == 1
    else:
        assert sum(bool(item["duplicate"]) for item in results) == 1
    assert snapshot(production_case)["order_status"] == "READY"
    with db.connect() as connection:
        assert (
            connection.execute("select count(*) as n from terminal_event").fetchone()[
                "n"
            ]
            == 1
        )


def test_http_expiry_does_not_lock_command_before_waiting_for_order(production_case):
    db, production, service, identity, order_id, command = production_case
    with db.connect() as connection:
        connection.execute(
            "update terminal_command set expires_at=now()-interval '1 minute' where message_id=%s",
            (command["messageId"],),
        )
    entered_expiry = Event()
    original = service.expire_order_for_command

    def observed_expiry(connection, candidate):
        entered_expiry.set()
        return original(connection, candidate)

    service.expire_order_for_command = observed_expiry
    with ThreadPoolExecutor(max_workers=1) as pool:
        with db.connect() as connection:
            connection.execute("set local lock_timeout='1s'")
            connection.execute(
                "select id from sales_order where id=%s for update", (order_id,)
            )
            pulling = pool.submit(service.commands, identity, "", 10)
            assert entered_expiry.wait(5)
            # An HTTP poll must be waiting on our order, not holding its command.
            # The real event coordinator can therefore finish under the same
            # order lock without forming order<->command deadlock.
            production.reconcile_device_event(
                connection,
                identity["id"],
                {
                    "payload": {"taskId": command["taskId"], "taskRevision": 1},
                },
                "task.succeeded",
            )
        assert pulling.result(timeout=5)["commands"] == []
    assert snapshot(production_case)["order_status"] == "READY"


def test_retry_clears_current_failure_but_keeps_original_event(production_case):
    db, _, _, _, order_id, _ = production_case
    event(production_case, "task.started", 1)
    event(
        production_case,
        "task.retry_wait",
        2,
        failure={"code": "PUMP_TIMEOUT", "retryable": True},
    )
    event(production_case, "task.retry", 3)
    event(production_case, "task.succeeded", 4)
    with db.connect() as connection:
        result = connection.execute(
            "select o.failure_code,j.failure_json from sales_order o join production_job j on j.order_id=o.id where o.id=%s",
            (order_id,),
        ).fetchone()
        assert result == {"failure_code": None, "failure_json": None}
        assert (
            connection.execute(
                "select count(*) as n from terminal_event where event_type='task.retry_wait'"
            ).fetchone()["n"]
            == 1
        )
