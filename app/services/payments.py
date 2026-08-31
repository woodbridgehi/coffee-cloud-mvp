from __future__ import annotations

import logging
import secrets
import uuid
from typing import Any, Callable

from ..db import UnitOfWork
from ..payment_providers import PaymentRequest
from ..payment_service import apply_paid_callback, callback_event_id, transition_payment
from ..protocol import PaymentCreateRequest, RefundCreateRequest, canonical_digest, utc_now
from ..repositories import OrderRepository, PaymentRepository
from ..security import hash_token, tokens_equal
from ..settings import Settings
from .errors import ServiceError
from .order_state import transition_order
from .presenters import payment_payload
from .refund_intents import create_refund_intent


log = logging.getLogger("coffee-cloud-mvp.payments")


class PaymentApplicationService:
    def __init__(
        self,
        uow: UnitOfWork,
        settings: Settings,
        *,
        provider_factory: Callable[[str], Any],
        mock_provider: Any,
    ) -> None:
        self.uow = uow
        self.settings = settings
        self.provider_factory = provider_factory
        self.mock_provider = mock_provider

    @staticmethod
    def _authenticate_order(
        repository: OrderRepository, order_id: uuid.UUID, token: str | None, *, for_update: bool = False
    ) -> dict[str, Any]:
        if not token:
            raise ServiceError(401, "missing order access token")
        order = repository.find_with_terminal(order_id, for_update=for_update)
        if order is None or not tokens_equal(order["access_token_hash"].strip(), hash_token(token)):
            raise ServiceError(404, "order not found")
        return order

    def _payment_with_order_auth(
        self, payments: PaymentRepository, orders: OrderRepository,
        payment_id: uuid.UUID, token: str | None,
    ) -> dict[str, Any]:
        payment = payments.find(payment_id)
        if not payment:
            raise ServiceError(404, "payment not found")
        self._authenticate_order(orders, payment["order_id"], token)
        return payment

    def create(
        self,
        order_id: uuid.UUID,
        payload: PaymentCreateRequest,
        access_token: str | None,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        if not idempotency_key or len(idempotency_key) > 160:
            raise ServiceError(400, "Idempotency-Key is required and must be <= 160 characters")
        provider_name = (payload.provider or self.settings.payment_default_provider).lower()
        if provider_name == "mock" and not self.settings.allow_mock_payment:
            raise ServiceError(503, "mock payment provider is disabled")
        digest = canonical_digest(payload.model_dump(mode="json"))
        existing: dict[str, Any] | None = None
        reused = False
        with self.uow.transaction() as connection:
            orders = OrderRepository(connection)
            payments = PaymentRepository(connection)
            order = self._authenticate_order(orders, order_id, access_token, for_update=True)
            if order["payment_mode"] == "TEST_FREE":
                raise ServiceError(409, "test-free order does not require payment")
            existing = payments.find_idempotent(order_id, idempotency_key)
            if existing:
                # Same-key semantics unchanged: digest conflict, or duplicate reply.
                if existing["request_digest"].strip() != digest:
                    raise ServiceError(409, "Idempotency-Key payload conflict")
                if existing["status"] != "CREATED":
                    return {**payment_payload(existing), "duplicate": True}
                payment = existing
            else:
                if order["payment_status"] in {"PAID", "REFUNDING", "PARTIALLY_REFUNDED", "REFUNDED"}:
                    raise ServiceError(409, "order payment is already complete")
                if order["status"] not in {"CREATED", "AWAITING_PAYMENT"}:
                    raise ServiceError(409, "order can no longer accept a new payment")
                open_intent = payments.latest_open_for_order(order_id, for_update=True)
                if open_intent is not None:
                    # A different key must not open a second merchant payment for the
                    # same order: reuse the active intent, or reject a provider change.
                    if open_intent["provider"] != provider_name:
                        raise ServiceError(409, "order already has an active payment intent with another provider")
                    payment = open_intent
                    reused = True
                else:
                    payment = payments.insert(
                        payment_id=uuid.uuid4(), order=order, provider=provider_name,
                        merchant_no=f"C{utc_now().strftime('%Y%m%d%H%M%S')}{secrets.token_hex(5).upper()}",
                        idempotency_key=idempotency_key, request_digest=digest,
                    )
                    payments.insert_created_event(payment["id"], payload.model_dump(mode="json"))
                    if order["status"] == "CREATED":
                        transition_order(connection, order, "AWAITING_PAYMENT", "payment-service", reason="payment created")
                    orders.update_payment_status(order_id, "PENDING")

        # A retried CREATED intent retains its original channel after a default switch.
        provider_name = payment["provider"]
        provider = self.provider_factory(provider_name)
        request_value = PaymentRequest(
            merchant_payment_no=payment["merchant_payment_no"], amount_minor=payment["amount_minor"],
            currency=payment["currency"], subject=payment["subject"],
            notify_url=f"{self.settings.public_base_url.rstrip('/')}/api/v1/payments/callback/{provider_name}",
            metadata={"orderId": str(order_id)},
        )
        try:
            if payment["status"] == "CREATED":
                try:
                    result = provider.query_payment(payment["merchant_payment_no"])
                    if result.status == "NOT_FOUND" or (result.status == "FAILED" and provider_name == "mock"):
                        result = provider.create_payment(request_value)
                except Exception:
                    result = provider.create_payment(request_value)
            else:
                result = provider.query_payment(payment["merchant_payment_no"])
        except Exception as exc:
            log.warning("payment create/query failed payment=%s provider=%s: %s", payment["id"], provider_name, exc)
            raise ServiceError(502, "payment provider temporarily unavailable") from exc

        with self.uow.transaction() as connection:
            payments = PaymentRepository(connection)
            if result.status == "PAID":
                # apply_paid_callback owns the order->payment lock order and the
                # primary/extra payment rules; never pre-lock the payment row here.
                current, _ = apply_paid_callback(
                    connection, provider=provider_name,
                    event_id=f"query-paid:{payment['merchant_payment_no']}",
                    values={
                        "merchant_payment_no": payment["merchant_payment_no"],
                        "amount_minor": str(payment["amount_minor"]),
                        "provider_trade_no": result.provider_trade_no or "",
                    },
                )
            else:
                current = payments.find(payment["id"], for_update=True)
                assert current is not None
                current = payments.save_provider_result(current["id"], result)
                if current["status"] == "CREATED":
                    current, _ = transition_payment(
                        connection, current, "PENDING", actor="payment-provider", payload=result.raw
                    )
                    payments.schedule_reconciliation(current["id"], self.settings.payment_reconcile_seconds)
        return {**payment_payload(current), "duplicate": existing is not None or reused}

    def get(self, payment_id: uuid.UUID, access_token: str | None) -> dict[str, Any]:
        with self.uow.transaction() as connection:
            payment = self._payment_with_order_auth(
                PaymentRepository(connection), OrderRepository(connection), payment_id, access_token
            )
            return payment_payload(payment)

    def qr_value(self, payment_id: uuid.UUID, access_token: str | None) -> str:
        with self.uow.transaction() as connection:
            payment = self._payment_with_order_auth(
                PaymentRepository(connection), OrderRepository(connection), payment_id, access_token
            )
        if not payment["qr_code"]:
            raise ServiceError(409, "payment QR code is not ready")
        return str(payment["qr_code"])

    def alipay_callback(self, values: dict[str, str], *, provider_name: str = "alipay") -> str:
        try:
            if provider_name not in {"alipay", "alipay_mock"}:
                raise ValueError("unsupported RSA2 callback channel")
            parsed = self.provider_factory(provider_name).verify_and_parse_callback(values)
            expected_app_id = getattr(self.settings, provider_name + "_app_id")
            if not expected_app_id or parsed.get("app_id") != expected_app_id:
                raise ValueError("Alipay callback app_id mismatch")
            if parsed.get("trade_status") not in {"TRADE_SUCCESS", "TRADE_FINISHED"}:
                return "success"
            with self.uow.transaction() as connection:
                apply_paid_callback(
                    connection, provider=provider_name, event_id=callback_event_id(provider_name, parsed), values=parsed
                )
            return "success"
        except (ValueError, ServiceError) as exc:
            log.warning("Alipay callback rejected: %s", exc)
            return "failure"
        except Exception as exc:
            # Existing HTTP-domain errors from legacy transition helpers are deliberately mapped to failure.
            if getattr(exc, "status_code", None) is not None:
                log.warning("Alipay callback rejected: %s", exc)
                return "failure"
            raise

    def mock_callback(self, values: dict[str, Any]) -> dict[str, Any]:
        if self.settings.payment_default_provider != "mock" or not self.settings.allow_mock_payment:
            raise ServiceError(404, "mock payment callback is disabled")
        merchant_no = str(values.get("merchant_payment_no") or "")
        with self.uow.transaction() as connection:
            payment = PaymentRepository(connection).find_mock_by_merchant_no(merchant_no)
            if not payment:
                raise ServiceError(404, "payment not found")
        result = self.mock_provider.set_paid(
            merchant_no, str(values.get("provider_trade_no") or "") or None
        )
        callback_values = {
            "merchant_payment_no": merchant_no, "amount_minor": str(payment["amount_minor"]),
            "provider_trade_no": result.provider_trade_no or "",
        }
        with self.uow.transaction() as connection:
            updated, duplicate = apply_paid_callback(
                connection, provider="mock",
                event_id=str(values.get("event_id") or f"mock-paid:{merchant_no}"), values=callback_values,
            )
        return {**payment_payload(updated), "duplicate": duplicate}

    def refund(
        self, payment_id: uuid.UUID, payload: RefundCreateRequest, idempotency_key: str | None
    ) -> dict[str, Any]:
        """Record a manual refund intent only; the background worker submits it to the channel.

        The API answers with the pending state (or the idempotent existing record,
        including a FAILED one, which is never resubmitted) and never races the
        worker on the same channel request.
        """
        if not idempotency_key or len(idempotency_key) > 160:
            raise ServiceError(400, "Idempotency-Key is required and must be <= 160 characters")
        digest = canonical_digest(payload.model_dump(mode="json"))
        with self.uow.transaction() as connection:
            payments = PaymentRepository(connection)
            orders = OrderRepository(connection)
            # Unlocked first pass only to locate the owning order.
            payment = payments.find(payment_id)
            if not payment:
                raise ServiceError(404, "payment not found")
            # Financial lock order: the order row first, then the payment row.
            if orders.find(payment["order_id"], for_update=True) is None:
                raise ServiceError(404, "order not found")
            intent = create_refund_intent(
                connection, payment_id=payment_id,
                idempotency_key=idempotency_key, request_digest=digest,
                amount_minor=payload.amountMinor, reason=payload.reason,
                actor="refund-service",
            )
        return {
            "refundId": str(intent.refund["id"]), "paymentId": str(payment_id),
            "status": intent.refund["status"], "duplicate": not intent.created,
        }
