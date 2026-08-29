from __future__ import annotations

import logging
from typing import Any, Callable

from ..db import UnitOfWork
from ..protocol import CommandResult, DeviceEvent, Heartbeat, canonical_digest
from ..repositories import MqttGatewayRepository
from ..telemetry import TelemetryCache
from .errors import ServiceError


class MqttGatewayService:
    def __init__(
        self, uow: UnitOfWork, *, logger: logging.Logger,
        retain_telemetry_history: bool = False,
        heartbeat: Callable[..., dict[str, Any]], event: Callable[..., dict[str, Any]],
        task_ack: Callable[..., dict[str, Any]], command_result: Callable[..., dict[str, Any]],
        request_dispatch: Callable[[Any, int, str], None],
        telemetry_cache: TelemetryCache | None = None,
    ) -> None:
        self.uow = uow
        self.logger = logger
        self.retain_telemetry_history = retain_telemetry_history
        self.heartbeat = heartbeat
        self.event = event
        self.task_ack = task_ack
        self.command_result = command_result
        self.request_dispatch = request_dispatch
        self.telemetry_cache = telemetry_cache

    def _terminal_for_telemetry(self, device_id: str) -> dict[str, Any] | None:
        if self.telemetry_cache:
            terminal_id = self.telemetry_cache.terminal_id(device_id)
            if terminal_id is not None:
                return {"id": terminal_id, "device_id": device_id}
        with self.uow.transaction() as connection:
            terminal = MqttGatewayRepository(connection).terminal(device_id)
        if terminal and self.telemetry_cache:
            self.telemetry_cache.remember_terminal(device_id, terminal["id"])
        return terminal

    def ingest(self, body: dict[str, Any]) -> dict[str, Any]:
        topic = str(body.get("topic") or "")
        envelope = body.get("envelope")
        parts = topic.split("/")
        if len(parts) != 4 or parts[:2] != ["v1", "devices"] or parts[3] not in {"up", "state", "presence"}:
            raise ServiceError(422, "invalid MQTT uplink topic")
        device_id = parts[2]
        if not isinstance(envelope, dict):
            raise ServiceError(422, "MQTT payload must be a JSON object")
        payload = envelope.get("payload") if parts[3] == "up" else envelope
        if not isinstance(payload, dict):
            raise ServiceError(422, "MQTT payload must be a JSON object")
        envelope_device = envelope.get("deviceId")
        payload_device = payload.get("deviceId")
        if envelope_device not in {None, device_id} or payload_device != device_id:
            detail = {"topic": topic, "envelopeDeviceId": envelope_device, "payloadDeviceId": payload_device}
            self.logger.warning("MQTT identity mismatch %s", detail)
            with self.uow.transaction() as connection:
                MqttGatewayRepository(connection).security_event(device_id, detail)
            raise ServiceError(403, "MQTT device identity mismatch")
        message_type = str(envelope.get("type") or parts[3])
        is_telemetry = parts[3] in {"presence", "state"} or message_type == "heartbeat"
        message_id = str(
            envelope.get("messageId") or payload.get("eventId") or payload.get("messageId")
            or f"{parts[3]}:{canonical_digest(payload)}"
        )
        digest = canonical_digest(envelope)
        nested = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        revision = nested.get("taskRevision") or payload.get("revision")
        lossy_progress_event = message_type == "event" and str(payload.get("type") or "") in {
            "task.progress",
        }
        if lossy_progress_event and self.telemetry_cache:
            terminal = self._terminal_for_telemetry(device_id)
            if not terminal:
                raise ServiceError(404, "device not registered")
            if self.telemetry_cache.progress(device_id, terminal["id"], payload):
                return {"ok": True, "duplicate": False, "telemetryMode": "redis-progress"}
        if is_telemetry and not self.retain_telemetry_history:
            terminal = self._terminal_for_telemetry(device_id)
            if not terminal:
                raise ServiceError(404, "device not registered")
            if parts[3] == "presence":
                if self.telemetry_cache:
                    cached, was_online = self.telemetry_cache.presence(
                        device_id, terminal["id"], bool(payload.get("online"))
                    )
                    if cached:
                        if bool(payload.get("online")) and not was_online:
                            with self.uow.transaction() as connection:
                                self.request_dispatch(connection, terminal["id"], "mqtt-presence-online")
                        return {"ok": True, "duplicate": False, "telemetryMode": "redis-latest"}
                with self.uow.transaction() as connection:
                    repository = MqttGatewayRepository(connection)
                    repository.presence(terminal["id"], bool(payload.get("online")))
                    if bool(payload.get("online")) and terminal.get("connection_status") != "online":
                        self.request_dispatch(connection, terminal["id"], "mqtt-presence-online")
                return {"ok": True, "duplicate": False, "telemetryMode": "latest"}
            if parts[3] == "state":
                if self.telemetry_cache and self.telemetry_cache.state(device_id, terminal["id"], payload):
                    return {"ok": True, "duplicate": False, "telemetryMode": "redis-latest"}
                with self.uow.transaction() as connection:
                    repository = MqttGatewayRepository(connection)
                    repository.state(terminal["id"], payload)
                return {"ok": True, "duplicate": False, "telemetryMode": "latest"}
            if self.telemetry_cache and self.telemetry_cache.heartbeat(device_id, terminal["id"], payload):
                return {"ok": True, "duplicate": False, "telemetryMode": "redis-latest"}
            result = self.heartbeat(device_id, Heartbeat.model_validate(payload), terminal, persist_history=False)
            return {"ok": True, "duplicate": False, "telemetryMode": "latest", "result": result}
        with self.uow.transaction() as connection:
            repository = MqttGatewayRepository(connection)
            terminal = repository.terminal(device_id)
            if not terminal:
                raise ServiceError(404, "device not registered")
            existing = repository.inbox(device_id, message_id)
            if existing and existing["payload_digest"].strip() != digest:
                raise ServiceError(409, "MQTT messageId payload conflict")
            if existing and existing["status"] == "PROCESSED":
                return {"ok": True, "duplicate": True, "disposition": existing["disposition"]}
            if not existing and not repository.insert_inbox((
                device_id, topic, message_id, message_type, payload.get("bootId"),
                payload.get("sequence"), revision, digest, envelope,
            )):
                return {"ok": True, "duplicate": True, "disposition": "DUPLICATE_SEQUENCE"}
        try:
            if parts[3] == "presence":
                with self.uow.transaction() as connection:
                    MqttGatewayRepository(connection).presence(terminal["id"], bool(payload.get("online")))
                    if bool(payload.get("online")) and terminal.get("connection_status") != "online":
                        self.request_dispatch(connection, terminal["id"], "mqtt-presence-online")
                result = {"ok": True}
            elif parts[3] == "state":
                with self.uow.transaction() as connection:
                    MqttGatewayRepository(connection).state(terminal["id"], payload)
                result = {"ok": True}
            elif message_type == "heartbeat":
                result = self.heartbeat(
                    device_id, Heartbeat.model_validate(payload), terminal,
                    persist_history=self.retain_telemetry_history,
                )
            elif message_type == "event":
                result = self.event(device_id, DeviceEvent.model_validate(payload), terminal)
            elif message_type == "command_result":
                if payload.get("commandType") == "MAKE_DRINK":
                    result = self.task_ack(terminal, str(payload.get("taskId") or ""), payload)
                else:
                    result = self.command_result(
                        terminal, str(payload.get("messageId") or ""), CommandResult.model_validate(payload)
                    )
            else:
                raise ServiceError(422, "unsupported MQTT envelope type")
        except Exception as exc:
            with self.uow.transaction() as connection:
                MqttGatewayRepository(connection).retry(device_id, message_id, str(exc))
            raise
        with self.uow.transaction() as connection:
            MqttGatewayRepository(connection).processed(device_id, message_id)
        return {"ok": True, "duplicate": False, "result": result}
