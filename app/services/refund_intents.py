"""Single choke point for refund money rules.

Every caller must already hold the ``sales_order`` row lock; these helpers then
lock the payment row and finally the refund rows, which is the domain-wide lock
order (order -> payment -> refund). The refund budget counts in-flight
REQUESTED/PROCESSING/UNKNOWN refunds plus SUCCEEDED ones; a permanently FAILED
channel outcome frees its budget again, an UNKNOWN outcome does not.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from ..payment_transitions import transition_payment, transition_refund
from ..protocol import canonical_digest
from ..repositories import OrderRepository, PaymentRepository
from .errors import ServiceError
from .order_state import transition_order


IN_FLIGHT_REFUND_STATUSES: tuple[str, ...] = ("REQUESTED", "PROCESSING", "UNKNOWN")
BUDGET_REFUND_STATUSES: tuple[str, ...] = IN_FLIGHT_REFUND_STATUSES + ("SUCCEEDED",)
REFUNDABLE_PAYMENT_STATUSES = frozenset({"PAID", "REFUNDING", "PARTIALLY_REFUNDED"})


@dataclass(frozen=True)
class RefundIntent:
    refund: dict[str, Any]
    created: bool
    payment: dict[str, Any] | None = None


def create_refund_intent(
    connection: Any,
    *,
    payment_id: uuid.UUID,
    idempotency_key: str,
    reason: str,
    amount_minor: int | None = None,
    request_digest: str | None = None,
    actor: str = "refund-service",
) -> RefundIntent:
    """Create (or idempotently return) one REQUESTED refund intent.

    ``amount_minor=None`` means "refund whatever budget remains", not the full
    paid amount. A replay with the same business key returns the existing record
    before any refundability check and is never resubmitted to the channel.
    """
    payments = PaymentRepository(connection)
    orders = OrderRepository(connection)
    payment = payments.find(payment_id, for_update=True)
    if payment is None:
        raise ServiceError(404, "payment not found")
    existing = payments.find_refund_idempotent(payment_id, idempotency_key)
    if existing is not None:
        if request_digest is not None and existing["request_digest"].strip() != request_digest:
            raise ServiceError(409, "Idempotency-Key payload conflict")
        return RefundIntent(existing, created=False, payment=payment)
    if payment["status"] not in REFUNDABLE_PAYMENT_STATUSES:
        raise ServiceError(409, "payment is not refundable")
    remaining = int(payment["amount_minor"]) - payments.refunded_total(
        payment_id, statuses=BUDGET_REFUND_STATUSES
    )
    amount = remaining if amount_minor is None else int(amount_minor)
    if amount <= 0 or amount > remaining:
        raise ServiceError(409, "refund amount exceeds unrefunded payment amount")
    refund = payments.insert_refund(
        refund_id=uuid.uuid4(), payment=payment,
        merchant_refund_no=f"R{uuid.uuid4().hex[:24].upper()}",
        idempotency_key=idempotency_key,
        request_digest=request_digest or canonical_digest({"amountMinor": amount, "reason": reason}),
        amount_minor=amount, reason=reason,
    )
    payment, _already_refunding = transition_payment(
        connection, payment, "REFUNDING", actor=actor, payload={"refundId": str(refund["id"])}
    )
    # Only the order's primary payment projects refund progress onto the order;
    # refunds of additional payments never touch the order payment status.
    if payment["order_id"] is not None:
        order = orders.find(payment["order_id"])
        if order is not None and str(order.get("paid_payment_id")) == str(payment["id"]):
            orders.update_payment_status(order["id"], "REFUNDING")
    return RefundIntent(refund, created=True, payment=payment)


def ensure_automatic_refund_intent(
    connection: Any,
    *,
    payment_id: uuid.UUID,
    idempotency_key: str,
    reason: str,
    actor: str = "auto-refund",
) -> RefundIntent | None:
    """Automatic "refund whatever remains" wrapper used by cancellation/expiry.

    Unlike the manual API this never returns 409 for a covered budget: when the
    full amount is already refunded or an in-flight refund covers the remainder
    it is a successful no-op (``None``). It only creates the unique refund for a
    strictly positive remaining budget and never frees an UNKNOWN reservation.
    """
    payments = PaymentRepository(connection)
    payment = payments.find(payment_id, for_update=True)
    if payment is None or payment["status"] not in REFUNDABLE_PAYMENT_STATUSES:
        return None
    existing = payments.find_refund_idempotent(payment_id, idempotency_key)
    if existing is not None:
        return RefundIntent(existing, created=False, payment=payment)
    remaining = int(payment["amount_minor"]) - payments.refunded_total(
        payment_id, statuses=BUDGET_REFUND_STATUSES
    )
    if remaining <= 0:
        return None
    # The payment row lock is held, so the remaining budget cannot change
    # concurrently; any conflict here would be a genuine rule violation.
    return create_refund_intent(
        connection, payment_id=payment_id, idempotency_key=idempotency_key,
        reason=reason, amount_minor=remaining, actor=actor,
    )


def apply_refund_outcome(
    connection: Any,
    *,
    refund_id: uuid.UUID,
    target: str,
    payload: dict[str, Any] | None = None,
    actor: str = "refund-worker",
) -> dict[str, Any] | None:
    """Persist one channel refund outcome under the domain lock order.

    The first (unlocked) pass only locates the owning order/payment; the locked
    pass re-reads every row before mutating it. SUCCEEDED and FAILED outcomes
    are terminal and never regress, whatever stale result arrives afterwards;
    both recompute the financial projection of the payment/order.
    """
    payments = PaymentRepository(connection)
    orders = OrderRepository(connection)
    refund = payments.find_refund(refund_id)
    if refund is None:
        return None
    payment = payments.find(refund["payment_id"])
    if payment is None:
        return None
    order = orders.find(payment["order_id"], for_update=True)
    payment = payments.find(payment["id"], for_update=True)
    assert payment is not None
    refund = payments.find_refund(refund_id, for_update=True)
    assert refund is not None
    if refund["status"] in ("SUCCEEDED", "FAILED"):
        return refund
    refund, _duplicate = transition_refund(connection, refund, target, payload=payload)
    if target in ("SUCCEEDED", "FAILED"):
        _settle_payment_after_refund(connection, orders, payments, payment, order, payload, actor)
    return refund


def _settle_payment_after_refund(
    connection: Any,
    orders: OrderRepository,
    payments: PaymentRepository,
    payment: dict[str, Any],
    order: dict[str, Any] | None,
    payload: dict[str, Any] | None,
    actor: str,
) -> None:
    # Success total -> in-flight -> zero rule: full success REFUNDED; money still
    # in flight REFUNDING; partial success PARTIALLY_REFUNDED; nothing succeeded
    # and nothing in flight (all failed) back to PAID. Replayed payment callbacks
    # never take this settlement-only path.
    succeeded = payments.refunded_total(payment["id"])
    if succeeded >= int(payment["amount_minor"]):
        payment_target = "REFUNDED"
    elif payments.inflight_refund_exists(payment["id"]):
        payment_target = "REFUNDING"
    elif succeeded > 0:
        payment_target = "PARTIALLY_REFUNDED"
    else:
        payment_target = "PAID"
    transition_payment(
        connection, payment, payment_target, actor=actor, payload=payload or {}
    )
    if order is None or str(order.get("paid_payment_id")) != str(payment["id"]):
        return  # Extra payments settle on their own rows only.
    orders.update_payment_status(order["id"], payment_target)
    if payment_target == "REFUNDED" and order["status"] == "FAILED":
        transition_order(
            connection, order, "REFUNDED", actor, reason="full refund completed"
        )


__all__ = [
    "BUDGET_REFUND_STATUSES", "IN_FLIGHT_REFUND_STATUSES", "REFUNDABLE_PAYMENT_STATUSES",
    "RefundIntent", "apply_refund_outcome", "create_refund_intent",
    "ensure_automatic_refund_intent",
]
