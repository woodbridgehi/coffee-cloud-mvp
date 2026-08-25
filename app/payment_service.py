from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from .payment_state import decide_payment_transition, decide_refund_transition
from .protocol import canonical_digest, utc_now


def transition_payment(connection: Any, payment: dict[str, Any], target: str, *, actor: str, payload: dict[str, Any] | None = None) -> tuple[dict[str, Any], bool]:
    decision = decide_payment_transition(payment["status"], target)
    if decision.duplicate:
        return payment, True
    if not decision.allowed:
        raise HTTPException(status_code=409, detail=decision.reason)
    revision = int(payment["revision"]) + 1
    updated = connection.execute(
        """update payment set status=%s,revision=%s,updated_at=now(),
             paid_at=case when %s='PAID' then coalesce(paid_at,now()) else paid_at end,
             closed_at=case when %s in ('CLOSED','FAILED') then coalesce(closed_at,now()) else closed_at end
             where id=%s returning *""",
        (target, revision, target, target, payment["id"]),
    ).fetchone()
    connection.execute(
        """insert into payment_event(payment_id,event_id,event_type,actor,payload_json)
             values(%s,%s,%s,%s,%s)""",
        (payment["id"], f"transition:{revision}", f"payment.{target.lower()}", actor, Jsonb(payload or {})),
    )
    return updated, False


def transition_refund(connection: Any, refund: dict[str, Any], target: str, *, payload: dict[str, Any] | None = None) -> tuple[dict[str, Any], bool]:
    decision = decide_refund_transition(refund["status"], target)
    if decision.duplicate:
        return refund, True
    if not decision.allowed:
        raise HTTPException(status_code=409, detail=decision.reason)
    updated = connection.execute(
        """update refund set status=%s,revision=revision+1,provider_response=coalesce(%s,provider_response),
             updated_at=now(),completed_at=case when %s in ('SUCCEEDED','FAILED') then now() else completed_at end
             where id=%s returning *""",
        (target, Jsonb(payload) if payload else None, target, refund["id"]),
    ).fetchone()
    return updated, False


def enqueue_outbox(connection: Any, event_type: str, aggregate_type: str, aggregate_id: str, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
    return connection.execute(
        """insert into business_outbox(id,event_type,aggregate_type,aggregate_id,payload_json,idempotency_key)
             values(%s,%s,%s,%s,%s,%s)
             on conflict(idempotency_key) do update set idempotency_key=excluded.idempotency_key
             returning *""",
        (uuid.uuid4(), event_type, aggregate_type, aggregate_id, Jsonb(payload), idempotency_key),
    ).fetchone()


def callback_event_id(provider: str, values: dict[str, Any]) -> str:
    explicit = values.get("notify_id") or values.get("event_id")
    if explicit:
        return str(explicit)
    return f"digest:{canonical_digest({key: value for key, value in values.items() if key != 'sign'})}"


def apply_paid_callback(
    connection: Any,
    *,
    provider: str,
    event_id: str,
    values: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    digest = canonical_digest(values)
    existing = connection.execute(
        "select * from payment_callback_inbox where provider=%s and provider_event_id=%s for update",
        (provider, event_id),
    ).fetchone()
    if existing:
        if existing["payload_digest"].strip() != digest:
            raise HTTPException(status_code=409, detail="provider event id payload conflict")
        payment = connection.execute("select * from payment where id=%s", (existing["payment_id"],)).fetchone()
        return payment, True

    merchant_no = str(values.get("out_trade_no") or values.get("merchant_payment_no") or "")
    payment = connection.execute(
        "select * from payment where provider=%s and merchant_payment_no=%s for update",
        (provider, merchant_no),
    ).fetchone()
    if not payment:
        raise HTTPException(status_code=404, detail="payment not found")
    callback_amount = values.get("total_amount") or values.get("amount_minor")
    if callback_amount is not None:
        amount_minor = int(round(float(callback_amount) * 100)) if not str(callback_amount).isdigit() else int(callback_amount)
        if amount_minor != int(payment["amount_minor"]):
            raise HTTPException(status_code=409, detail="payment callback amount mismatch")
    provider_trade_no = values.get("trade_no") or values.get("provider_trade_no")
    if provider_trade_no:
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
    payment, duplicate = transition_payment(connection, payment, "PAID", actor=f"{provider}-callback", payload=values)
    connection.execute(
        """insert into payment_callback_inbox(provider,provider_event_id,payment_id,payload_digest,status,payload_json,processed_at)
             values(%s,%s,%s,%s,'PROCESSED',%s,now())""",
        (provider, event_id, payment["id"], digest, Jsonb(values)),
    )
    order = connection.execute("select * from sales_order where id=%s for update", (payment["order_id"],)).fetchone()
    if order["status"] == "CANCELLED":
        refund_key = f"payment:{payment['id']}:cancelled-order-refund"
        existing_refund = connection.execute(
            "select * from refund where payment_id=%s and idempotency_key=%s", (payment["id"], refund_key)
        ).fetchone()
        if not existing_refund:
            request_body = {"amountMinor": payment["amount_minor"], "reason": "payment completed after order cancellation"}
            refund = connection.execute(
                """insert into refund(id,payment_id,provider,merchant_refund_no,idempotency_key,
                       request_digest,status,amount_minor,reason,next_attempt_at)
                     values(%s,%s,%s,%s,%s,%s,'REQUESTED',%s,%s,now()) returning *""",
                (uuid.uuid4(), payment["id"], payment["provider"], f"R{uuid.uuid4().hex[:24].upper()}",
                 refund_key, canonical_digest(request_body), payment["amount_minor"], request_body["reason"]),
            ).fetchone()
            payment, _ = transition_payment(
                connection, payment, "REFUNDING", actor="payment-service",
                payload={"refundId": str(refund["id"]), "reason": "paid after cancellation"},
            )
        connection.execute(
            "update sales_order set payment_status='REFUNDING',updated_at=now() where id=%s", (order["id"],)
        )
        return payment, duplicate
    if order["payment_status"] != "PAID":
        connection.execute(
            "update sales_order set payment_status='PAID',status='PAID',updated_at=now() where id=%s",
            (order["id"],),
        )
        enqueue_outbox(
            connection, "payment.paid", "payment", str(payment["id"]),
            {"paymentId": str(payment["id"]), "orderId": str(order["id"]), "terminalId": order["terminal_id"]},
            f"payment:{payment['id']}:paid",
        )
    return payment, duplicate
