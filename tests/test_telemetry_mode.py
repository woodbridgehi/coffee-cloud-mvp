from contextlib import contextmanager
from datetime import datetime, timezone
import logging

from app.protocol import Heartbeat
from app.services.device_messages import DeviceMessageService
from app.services.mqtt_gateway import MqttGatewayService


class FakeUnitOfWork:
    @contextmanager
    def transaction(self):
        yield object()


class FakeMqttRepository:
    calls: list[tuple[str, object]] = []

    def __init__(self, _: object) -> None:
        pass

    def terminal(self, device_id: str) -> dict[str, object]:
        return {"id": 7, "device_id": device_id}

    def presence(self, terminal_id: int, online: bool) -> None:
        self.calls.append(("presence", (terminal_id, online)))

    def state(self, terminal_id: int, payload: dict[str, object]) -> None:
        self.calls.append(("state", (terminal_id, payload)))


def service(heartbeat):
    return MqttGatewayService(
        FakeUnitOfWork(),
        logger=logging.getLogger("test-telemetry-mode"),
        retain_telemetry_history=False,
        heartbeat=heartbeat,
        event=lambda *args, **kwargs: {"ok": True},
        task_ack=lambda *args, **kwargs: {"ok": True},
        command_result=lambda *args, **kwargs: {"ok": True},
    )


def test_latest_presence_and_state_skip_history_inbox(monkeypatch) -> None:
    FakeMqttRepository.calls = []
    monkeypatch.setattr("app.services.mqtt_gateway.MqttGatewayRepository", FakeMqttRepository)
    gateway = service(lambda *args, **kwargs: {"ok": True})

    presence = gateway.ingest({
        "topic": "v1/devices/coffee-bot-001/presence",
        "envelope": {"deviceId": "coffee-bot-001", "online": True},
    })
    state = gateway.ingest({
        "topic": "v1/devices/coffee-bot-001/state",
        "envelope": {"deviceId": "coffee-bot-001", "deviceStatus": "IDLE"},
    })

    assert presence["telemetryMode"] == "latest"
    assert state["telemetryMode"] == "latest"
    assert [name for name, _ in FakeMqttRepository.calls] == ["presence", "state"]


def test_latest_heartbeat_delegates_without_history(monkeypatch) -> None:
    monkeypatch.setattr("app.services.mqtt_gateway.MqttGatewayRepository", FakeMqttRepository)
    heartbeat_calls = []

    def heartbeat(*args, **kwargs):
        heartbeat_calls.append((args, kwargs))
        return {"ok": True}

    result = service(heartbeat).ingest({
        "topic": "v1/devices/coffee-bot-001/up",
        "envelope": {
            "deviceId": "coffee-bot-001",
            "type": "heartbeat",
            "payload": {"deviceId": "coffee-bot-001", "deviceStatus": "IDLE", "sequence": 3},
        },
    })

    assert result["telemetryMode"] == "latest"
    assert heartbeat_calls[0][1] == {"persist_history": False}


def test_latest_heartbeat_updates_online_state_without_history(monkeypatch) -> None:
    calls = []

    class FakeDeviceMessageRepository:
        def __init__(self, _: object) -> None:
            pass

        def heartbeat(self, *_: object):  # pragma: no cover - latest mode must not call this
            raise AssertionError("latest heartbeat unexpectedly queried heartbeat history")

        def touch_online(self, *args: object) -> None:
            calls.append(args)

    class FakeDeviceUnitOfWork:
        @contextmanager
        def transaction(self):
            yield object()

    monkeypatch.setattr("app.services.device_messages.DeviceMessageRepository", FakeDeviceMessageRepository)
    service = DeviceMessageService(
        FakeDeviceUnitOfWork(),
        dispatch_next_order=lambda *_: None,
        transition_command=lambda *_args, **_kwargs: ({}, False),
        expire_order_for_command=lambda *_: None,
        reconcile_command_event=lambda *_: None,
        reconcile_order_event=lambda *_: None,
        reconcile_order_ack=lambda *_: None,
        order_url=lambda device_id: f"https://example.test/{device_id}",
    )

    service.heartbeat(
        "coffee-bot-001",
        Heartbeat(deviceId="coffee-bot-001", bootId="boot-1", sequence=3),
        {
            "id": 7,
            "device_id": "coffee-bot-001",
            "active_boot_id": "boot-1",
            "last_sequence": 3,
            "connection_status": "online",
            "last_connected_at": datetime.now(timezone.utc),
        },
        persist_history=False,
    )

    assert len(calls) == 1
