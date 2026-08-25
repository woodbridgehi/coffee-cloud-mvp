from __future__ import annotations

from dataclasses import dataclass


PAYMENT_CREATED = "CREATED"
PAYMENT_PENDING = "PENDING"
PAYMENT_PAID = "PAID"
PAYMENT_REFUNDING = "REFUNDING"
PAYMENT_PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
PAYMENT_REFUNDED = "REFUNDED"
PAYMENT_CLOSED = "CLOSED"
PAYMENT_FAILED = "FAILED"

PAYMENT_TERMINAL = frozenset({PAYMENT_REFUNDED, PAYMENT_CLOSED, PAYMENT_FAILED})
PAYMENT_TRANSITIONS: dict[str, frozenset[str]] = {
    PAYMENT_CREATED: frozenset({PAYMENT_PENDING, PAYMENT_PAID, PAYMENT_CLOSED, PAYMENT_FAILED}),
    PAYMENT_PENDING: frozenset({PAYMENT_PAID, PAYMENT_CLOSED, PAYMENT_FAILED}),
    PAYMENT_PAID: frozenset({PAYMENT_REFUNDING, PAYMENT_PARTIALLY_REFUNDED, PAYMENT_REFUNDED}),
    PAYMENT_REFUNDING: frozenset({PAYMENT_PAID, PAYMENT_PARTIALLY_REFUNDED, PAYMENT_REFUNDED, PAYMENT_FAILED}),
    PAYMENT_PARTIALLY_REFUNDED: frozenset({PAYMENT_REFUNDING, PAYMENT_REFUNDED}),
}

REFUND_REQUESTED = "REQUESTED"
REFUND_PROCESSING = "PROCESSING"
REFUND_SUCCEEDED = "SUCCEEDED"
REFUND_FAILED = "FAILED"
REFUND_UNKNOWN = "UNKNOWN"

REFUND_TERMINAL = frozenset({REFUND_SUCCEEDED, REFUND_FAILED})
REFUND_TRANSITIONS: dict[str, frozenset[str]] = {
    REFUND_REQUESTED: frozenset({REFUND_PROCESSING, REFUND_SUCCEEDED, REFUND_FAILED, REFUND_UNKNOWN}),
    REFUND_PROCESSING: frozenset({REFUND_SUCCEEDED, REFUND_FAILED, REFUND_UNKNOWN}),
    REFUND_UNKNOWN: frozenset({REFUND_PROCESSING, REFUND_SUCCEEDED, REFUND_FAILED}),
}


@dataclass(frozen=True)
class StateDecision:
    allowed: bool
    duplicate: bool = False
    reason: str | None = None


def decide_payment_transition(current: str, target: str) -> StateDecision:
    if current == target:
        return StateDecision(True, duplicate=True)
    if target not in PAYMENT_TRANSITIONS.get(current, frozenset()):
        return StateDecision(False, reason=f"illegal payment transition {current} -> {target}")
    return StateDecision(True)


def decide_refund_transition(current: str, target: str) -> StateDecision:
    if current == target:
        return StateDecision(True, duplicate=True)
    if target not in REFUND_TRANSITIONS.get(current, frozenset()):
        return StateDecision(False, reason=f"illegal refund transition {current} -> {target}")
    return StateDecision(True)
