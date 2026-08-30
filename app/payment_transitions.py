"""Persistent payment/refund transition helpers.

The pure decisions come from ``payment_state``; the SQL writes live in
``PaymentRepository``. These helpers combine both so callers (payment_service,
refund_intents, worker, public order cancel) share one choke point. Kept outside
``app/services`` and ``app/payment_state`` so the pure domain file stays free of
FastAPI/SQL while the services layer keeps its "no direct SQL" rule.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .payment_state import decide_payment_transition, decide_refund_transition
from .repositories import PaymentRepository


def transition_payment(
    connection: Any, payment: dict[str, Any], target: str, *, actor: str,
    payload: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    decision = decide_payment_transition(payment["status"], target)
    if decision.duplicate:
        return payment, True
    if not decision.allowed:
        raise HTTPException(status_code=409, detail=decision.reason)
    updated = PaymentRepository(connection).transition_payment(payment, target, actor=actor, payload=payload)
    return updated, False


def transition_refund(
    connection: Any, refund: dict[str, Any], target: str, *,
    payload: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    decision = decide_refund_transition(refund["status"], target)
    if decision.duplicate:
        return refund, True
    if not decision.allowed:
        raise HTTPException(status_code=409, detail=decision.reason)
    updated = PaymentRepository(connection).transition_refund(refund, target, payload)
    return updated, False
