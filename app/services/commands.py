from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, Callable

from ..command_state import CREATED, DELIVERING, PUBLISHED
from ..db import UnitOfWork
from ..protocol import canonical_digest, utc_now
from ..repositories import CommandRepository, TerminalRepository
from .errors import ServiceError
from .presenters import iso


class CommandService:
    def __init__(
        self, uow: UnitOfWork, *, lease_seconds: int,
        transition_command: Callable[..., tuple[dict[str, Any], bool]],
    ) -> None:
        self.uow = uow
        self.lease_seconds = lease_seconds
        self.transition_command = transition_command

    @staticmethod
    def _enqueue_outbox(connection: Any, command: dict[str, Any], terminal: dict[str, Any]) -> None:
        envelope = {
            "schema": "coffee.mqtt-envelope.v1", "messageId": command["message_id"],
            "deviceId": terminal["device_id"], "type": "command", "sentAt": iso(utc_now()),
            "payload": command["payload_json"],
        }
        CommandRepository(connection).insert_outbox(
            command["id"], terminal["id"], f"v1/devices/{terminal['device_id']}/down", envelope
        )

    @staticmethod
    def payload(row: dict[str, Any], transitions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        result = {
            "messageId": row["message_id"], "deviceId": row.get("device_id"),
            "type": row["command_type"], "status": row["status"], "revision": row["revision"],
            "command": row["payload_json"], "result": row["result_json"],
            "createdAt": iso(row["created_at"]), "deliveredAt": iso(row["delivered_at"]),
            "ackedAt": iso(row["acked_at"]), "executingAt": iso(row["executing_at"]),
            "completedAt": iso(row["completed_at"]), "expiresAt": iso(row["expires_at"]),
        }
        if transitions is not None:
            result["transitions"] = [{
                "revision": item["revision"], "from": item["from_status"], "to": item["to_status"],
                "actor": item["actor"], "reason": item["reason"], "createdAt": iso(item["created_at"]),
                "payload": item["payload_json"],
            } for item in transitions]
        return result

    def claim(self, gateway_id: str, limit: int) -> dict[str, Any]:
        with self.uow.transaction() as connection:
            rows = CommandRepository(connection).claim(gateway_id, limit, self.lease_seconds)
        return {"commands": [{
            "outboxId": str(row["id"]), "topic": row["topic"],
            "envelope": row["envelope_json"], "attempt": row["attempt_count"],
        } for row in rows]}

    def published(self, outbox_id: uuid.UUID, gateway_id: str) -> dict[str, Any]:
        with self.uow.transaction() as connection:
            repository = CommandRepository(connection)
            located = repository.find_outbox(outbox_id)
            if not located:
                raise ServiceError(404, "command outbox item not found")
            # Publish confirmation locks command -> outbox: the unlocked locate
            # above only finds the owning command row, which is locked first.
            command = (
                repository.by_db_id(located["command_id"])
                if located["command_id"] is not None else None
            )
            outbox = repository.outbox(outbox_id)
            if outbox["status"] == "PUBLISHED":
                return {"ok": True, "duplicate": True}
            if outbox["status"] == "EXPIRED":
                # Late confirmation after expiry terminalized the outbox:
                # record the delivery evidence but never revive command/order.
                if command is not None:
                    repository.set_published_at(command["id"])
                return {"ok": True, "duplicate": True, "late": True}
            if outbox["status"] != "PUBLISHING" or outbox["locked_by"] != gateway_id:
                raise ServiceError(409, "command publish lease mismatch")
            repository.mark_published(outbox_id)
            command = repository.by_db_id(outbox["command_id"])
            if command and command["status"] in {CREATED, DELIVERING}:
                command, _ = self.transition_command(
                    connection, command, PUBLISHED, "mqtt-gateway", reason="broker PUBACK"
                )
            if command:
                repository.set_published_at(command["id"])
        return {"ok": True, "duplicate": False}

    def retry(self, outbox_id: uuid.UUID, gateway_id: str, error: str) -> dict[str, Any]:
        with self.uow.transaction() as connection:
            repository = CommandRepository(connection)
            if not repository.find_outbox(outbox_id):
                raise ServiceError(404, "command outbox item not found")
            row = repository.outbox(outbox_id)
            if row["status"] == "PUBLISHED":
                return {"ok": True, "duplicate": True}
            if row["locked_by"] != gateway_id:
                raise ServiceError(409, "command publish lease mismatch")
            repository.mark_retry(outbox_id, error[:1000])
        return {"ok": True, "duplicate": False}

    def create_raw(self, identity: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        with self.uow.transaction() as connection:
            repository = CommandRepository(connection)
            row = repository.insert(
                terminal_id=identity["id"], message_id=payload["messageId"],
                command_type=payload["type"], payload=payload, digest=canonical_digest(payload),
                expires_at=payload.get("expiresAt"),
            )
            repository.insert_initial_transition(row["id"], "debug-api", "legacy debug command", payload)
            self._enqueue_outbox(connection, row, identity)
        return payload

    def create_debug_order(self, identity: dict[str, Any], recipe_id: str | None) -> dict[str, Any]:
        debug_order_no = f"C{utc_now().strftime('%m%d')}-{secrets.token_hex(3).upper()}"
        command = {
            "messageId": f"cmd-{uuid.uuid4()}", "type": "MAKE_DRINK",
            "taskId": f"task-{uuid.uuid4()}", "orderId": f"debug-{uuid.uuid4()}",
            "orderNo": debug_order_no,
            "recipeId": recipe_id, "expiresAt": iso(utc_now() + timedelta(minutes=5)),
        }
        self.create_raw(identity, command)
        return {"ok": True, "command": command}

    def create_debug_command(self, identity: dict[str, Any], action: str | None) -> dict[str, Any]:
        command = {"messageId": f"cmd-{uuid.uuid4()}", "type": "DEBUG_COMMAND", "action": action}
        self.create_raw(identity, command)
        return {"ok": True, "command": command}

    @staticmethod
    def debug_overrides(identity: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "deviceId": identity["device_id"], "overrides": body}

    def create_admin(self, identifier: str, payload: Any, key: str | None) -> dict[str, Any]:
        if not key or len(key) > 160:
            raise ServiceError(400, "Idempotency-Key is required and must be <= 160 characters")
        if payload.type == "MAKE_DRINK" and not all((payload.taskId, payload.orderId, payload.recipeId)):
            raise ServiceError(422, "MAKE_DRINK requires taskId, orderId and recipeId")
        expires_at = payload.expiresAt or (utc_now() + timedelta(minutes=5))
        if expires_at <= utc_now():
            raise ServiceError(422, "expiresAt must be in the future")
        request_body = payload.model_dump(mode="json", exclude_none=True)
        digest = canonical_digest(request_body)
        with self.uow.transaction() as connection:
            terminal = TerminalRepository(connection).find(identifier, for_update=True)
            if not terminal:
                raise ServiceError(404, "device not found")
            repository = CommandRepository(connection)
            existing = repository.by_idempotency(terminal["id"], key)
            if existing:
                if (existing["payload_digest"] or "").strip() != digest:
                    raise ServiceError(409, "Idempotency-Key payload conflict")
                return {"duplicate": True, **self.payload(existing)}
            message_id = f"cmd-{uuid.uuid4()}"
            command = {**payload.payload, "messageId": message_id, "type": payload.type, "expiresAt": iso(expires_at)}
            for name, value in {
                "taskId": payload.taskId, "orderId": payload.orderId, "recipeId": payload.recipeId,
                "recipeVersion": payload.recipeVersion, "action": payload.action,
            }.items():
                if value is not None:
                    command[name] = value
            row = repository.insert(
                terminal_id=terminal["id"], message_id=message_id, command_type=payload.type,
                payload=command, digest=digest, expires_at=expires_at, idempotency_key=key,
            )
            repository.insert_initial_transition(row["id"], "admin-api", "command created", command)
            self._enqueue_outbox(connection, row, terminal)
        return {"duplicate": False, **self.payload(row)}

    def get_admin(self, identifier: str, message_id: str) -> dict[str, Any]:
        with self.uow.transaction() as connection:
            terminal = TerminalRepository(connection).find(identifier)
            if not terminal:
                raise ServiceError(404, "device not found")
            repository = CommandRepository(connection)
            row = repository.find(terminal["id"], message_id)
            if not row:
                raise ServiceError(404, "command not found")
            transitions = repository.transitions(row["id"])
        return self.payload(row, transitions)
