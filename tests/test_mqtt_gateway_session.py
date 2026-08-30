"""Real-broker MQTT session lifecycle tests for the multi-device gateway (B1.1).

Requires a local plaintext test broker (default 127.0.0.1:51887). The gateway
production client always enables TLS verification; tests neutralise tls_set
locally and never weaken production defaults.
"""
from __future__ import annotations

import importlib
import json
import os
import socket
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

import paho.mqtt.client as mqtt

BROKER_HOST = os.getenv("MQTT_TEST_BROKER_HOST", "127.0.0.1")
BROKER_PORT = int(os.getenv("MQTT_TEST_BROKER_PORT", "51887"))
DEFAULT_GATEWAY_ID = "coffee-mqtt-gateway-v1"


def _broker_available() -> bool:
    try:
        with socket.create_connection((BROKER_HOST, BROKER_PORT), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _broker_available(),
    reason=f"local test broker not running on {BROKER_HOST}:{BROKER_PORT}",
)


@pytest.fixture()
def plaintext_broker(monkeypatch):
    monkeypatch.setattr(mqtt.Client, "tls_set", lambda self, **_kwargs: None)


def make_gateway_module(monkeypatch, tmp_path, gateway_id=None, extra=None):
    monkeypatch.setenv("INTERNAL_GATEWAY_TOKEN", "test-gateway-token")
    monkeypatch.setenv("MQTT_USERNAME", "gateway-test")
    monkeypatch.setenv("MQTT_PASSWORD", "gateway-test")
    monkeypatch.setenv("MQTT_HOST", BROKER_HOST)
    monkeypatch.setenv("MQTT_PORT", str(BROKER_PORT))
    monkeypatch.setenv("GATEWAY_HEALTH_FILE", str(tmp_path / "gateway-health.json"))
    if gateway_id is None:
        monkeypatch.delenv("MQTT_GATEWAY_ID", raising=False)
    else:
        monkeypatch.setenv("MQTT_GATEWAY_ID", gateway_id)
    for key, value in (extra or {}).items():
        monkeypatch.setenv(key, value)
    module = importlib.import_module("app.mqtt_gateway")
    return importlib.reload(module)


class FakeApi:
    """Stands in for GatewayApiClient; records every request."""

    def __init__(self, delay: float = 0.0, fail: bool = False, kill: bool = False) -> None:
        self.delay = delay
        self.fail = fail
        self.kill = kill
        self.lock = threading.Lock()
        self.requests: list[tuple[str, str, dict | None]] = []

    def request(self, method: str, path: str, payload: dict | None = None) -> dict:
        with self.lock:
            self.requests.append((method, path, payload))
        if self.kill and (path.endswith("/mqtt/messages") or path.endswith("/messages/batch")):
            raise KeyboardInterrupt("simulated uplink worker crash")
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise ConnectionError("simulated cloud outage")
        if path.endswith("/messages/batch"):
            messages = (payload or {}).get("messages", [])
            return {"accepted": list(range(len(messages))), "rejected": []}
        if path.endswith("/claim"):
            return {"commands": []}
        return {}

    def close(self) -> None:  # pragma: no cover - trivial
        pass

    def posted_messages(self, message_type: str) -> list[dict]:
        found: list[dict] = []
        with self.lock:
            for _method, path, payload in self.requests:
                if path.endswith("/messages/batch"):
                    for item in (payload or {}).get("messages", []):
                        envelope = item.get("envelope") or {}
                        if envelope.get("type") == message_type:
                            found.append(envelope)
                elif path.endswith("/mqtt/messages"):
                    envelope = (payload or {}).get("envelope") or {}
                    if envelope.get("type") == message_type:
                        found.append(envelope)
        return found


