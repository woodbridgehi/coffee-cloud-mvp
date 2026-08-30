"""Pure production decisions; revisions never authorize a state rollback."""

from __future__ import annotations

from dataclasses import dataclass

FINAL_JOBS = frozenset({"SUCCEEDED", "FAILED", "REJECTED", "CANCELLED", "EXPIRED"})
ACTIVE_JOBS = frozenset(
    {"DISPATCHED", "ACCEPTED", "EXECUTING", "PAUSED", "RETRY_WAIT", "HOLD", "UNKNOWN"}
)
FINAL_ORDERS = frozenset({"READY", "FAILED", "CANCELLED", "EXPIRED", "REFUNDED"})
ORDER_TRANSITIONS = {
    "CREATED": {"AWAITING_PAYMENT", "PAID", "QUEUED", "CANCELLED", "EXPIRED"},
    "AWAITING_PAYMENT": {"PAID", "CANCELLED", "EXPIRED"},
    "PAID": {"QUEUED", "CANCELLED", "HOLD"},
    "QUEUED": {"DISPATCHED", "CANCELLED", "EXPIRED", "HOLD"},
    "DISPATCHED": {
        "ACCEPTED",
        "MAKING",
        "READY",
        "FAILED",
        "CANCELLED",
        "EXPIRED",
        "HOLD",
    },
    "ACCEPTED": {"MAKING", "READY", "FAILED", "CANCELLED", "HOLD"},
    "MAKING": {"READY", "FAILED", "CANCELLED", "HOLD"},
    "HOLD": {"READY", "FAILED", "CANCELLED"},
    "FAILED": {"REFUNDED"},
}
EVENT_TARGETS = {
    "task.acknowledged": ("ACCEPTED", "ACCEPTED", "ACKED"),
    "task.started": ("MAKING", "EXECUTING", "EXECUTING"),
    "task.paused": ("MAKING", "PAUSED", "EXECUTING"),
    "task.resumed": ("MAKING", "EXECUTING", "EXECUTING"),
    "task.retry_wait": ("MAKING", "RETRY_WAIT", "EXECUTING"),
    "task.retry": ("MAKING", "EXECUTING", "EXECUTING"),
    "task.recovered": ("HOLD", "HOLD", "UNKNOWN"),
    "task.succeeded": ("READY", "SUCCEEDED", "SUCCEEDED"),
    "task.failed": ("FAILED", "FAILED", "FAILED"),
    "task.rejected": ("FAILED", "REJECTED", "REJECTED"),
    "task.cancelled": ("CANCELLED", "CANCELLED", "CANCELLED"),
}


def order_transition_allowed(current: str, target: str) -> bool:
    return current == target or target in ORDER_TRANSITIONS.get(current, set())


@dataclass(frozen=True)
class EventDecision:
    allowed: bool
    duplicate: bool = False
    reason: str | None = None


def decide_job_event(
    current: str, event: str, revision: int | None, last_revision: int
) -> EventDecision:
    target = EVENT_TARGETS[event][1]
    if revision is not None and revision < last_revision:
        return EventDecision(False, True, "STALE_REVISION")
    if revision is not None and revision == last_revision:
        return EventDecision(
            False,
            current == target,
            "DUPLICATE_REVISION" if current == target else "REVISION_CONFLICT",
        )
    if current in FINAL_JOBS:
        return EventDecision(False, current == target, "FINAL_JOB")
    if current in {"HOLD", "UNKNOWN"}:
        return EventDecision(target in FINAL_JOBS, reason="MANUAL_REVIEW_REQUIRED")
    if current == "QUEUED":
        return EventDecision(False, reason="NOT_DISPATCHED")
    if event in {"task.acknowledged", "task.rejected"}:
        allowed = current in {"DISPATCHED", "ACCEPTED"}
    elif event == "task.started":
        allowed = current in {"DISPATCHED", "ACCEPTED", "EXECUTING"}
    elif event == "task.resumed":
        allowed = current in {"PAUSED", "EXECUTING"}
    elif event == "task.retry":
        allowed = current in {"RETRY_WAIT", "EXECUTING"}
    elif event in {"task.paused", "task.retry_wait"}:
        allowed = current in {"DISPATCHED", "ACCEPTED", "EXECUTING", target}
    else:
        allowed = current in ACTIVE_JOBS
    return EventDecision(
        allowed,
        current == target and revision is None,
        None if allowed else "ILLEGAL_JOB_TRANSITION",
    )


def device_is_busy(reported: dict | None) -> bool:
    value = reported or {}
    if not isinstance(value, dict):
        return True  # malformed device projections must not authorize hardware work
    task = value.get("currentTask") or {}
    if not isinstance(task, dict):
        return True
    task_state = value.get("currentTaskState") or (
        task.get("state") if isinstance(task, dict) else None
    )
    if task_state is not None and not isinstance(task_state, str):
        return True
    if value.get("deviceStatus") is not None and not isinstance(
        value["deviceStatus"], str
    ):
        return True
    return task_state in {
        "RECEIVED",
        "VALIDATING",
        "ACKNOWLEDGED",
        "RUNNING",
        "PAUSED",
        "RETRY_WAIT",
    } or value.get("deviceStatus") in {
        "BUSY",
        "RESERVED",
        "RECOVERING",
        "RUNNING",
        "PAUSED",
        "RETRY_WAIT",
    }
