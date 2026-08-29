from __future__ import annotations

import uuid
from typing import Any, Callable

from psycopg.errors import UniqueViolation

from ..command_state import ACKED, CREATED, DELIVERING, EXECUTING, EXPIRED, PUBLISHED, TERMINAL_STATES, result_state
from ..db import UnitOfWork
from ..protocol import CommandResult, DeviceEvent, Heartbeat, canonical_digest, utc_now
from ..repositories import DeviceMessageRepository
from .errors import ServiceError
from .presenters import iso


class DeviceMessageService:
    def __init__(
        self,
        uow: UnitOfWork,
        *,
        request_dispatch: Callable[[Any, int, str], None],
        transition_command: Callable[..., tuple[dict[str, Any], bool]],
        expire_order_for_command: Callable[[Any, dict[str, Any]], None],
        reconcile_command_event: Callable[[Any, int, dict[str, Any], str], dict[str, Any] | None],
        reconcile_order_event: Callable[[Any, int, dict[str, Any], str], dict[str, Any] | None],
        reconcile_order_ack: Callable[[Any, int, str, dict[str, Any]], dict[str, Any] | None],
        order_url: Callable[[str], str],
    ) -> None:
        self.uow = uow
        self.request_dispatch = request_dispatch
        self.transition_command = transition_command
        self.expire_order_for_command = expire_order_for_command
        self.reconcile_command_event = reconcile_command_event
        self.reconcile_order_event = reconcile_order_event
        self.reconcile_order_ack = reconcile_order_ack
        self.order_url = order_url

    def heartbeat(
        self,
        device_id: str,
        payload: Heartbeat,
        identity: dict[str, Any],
        *,
        persist_history: bool = False,
    ) -> dict[str, Any]:
        if payload.deviceId != device_id:
            raise ServiceError(400, "payload deviceId mismatch")
        body = payload.model_dump(mode="json", exclude_none=True)
        digest = canonical_digest(body)
        message_id = payload.messageId or f"legacy:{digest}"
        received_at = utc_now()
        disposition = "ACCEPTED"
        with self.uow.transaction() as connection:
            messages = DeviceMessageRepository(connection)
            existing = messages.heartbeat(identity["id"], message_id) if persist_history else None
            if existing:
                if existing["payload_digest"].strip() != digest:
                    raise ServiceError(409, "messageId payload conflict")
                messages.touch_online(identity["id"], received_at)
                if identity.get("connection_status") != "online":
                    self.request_dispatch(connection, identity["id"], "heartbeat-online")
                return {
                    "ok": True, "duplicate": True, "disposition": existing["disposition"],
                    "receivedAt": iso(received_at), "qrUrl": self.order_url(identity["device_id"]),
                }
            current_boot = identity.get("active_boot_id")
            last_sequence = identity.get("last_sequence")
            out_of_order = bool(
                payload.bootId and current_boot == payload.bootId and payload.sequence is not None
                and last_sequence is not None and payload.sequence <= last_sequence
            )
            was_offline = identity.get("connection_status") != "online"
            if out_of_order:
                disposition = "OUT_OF_ORDER"
            if persist_history:
                try:
                    messages.insert_heartbeat(
                        terminal_id=identity["id"], message_id=message_id, digest=digest, body=body,
                        boot_id=payload.bootId, sequence=payload.sequence, occurred_at=payload.sentAt,
                        received_at=received_at, disposition=disposition,
                    )
                except UniqueViolation as exc:
                    raise ServiceError(409, "bootId/sequence conflict") from exc
            connected_at = identity.get("last_connected_at") or received_at
            if identity.get("connection_status") != "online" or current_boot != payload.bootId:
                connected_at = received_at
            if out_of_order:
                messages.touch_online(identity["id"], received_at, connected_at)
            else:
                messages.update_from_heartbeat(
                    terminal_id=identity["id"], received_at=received_at, connected_at=connected_at,
                    body=body, boot_id=payload.bootId, sequence=payload.sequence,
                    reported_status={
                        "deviceStatus": payload.deviceStatus,
                        "currentTaskId": body.get("currentTaskId"),
                        "currentTaskState": body.get("currentTaskState"),
                        "currentTaskRevision": body.get("currentTaskRevision"),
                        "deliveries": body.get("deliveries"), "sentAt": body.get("sentAt"),
                    },
                )
            if was_offline:
                self.request_dispatch(connection, identity["id"], "heartbeat-online")
        return {
            "ok": True, "duplicate": False, "disposition": disposition,
            "receivedAt": iso(received_at), "qrUrl": self.order_url(identity["device_id"]),
        }

    def commands(self, identity: dict[str, Any], after: str, limit: int) -> dict[str, Any]:
        try:
            cursor = int(after) if after else 0
        except ValueError:
            cursor = 0
        with self.uow.transaction() as connection:
            rows = DeviceMessageRepository(connection).commands_after(identity["id"], cursor, limit)
            deliverable: list[dict[str, Any]] = []
            for row in rows:
                cursor = row["id"]
                if row["expires_at"] and row["expires_at"] <= utc_now() and row["status"] not in TERMINAL_STATES:
                    updated, _ = self.transition_command(
                        connection, row, EXPIRED, "cloud", reason="command expired before delivery"
                    )
                    self.expire_order_for_command(connection, updated)
                    continue
                if row["status"] == CREATED:
                    row, _ = self.transition_command(
                        connection, row, DELIVERING, "cloud", reason="device polled command"
                    )
                if row["status"] in {DELIVERING, PUBLISHED}:
                    deliverable.append(row["payload_json"])
        return {"commands": deliverable, "nextCursor": str(cursor)}

    def snapshot(
        self, identity: dict[str, Any], snapshot_type: str, payload: dict[str, Any], version: str | None
    ) -> dict[str, Any]:
        if payload.get("deviceId") != identity["device_id"]:
            raise ServiceError(400, "payload deviceId mismatch")
        with self.uow.transaction() as connection:
            DeviceMessageRepository(connection).upsert_snapshot(
                identity["id"], snapshot_type, version, payload
            )
        return {"ok": True, "receivedAt": iso(utc_now())}

    def event(self, device_id: str, payload: DeviceEvent, identity: dict[str, Any]) -> dict[str, Any]:
        if payload.deviceId != device_id:
            raise ServiceError(400, "payload deviceId mismatch")
        body = payload.model_dump(mode="json")
        digest = canonical_digest(body)
        with self.uow.transaction() as connection:
            messages = DeviceMessageRepository(connection)
            existing = messages.event(identity["id"], payload.eventId)
            if existing:
                if existing["payload_digest"].strip() != digest:
                    raise ServiceError(409, "eventId payload conflict")
                command_transition = self.reconcile_command_event(
                    connection, identity["id"], body, payload.type
                )
                return {
                    "ok": True, "duplicate": True, "commandTransition": command_transition,
                    "orderTransition": {"duplicate": True},
                }
            messages.insert_event(
                terminal_id=identity["id"], event_id=payload.eventId,
                boot_id=payload.bootId, sequence=payload.sequence, event_type=payload.type,
                occurred_at=payload.occurredAt, digest=digest, body=body,
            )
            command_transition = self.reconcile_command_event(
                connection, identity["id"], body, payload.type
            )
            order_transition = self.reconcile_order_event(
                connection, identity["id"], body, payload.type
            )
        return {
            "ok": True, "duplicate": False, "commandTransition": command_transition,
            "orderTransition": order_transition,
        }

    def task_ack(self, identity: dict[str, Any], task_id: str, body: dict[str, Any]) -> dict[str, Any]:
        with self.uow.transaction() as connection:
            command = DeviceMessageRepository(connection).command(
                identity["id"], str(body.get("messageId") or ""), for_update=True
            )
            if command is None or command["payload_json"].get("taskId") != task_id:
                raise ServiceError(404, "task command not found")
            target = ACKED if body.get("accepted") else "REJECTED"
            if target == ACKED and command["status"] in {ACKED, EXECUTING, *TERMINAL_STATES}:
                return {
                    "ok": True, "duplicate": True, "stale": command["status"] != ACKED,
                    "taskId": task_id, "deviceId": identity["device_id"],
                    "commandStatus": command["status"], "revision": command["revision"],
                }
            updated, duplicate = self.transition_command(
                connection, command, target, "device-ack",
                reason=body.get("reason") or body.get("reasonCode"), payload=body,
            )
            self.reconcile_order_ack(connection, identity["id"], task_id, body)
        return {
            "ok": True, "duplicate": duplicate, "stale": False,
            "taskId": task_id, "deviceId": identity["device_id"],
            "commandStatus": updated["status"], "revision": updated["revision"],
        }

    def command_result(
        self, identity: dict[str, Any], message_id: str, payload: CommandResult
    ) -> dict[str, Any]:
        body = payload.model_dump(mode="json")
        target = result_state(payload.status)
        with self.uow.transaction() as connection:
            command = DeviceMessageRepository(connection).command(
                identity["id"], message_id, for_update=True
            )
            if command is None:
                raise ServiceError(404, "command not found")
            updated, duplicate = self.transition_command(
                connection, command, target, "device-result", reason=payload.status, payload=body
            )
        return {
            "ok": True, "duplicate": duplicate,
            "status": updated["status"], "revision": updated["revision"],
        }
