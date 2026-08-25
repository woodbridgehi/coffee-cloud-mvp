from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


ACTIVE_ORDER_STATUSES = frozenset({"QUEUED", "DISPATCHED", "ACCEPTED", "MAKING"})
TERMINAL_ORDER_STATUSES = frozenset({"READY", "FAILED", "CANCELLED", "EXPIRED"})


def device_progress(
    payload: dict[str, Any],
    current_overall: float = 0.0,
    current_step: float = 0.0,
) -> tuple[float, float]:
    """Normalize v1.1 device progress while keeping legacy step-only events monotonic."""
    legacy = payload.get("progress")
    if payload.get("overallProgress") is not None:
        overall = float(payload["overallProgress"])
    elif legacy is not None:
        overall = max(float(current_overall), float(legacy))
    else:
        overall = float(current_overall)
    step = float(payload.get("stepProgress", legacy if legacy is not None else current_step))
    return max(0.0, min(1.0, overall)), max(0.0, min(1.0, step))


def terminal_is_online(terminal: dict[str, Any], threshold_seconds: int, *, now: datetime | None = None) -> bool:
    heartbeat = terminal.get("last_heartbeat_at")
    if not heartbeat:
        return False
    current = now or datetime.now(timezone.utc)
    return heartbeat >= current - timedelta(seconds=threshold_seconds)


def public_menu(
    terminal: dict[str, Any],
    capabilities: dict[str, Any] | None,
    inventory: dict[str, Any] | None,
    threshold_seconds: int,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    online = terminal_is_online(terminal, threshold_seconds, now=now)
    device_ready = terminal.get("lifecycle_status") == "ACTIVE"
    products: list[dict[str, Any]] = []
    for raw in (capabilities or {}).get("products", []):
        remaining = max(0, int(raw.get("maxServings") or 0))
        available = bool(raw.get("enabled", True) and raw.get("available", False) and remaining > 0 and online and device_ready)
        reasons = list(raw.get("unavailableReasons") or [])
        if not online:
            reasons.append("DEVICE_OFFLINE")
        if not device_ready:
            reasons.append("DEVICE_NOT_ACTIVE")
        products.append({
            "recipeId": raw.get("recipeId"),
            "recipeVersion": raw.get("version"),
            "skuCode": raw.get("skuCode"),
            "name": raw.get("name"),
            "description": (raw.get("display") or {}).get("description"),
            "sortOrder": (raw.get("display") or {}).get("sortOrder", 100),
            "visual": raw.get("visual") or {"profile": "generic"},
            "available": available,
            "remainingServings": remaining,
            "estimatedDurationSeconds": raw.get("estimatedDurationSeconds"),
            "durationRangeSeconds": raw.get("durationRangeSeconds"),
            "unavailableReasons": sorted(set(reasons)),
            "priceMinor": 0,
            "currency": "TWD",
        })
    products.sort(key=lambda item: (item["sortOrder"], item["name"] or ""))
    materials = (inventory or {}).get("materials", [])
    alerts = [
        {"materialId": item.get("materialId"), "name": item.get("name"), "status": item.get("status")}
        for item in materials if item.get("status") in {"LOW", "CRITICAL"}
    ]
    return {
        "deviceId": terminal.get("device_id"),
        "storeId": terminal.get("store_id"),
        "online": online,
        "deviceStatus": (terminal.get("reported_status") or {}).get("deviceStatus", "UNKNOWN"),
        "salesEnabled": online and device_ready and any(item["available"] for item in products),
        "paymentMode": "TEST_FREE",
        "products": products,
        "inventoryVersion": (inventory or {}).get("inventoryVersion"),
        "inventoryUpdatedAt": (inventory or {}).get("updatedAt"),
        "materialAlertCount": len(alerts),
    }


def order_state_for_event(event_type: str) -> tuple[str, str] | None:
    return {
        "task.acknowledged": ("ACCEPTED", "ACCEPTED"),
        "task.started": ("MAKING", "EXECUTING"),
        "task.succeeded": ("READY", "SUCCEEDED"),
        "task.failed": ("FAILED", "FAILED"),
        "task.cancelled": ("CANCELLED", "CANCELLED"),
        "task.rejected": ("FAILED", "REJECTED"),
    }.get(event_type)