class StubClient:
    """Records protocol actions without any network."""

    def __init__(self) -> None:
        self.acks: list[tuple[int, int]] = []
        self.disconnects = 0
        self.loop_starts = 0
        self.loop_stops = 0
        self.reconnects = 0
        self.lock = threading.Lock()

    def ack(self, mid: int, qos: int) -> None:
        with self.lock:
            self.acks.append((mid, qos))

    def disconnect(self) -> None:
        with self.lock:
            self.disconnects += 1

    def loop_start(self) -> None:
        with self.lock:
            self.loop_starts += 1

    def loop_stop(self) -> None:
        with self.lock:
            self.loop_stops += 1

    def reconnect(self) -> int:
        with self.lock:
            self.reconnects += 1
        return mqtt.MQTT_ERR_SUCCESS

    def reconnect_delay_set(self, *args, **kwargs) -> None:
        pass

    def manual_ack_set(self, *args, **kwargs) -> None:
        pass


class HelperPublisher:
    def __init__(self) -> None:
        self.connected = threading.Event()
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=f"helper-{uuid.uuid4().hex[:8]}", protocol=mqtt.MQTTv5
        )
        self.client.on_connect = lambda *_args: self.connected.set()
        self.client.connect(BROKER_HOST, BROKER_PORT, keepalive=30)
        self.client.loop_start()
        assert self.connected.wait(timeout=10), "helper publisher failed to connect"

    def publish_uplink(self, device_id: str, message_id: str, kind: str = "heartbeat") -> None:
        envelope = {
            "schema": "coffee.mqtt-envelope.v1",
            "messageId": message_id,
            "deviceId": device_id,
            "type": kind,
            "sentAt": "2026-08-30T00:00:00Z",
            "payload": {"deviceId": device_id, "status": "healthy"},
        }
        info = self.client.publish(f"v1/devices/{device_id}/up", json.dumps(envelope), qos=1)
        info.wait_for_publish(timeout=5)
        assert info.is_published(), "helper publish was not acknowledged"

    def close(self) -> None:
        self.client.disconnect()
        self.client.loop_stop()


def wait_until(condition, timeout: float, message: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError(message)


def gateway_threads(prefix: str) -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name.startswith(prefix) and t.is_alive()]


def build_gateway(module, api: FakeApi | None = None):
    gateway = module.Gateway(api_client=api or FakeApi())
    return gateway


def test_default_gateway_id_is_stable_and_matches_client_id(monkeypatch, tmp_path) -> None:
    module = make_gateway_module(monkeypatch, tmp_path)
    first = module.GATEWAY_ID
    module = importlib.reload(module)
    second = module.GATEWAY_ID
    assert first == second == DEFAULT_GATEWAY_ID, "default gateway id must not be random"
    gateway = build_gateway(module)
    assert gateway.client._client_id.decode() == DEFAULT_GATEWAY_ID


def test_offline_qos1_redelivered_after_gateway_rebuild(monkeypatch, tmp_path, plaintext_broker) -> None:
    gateway_id = f"gw-{uuid.uuid4().hex[:8]}"
    module = make_gateway_module(monkeypatch, tmp_path, gateway_id=gateway_id)
    device_id = f"device-{uuid.uuid4().hex[:8]}"

    first_api = FakeApi()
    first = build_gateway(module, first_api)
    first.start()
    try:
        wait_until(lambda: first.connected, timeout=15, message="first gateway never connected")
        helper = HelperPublisher()
        try:
            helper.publish_uplink(device_id, "live-1")
        finally:
            helper.close()
        wait_until(
            lambda: len(first_api.posted_messages("heartbeat")) >= 1,
            timeout=15,
            message="live uplink was not ingested before shutdown",
        )
    finally:
        first.shutdown()

    helper = HelperPublisher()
    try:
        helper.publish_uplink(device_id, "offline-1")
        helper.publish_uplink(device_id, "offline-2")
    finally:
        helper.close()

    second_api = FakeApi()
    second = build_gateway(module, second_api)
    second.start()
    try:
        wait_until(lambda: second.connected, timeout=15, message="rebuilt gateway never connected")

        def received_offline() -> bool:
            ids = {item.get("messageId") for item in second_api.posted_messages("heartbeat")}
            return {"offline-1", "offline-2"} <= ids

        wait_until(received_offline, timeout=20, message="offline QoS1 uplinks were not redelivered")
    finally:
        second.shutdown()


