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

    def inbox(self, _device_id: str, _message_id: str):
        return None

    def insert_inbox(self, _values: object) -> bool:
        self.calls.append(("insert_inbox", _values))
        return True

    def processed(self, _device_id: str, _message_id: str) -> None:
        self.calls.append(("processed", _message_id))

    def retry(self, _device_id: str, _message_id: str, _error: str) -> None:
        self.calls.append(("retry", _message_id))


def service(heartbeat, request_dispatch=lambda *_: None, telemetry_cache=None, event=None):
    return MqttGatewayService(
        FakeUnitOfWork(),
        logger=logging.getLogger("test-telemetry-mode"),
        retain_telemetry_history=False,
        heartbeat=heartbeat,
        event=event or (lambda *args, **kwargs: {"ok": True}),
        task_ack=lambda *args, **kwargs: {"ok": True},
        command_result=lambda *args, **kwargs: {"ok": True},
        request_dispatch=request_dispatch,
        telemetry_cache=telemetry_cache,
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


def test_latest_heartbeat_is_coalesced_in_redis_before_database(monkeypatch) -> None:
    monkeypatch.setattr("app.services.mqtt_gateway.MqttGatewayRepository", FakeMqttRepository)
    heartbeat_calls = []

    class FakeTelemetryCache:
        def terminal_id(self, _device_id: str):
            return None

        def remember_terminal(self, _device_id: str, _terminal_id: int) -> None:
            pass

        def heartbeat(self, device_id: str, terminal_id: int, payload: dict[str, object]) -> bool:
            assert (device_id, terminal_id, payload["sequence"]) == ("coffee-bot-001", 7, 3)
            return True

    result = service(
        lambda *args, **kwargs: heartbeat_calls.append((args, kwargs)),
        telemetry_cache=FakeTelemetryCache(),
    ).ingest({
        "topic": "v1/devices/coffee-bot-001/up",
        "envelope": {
            "deviceId": "coffee-bot-001", "type": "heartbeat",
            "payload": {"deviceId": "coffee-bot-001", "deviceStatus": "IDLE", "sequence": 3},
        },
    })

    assert result["telemetryMode"] == "redis-latest"
    assert heartbeat_calls == []


def test_progress_event_is_coalesced_in_redis_before_event_inbox(monkeypatch) -> None:
    monkeypatch.setattr("app.services.mqtt_gateway.MqttGatewayRepository", FakeMqttRepository)

    class FakeTelemetryCache:
        def terminal_id(self, _device_id: str):
            return 7

        def progress(self, device_id: str, terminal_id: int, event: dict[str, object]) -> bool:
            assert (device_id, terminal_id, event["type"]) == ("coffee-bot-001", 7, "task.progress")
            return True

    result = service(
        lambda *args, **kwargs: {"ok": True}, telemetry_cache=FakeTelemetryCache()
    ).ingest({
        "topic": "v1/devices/coffee-bot-001/up",
        "envelope": {
            "deviceId": "coffee-bot-001", "type": "event",
            "payload": {
                "eventId": "progress-1", "deviceId": "coffee-bot-001", "type": "task.progress",
                "payload": {"taskId": "task-1", "overallProgress": 0.5, "stepProgress": 0.2},
            },
        },
    })

    assert result["telemetryMode"] == "redis-progress"


def test_step_lifecycle_event_bypasses_lossy_telemetry_cache(monkeypatch) -> None:
    FakeMqttRepository.calls = []
    monkeypatch.setattr("app.services.mqtt_gateway.MqttGatewayRepository", FakeMqttRepository)
    events = []

    class FakeTelemetryCache:
        def progress(self, *_args: object) -> bool:  # pragma: no cover - lifecycle must bypass this
            raise AssertionError("step lifecycle was incorrectly treated as lossy telemetry")

    result = service(
        lambda *_args, **_kwargs: {"ok": True},
        telemetry_cache=FakeTelemetryCache(),
        event=lambda *args, **kwargs: events.append((args, kwargs)) or {"ok": True},
    ).ingest({
        "topic": "v1/devices/coffee-bot-001/up",
        "envelope": {
            "deviceId": "coffee-bot-001", "type": "event",
            "payload": {
                "eventId": "step-started-1", "deviceId": "coffee-bot-001", "type": "step.started",
                "occurredAt": "2026-08-30T00:00:00Z", "payload": {"taskId": "task-1", "stepId": "brew"},
            },
        },
    })

    assert result["ok"] is True
    assert len(events) == 1
    assert [name for name, _ in FakeMqttRepository.calls] == ["insert_inbox", "processed"]


def test_latest_heartbeat_updates_online_state_without_history(monkeypatch) -> None:
    calls = []
    dispatches = []

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
        request_dispatch=lambda *_args: dispatches.append(_args),
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
    assert dispatches == []
