"""Ephemeral progress keys and safe overlays over durable order snapshots."""
from __future__ import annotations

import json
import math
from typing import Any

PROGRESS_CHANNEL = "coffee:progress:updates:v1"
PROGRESS_TTL_SECONDS = 3600


def progress_key(device_id: str, task_id: str) -> str:
    return "coffee:progress:" + json.dumps([device_id, task_id], separators=(",", ":"))


def validate_progress(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    if not isinstance(payload, dict) or not isinstance(payload.get("taskId"), str) or not payload["taskId"]:
        raise ValueError("progress requires taskId")
    revision = payload.get("taskRevision")
    if type(revision) is not int or not 0 <= revision <= 9007199254740991:
        raise ValueError("progress requires a non-negative taskRevision")
    for name in ("overallProgress", "stepProgress", "progress", "elapsedSeconds", "remainingSeconds"):
        value = payload.get(name)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise ValueError(f"invalid progress field: {name}")
    return payload


def merge_progress(snapshot: dict[str, Any], event: dict[str, Any] | None) -> dict[str, Any]:
    job = snapshot.get("production")
    # Durable lifecycle states always win, including pauses/holds and terminal states.
    if not event or not job or snapshot.get("status") != "MAKING" or job.get("status") != "EXECUTING":
        return snapshot
    try:
        payload = validate_progress(event)
    except (ValueError, TypeError):
        return snapshot
    if event.get("deviceId") != snapshot.get("deviceId") or payload["taskId"] != job.get("taskId"):
        return snapshot
    if payload["taskRevision"] <= int(job.get("deviceRevision") or 0):
        return snapshot
    updated = dict(job)
    for source, target in (("stepId", "currentStepId"), ("stepName", "currentStepName"),
                           ("elapsedSeconds", "elapsedSeconds"), ("remainingSeconds", "remainingSeconds")):
        if payload.get(source) is not None:
            updated[target] = payload[source]
    overall = payload.get("overallProgress", payload.get("progress", job["overallProgress"]))
    step = payload.get("stepProgress", payload.get("progress", job["stepProgress"]))
    updated.update(progress=max(0.0, min(1.0, overall)), overallProgress=max(0.0, min(1.0, overall)),
                   stepProgress=max(0.0, min(1.0, step)), deviceRevision=payload["taskRevision"])
    return {**snapshot, "production": updated}


# Atomic revision guard + snapshot + notification: readers never see a notification
# before its snapshot. Older QoS replays cannot replace a newer task revision.
STORE_PROGRESS_LUA = """
local previous = tonumber(redis.call('HGET', KEYS[1], 'revision') or '-1')
if previous >= tonumber(ARGV[1]) then return 0 end
redis.call('HSET', KEYS[1], 'revision', ARGV[1], 'event', ARGV[2])
redis.call('EXPIRE', KEYS[1], ARGV[3])
redis.call('PUBLISH', ARGV[4], KEYS[1])
return 1
"""