def test_backpressure_disconnect_recovers(monkeypatch, tmp_path, plaintext_broker) -> None:
    gateway_id = f"gw-{uuid.uuid4().hex[:8]}"
    module = make_gateway_module(
        monkeypatch,
        tmp_path,
        gateway_id=gateway_id,
        extra={"MQTT_GATEWAY_WORKERS": "1", "MQTT_GATEWAY_QUEUE_CAPACITY": "100"},
    )
    device_id = f"device-{uuid.uuid4().hex[:8]}"
    api = FakeApi(delay=0.05)
    gateway = build_gateway(module, api)
    gateway.start()
    try:
        wait_until(lambda: gateway.connected, timeout=15, message="gateway never connected")
        helper = HelperPublisher()
        try:
            for index in range(150):
                helper.publish_uplink(device_id, f"command_result-{index}", kind="command_result")
        finally:
            helper.close()
        wait_until(lambda: gateway.connected, timeout=20, message="gateway did not recover after backpressure")
        api.delay = 0.0

        def all_messages_ingested() -> bool:
            ingested = {item.get("messageId") for item in api.posted_messages("command_result")}
            return len(ingested) >= 150

        wait_until(all_messages_ingested, timeout=40, message="backlogged uplinks were not drained after recovery")
    finally:
        gateway.shutdown()


def test_ack_isolation_for_stale_connection_generation(monkeypatch, tmp_path) -> None:
    module = make_gateway_module(monkeypatch, tmp_path)
    gateway = module.Gateway(api_client=FakeApi(), client=StubClient())
    gateway.generation = 5
    stale = SimpleNamespace(qos=1, mid=42)
    current = SimpleNamespace(qos=1, mid=43)

    gateway.ack(stale, 4)
    assert gateway.client.acks == [], "stale generation message must not be ACKed"

    gateway.ack(current, 5)
    assert gateway.client.acks == [(43, 1)]


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_worker_death_fails_health_and_signals_exit(monkeypatch, tmp_path, plaintext_broker) -> None:
    gateway_id = f"gw-{uuid.uuid4().hex[:8]}"
    module = make_gateway_module(
        monkeypatch,
        tmp_path,
        gateway_id=gateway_id,
        extra={"MQTT_GATEWAY_WORKERS": "1", "MQTT_GATEWAY_QUEUE_CAPACITY": "100"},
    )
    device_id = f"device-{uuid.uuid4().hex[:8]}"
    api = FakeApi(kill=True)
    gateway = build_gateway(module, api)
    gateway.start()
    try:
        wait_until(lambda: gateway.connected, timeout=15, message="gateway never connected")
        helper = HelperPublisher()
        try:
            helper.publish_uplink(device_id, "trigger-crash", kind="command_result")
        finally:
            helper.close()
        wait_until(
            lambda: not all(thread.is_alive() for thread in gateway.worker_threads),
            timeout=15,
            message="worker thread did not die from injected crash",
        )
        assert gateway.monitor_once() == 1, "dead worker must produce a failing exit code"
        health = json.loads(Path(os.environ["GATEWAY_HEALTH_FILE"]).read_text(encoding="utf-8"))
        assert health["workersAlive"] is False
    finally:
        gateway.shutdown()


def test_shutdown_is_idempotent_and_stops_all_threads(monkeypatch, tmp_path, plaintext_broker) -> None:
    gateway_id = f"gw-{uuid.uuid4().hex[:8]}"
    module = make_gateway_module(monkeypatch, tmp_path, gateway_id=gateway_id)
    gateway = build_gateway(module, FakeApi())
    gateway.start()
    wait_until(lambda: gateway.connected, timeout=15, message="gateway never connected")

    gateway.shutdown()
    gateway.shutdown()

    wait_until(
        lambda: not gateway_threads(f"paho-mqtt-client-{gateway_id}")
        and not gateway_threads(f"mqtt-gateway-supervisor-{gateway_id}"),
        timeout=5,
        message="network or supervisor threads still alive after shutdown",
    )
    time.sleep(0.5)
    assert not gateway_threads(f"paho-mqtt-client-{gateway_id}"), "gateway reconnected after shutdown"
