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
from ..repositories import DispatchRepository, OrderRepository, PaymentRepository, TelemetryRepository, WorkerRepository
from ..settings import Settings
from ..telemetry import TelemetryCache
from .order_state import transition_order
from .production import ProductionService
from .refund_intents import apply_refund_outcome


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
        telemetry_cache: TelemetryCache | None = None,
    ) -> None:
        self.uow = uow
        self.settings = settings
        self.payment_provider = payment_provider
        self.production = production
        self.telemetry_cache = telemetry_cache

    def flush_telemetry_batch(self) -> int:
        if not self.telemetry_cache:
            return 0
        snapshots = self.telemetry_cache.claim_dirty(self.settings.telemetry_flush_batch_size)
        if not snapshots:
            return 0
        try:
            with self.uow.transaction() as connection:
                TelemetryRepository(connection).apply_snapshots(snapshots)
            return len(snapshots)
        except Exception:
            self.telemetry_cache.restore_dirty([device_id for device_id, _ in snapshots])
            raise

    def offline_scan_once(self) -> None:
        cutoff = utc_now() - timedelta(seconds=self.settings.offline_threshold_seconds)
        with self.uow.transaction() as connection:
            workers = WorkerRepository(connection)
            workers.expire_credentials()
            workers.mark_offline(cutoff)
        with self.uow.transaction() as connection:
            candidates = WorkerRepository(connection).expired_commands()
        for command in candidates:
            # One transaction per command: expire_order_for_command owns the
            # full command/order/refund transition under the domain lock order
            # (order -> job -> command -> outbox) and skips candidates that an
            # event already advanced, so no terminal locks are held long and a
            # publish confirmation can never deadlock with this scan.
            with self.uow.transaction() as connection:
                self.production.expire_order_for_command(connection, command)

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
        if order["status"] in TERMINAL_ORDER_STATUSES:
            # A terminal order (READY refunded afterwards, CANCELLED, EXPIRED,
            # FAILED...) must never grow a production job from a replayed or
            # legacy payment.paid outbox event.
            return
        primary_id = order.get("paid_payment_id")
        if primary_id is not None and str(primary_id) != str(event["payload_json"].get("paymentId")):
            # Only the primary payment may create work; extra payments are refunded.
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
        self.production.request_dispatch(connection, order["terminal_id"], "payment-paid")

    def process_dispatch_batch(self, limit: int = 50) -> int:
        """Dispatch only in response to durable domain events, never heartbeats."""
        processed = 0
        worker_id = f"dispatch-{uuid.uuid4()}"
        for _ in range(max(1, min(limit, 200))):
            with self.uow.transaction() as connection:
                request = DispatchRepository(connection).claim(worker_id)
                if request is None:
                    break
            try:
                with self.uow.transaction() as connection:
                    self.production.dispatch_next_order(connection, request["terminal_id"])
                    DispatchRepository(connection).complete(request["terminal_id"], request["revision"])
                processed += 1
            except Exception as exc:
                log.exception("terminal dispatch failed terminal=%s", request["terminal_id"])
                with self.uow.transaction() as connection:
                    DispatchRepository(connection).retry(request["terminal_id"], request["revision"], str(exc))
        return processed

    def reconcile_payment_once(self) -> int:
        with self.uow.transaction() as connection:
            payment = WorkerRepository(connection).claim_payment(self.settings.payment_reconcile_seconds)
        if payment is None:
            return 0
        try:
            provider = self.payment_provider(payment["provider"])
            result = provider.query_payment(payment["merchant_payment_no"])
        except Exception as exc:
            log.info("payment reconciliation deferred payment=%s: %s", payment["id"], exc)
            return 0
        expired = payment["created_at"] <= utc_now() - timedelta(
            seconds=self.settings.payment_pending_ttl_seconds
        )
        if expired and result.status not in {"PAID", "CLOSED", "FAILED"}:
            try:
                result = provider.close_payment(payment["merchant_payment_no"])
            except Exception as exc:
                log.info("expired payment close deferred payment=%s: %s", payment["id"], exc)
                return 0
        with self.uow.transaction() as connection:
            payments = PaymentRepository(connection)
            if result.status == "PAID":
                # apply_paid_callback enforces the order->payment lock order and
                # all paid/extra/late-payment rules; do not pre-lock rows here.
                apply_paid_callback(
                    connection, provider=payment["provider"],
                    event_id=f"reconcile-paid:{payment['merchant_payment_no']}",
                    values={
                        "merchant_payment_no": payment["merchant_payment_no"],
                        "amount_minor": str(payment["amount_minor"]),
                        "provider_trade_no": result.provider_trade_no or "",
                    },
                )
                return 1
            if result.status not in {"CLOSED", "FAILED"}:
                return 1
            orders = OrderRepository(connection)
            # Unlocked locate, then the financial lock order: order first, payment second.
            if orders.find(payment["order_id"], for_update=True) is None:
                return 1
            current = payments.find(payment["id"], for_update=True)
            if current is not None and current["status"] in {"CREATED", "PENDING"}:
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
            if result.status == "REFUNDED":
                target = "SUCCEEDED"
            elif result.status == "FAILED":
                # Explicit permanent channel failure: frees the refund budget and
                # must not be retried as if it were still processing.
                target = "FAILED"
            else:
                target = "PROCESSING"
            provider_payload = result.raw
        except Exception as exc:
            log.warning("refund reconciliation outcome unknown refund=%s: %s", refund["id"], exc)
            target = "UNKNOWN"
            provider_payload = {"error": f"{type(exc).__name__}: {exc}"}
        with self.uow.transaction() as connection:
            payments = PaymentRepository(connection)
            # apply_refund_outcome re-reads and locks order -> payment -> refund,
            # and keeps SUCCEEDED terminal against stale duplicate results.
            current = apply_refund_outcome(
                connection, refund_id=refund["id"], target=target,
                payload=provider_payload, actor="refund-reconciliation",
            )
            if current is None:
                return 1
            if current["status"] == "UNKNOWN":
                payments.schedule_refund(current["id"], increment_attempt=True)
            elif current["status"] == "PROCESSING":
                payments.schedule_processing_refund(current["id"])
            # SUCCEEDED/FAILED are terminal: nothing further is scheduled.
        return 1

    def watchdog_scan_once(self) -> None:
        with self.uow.transaction() as connection:
            candidates = WorkerRepository(connection).watchdog_rows(
                self.settings.command_ack_timeout_seconds,
                self.settings.command_start_timeout_seconds,
                self.settings.production_timeout_grace_seconds,
                self.settings.production_wait_timeout_seconds,
            )
        for candidate in candidates:
            with self.uow.transaction() as connection:
                self.production.hold_overdue_job(connection, candidate["order_id"], candidate["job_id"])

    def cleanup_history_once(self) -> dict[str, int]:
        with self.uow.transaction() as connection:
            return WorkerRepository(connection).cleanup_history(
                heartbeat_days=self.settings.heartbeat_retention_days,
                mqtt_days=self.settings.mqtt_inbox_retention_days,
                event_days=self.settings.device_event_retention_days,
                outbox_days=self.settings.processed_outbox_retention_days,
                audit_days=self.settings.audit_retention_days,
            )

    def reconcile_stored_command_events(self) -> None:
        with self.uow.transaction() as connection:
            self.production.reconcile_stored_command_events(connection)

    def reconcile_stored_order_events(self) -> None:
        with self.uow.transaction() as connection:
            self.production.reconcile_stored_order_events(connection)
