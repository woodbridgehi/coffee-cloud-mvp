from __future__ import annotations

import uuid
import math
from datetime import timedelta
from typing import Any, Callable

from ..command_state import decide_transition, TERMINAL_STATES
from ..command_state import EXPIRED as COMMAND_EXPIRED
from ..command_state import UNKNOWN as COMMAND_UNKNOWN
from ..order_logic import TERMINAL_ORDER_STATUSES, device_progress
from ..production_state import EVENT_TARGETS, FINAL_JOBS, FINAL_ORDERS, decide_job_event, device_is_busy, order_transition_allowed
from ..protocol import canonical_digest, utc_now
from ..repositories import CommandRepository, DeviceMessageRepository, DispatchRepository, OrderRepository, PaymentRepository
from ..settings import Settings
from .command_state import transition_command
from .order_state import transition_order
from .refund_intents import REFUNDABLE_PAYMENT_STATUSES, ensure_automatic_refund_intent
from .errors import ServiceError


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
        # Compatibility entry; never apply the command independently of its job.
        result = self.reconcile_device_event(connection, terminal_id, body, event_type)
        return result.get("commandTransition") if result else None

    def expire_order_for_command(self, connection: Any, command: dict[str, Any]) -> str | None:
        """Fully expire one delivery-deadline-exceeded command and its order.

        The caller passes an unlocked, possibly stale candidate row. This entry
        re-reads everything under the domain lock order order -> job ->
        command -> outbox (a standalone debug command without a job uses
        command -> outbox) and performs the complete transition itself: the
        command verdict, the job/order outcome and, for a provably never-sent
        command, the unique automatic refund intent all commit in one
        transaction. Returns the recorded verdict, or ``None`` when the command
        was already advanced by an event or another expiry pass (skip; never
        transition from a stale snapshot).

        A command whose outbox was ever claimed (PUBLISHING/RETRY, any attempt,
        any published_at) or that has delivery evidence may already be at the
        broker, so it can only be held for manual reconciliation. Only a fresh
        unclaimed PENDING outbox (or a command without an outbox and without
        delivery evidence) is provably never sent; its outbox is terminalized in
        the same transaction so no later claim can publish it after the refund.
        """
        orders = OrderRepository(connection)
        payments = PaymentRepository(connection)
        commands = CommandRepository(connection)
        # Unlocked first pass only locates the owning job/order.
        located_job = orders.job_for_command(command["id"])
        order = None
        job = None
        if located_job is not None:
            order = orders.find_with_terminal(located_job["order_id"], for_update=True)
            if order is not None:
                job = orders.job_for_command(command["id"], for_update=True)
        current = commands.by_db_id(command["id"])
        if current is None or current["status"] != "CREATED":
            return None
        if current["expires_at"] is None or current["expires_at"] > utc_now():
            return None  # stale candidate: the deadline is not actually due
        outbox = commands.outbox_for_command(current["id"])
        outbox_claimed = outbox is not None and (
            outbox["status"] != "PENDING"
            or int(outbox["attempt_count"] or 0) > 0
            or outbox["published_at"] is not None
        )
        if outbox is not None and not outbox_claimed:
            # Same transaction: the refund and the unpublishable outbox commit atomically.
            commands.terminalize_outbox(outbox["id"], "EXPIRED")
        delivered_evidence = outbox_claimed or bool(
            current.get("published_at") or current.get("delivered_at")
        )
        verdict = COMMAND_UNKNOWN if delivered_evidence else COMMAND_EXPIRED
        if job is None or job["status"] not in {"DISPATCHED", "QUEUED"} or order is None:
            # Standalone debug command (no job/order): only the command expires.
            transition_command(
                connection, current, verdict, "timeout-monitor",
                reason="command delivery deadline exceeded",
            )
            return verdict
        if delivered_evidence:
            # The command reached the broker/device, so the physical outcome is
            # unknown: hold for manual reconciliation instead of auto-refunding.
            orders.update_job_hold(
                job["id"], hold_reason="COMMAND_EXPIRED_AFTER_DELIVERY",
                failure={"code": "COMMAND_EXPIRED", "messageId": current["message_id"]},
            )
            orders.update_failure(order["id"], "COMMAND_EXPIRED", "制作指令送达后超时，物理结果未知，需人工核对")
            transition_order(
                connection, order, "HOLD", "timeout-monitor",
                reason="command expired after delivery; outcome unknown",
            )
        else:
            orders.update_job_expired(
                job["id"], {"code": "COMMAND_EXPIRED", "messageId": current["message_id"]}
            )
            orders.update_failure(order["id"], "COMMAND_EXPIRED", "设备未在时限内接收制作指令")
            transition_order(connection, order, "EXPIRED", "timeout-monitor", reason="device command expired")
            # Confirmed never delivered to the device: refund the collected money in
            # the same transaction, using the remaining refund budget.
            if order["payment_status"] in REFUNDABLE_PAYMENT_STATUSES:
                payment_id = order.get("paid_payment_id")
                if not payment_id:
                    payment = payments.paid_for_order(order["id"])
                    payment_id = payment["id"] if payment else None
                if payment_id:
                    ensure_automatic_refund_intent(
                        connection, payment_id=payment_id,
                        idempotency_key=f"order:{order['id']}:command-expired-refund",
                        reason="command expired before delivery", actor="timeout-monitor",
                    )
        transition_command(
            connection, current, verdict, "timeout-monitor",
            reason="command delivery deadline exceeded",
        )
        return verdict

    def reconcile_order_ack(
        self, connection: Any, terminal_id: int, task_id: str, body: dict[str, Any]
    ) -> dict[str, Any] | None:
        if type(body.get("accepted")) is not bool:
            raise ServiceError(422, "accepted must be a boolean")
        message_id = body.get("messageId")
        if not isinstance(message_id, str) or not message_id or not task_id:
            raise ServiceError(422, "messageId and taskId are required")
        command = DeviceMessageRepository(connection).command(terminal_id, message_id)
        if not command or command["command_type"] != "MAKE_DRINK" or command["payload_json"].get("taskId") != task_id:
            raise ServiceError(404, "task command not found")
        return self.reconcile_device_event(
            connection, terminal_id, {"payload": {**body, "taskId": task_id}},
            "task.acknowledged" if body["accepted"] else "task.rejected",
        )

    def reconcile_order_event(
        self, connection: Any, terminal_id: int, body: dict[str, Any], event_type: str
    ) -> dict[str, Any] | None:
        return self.reconcile_device_event(connection, terminal_id, body, event_type)

    @staticmethod
    def _revision(payload: dict[str, Any]) -> int | None:
        revision = payload.get("taskRevision")
        if revision is not None and (type(revision) is not int or revision < 0):
            raise ServiceError(422, "taskRevision must be a non-negative integer")
        return revision

    @staticmethod
    def _validate_metrics(payload: dict[str, Any]) -> None:
        for key in ("taskId", "messageId", "orderId", "stepId", "stepName", "state"):
            if payload.get(key) is not None and not isinstance(payload[key], str):
                raise ServiceError(422, f"{key} must be a string")
        for key in ("overallProgress", "stepProgress", "progress", "plannedDurationSeconds", "elapsedSeconds", "remainingSeconds"):
            value = payload.get(key)
            if value is not None and (type(value) not in {int, float} or not math.isfinite(value) or value < 0):
                raise ServiceError(422, f"{key} must be a finite non-negative number")
        if payload.get("failure") is not None and not isinstance(payload["failure"], dict):
            raise ServiceError(422, "failure must be an object")

    def reconcile_device_event(
        self, connection: Any, terminal_id: int, body: dict[str, Any], event_type: str
    ) -> dict[str, Any] | None:
        """Validate the complete order/job/command plan before changing any row."""
        if event_type == "task.progress":
            return {"status": "EPHEMERAL_PROGRESS"}
        if event_type not in EVENT_TARGETS and event_type not in {"step.started", "step.completed"}:
            return None
        event_payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
        device_revision = self._revision(event_payload)
        self._validate_metrics(event_payload)
        task_id = self.event_task_id(body)
        if not task_id:
            raise ServiceError(422, "taskId is required for production events")
        if body.get("taskId") is not None and event_payload.get("taskId") is not None and body["taskId"] != event_payload["taskId"]:
            raise ServiceError(409, "conflicting taskId fields")
        orders = OrderRepository(connection)
        if event_type == "task.recovered" and event_payload.get("state") != "PAUSED":
            return {"status": "IGNORED_RECOVERY"}
        located = orders.job_for_task(terminal_id, task_id)
        commands = CommandRepository(connection)
        if not located:
            # Standalone/debug task: filter MAKE_DRINK, never select a control
            # command merely because it has the same taskId.
            command = commands.by_task(terminal_id, task_id, for_update=True)
            if command is None or event_type not in EVENT_TARGETS:
                return None
            if event_payload.get("messageId") not in {None, command["message_id"]}:
                raise ServiceError(409, "task command association mismatch")
            target = EVENT_TARGETS[event_type][2]
            if command["status"] == "UNKNOWN" and target not in TERMINAL_STATES:
                return {"status": "HOLD", "stale": True, "duplicate": True}
            updated, duplicate = transition_command(connection, command, target, "device-event", reason=event_type, payload=body, strict=False)
            return {"status": updated["status"], "duplicate": duplicate, "commandTransition": {
                "messageId": updated["message_id"], "status": updated["status"], "revision": updated["revision"], "duplicate": duplicate,
            }}
        order = orders.find_with_terminal(located["order_id"], for_update=True)
        row = orders.lock_job(located["id"])
        if not order or not row or not row.get("command_id"):
            return {"status": "NOT_DISPATCHED", "stale": True}
        command = commands.by_db_id(row["command_id"])
        if not command or command["command_type"] != "MAKE_DRINK" or command["terminal_id"] != terminal_id or command["payload_json"].get("taskId") != task_id:
            raise ServiceError(409, "production command association mismatch")
        if event_payload.get("messageId") not in {None, command["message_id"]} or (
            event_payload.get("orderId") is not None and str(event_payload["orderId"]) != str(order["id"])
        ):
            raise ServiceError(409, "task event association mismatch")

        def ignored(reason: str) -> dict[str, Any]:
            return {"orderId": str(order["id"]), "status": order["status"], "stale": True,
                    "duplicate": True, "reason": reason, "commandTransition": {
                        "messageId": command["message_id"], "status": command["status"],
                        "revision": command["revision"], "duplicate": True,
                    }}

        if order["status"] in FINAL_ORDERS or row["status"] in FINAL_JOBS or command["status"] in TERMINAL_STATES:
            return ignored("FINAL_STATE")
        if event_type in {"step.started", "step.completed"}:
            if row["status"] != "EXECUTING" or order["status"] != "MAKING" or (device_revision is not None and device_revision <= int(row["last_device_revision"] or 0)):
                return ignored("STALE_STEP")
            progress, step_progress = device_progress(
                event_payload, float(row["progress"] or 0), float(row.get("step_progress") or 0)
            )
            orders.update_job_progress(
                row["id"], progress=progress, step_progress=step_progress,
                step_id=event_payload.get("stepId"), step_name=event_payload.get("stepName") or body.get("message"),
                elapsed=event_payload.get("elapsedSeconds"), remaining=event_payload.get("remainingSeconds"),
                device_revision=device_revision,
            )
            return {"orderId": str(order["id"]), "status": "PROGRESS"}
        order_status, job_status, command_status = EVENT_TARGETS[event_type]
        decision = decide_job_event(row["status"], event_type, device_revision, int(row["last_device_revision"] or 0))
        if not decision.allowed or decision.duplicate:
            return ignored(decision.reason or "DUPLICATE")
        if not order_transition_allowed(order["status"], order_status) or not decide_transition(command["status"], command_status).allowed:
            return ignored("ILLEGAL_COORDINATED_TRANSITION")
        planned = event_payload.get("plannedDurationSeconds")
        steps = event_payload.get("stepPlan") or event_payload.get("stepDurations")
        failure = event_payload.get("failure") or (
            {"code": event_payload.get("reasonCode"), "details": event_payload.get("details")}
            if event_type == "task.rejected" else None
        )
        progress, step_progress = device_progress(event_payload, float(row["progress"] or 0), float(row.get("step_progress") or 0))
        if event_type == "task.succeeded":
            progress = step_progress = 1.0
        elapsed = planned if event_type == "task.succeeded" and planned is not None else event_payload.get("elapsedSeconds")
        remaining = 0.0 if event_type == "task.succeeded" else event_payload.get("remainingSeconds")
        accepted_at = utc_now() if job_status == "ACCEPTED" and not row.get("accepted_at") else row.get("accepted_at")
        started_at = utc_now() if job_status == "EXECUTING" and not row.get("started_at") else row.get("started_at")
        completed_at = utc_now() if job_status in FINAL_JOBS else row.get("completed_at")
        updated_command, duplicate = transition_command(connection, command, command_status, "device-event", reason=event_type, payload=body)
        orders.update_job_terminal(
            row["id"], status=job_status, progress=progress, step_progress=step_progress,
            planned=planned, steps=steps, failure=failure, elapsed=elapsed, remaining=remaining,
            device_revision=device_revision, accepted_at=accepted_at, started_at=started_at,
            completed_at=completed_at,
        )
        if job_status == "HOLD":
            orders.update_job_hold(row["id"], hold_reason="DEVICE_RESTARTED_OUTCOME_UNKNOWN")
        elif job_status in FINAL_JOBS:
            orders.clear_job_hold(row["id"])
        if failure:
            failure_code = failure.get("code") or failure.get("errorCode") or "PRODUCTION_FAILED"
            orders.update_failure(order["id"], failure_code, body.get("message") or "制作失败")
        elif job_status in {"EXECUTING", "SUCCEEDED"} and order.get("failure_code"):
            orders.update_failure(order["id"], None, None)
        order = transition_order(connection, order, order_status, "device-event", reason=event_type, payload=body)
        if event_type in {"task.failed", "task.rejected", "task.cancelled"}:
            self.create_automatic_refund_record(connection, order, row, event_type)
        if order_status in TERMINAL_ORDER_STATUSES:
            self.request_dispatch(connection, terminal_id, f"order-{order_status.lower()}")
        return {"orderId": str(order["id"]), "status": order["status"], "commandTransition": {
            "messageId": updated_command["message_id"], "status": updated_command["status"],
            "revision": updated_command["revision"], "duplicate": duplicate,
        }}

    def create_automatic_refund_record(
        self, connection: Any, order: dict[str, Any], job: dict[str, Any], reason: str
    ) -> dict[str, Any] | None:
        payments = PaymentRepository(connection)
        payment_id = order.get("paid_payment_id")
        if not payment_id:
            payment = payments.paid_for_order(order["id"])
            payment_id = payment["id"] if payment else None
        payment = payments.find(payment_id) if payment_id else None
        if payment is None or payment["status"] not in REFUNDABLE_PAYMENT_STATUSES:
            return None
        intent = ensure_automatic_refund_intent(
            connection, payment_id=payment_id,
            idempotency_key=f"production:{job['id']}:automatic-refund",
            reason=f"production failure: {reason}", actor="production-service",
        )
        return intent.refund if intent is not None else None

    def dispatch_next_order(self, connection: Any, terminal_id: int) -> dict[str, Any] | None:
        orders = OrderRepository(connection)
        terminal = orders.terminal_for_update(terminal_id)
        cutoff = utc_now() - timedelta(seconds=self.settings.offline_threshold_seconds)
        if not terminal or not terminal.get("last_heartbeat_at") or terminal["last_heartbeat_at"] < cutoff or terminal.get("lifecycle_status") != "ACTIVE":
            return None
        if orders.active_job_exists(terminal_id) or device_is_busy(terminal.get("reported_status")):
            return None
        job = orders.next_queued_job(terminal_id)
        if not job:
            return None
        order = orders.find_with_terminal(job["order_id"], for_update=True)
        current_job = orders.lock_job(job["id"])
        if not order or not current_job or order["status"] != "QUEUED" or current_job["status"] != "QUEUED":
            return None
        expires_at = utc_now() + timedelta(minutes=10)
        message_id = f"cmd-{uuid.uuid4()}"
        command = {
            "messageId": message_id, "type": "MAKE_DRINK", "taskId": job["task_id"],
            "orderId": str(job["order_id"]), "orderNo": order["order_no"], "recipeId": job["recipe_id"],
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

    def hold_overdue_job(self, connection: Any, order_id: uuid.UUID, job_id: uuid.UUID) -> None:
        orders = OrderRepository(connection)
        order = orders.find_with_terminal(order_id, for_update=True)
        job = orders.lock_job(job_id)
        if not order or order["status"] in FINAL_ORDERS or not job or job["status"] not in {"DISPATCHED", "ACCEPTED", "EXECUTING", "PAUSED", "RETRY_WAIT"}:
            return
        command = CommandRepository(connection).by_db_id(job["command_id"]) if job["command_id"] else None
        if not command or command["status"] in TERMINAL_STATES:
            return
        now = utc_now()
        due = False
        if job["status"] in {"PAUSED", "RETRY_WAIT"}:
            due = job["updated_at"] + timedelta(seconds=self.settings.production_wait_timeout_seconds) < now
        elif command["status"] in {"DELIVERING", "PUBLISHED"}:
            sent = command.get("published_at") or command.get("delivered_at")
            due = bool(sent and sent + timedelta(seconds=self.settings.command_ack_timeout_seconds) < now)
        elif command["status"] == "ACKED":
            acked = command.get("acked_at")
            due = bool(acked and acked + timedelta(seconds=self.settings.command_start_timeout_seconds) < now)
        elif command["status"] == "EXECUTING":
            remaining = job.get("remaining_seconds")
            seconds = float(remaining if remaining is not None else job.get("planned_duration_seconds") or 300)
            due = job["updated_at"] + timedelta(seconds=seconds + self.settings.production_timeout_grace_seconds) < now
        if due:
            transition_command(connection, command, "UNKNOWN", "watchdog", reason="device outcome requires reconciliation")
            orders.update_job_hold(job_id, hold_reason="DEVICE_OUTCOME_UNKNOWN")
            transition_order(connection, order, "HOLD", "watchdog", reason="device outcome unknown")

    def reconcile_stored_command_events(self, connection: Any) -> None:
        for item in OrderRepository(connection).stored_command_events():
            self.reconcile_command_event(connection, item["terminal_id"], item["payload_json"], item["event_type"])

    def reconcile_stored_order_events(self, connection: Any) -> None:
        for item in OrderRepository(connection).stored_order_events():
            self.reconcile_order_event(connection, item["terminal_id"], item["payload_json"], item["event_type"])
