"""Whitelist visual metadata from the existing durable step plan for customer views."""
from __future__ import annotations

import math
from typing import Any

ACTIONS = {"cups", "brew", "water", "milk", "ice", "syrup", "lid", "pickup", "wait"}


def public_robot_view(plan: Any) -> dict[str, Any] | None:
    if not isinstance(plan, list) or not plan or len(plan) > 100:
        return None
    steps = []
    for index, step in enumerate(plan[:100]):
        if not isinstance(step, dict):
            return None
        visual = step.get("visual")
        if not isinstance(visual, dict) or visual.get("version") != 1:
            return None  # Legacy devices keep the existing 2D display.
        actions = visual.get("actions")
        duration = step.get("durationSeconds")
        if (not isinstance(actions, list) or not actions or
                any(not isinstance(action, str) or action not in ACTIONS for action in actions) or
                not isinstance(duration, (float, int)) or isinstance(duration, bool) or not math.isfinite(duration) or duration <= 0):
            return None
        materials = []
        raw_materials = visual.get("materials") or []
        if not isinstance(raw_materials, list):
            return None
        for item in raw_materials[:32]:
            if not isinstance(item, dict):
                continue
            amount = item.get("amount")
            if not isinstance(amount, (int, float)) or isinstance(amount, bool) or not math.isfinite(amount) or amount < 0:
                continue
            materials.append({"materialId": str(item.get("materialId", ""))[:128],
                              "name": str(item.get("name", ""))[:128], "amount": amount,
                              "unit": str(item.get("unit", ""))[:24]})
        steps.append({"stepId": str(step.get("stepId", ""))[:128], "stepName": str(step.get("stepName", ""))[:128],
                      "stepIndex": index, "durationSeconds": duration,
                      "visual": {"version": 1, "actions": actions, "materials": materials}})
    return {"version": 1, "steps": steps} if steps else None
