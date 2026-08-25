#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import secrets
import sys
import uuid
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:8790").rstrip("/")
DEVICE_ID = os.environ.get("DEVICE_ID", "coffee-bot-002")
ADMIN_TOKEN = os.environ["ADMIN_TOKEN"]
INITIAL_DEVICE_TOKEN = os.environ["DEVICE_TOKEN"]


def call(
    method: str,
    path: str,
    payload: dict | None = None,
    *,
    token: str | None = None,
    admin: bool = False,
    headers: dict[str, str] | None = None,
    expected: int = 200,
) -> dict:
    request_headers = {
        "Accept": "application/json", "Content-Type": "application/json",
        "User-Agent": "CoffeeCloudContractSmoke/0.2.0", **(headers or {}),
    }
    if admin:
        request_headers["Authorization"] = f"Bearer {ADMIN_TOKEN}"
    elif token:
        request_headers["Authorization"] = f"Bearer {token}"
        request_headers["X-Device-Id"] = DEVICE_ID
    body = None if payload is None else json.dumps(payload).encode()
    try:
        with urlopen(Request(f"{BASE_URL}{path}", data=body, method=method, headers=request_headers), timeout=8) as response:
            if response.status != expected:
                raise AssertionError(f"{method} {path}: expected {expected}, got {response.status}")
            return json.load(response)
    except HTTPError as exc:
        if exc.code == expected:
            return {}
        raise AssertionError(f"{method} {path}: expected {expected}, got {exc.code}") from exc


def heartbeat(token: str, suffix: str, *, expected: int = 200) -> dict:
    return call(
        "POST", f"/api/v1/devices/{DEVICE_ID}/heartbeat",
        {
            "deviceId": DEVICE_ID, "messageId": f"smoke-hb-{suffix}-{uuid.uuid4()}",
            "bootId": f"smoke-{suffix}", "sequence": 1, "deviceStatus": "IDLE",
            "sentAt": datetime.now(timezone.utc).isoformat(),
        }, token=token, expected=expected,
    )


def main() -> None:
    activation = call(
        "POST", f"/api/v1/admin/devices/{DEVICE_ID}/activation-codes",
        {"ttlSeconds": 600}, admin=True,
    )
    token_v2 = secrets.token_urlsafe(48)
    activated = call(
        "POST", "/api/v1/device-activations",
        {"deviceId": DEVICE_ID, "activationCode": activation["activationCode"], "deviceToken": token_v2},
    )
    retried = call(
        "POST", "/api/v1/device-activations",
        {"deviceId": DEVICE_ID, "activationCode": activation["activationCode"], "deviceToken": token_v2},
    )
    assert retried["duplicate"] is True
    heartbeat(INITIAL_DEVICE_TOKEN, "initial-grace")
    heartbeat(token_v2, "activated")

    token_v3 = secrets.token_urlsafe(48)
    rotation_key = f"smoke-rotation-{uuid.uuid4()}"
    rotated = call(
        "POST", f"/api/v1/devices/{DEVICE_ID}/credentials/rotate", {"newToken": token_v3},
        token=token_v2, headers={"Idempotency-Key": rotation_key},
    )
    rotation_retry = call(
        "POST", f"/api/v1/devices/{DEVICE_ID}/credentials/rotate", {"newToken": token_v3},
        token=token_v2, headers={"Idempotency-Key": rotation_key},
    )
    assert rotation_retry["duplicate"] is True
    heartbeat(token_v2, "rotation-grace")
    heartbeat(token_v3, "rotated")

    command_key = f"smoke-command-{uuid.uuid4()}"
    task_id = f"task-{uuid.uuid4()}"
    order_id = f"order-{uuid.uuid4()}"
    command_request = {
        "type": "MAKE_DRINK", "taskId": task_id, "orderId": order_id,
        "recipeId": "espresso-v1", "recipeVersion": "1.0.0",
        "expiresAt": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
    }
    created = call(
        "POST", f"/api/v1/admin/devices/{DEVICE_ID}/commands", command_request,
        admin=True, headers={"Idempotency-Key": command_key}, expected=201,
    )
    repeated = call(
        "POST", f"/api/v1/admin/devices/{DEVICE_ID}/commands", command_request,
        admin=True, headers={"Idempotency-Key": command_key}, expected=201,
    )
    assert repeated["duplicate"] is True
    conflict = {**command_request, "recipeId": "different-recipe"}
    call(
        "POST", f"/api/v1/admin/devices/{DEVICE_ID}/commands", conflict,
        admin=True, headers={"Idempotency-Key": command_key}, expected=409,
    )

    polled = call("GET", f"/api/v1/devices/{DEVICE_ID}/commands?{urlencode({'after': '', 'limit': 100})}", token=token_v3)
    message_id = created["messageId"]
    assert any(item["messageId"] == message_id for item in polled["commands"])
    ack = call(
        "POST", f"/api/v1/tasks/{task_id}/ack",
        {"messageId": message_id, "accepted": True}, token=token_v3,
    )
    assert ack["commandStatus"] == "ACKED"
    for event_type in ("task.started", "task.succeeded"):
        call(
            "POST", f"/api/v1/devices/{DEVICE_ID}/events",
            {
                "eventId": f"event-{uuid.uuid4()}", "deviceId": DEVICE_ID,
                "type": event_type, "taskId": task_id,
                "occurredAt": datetime.now(timezone.utc).isoformat(),
            }, token=token_v3,
        )
    late_ack = call(
        "POST", f"/api/v1/tasks/{task_id}/ack",
        {"messageId": message_id, "accepted": True}, token=token_v3,
    )
    assert late_ack["stale"] is True
    observed = call(
        "GET", f"/api/v1/admin/devices/{DEVICE_ID}/commands/{message_id}", admin=True,
    )
    assert observed["status"] == "SUCCEEDED"
    assert [item["to"] for item in observed["transitions"]] == [
        "CREATED", "DELIVERING", "ACKED", "EXECUTING", "SUCCEEDED",
    ]

    call(
        "POST", f"/api/v1/admin/devices/{DEVICE_ID}/credentials/{activated['credentialId']}/revoke",
        {}, admin=True,
    )
    heartbeat(token_v2, "revoked", expected=401)
    heartbeat(token_v3, "active-final")
    print(
        "smoke-ok: activation retry, dual credential window, rotation retry, "
        "command idempotency, transitions, late ACK and revocation"
    )


if __name__ == "__main__":
    main()
