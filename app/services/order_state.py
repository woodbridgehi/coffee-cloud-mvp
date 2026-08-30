from __future__ import annotations

from typing import Any

from ..production_state import order_transition_allowed
from ..protocol import utc_now
from ..repositories import OrderRepository


def transition_order(
    connection: Any,
    order: dict[str, Any],
    target: str,
    actor: str,
    *,
    reason: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist one order transition inside the caller-owned transaction."""
    if order["status"] == target:
        return order
    if not order_transition_allowed(order["status"], target):
        return order
    repository = OrderRepository(connection)
    revision = repository.next_transition_revision(order["id"])
    now_at = utc_now()
    started_at = now_at if target == "MAKING" and not order.get("started_at") else order.get("started_at")
    completed_at = now_at if target in {"READY", "FAILED", "EXPIRED"} else order.get("completed_at")
    cancelled_at = now_at if target == "CANCELLED" else order.get("cancelled_at")
    updated = repository.update_transition_state(
        order["id"], target, now_at, started_at, completed_at, cancelled_at
    )
    repository.insert_transition(
        order["id"], revision, order["status"], target, actor, reason, payload
    )
    return updated
