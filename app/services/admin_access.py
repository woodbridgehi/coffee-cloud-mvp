from __future__ import annotations

import secrets
import uuid
from typing import Any

from ..db import UnitOfWork
from ..repositories import AdminAccessRepository
from ..security import hash_token, tokens_equal
from ..settings import Settings
from ..protocol import utc_now
from .errors import ServiceError
from .presenters import iso


ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "VIEWER": frozenset({"dashboard.read", "devices.read", "orders.read"}),
    "OPERATOR": frozenset({
        "dashboard.read", "devices.read", "orders.read", "devices.manage", "commands.execute",
    }),
    "MANAGER": frozenset({
        "dashboard.read", "devices.read", "orders.read", "devices.manage", "commands.execute",
        "refunds.manage", "access.read", "audit.read",
    }),
    "OWNER": frozenset({
        "dashboard.read", "devices.read", "orders.read", "devices.manage", "commands.execute",
        "refunds.manage", "access.read", "access.manage", "audit.read",
    }),
}


class AdminAccessService:
    def __init__(self, uow: UnitOfWork, settings: Settings) -> None:
        self.uow = uow
        self.settings = settings

    @staticmethod
    def _principal(row: dict[str, Any]) -> dict[str, Any]:
        role = row["role"]
        return {
            "actorType": "OPERATOR", "actorId": str(row["id"]),
            "displayName": row["display_name"], "role": role,
            "permissions": sorted(ROLE_PERMISSIONS[role]), "tokenId": str(row["token_id"]),
            "tokenLabel": row["token_label"],
        }

    def authenticate(self, token: str | None) -> dict[str, Any]:
        if not token:
            raise ServiceError(401, "missing admin credential")
        if tokens_equal(token, self.settings.admin_token):
            return {
                "actorType": "BOOTSTRAP", "actorId": "bootstrap-admin",
                "displayName": "应急超级管理员", "role": "OWNER",
                "permissions": sorted(ROLE_PERMISSIONS["OWNER"]), "tokenId": None,
                "tokenLabel": "ADMIN_TOKEN",
            }
        with self.uow.transaction() as connection:
            row = AdminAccessRepository(connection).authenticate(hash_token(token))
        if not row:
            raise ServiceError(401, "invalid or expired admin credential")
        return self._principal(row)

    @staticmethod
    def require(principal: dict[str, Any], permission: str) -> dict[str, Any]:
        if permission not in principal["permissions"]:
            raise ServiceError(403, f"permission required: {permission}")
        return principal

    def session(self, principal: dict[str, Any]) -> dict[str, Any]:
        return {**principal, "availableRoles": [
            {"role": role, "permissions": sorted(permissions)}
            for role, permissions in ROLE_PERMISSIONS.items()
        ]}

    @staticmethod
    def _operator_payload(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "operatorId": str(row["id"]), "displayName": row["display_name"],
            "role": row["role"], "status": row["status"],
            "permissions": sorted(ROLE_PERMISSIONS[row["role"]]),
            "activeTokenCount": int(row.get("active_token_count", 0)),
            "lastUsedAt": iso(row.get("last_used_at")),
            "createdAt": iso(row["created_at"]), "updatedAt": iso(row["updated_at"]),
        }

    def list_operators(self) -> dict[str, Any]:
        with self.uow.transaction() as connection:
            rows = AdminAccessRepository(connection).list_operators()
        return {"operators": [self._operator_payload(row) for row in rows]}

    def create_operator(self, display_name: str, role: str) -> dict[str, Any]:
        with self.uow.transaction() as connection:
            row = AdminAccessRepository(connection).create_operator(uuid.uuid4(), display_name, role)
        return self._operator_payload(row)

    def update_operator(
        self, operator_id: uuid.UUID, *, display_name: str | None,
        role: str | None, status: str | None,
    ) -> dict[str, Any]:
        with self.uow.transaction() as connection:
            repository = AdminAccessRepository(connection)
            current = repository.operator(operator_id, for_update=True)
            if not current:
                raise ServiceError(404, "operator not found")
            row = repository.update_operator(
                operator_id, display_name or current["display_name"],
                role or current["role"], status or current["status"],
            )
        return self._operator_payload(row)

    def list_tokens(self, operator_id: uuid.UUID) -> dict[str, Any]:
        with self.uow.transaction() as connection:
            repository = AdminAccessRepository(connection)
            if not repository.operator(operator_id):
                raise ServiceError(404, "operator not found")
            rows = repository.list_tokens(operator_id)
        return {"operatorId": str(operator_id), "tokens": [{
            "tokenId": str(row["id"]), "label": row["label"], "status": row["status"],
            "expiresAt": iso(row["expires_at"]), "lastUsedAt": iso(row["last_used_at"]),
            "createdAt": iso(row["created_at"]), "revokedAt": iso(row["revoked_at"]),
        } for row in rows]}

    def create_token(self, operator_id: uuid.UUID, label: str, expires_at: Any) -> dict[str, Any]:
        if expires_at is not None and expires_at <= utc_now():
            raise ServiceError(422, "expiresAt must be in the future")
        token = secrets.token_urlsafe(36)
        with self.uow.transaction() as connection:
            repository = AdminAccessRepository(connection)
            if not repository.operator(operator_id):
                raise ServiceError(404, "operator not found")
            row = repository.create_token(
                uuid.uuid4(), operator_id, hash_token(token), label, expires_at
            )
        return {
            "tokenId": str(row["id"]), "operatorId": str(operator_id), "label": row["label"],
            "token": token, "expiresAt": iso(row["expires_at"]),
            "warning": "token is returned once and must be stored securely",
        }

    def revoke_token(self, operator_id: uuid.UUID, token_id: uuid.UUID) -> dict[str, Any]:
        with self.uow.transaction() as connection:
            row = AdminAccessRepository(connection).revoke_token(operator_id, token_id)
        if not row:
            raise ServiceError(404, "admin token not found")
        return {"operatorId": str(operator_id), "tokenId": str(token_id), "status": "REVOKED"}

    def audit(
        self, principal: dict[str, Any], action: str, resource_type: str,
        resource_id: str | None, detail: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        with self.uow.transaction() as connection:
            AdminAccessRepository(connection).write_audit(
                principal, action, resource_type, resource_id, detail or {}, request_id
            )

    def audit_logs(
        self, *, limit: int, action: str | None, resource_type: str | None
    ) -> dict[str, Any]:
        with self.uow.transaction() as connection:
            rows = AdminAccessRepository(connection).list_audit(
                limit=limit, action=action, resource_type=resource_type
            )
        return {"auditLogs": [{
            "id": row["id"], "actorType": row["actor_type"], "actorId": row["actor_id"],
            "actorName": row["actor_name"], "action": row["action"],
            "resourceType": row["resource_type"], "resourceId": row["resource_id"],
            "requestId": row["request_id"], "detail": row["detail_json"],
            "createdAt": iso(row["created_at"]),
        } for row in rows]}

    def dashboard(self) -> dict[str, Any]:
        with self.uow.transaction() as connection:
            row = AdminAccessRepository(connection).dashboard_summary()
        orders = int(row["orders_today"])
        ready = int(row["ready_today"])
        return {
            "devices": {
                "total": int(row["devices_total"]), "online": int(row["devices_online"]),
                "restricted": int(row["devices_restricted"]),
            },
            "orders": {
                "today": orders, "readyToday": ready,
                "successRate": round(ready / orders, 4) if orders else None,
                "exceptionsToday": int(row["exceptions_today"]),
            },
            "operations": {
                "manualReviews": int(row["manual_reviews"]),
                "pendingRefunds": int(row["pending_refunds"]),
                "pendingBusinessEvents": int(row["pending_business_events"]),
                "pendingCommands": int(row["pending_commands"]),
            },
        }
