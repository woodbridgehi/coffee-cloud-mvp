from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any, Callable

from ..db import UnitOfWork
from ..order_logic import TERMINAL_ORDER_STATUSES
from ..payment_providers import RefundRequest
from ..payment_service import apply_paid_callback, transition_payment, transition_refund
from ..protocol import utc_now
from ..repositories import OrderRepository, PaymentRepository, WorkerRepository
from ..settings import Settings
from .command_state import transition_command
from .order_state import transition_order
from .production import ProductionService


log = logging.getLogger("coffee-cloud-mvp.background")


class BackgroundWorkerService:
    """Owns retryable jobs and recovery scans outside the HTTP composition root."""

    def __init__(
        self,
        uow: UnitOfWork,
        settings: Settings,
        *,
        payment_provider: Callable[[str], Any],
        production: ProductionService,
    ) -> None:
        self.uow = uow
        self.settings = settings
        self.payment_provider = payment_provider
        self.production = production

    def offline_scan_once(self) -> None:
        cutoff = utc_now() - timedelta(seconds=self.settings.offline_threshold_seconds)
        with self.uow.transaction() as connection:
            workers = WorkerRepository(connection)
            workers.expire_credentials()
            workers.mark_offline(cutoff)
            for command in workers.expired_commands():
                updated, _ = transition_command(
                    connection, command, "EXPIRED", "timeout-monitor",
                    reason="command delivery deadline exceeded",
                )
                self.production.expire_order_for_command(connection, updated)

    def process_business_outbox_batch(self, limit: int = 20) -> int:
        processed = 0
        worker_id = f"domain-{uuid.uuid4()}"
        with self.uow.transaction() as connection:
            events = WorkerRepository(connection).claim_business_events(worker_id, max(1, min(limit, 100)))
            workers = WorkerRepository(connection)
            for event in events:
                event_id = event["id"]
                try:
                    # A savepoint isolates one bad event without losing the rest of the claimed batch.
                    with connection.transaction():
                        if event["event_type"] == "payment.paid":
                            self._process_paid_event(connection, event)
                        workers.mark_business_processed(event_id)
                        processed += 1
                except Exception as exc:
                    log.exception("business outbox event failed id=%s", event_id)
                    with connection.transaction():
                        workers.mark_business_retry(event_id, str(exc))
        return processed

    def _process_paid_event(self, connection: Any, event: dict[str, Any]) -> None:
        order_id = uuid.UUID(str(event["payload_json"]["orderId"]))
        orders = OrderRepository(connection)
        order = orders.find_with_terminal(order_id, for_update=True)
        if not order or order["payment_status"] != "PAID":
            return
        if not orders.job(order_id):
            snapshot = order["product_snapshot"] or {}
            orders.insert_production_job(
                job_id=uuid.uuid4(), task_id=f"task-{uuid.uuid4()}", order_id=order_id,
                terminal_id=order["terminal_id"],
                planned_duration_seconds=snapshot.get("estimatedDurationSeconds"),
            )
        if order["status"] == "PAID":
            order = transition_order(connection, order, "QUEUED", "outbox-worker", reason="paid order queued")
        self.production.dispatch_next_order(connection, order["terminal_id"])

    def reconcile_payment_once(self) -> int:
        with self.uow.transaction() as connection:
            payment = WorkerRepository(connection).claim_payment(self.settings.payment_reconcile_seconds)
        if payment is None:
            return 0
        try:
            result = self.payment_provider(payment["provider"]).query_payment(payment["merchant_payment_no"])
        except Exception as exc:
            log.info("payment reconciliation deferred payment=%s: %s", payment["id"], exc)
            return 0
        with self.uow.transaction() as connection:
            payments = PaymentRepository(connection)
            current = payments.find(payment["id"], for_update=True)
            if current is None or current["status"] not in {"CREATED", "PENDING"}:
                return 1
            if result.status == "PAID":
                apply_paid_callback(
                    connection, provider=current["provider"],
                    event_id=f"reconcile-paid:{current['merchant_payment_no']}",
                    values={
                        "merchant_payment_no": current["merchant_payment_no"],
                        "amount_minor": str(current["amount_minor"]),
                        "provider_trade_no": result.provider_trade_no or "",
                    },
                )
            elif result.status in {"CLOSED", "FAILED"}:
                target = "CLOSED" if result.status == "CLOSED" else "FAILED"
                transition_payment(connection, current, target, actor="payment-reconciliation", payload=result.raw)
                OrderRepository(connection).update_payment_outcome(current["order_id"], target)
        return 1

    def process_refund_batch(self) -> int:
        with self.uow.transaction() as connection:
            workers = WorkerRepository(connection)
            refund = workers.claim_refund()
            if refund is None:
                return 0
            payment = PaymentRepository(connection).find(refund["payment_id"])
            if payment is None:
                return 0
            if refund["status"] != "PROCESSING":
                refund, _ = transition_refund(connection, refund, "PROCESSING")
                workers.mark_refund_attempt(refund["id"], set_processing_delay=True)
            else:
                workers.mark_refund_attempt(refund["id"])
        try:
            provider = self.payment_provider(payment["provider"])
            request = RefundRequest(
                merchant_payment_no=payment["merchant_payment_no"],
                merchant_refund_no=refund["merchant_refund_no"], amount_minor=refund["amount_minor"],
                reason=refund["reason"], provider_trade_no=payment["provider_trade_no"],
            )
            result = provider.query_refund(request) if int(refund["attempt_count"] or 0) > 0 else provider.refund(request)
            if result.status == "NOT_FOUND":
                result = provider.refund(request)
            target = "SUCCEEDED" if result.status == "REFUNDED" else "PROCESSING"
            provider_payload = result.raw
        except Exception as exc:
            log.warning("refund reconciliation outcome unknown refund=%s: %s", refund["id"], exc)
            target = "UNKNOWN"
            provider_payload = {"error": f"{type(exc).__name__}: {exc}"}
        with self.uow.transaction() as connection:
            payments = PaymentRepository(connection)
            current = payments.find_refund(refund["id"], for_update=True)
            if current is None:
                return 1
            current, _ = transition_refund(connection, current, target, payload=provider_payload)
            if target == "SUCCEEDED":
                current_payment = payments.find(current["payment_id"], for_update=True)
                if current_payment is not None:
                    refunded = payments.refunded_total(current_payment["id"])
                    payment_target = "REFUNDED" if refunded >= current_payment["amount_minor"] else "PARTIALLY_REFUNDED"
                    transition_payment(
                        connection, current_payment, payment_target,
                        actor="refund-reconciliation", payload=provider_payload,
                    )
                    order = OrderRepository(connection).find_with_terminal(current_payment["order_id"], for_update=True)
                    if order is not None:
                        OrderRepository(connection).update_payment_status(order["id"], payment_target)
                        if payment_target == "REFUNDED" and order["status"] == "FAILED":
                            transition_order(connection, order, "REFUNDED", "refund-reconciliation", reason="full refund completed")
            else:
                payments.schedule_refund(current["id"], increment_attempt=target == "UNKNOWN")
        return 1

    def watchdog_scan_once(self) -> None:
        with self.uow.transaction() as connection:
            workers = WorkerRepository(connection)
            for row in workers.watchdog_rows(
                self.settings.command_ack_timeout_seconds,
                self.settings.command_start_timeout_seconds,
                self.settings.production_timeout_grace_seconds,
            ):
                transition_command(
                    connection, row, "UNKNOWN", "watchdog",
                    reason="device outcome requires reconciliation", strict=False,
                )
                workers.mark_job_hold(row["job_id"])
                order = OrderRepository(connection).find_with_terminal(row["order_id"], for_update=True)
                if order and order["status"] not in TERMINAL_ORDER_STATUSES:
                    transition_order(connection, order, "HOLD", "watchdog", reason="device outcome unknown")

    def reconcile_stored_command_events(self) -> None:
        with self.uow.transaction() as connection:
            self.production.reconcile_stored_command_events(connection)

    def reconcile_stored_order_events(self) -> None:
        with self.uow.transaction() as connection:
            self.production.reconcile_stored_order_events(connection)
