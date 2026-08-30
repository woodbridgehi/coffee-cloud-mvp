from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from .payment_state import (
    PAYMENT_CLOSED, PAYMENT_FAILED, PAYMENT_PAID, PAYMENT_PARTIALLY_REFUNDED, PAYMENT_REFUNDED,
    PAYMENT_REFUNDING,
)
from .payment_transitions import transition_payment, transition_refund  # re-exported for legacy callers
from .protocol import canonical_digest
from .services.refund_intents import REFUNDABLE_PAYMENT_STATUSES, ensure_automatic_refund_intent

# A second callback (even with a different provider event id) only re-confirms an
# already recorded payment fact; it must never rewrite PAID over a refund state.
PAID_CALLBACK_STATUSES = frozenset({PAYMENT_PAID, PAYMENT_REFUNDING, PAYMENT_PARTIALLY_REFUNDED, PAYMENT_REFUNDED})
# Orders in these states can never be revived by a late payment; money must return.
DEAD_ORDER_STATUSES = frozenset({"CANCELLED", "EXPIRED", "FAILED"})

__all__ = [
    "DEAD_ORDER_STATUSES", "PAID_CALLBACK_STATUSES",
    "apply_paid_callback", "callback_amount_minor", "callback_event_id",
    "enqueue_outbox", "transition_payment", "transition_refund",
]


def callback_event_id(provider: str, values: dict[str, Any]) -> str:
    explicit = values.get("notify_id") or values.get("event_id")
    if explicit:
        return str(explicit)
    return f"digest:{canonical_digest({key: value for key, value in values.items() if key != 'sign'})}"


def callback_amount_minor(values: dict[str, Any]) -> int | None:
    """Parse the channel amount with Decimal: ``total_amount`` is yuan, ``amount_minor`` is cents."""
    source: str | None = None
    raw: Any = values.get("total_amount")
    if raw is None or str(raw).strip() == "":
        raw = values.get("amount_minor")
        if raw is not None and str(raw).strip() != "":
            source = "minor"
    elif str(raw).strip() != "":
        source = "total"
    if source is None:
        return None
    try:
        amount = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=409, detail="payment callback amount is invalid")
    if not amount.is_finite() or amount <= 0:
        raise HTTPException(status_code=409, detail="payment callback amount is invalid")
    cents = amount * 100 if source == "total" else amount
    if cents != cents.to_integral_value():
        raise HTTPException(status_code=409, detail="payment callback amount has fractional minor units")
    return int(cents)


def enqueue_outbox(
    connection: Any, event_type: str, aggregate_type: str, aggregate_id: str,
    payload: dict[str, Any], idempotency_key: str,
) -> dict[str, Any]:
    return connection.execute(
        """insert into business_outbox(id,event_type,aggregate_type,aggregate_id,payload_json,idempotency_key)
             values(%s,%s,%s,%s,%s,%s)
             on conflict(idempotency_key) do update set idempotency_key=excluded.idempotency_key
             returning *""",
        (uuid.uuid4(), event_type, aggregate_type, aggregate_id, Jsonb(payload), idempotency_key),
    ).fetchone()


def _record_late_paid(
    connection: Any, payment: dict[str, Any], provider: str, values: dict[str, Any]
) -> dict[str, Any]:
    """Record the channel-verified fact that a CLOSED/FAILED intent actually received money.

    Only the verified callback path may do this; generic state-machine callers
    keep CLOSED/FAILED as terminal.
    """
    revision = int(payment["revision"]) + 1
    updated = connection.execute(
        """update payment set status='PAID',revision=%s,updated_at=now(),
             paid_at=coalesce(paid_at,now()),provider_response=coalesce(provider_response,%s)
             where id=%s returning *""",
        (revision, Jsonb(values), payment["id"]),
    ).fetchone()
    connection.execute(
        """insert into payment_event(payment_id,event_id,event_type,actor,payload_json)
             values(%s,%s,'payment.late_paid_recorded',%s,%s)""",
        (payment["id"], f"late-paid:{revision}", f"{provider}-callback", Jsonb(values)),
    )
    return updated


def _inbox_conflict(existing: dict[str, Any], digest: str) -> None:
    if existing["payload_digest"].strip() != digest:
        raise HTTPException(status_code=409, detail="provider event id payload conflict")


def _ensure_extra_refund(
    connection: Any, payment: dict[str, Any], *, idempotency_key: str, reason: str,
) -> dict[str, Any]:
    """Schedule the automatic refund for late/extra money; zero budget is a no-op."""
    if payment["status"] not in REFUNDABLE_PAYMENT_STATUSES:
        return payment
    intent = ensure_automatic_refund_intent(
        connection, payment_id=payment["id"], idempotency_key=idempotency_key, reason=reason,
        actor="payment-service",
    )
    return intent.payment if intent is not None else payment


