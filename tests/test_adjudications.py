import os
import uuid

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from app.db import UnitOfWork
from app.protocol import OrderAdjudicationRequest
from app.repositories import AdminAccessRepository
from app.services.adjudications import OrderAdjudicationService
from app.services.admin_access import AdminAccessService, ROLE_PERMISSIONS
from app.services.errors import ServiceError
from app.settings import Settings
from test_payment_consistency import (
    postgres_database as postgres_database,
    seed_paid_queued_order,
)
from test_production_consistency import (
    production_case as production_case,
    event,
    snapshot,
)


def principal(role="MANAGER"):
    return {
        "actorType": "OPERATOR",
        "actorId": str(uuid.uuid4()),
        "displayName": "Test manager",
        "permissions": sorted(ROLE_PERMISSIONS[role]),
        "role": role,
    }


@pytest.fixture
def held_case(production_case):
    db, production, _, _, _, command = production_case
    event(production_case, "task.started", 1)
    event(production_case, "task.recovered", 2, state="PAUSED")
    payload = OrderAdjudicationRequest(
        taskId=command["taskId"],
        expectedRevision=snapshot(production_case)["revision"],
        outcome="SUCCEEDED",
        reason="现场确认已经出杯，已核对设备停止",
    )
    return (
        production_case,
        OrderAdjudicationService(UnitOfWork(db), production),
        payload,
    )


@pytest.mark.parametrize(
    "outcome,expected",
    [("SUCCEEDED", "READY"), ("FAILED", "FAILED"), ("CANCELLED", "CANCELLED")],
)
def test_adjudication_is_atomic_idempotent_and_refunds_only_failure(
    held_case, outcome, expected
):
    case, service, payload = held_case
    db, _, _, _, order_id, _ = case
    payload = payload.model_copy(update={"outcome": outcome})
    actor = principal()
    result = service.adjudicate(order_id, payload, "manual-1", actor)
    assert result["status"] == expected
    assert result["productionRevision"] == payload.expectedRevision + 1
    assert result["physicalStopConfirmedByServer"] is False
    assert service.adjudicate(order_id, payload, "manual-1", actor) == result
    row = snapshot(case)
    assert (
        row["order_status"] == expected
        and row["job_status"] == outcome
        and row["command_status"] == outcome
    )
    assert not row["manual_review_required"] and row["hold_reason"] is None
    assert row["refunds"] == (0 if outcome == "SUCCEEDED" else 1)
    with db.connect() as connection:
        assert (
            connection.execute(
                "select count(*) as n from order_adjudication"
            ).fetchone()["n"]
            == 1
        )
        assert (
            connection.execute(
                "select count(*) as n from audit_log where action='order.adjudicate'"
            ).fetchone()["n"]
            == 1
        )
    with pytest.raises(ServiceError) as conflict:
        service.adjudicate(
            order_id,
            payload.model_copy(update={"reason": "different"}),
            "manual-1",
            actor,
        )
    assert conflict.value.status_code == 409


def test_stale_revision_and_wrong_task_do_not_change_hold(held_case):
    case, service, payload = held_case
    before = snapshot(case)
    for update in (
        {"expectedRevision": payload.expectedRevision - 1},
        {"taskId": "another-task"},
    ):
        with pytest.raises(ServiceError) as conflict:
            service.adjudicate(
                case[4],
                payload.model_copy(update=update),
                str(uuid.uuid4()),
                principal(),
            )
        assert conflict.value.status_code == 409
        assert snapshot(case) == before


def test_audit_failure_rolls_back_job_order_refund_and_adjudication(
    held_case, monkeypatch
):
    case, service, payload = held_case
    before = snapshot(case)

    def fail_audit(*_):
        raise RuntimeError("audit storage unavailable")

    monkeypatch.setattr(AdminAccessRepository, "write_audit", fail_audit)
    with pytest.raises(RuntimeError, match="audit storage"):
        service.adjudicate(
            case[4],
            payload.model_copy(update={"outcome": "FAILED"}),
            "rollback",
            principal(),
        )
    assert snapshot(case) == before
    with case[0].connect() as connection:
        assert (
            connection.execute(
                "select count(*) as n from order_adjudication"
            ).fetchone()["n"]
            == 0
        )


@pytest.mark.parametrize(
    "reported",
    [
        {"deviceStatus": "BUSY"},
        {"deviceStatus": "RECOVERING"},
        {"currentTaskState": "PAUSED"},
        {"currentTaskState": "RETRY_WAIT"},
        {"currentTask": {"state": "RUNNING"}},
    ],
)
def test_manual_resolution_does_not_dispatch_while_device_remains_active(
    held_case, reported
):
    case, service, payload = held_case
    db, production, _, identity, order_id, _ = case
    with db.connect() as connection:
        connection.execute(
            "update terminal set reported_status=%s where id=%s",
            (Jsonb(reported), identity["id"]),
        )
        next_order, _ = seed_paid_queued_order(connection, identity["id"])
    result = service.adjudicate(order_id, payload, "device-pending", principal())
    assert result["deviceReleasePending"]
    with db.connect() as connection:
        assert production.dispatch_next_order(connection, identity["id"]) is None
        connection.execute(
            "update terminal set reported_status=%s where id=%s",
            (
                Jsonb({"deviceStatus": "IDLE", "currentTaskState": "CANCELLED"}),
                identity["id"],
            ),
        )
        assert production.dispatch_next_order(connection, identity["id"])[
            "orderId"
        ] == str(next_order)


@pytest.mark.parametrize(
    "role,expected", [(None, 401), ("VIEWER", 403), ("OPERATOR", 403), ("MANAGER", 200)]
)
def test_http_adjudication_requires_authentication_and_both_permissions(
    held_case, monkeypatch, role, expected
):
    # Test the real route and real token authentication, without application
    # startup workers or any production service connections.
    os.environ.setdefault(
        "DATABASE_URL", "postgresql://unused:unused@127.0.0.1:1/unused"
    )
    os.environ.setdefault("ADMIN_TOKEN", "test-admin-token-at-least-24-characters")
    from app import main

    case, service, payload = held_case
    access = AdminAccessService(
        UnitOfWork(case[0]),
        Settings.model_construct(admin_token="test-bootstrap-never-used-token"),
    )
    headers = {"Idempotency-Key": "http-adjudication"}
    if role:
        operator = access.create_operator("Test operator", role)
        credential = access.create_token(
            uuid.UUID(operator["operatorId"]), "test-token", None
        )
        headers["Authorization"] = f"Bearer {credential['token']}"
    monkeypatch.setattr(main, "admin_access_service", access)
    monkeypatch.setattr(main, "order_adjudication_service", service)
    client = TestClient(main.app)
    try:
        response = client.post(
            f"/api/v1/admin/orders/{case[4]}/adjudication",
            headers=headers,
            json=payload.model_dump(),
        )
        assert response.status_code == expected, response.text
    finally:
        client.close()


@pytest.mark.parametrize(
    "updates", [{"expectedRevision": True}, {"reason": "   "}, {"outcome": "RESUME"}]
)
def test_adjudication_rejects_unsafe_body(updates):
    from pydantic import ValidationError

    body = {
        "taskId": "task",
        "expectedRevision": 1,
        "outcome": "SUCCEEDED",
        "reason": "confirmed",
    }
    with pytest.raises(ValidationError):
        OrderAdjudicationRequest(**{**body, **updates})
