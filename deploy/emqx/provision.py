#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
API = "http://127.0.0.1:18083/api/v5"
AUTH_ID = "password_based%3Abuilt_in_database"


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def request(method: str, path: str, payload: object | None = None, token: str | None = None) -> tuple[int, object]:
    headers = {"Accept": "application/json"}
    body = None
    if payload is not None:
        body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(API + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            detail = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            detail = raw.decode(errors="replace")
        return exc.code, detail


def ensure_secret(name: str) -> tuple[str, Path]:
    secret_dir = ROOT / "secrets"
    secret_dir.mkdir(mode=0o700, exist_ok=True)
    path = secret_dir / f"{name}.env"
    if path.exists():
        password = read_env(path)["MQTT_PASSWORD"]
    else:
        password = secrets.token_urlsafe(36)
        path.write_text(
            "MQTT_HOST=mqtt-api.woodbridge.top\n"
            "MQTT_PORT=8883\n"
            "MQTT_TLS=true\n"
            f"MQTT_USERNAME={name}\n"
            f"MQTT_PASSWORD={password}\n"
        )
        path.chmod(0o600)
    return password, path


def ensure_user(token: str, username: str, password: str) -> str:
    payload = {"user_id": username, "password": password, "is_superuser": False}
    status, _ = request("POST", f"/authentication/{AUTH_ID}/users", payload, token)
    if status in {200, 201, 204}:
        return "created"
    if status == 409:
        status, detail = request(
            "PUT",
            f"/authentication/{AUTH_ID}/users/{urllib.parse.quote(username, safe='')}",
            {"password": password, "is_superuser": False},
            token,
        )
        if status in {200, 204}:
            return "updated"
        raise RuntimeError(f"cannot update MQTT user {username}: HTTP {status} {detail}")
    raise RuntimeError(f"cannot create MQTT user {username}: HTTP {status}")


def ensure_rules(token: str, username: str, rules: list[dict[str, object]]) -> str:
    encoded = urllib.parse.quote(username, safe="")
    payload = {"username": username, "rules": rules}
    status, _ = request(
        "PUT", f"/authorization/sources/built_in_database/rules/users/{encoded}", payload, token
    )
    if status in {200, 204}:
        return "updated"
    if status == 404:
        status, detail = request(
            "POST", "/authorization/sources/built_in_database/rules/users", [payload], token
        )
        if status in {200, 201, 204}:
            return "created"
        raise RuntimeError(f"cannot create ACL for {username}: HTTP {status} {detail}")
    raise RuntimeError(f"cannot update ACL for {username}: HTTP {status}")


def rule(topic: str, action: str, qos: list[int], retain: str | bool = "all") -> dict[str, object]:
    return {"topic": topic, "permission": "allow", "action": action, "qos": qos, "retain": retain}


def main() -> None:
    env = read_env(ROOT / ".env")
    status, login = request(
        "POST",
        "/login",
        {"username": env["EMQX_DASHBOARD_USERNAME"], "password": env["EMQX_DASHBOARD_PASSWORD"]},
    )
    if status != 200 or not isinstance(login, dict) or not login.get("token"):
        raise RuntimeError(f"EMQX login failed: HTTP {status}")
    token = str(login["token"])

    accounts = {
        "coffee-bot-002": [
            rule("v1/devices/coffee-bot-002/up", "publish", [0, 1], False),
            rule("v1/devices/coffee-bot-002/presence", "publish", [0, 1], "all"),
            rule("v1/devices/coffee-bot-002/state", "publish", [0, 1], "all"),
            rule("v1/devices/coffee-bot-002/down", "subscribe", [1], False),
        ],
        "coffee-cloud-gateway": [
            rule("v1/devices/+/down", "publish", [1], False),
            rule("v1/devices/+/up", "subscribe", [0, 1], "all"),
            rule("v1/devices/+/presence", "subscribe", [0, 1], "all"),
            rule("v1/devices/+/state", "subscribe", [0, 1], "all"),
        ],
    }
    for username, rules in accounts.items():
        password, _ = ensure_secret(username)
        user_status = ensure_user(token, username, password)
        acl_status = ensure_rules(token, username, rules)
        print(f"{username}: user={user_status}, acl={acl_status}")


if __name__ == "__main__":
    os.umask(0o077)
    main()