def apply_paid_callback(
    connection: Any,
    *,
    provider: str,
    event_id: str,
    values: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    digest = canonical_digest(values)
    # Fast path for an already processed provider event (locks only the inbox row).
    existing = connection.execute(
        "select * from payment_callback_inbox where provider=%s and provider_event_id=%s for update",
        (provider, event_id),
    ).fetchone()
    if existing:
        _inbox_conflict(existing, digest)
        payment = connection.execute(
            "select * from payment where id=%s", (existing["payment_id"],)
        ).fetchone()
        return payment, True

    merchant_no = str(values.get("out_trade_no") or values.get("merchant_payment_no") or "")
    # Unlocked first pass only to locate the owning order/payment rows.
    payment = connection.execute(
        "select * from payment where provider=%s and merchant_payment_no=%s",
        (provider, merchant_no),
    ).fetchone()
    if not payment:
        raise HTTPException(status_code=404, detail="payment not found")
    # A paid fact may only be confirmed with a valid amount; a missing or
    # non-matching amount must never mark money as received.
    amount_minor = callback_amount_minor(values)
    if amount_minor is None:
        raise HTTPException(status_code=409, detail="payment callback amount is required")
    if amount_minor != int(payment["amount_minor"]):
        raise HTTPException(status_code=409, detail="payment callback amount mismatch")
    provider_trade_no = values.get("trade_no") or values.get("provider_trade_no")

    # Financial lock order: sales_order first, then payment, then refund rows.
    order = connection.execute(
        "select * from sales_order where id=%s for update", (payment["order_id"],)
    ).fetchone()
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    payment = connection.execute(
        "select * from payment where id=%s for update", (payment["id"],)
    ).fetchone()
    assert payment is not None
    # Re-check the inbox under the financial locks: a concurrent callback with the
    # same provider event may have inserted it after the first (unlocked) check.
    existing = connection.execute(
        "select * from payment_callback_inbox where provider=%s and provider_event_id=%s",
        (provider, event_id),
    ).fetchone()
    if existing:
        _inbox_conflict(existing, digest)
        return payment, True

    if provider_trade_no:
        # The first recorded channel trade number is the financial fact; a later
        # callback claiming a different trade number is rejected, never merged.
        recorded = (payment["provider_trade_no"] or "").strip()
        incoming = str(provider_trade_no).strip()
        if recorded and recorded != incoming:
            raise HTTPException(status_code=409, detail="provider trade number conflict")
        conflict = connection.execute(
            "select id from payment where provider=%s and provider_trade_no=%s and id<>%s",
            (provider, provider_trade_no, payment["id"]),
        ).fetchone()
        if conflict:
            raise HTTPException(status_code=409, detail="provider trade number conflict")
        payment = connection.execute(
            "update payment set provider_trade_no=%s,provider_response=%s,updated_at=now() where id=%s returning *",
            (provider_trade_no, Jsonb(values), payment["id"]),
        ).fetchone()

    duplicate = False
    if payment["status"] in PAID_CALLBACK_STATUSES:
        # The paid fact was already recorded (possibly already refunding): this
        # callback only idempotently re-confirms it further down.
        duplicate = True
    elif payment["status"] in {PAYMENT_CLOSED, PAYMENT_FAILED}:
        payment = _record_late_paid(connection, payment, provider, values)
    else:
        payment, duplicate = transition_payment(
            connection, payment, PAYMENT_PAID, actor=f"{provider}-callback", payload=values
        )
    connection.execute(
        """insert into payment_callback_inbox(provider,provider_event_id,payment_id,payload_digest,status,payload_json,processed_at)
             values(%s,%s,%s,%s,'PROCESSED',%s,now())""",
        (provider, event_id, payment["id"], digest, Jsonb(values)),
    )

    primary_id = order["paid_payment_id"]
    if order["status"] in DEAD_ORDER_STATUSES:
        # Late money on a cancelled/expired/finally-failed order is refunded,
        # never dispatched; the order itself never revives. A pure replay of an
        # already recorded fact changes nothing at all.
        if not duplicate:
            if primary_id is None:
                connection.execute(
                    "update sales_order set paid_payment_id=%s,updated_at=now() where id=%s and paid_payment_id is null",
                    (payment["id"], order["id"]),
                )
                primary_id = payment["id"]
            if str(primary_id) == str(payment["id"]):
                connection.execute(
                    """update sales_order set payment_status='REFUNDING',updated_at=now()
                         where id=%s and payment_status in ('NOT_STARTED','PENDING','PAID','PARTIALLY_REFUNDED')""",
                    (order["id"],),
                )
            payment = _ensure_extra_refund(
                connection, payment,
                idempotency_key=f"payment:{payment['id']}:cancelled-order-refund",
                reason="payment completed after order cancellation",
            )
        return payment, duplicate

    if duplicate:
        # Live order + already recorded money: idempotent confirmation only. The
        # order projection is never rewritten (not to PAID, not away from refund
        # states) and payment.paid is never enqueued twice.
        return payment, True

    if primary_id is None:
        connection.execute(
            "update sales_order set paid_payment_id=%s,updated_at=now() where id=%s and paid_payment_id is null",
            (payment["id"], order["id"]),
        )
        primary_id = payment["id"]
    if str(primary_id) != str(payment["id"]):
        # Additional money on another intent: refund that payment only; never
        # dispatch again and never touch the primary payment's order projection.
        payment = _ensure_extra_refund(
            connection, payment,
            idempotency_key=f"payment:{payment['id']}:extra-paid-refund",
            reason="duplicate payment received for order",
        )
        return payment, duplicate
    if order["payment_status"] != PAYMENT_PAID:
        connection.execute(
            """update sales_order set payment_status='PAID',
                 status=case when status in ('CREATED','AWAITING_PAYMENT') then 'PAID' else status end,
                 updated_at=now() where id=%s""",
            (order["id"],),
        )
        enqueue_outbox(
            connection, "payment.paid", "payment", str(payment["id"]),
            {"paymentId": str(payment["id"]), "orderId": str(order["id"]), "terminalId": order["terminal_id"]},
            f"payment:{payment['id']}:paid",
        )
    return payment, duplicate
