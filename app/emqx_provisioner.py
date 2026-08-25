from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


AUTH_ID = "password_based%3Abuilt_in_database"


@dataclass
class EmqxProvisioner:
    base_url: str
    dashboard_username: str
    dashboard_password: str

    def _request(self, method: str, path: str, payload: Any = None, token: str | None = None) -> tuple[int, Any]:
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(self.base_url.rstrip("/") + path, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=8) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else {}
        except HTTPError as exc:
            raw = exc.read()
            try:
                detail = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                detail = raw.decode(errors="replace")
            return exc.code, detail
        except URLError as exc:
            raise ConnectionError(f"EMQX management API unavailable: {exc.reason}") from exc

    def _token(self) -> str:
        status, result = self._request("POST", "/login", {
            "username": self.dashboard_username, "password": self.dashboard_password,
        })
        if status != 200 or not isinstance(result, dict) or not result.get("token"):
            raise ConnectionError(f"EMQX login failed: HTTP {status}")
        return str(result["token"])

    @staticmethod
    def _rule(topic: str, action: str, qos: list[int], retain: str | bool = "all") -> dict[str, Any]:
        return {"topic": topic, "permission": "allow", "action": action, "qos": qos, "retain": retain}

    def provision_device(self, device_id: str, password: str) -> None:
        token = self._token()
        user_path = f"/authentication/{AUTH_ID}/users/{quote(device_id, safe='')}"
        create_path = f"/authentication/{AUTH_ID}/users"
        status, detail = self._request("POST", create_path, {
            "user_id": device_id, "password": password, "is_superuser": False,
        }, token)
        if status == 409:
            status, detail = self._request("PUT", user_path, {"password": password, "is_superuser": False}, token)
        if status not in {200, 201, 204}:
            raise ConnectionError(f"cannot provision EMQX user: HTTP {status} {detail}")
        rules = [
            self._rule(f"v1/devices/{device_id}/up", "publish", [0, 1], False),
            self._rule(f"v1/devices/{device_id}/presence", "publish", [0, 1], "all"),
            self._rule(f"v1/devices/{device_id}/state", "publish", [0, 1], "all"),
            self._rule(f"v1/devices/{device_id}/down", "subscribe", [1], False),
        ]
        payload = {"username": device_id, "rules": rules}
        rule_path = f"/authorization/sources/built_in_database/rules/users/{quote(device_id, safe='')}"
        status, detail = self._request("PUT", rule_path, payload, token)
        if status == 404:
            status, detail = self._request("POST", "/authorization/sources/built_in_database/rules/users", [payload], token)
        if status not in {200, 201, 204}:
            raise ConnectionError(f"cannot provision EMQX ACL: HTTP {status} {detail}")

    def revoke_device(self, device_id: str) -> None:
        token = self._token()
        status, detail = self._request(
            "DELETE", f"/authentication/{AUTH_ID}/users/{quote(device_id, safe='')}", token=token,
        )
        if status not in {200, 204, 404}:
            raise ConnectionError(f"cannot revoke EMQX user: HTTP {status} {detail}")
        status, detail = self._request(
            "DELETE",
            f"/authorization/sources/built_in_database/rules/users/{quote(device_id, safe='')}",
            token=token,
        )
        if status not in {200, 204, 404}:
            raise ConnectionError(f"cannot revoke EMQX ACL: HTTP {status} {detail}")
