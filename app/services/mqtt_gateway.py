from __future__ import annotations

import logging
from typing import Any, Callable

from ..db import UnitOfWork
from ..protocol import CommandResult, DeviceEvent, Heartbeat, canonical_digest
from ..repositories import MqttGatewayRepository
from .errors import ServiceError


class MqttGatewayService:
    def __init__(
        self, uow: UnitOfWork, *, logger: logging.Logger,
        heartbeat: Callable[..., dict[str, Any]], event: Callable[..., dict[str, Any]],
        task_ack: Callable[..., dict[str, Any]], command_result: Callable[..., dict[str, Any]],
    ) -> None:
        self.uow = uow
        self.logger = logger
        self.heartbeat = heartbeat
        self.event = event
        self.task_ack = task_ack
        self.command_result = command_result

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
        message_id = str(
            envelope.get("messageId") or payload.get("eventId") or payload.get("messageId")
            or f"{parts[3]}:{canonical_digest(payload)}"
        )
        digest = canonical_digest(envelope)
        nested = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        revision = nested.get("taskRevision") or payload.get("revision")
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
                result = {"ok": True}
            elif parts[3] == "state":
                with self.uow.transaction() as connection:
                    MqttGatewayRepository(connection).state(terminal["id"], payload)
                result = {"ok": True}
            elif message_type == "heartbeat":
                result = self.heartbeat(device_id, Heartbeat.model_validate(payload), terminal)
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
