from __future__ import annotations

from dataclasses import dataclass


CREATED = "CREATED"
DELIVERING = "DELIVERING"
PUBLISHED = "PUBLISHED"
ACKED = "ACKED"
EXECUTING = "EXECUTING"
SUCCEEDED = "SUCCEEDED"
REJECTED = "REJECTED"
FAILED = "FAILED"
EXPIRED = "EXPIRED"
CANCELLED = "CANCELLED"
UNKNOWN = "UNKNOWN"

TERMINAL_STATES = frozenset({SUCCEEDED, REJECTED, FAILED, EXPIRED, CANCELLED})
LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    CREATED: frozenset({DELIVERING, PUBLISHED, CANCELLED, EXPIRED}),
    DELIVERING: frozenset({PUBLISHED, ACKED, EXECUTING, SUCCEEDED, REJECTED, FAILED, CANCELLED, EXPIRED, UNKNOWN}),
    PUBLISHED: frozenset({ACKED, EXECUTING, SUCCEEDED, REJECTED, FAILED, CANCELLED, EXPIRED, UNKNOWN}),
    ACKED: frozenset({EXECUTING, SUCCEEDED, FAILED, CANCELLED, UNKNOWN}),
    EXECUTING: frozenset({SUCCEEDED, FAILED, CANCELLED, UNKNOWN}),
    UNKNOWN: frozenset({ACKED, EXECUTING, SUCCEEDED, REJECTED, FAILED, CANCELLED, EXPIRED}),
}


@dataclass(frozen=True)
class TransitionDecision:
    allowed: bool
    duplicate: bool = False
    reason: str | None = None


def decide_transition(current: str, target: str) -> TransitionDecision:
    if current == target:
        return TransitionDecision(allowed=True, duplicate=True)
    if current in TERMINAL_STATES:
        return TransitionDecision(False, reason=f"terminal state {current} cannot transition to {target}")
    if target not in LEGAL_TRANSITIONS.get(current, frozenset()):
        return TransitionDecision(False, reason=f"illegal command transition {current} -> {target}")
    return TransitionDecision(True)


def result_state(value: str | None) -> str:
    normalized = (value or "").upper()
    if normalized in {"SUCCEEDED", "SUCCESS", "COMPLETED", "APPLIED", "OK"}:
        return SUCCEEDED
    if normalized in {"REJECTED", "DECLINED"}:
        return REJECTED
    if normalized in {"CANCELLED", "CANCELED"}:
        return CANCELLED
    if normalized == "EXPIRED":
        return EXPIRED
    return FAILED


def event_state(event_type: str) -> str | None:
    return {
        "task.started": EXECUTING,
        "task.succeeded": SUCCEEDED,
        "task.failed": FAILED,
        "task.cancelled": CANCELLED,
    }.get(event_type)
