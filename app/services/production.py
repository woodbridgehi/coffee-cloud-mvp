from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, Callable

from ..command_state import event_state
from ..order_logic import TERMINAL_ORDER_STATUSES, device_progress, order_state_for_event
from ..payment_service import transition_payment, transition_refund
from ..protocol import canonical_digest, utc_now
from ..repositories import CommandRepository, DispatchRepository, OrderRepository, PaymentRepository
from ..settings import Settings
from .command_state import transition_command
from .order_state import transition_order


class ProductionService:
    """Production/order orchestration shared by HTTP ingestion and background recovery."""

    def __init__(
        self,
        settings: Settings,
        *,
        payment_provider: Callable[[str], Any],
    ) -> None:
        self.settings = settings
        self.payment_provider = payment_provider

    @staticmethod
    def event_task_id(body: dict[str, Any]) -> str | None:
        direct = body.get("taskId")
        nested = body.get("payload")
        value = direct or (nested.get("taskId") if isinstance(nested, dict) else None)
        return value if isinstance(value, str) and value else None

    def reconcile_command_event(
        self, connection: Any, terminal_id: int, body: dict[str, Any], event_type: str
    ) -> dict[str, Any] | None:
        target = event_state(event_type)
        task_id = self.event_task_id(body)
        if not target or not task_id:
            return None
        command = CommandRepository(connection).by_task(terminal_id, task_id, for_update=True)
        if command is None:
            return None
        updated, duplicate = transition_command(
            connection, command, target, "device-event", reason=event_type, payload=body, strict=False
        )
        return {
            "messageId": updated["message_id"], "status": updated["status"],
            "revision": updated["revision"], "duplicate": duplicate,
        }

    def expire_order_for_command(self, connection: Any, command: dict[str, Any]) -> None:
        orders = OrderRepository(connection)
        job = orders.job_for_command(command["id"], for_update=True)
        if not job or job["status"] not in {"DISPATCHED", "QUEUED"}:
            return
        orders.update_job_expired(job["id"], {"code": "COMMAND_EXPIRED", "messageId": command["message_id"]})
        order = orders.find_with_terminal(job["order_id"], for_update=True)
        if order is None:
            return
        orders.update_failure(order["id"], "COMMAND_EXPIRED", "设备未在时限内接收制作指令")
        transition_order(connection, order, "EXPIRED", "timeout-monitor", reason="device command expired")

    def reconcile_order_ack(
        self, connection: Any, terminal_id: int, task_id: str, body: dict[str, Any]
    ) -> dict[str, Any] | None:
        orders = OrderRepository(connection)
        row = orders.job_for_task(terminal_id, task_id, for_update=True)
        if not row:
            return None
        order = orders.find_with_terminal(row["sales_order_id"], for_update=True)
        if order is None:
            return None
        accepted = bool(body.get("accepted"))
        orders.update_job_acknowledged(row["id"], accepted=accepted, payload=body)
        if accepted:
            order = transition_order(
                connection, order, "ACCEPTED", "device-ack",
                reason="device reserved recipe and materials", payload=body,
            )
        else:
            reason = body.get("reasonCode") or body.get("reason") or "DEVICE_REJECTED"
            orders.update_failure(order["id"], reason, "设备未接受制作任务")
            order = transition_order(connection, order, "FAILED", "device-ack", reason=reason, payload=body)
            self.request_dispatch(connection, terminal_id, "task-rejected")
        return {"orderId": str(order["id"]), "status": order["status"]}

    def reconcile_order_event(
        self, connection: Any, terminal_id: int, body: dict[str, Any], event_type: str
    ) -> dict[str, Any] | None:
        task_id = self.event_task_id(body)
        if not task_id:
            return None
        orders = OrderRepository(connection)
        row = orders.job_for_task(terminal_id, task_id, for_update=True)
        if not row:
            return None
        event_payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
        device_revision = event_payload.get("taskRevision")
        if isinstance(device_revision, int) and device_revision < int(row.get("last_device_revision") or 0):
            return {"orderId": str(row["sales_order_id"]), "status": "STALE", "duplicate": True}
        if event_type in {"task.progress", "step.started", "step.completed"}:
            if row["status"] in {"SUCCEEDED", "FAILED", "REJECTED", "CANCELLED", "EXPIRED", "HOLD"}:
                return {"orderId": str(row["sales_order_id"]), "status": "STALE_TERMINAL", "duplicate": True}
            progress, step_progress = device_progress(
                event_payload, float(row["progress"] or 0), float(row.get("step_progress") or 0)
            )
            orders.update_job_progress(
                row["id"], progress=progress, step_progress=step_progress,
                step_id=event_payload.get("stepId"), step_name=event_payload.get("stepName") or body.get("message"),
                elapsed=event_payload.get("elapsedSeconds"), remaining=event_payload.get("remainingSeconds"),
                device_revision=device_revision,
            )
            return {"orderId": str(row["sales_order_id"]), "status": "PROGRESS"}
        mapped = order_state_for_event(event_type)
        if not mapped:
            return None
        order_status, job_status = mapped
        order = orders.find_with_terminal(row["sales_order_id"], for_update=True)
        if order is None:
            return None
        planned = event_payload.get("plannedDurationSeconds")
        steps = event_payload.get("stepPlan") or event_payload.get("stepDurations")
        failure = event_payload.get("failure") or (
            {"code": event_payload.get("reasonCode"), "details": event_payload.get("details")}
            if event_type == "task.rejected" else None
        )
        progress = 1.0 if event_type == "task.succeeded" else float(event_payload.get("overallProgress", row["progress"] or 0))
        step_progress = 1.0 if event_type == "task.succeeded" else float(event_payload.get("stepProgress", row.get("step_progress") or 0))
        elapsed = planned if event_type == "task.succeeded" and planned is not None else event_payload.get("elapsedSeconds")
        remaining = 0.0 if event_type == "task.succeeded" else event_payload.get("remainingSeconds")
        accepted_at = utc_now() if job_status == "ACCEPTED" and not row.get("accepted_at") else row.get("accepted_at")
        started_at = utc_now() if job_status == "EXECUTING" and not row.get("started_at") else row.get("started_at")
        completed_at = utc_now() if job_status in {"SUCCEEDED", "FAILED", "CANCELLED", "REJECTED"} else row.get("completed_at")
        orders.update_job_terminal(
            row["id"], status=job_status, progress=progress, step_progress=step_progress,
            planned=planned, steps=steps, failure=failure, elapsed=elapsed, remaining=remaining,
            device_revision=device_revision, accepted_at=accepted_at, started_at=started_at,
            completed_at=completed_at,
        )
        if failure:
            failure_code = failure.get("code") or failure.get("errorCode") or "PRODUCTION_FAILED"
            orders.update_failure(order["id"], failure_code, body.get("message") or "制作失败")
        order = transition_order(connection, order, order_status, "device-event", reason=event_type, payload=body)
        if order_status == "FAILED" and event_type in {"task.failed", "task.rejected"}:
            self.create_automatic_refund_record(connection, order, row, event_type)
        if order_status in TERMINAL_ORDER_STATUSES:
            self.request_dispatch(connection, terminal_id, f"order-{order_status.lower()}")
        return {"orderId": str(order["id"]), "status": order["status"]}

    def create_automatic_refund_record(
        self, connection: Any, order: dict[str, Any], job: dict[str, Any], reason: str
    ) -> dict[str, Any] | None:
        payments = PaymentRepository(connection)
        payment = payments.paid_for_order(order["id"])
        if not payment:
            return None
        key = f"production:{job['id']}:automatic-refund"
        existing = payments.find_refund_idempotent(payment["id"], key)
        if existing:
            return existing
        request_body = {"amountMinor": payment["amount_minor"], "reason": reason}
        refund = payments.insert_refund(
            refund_id=uuid.uuid4(), payment=payment,
            merchant_refund_no=f"R{uuid.uuid4().hex[:24].upper()}",
            idempotency_key=key, request_digest=canonical_digest(request_body),
            amount_minor=payment["amount_minor"], reason=f"production failure: {reason}",
        )
        transition_payment(connection, payment, "REFUNDING", actor="production-service", payload={"refundId": str(refund["id"])})
        OrderRepository(connection).update_payment_status(order["id"], "REFUNDING")
        return refund

    def dispatch_next_order(self, connection: Any, terminal_id: int) -> dict[str, Any] | None:
        orders = OrderRepository(connection)
        terminal = orders.terminal_for_update(terminal_id)
        cutoff = utc_now() - timedelta(seconds=self.settings.offline_threshold_seconds)
        if not terminal or not terminal.get("last_heartbeat_at") or terminal["last_heartbeat_at"] < cutoff or terminal.get("lifecycle_status") != "ACTIVE":
            return None
        if orders.active_job_exists(terminal_id):
            return None
        job = orders.next_queued_job(terminal_id)
        if not job:
            return None
        expires_at = utc_now() + timedelta(minutes=10)
        message_id = f"cmd-{uuid.uuid4()}"
        command = {
            "messageId": message_id, "type": "MAKE_DRINK", "taskId": job["task_id"],
            "orderId": str(job["order_id"]), "recipeId": job["recipe_id"],
            "recipeVersion": job["recipe_version"], "expiresAt": expires_at.isoformat().replace("+00:00", "Z"),
        }
        commands = CommandRepository(connection)
        command_row = commands.insert(
            terminal_id=terminal_id, message_id=message_id, command_type="MAKE_DRINK",
            payload=command, digest=canonical_digest(command), expires_at=expires_at,
            idempotency_key=f"order:{job['order_id']}:make",
        )
        commands.insert_initial_transition(command_row["id"], "order-service", "dispatch queued order", command)
        terminal_device_id = terminal["device_id"]
        envelope = {
            "schema": "coffee.mqtt-envelope.v1", "messageId": message_id,
            "deviceId": terminal_device_id, "type": "command", "sentAt": utc_now().isoformat().replace("+00:00", "Z"),
            "payload": command,
        }
        commands.insert_outbox(command_row["id"], terminal_id, f"v1/devices/{terminal_device_id}/down", envelope)
        orders.link_command(job["id"], command_row["id"])
        order = orders.find_with_terminal(job["order_id"], for_update=True)
        if order:
            transition_order(connection, order, "DISPATCHED", "order-service", reason="device command created", payload={"messageId": message_id})
        return command

    def request_dispatch(self, connection: Any, terminal_id: int, reason: str) -> None:
        DispatchRepository(connection).enqueue(terminal_id, reason)

    def reconcile_stored_command_events(self, connection: Any) -> None:
        for item in OrderRepository(connection).stored_command_events():
            self.reconcile_command_event(connection, item["terminal_id"], item["payload_json"], item["event_type"])

    def reconcile_stored_order_events(self, connection: Any) -> None:
        for item in OrderRepository(connection).stored_order_events():
            self.reconcile_order_event(connection, item["terminal_id"], item["payload_json"], item["event_type"])
