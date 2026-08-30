"""Offline regression probes using real Paho methods (no Broker required)."""

import socket
import json
import subprocess
import sys
import threading
from types import SimpleNamespace

import paho.mqtt.client as mqtt
import pytest

from test_mqtt_gateway_session import FakeApi, make_gateway_module


@pytest.fixture
def gateway(monkeypatch, tmp_path):
    module = make_gateway_module(monkeypatch, tmp_path)
    monkeypatch.setattr(mqtt.Client, "tls_set", lambda *a, **k: None)
    return module.Gateway(api_client=FakeApi())


def test_ack_write_error_can_reenter_disconnect_without_deadlock(gateway):
    client = gateway.client
    left, right = socket.socketpair()
    client._sock = left
    gateway._generation = 5
    gateway._connection_valid = True

    def fail_send(data):
        raise OSError("injected write failure")

    client._sock_send = fail_send
    worker = threading.Thread(
        target=lambda: gateway.ack(SimpleNamespace(mid=42, qos=1), 5), daemon=True
    )
    try:
        worker.start()
        worker.join(1)
        assert not worker.is_alive(), "ACK reentered on_disconnect and deadlocked"
        assert not gateway._connection_valid
    finally:
        left.close()
        right.close()


@pytest.mark.parametrize("supervised", [False, True])
def test_reconnect_revokes_ack_before_new_socket_and_connack(
    gateway, monkeypatch, supervised
):
    client = gateway.client
    client.connect_async("127.0.0.1", 1883, clean_start=False)
    gateway._generation = 5
    gateway._connection_valid = True
    gateway._connected.set()
    left, right = socket.socketpair()
    right.settimeout(1)
    observed = []

    def create_socket():
        observed.append(gateway._connection_valid)
        return left

    monkeypatch.setattr(client, "_create_socket", create_socket)
    monkeypatch.setattr(client, "loop_start", lambda: None)
    try:
        if supervised:
            gateway._recover_once()
        else:
            client.reconnect()  # same method Paho's automatic retry calls
        gateway.ack(SimpleNamespace(mid=42, qos=1), 5)
        wire = right.recv(4096)
        assert observed == [False]
        assert b"\x40\x02\x00\x2a" not in wire, "old PUBACK leaked onto new socket"
        assert not gateway.connected
    finally:
        client.disconnect()
        left.close()
        right.close()


def connect_without_network(gateway, monkeypatch):
    mids = iter(range(1, 30))
    monkeypatch.setattr(gateway.client, "subscribe", lambda *a, **k: (0, next(mids)))
    monkeypatch.setattr(gateway.client, "disconnect", lambda: None)
    return lambda: gateway.on_connect(
        gateway.client,
        None,
        SimpleNamespace(session_present=True),
        SimpleNamespace(is_failure=False),
        None,
    )


def test_denied_suback_never_sets_ready(gateway, monkeypatch):
    connect_without_network(gateway, monkeypatch)()
    assert not gateway.connected, "production readiness must wait for subscriptions"
    for mid in (1, 2, 3):
        gateway._on_subscribe(
            gateway.client,
            None,
            mid,
            [mqtt.ReasonCode(mqtt.PacketTypes.SUBACK, identifier=128)],
            None,
        )
    assert not gateway.wait_subscribed(0)
    assert not gateway.connected


def test_pending_subscriptions_do_not_cross_connections(gateway, monkeypatch):
    connect = connect_without_network(gateway, monkeypatch)
    connect()
    gateway.on_disconnect(gateway.client, None, None, "test", None)
    connect()
    for mid in (4, 5, 6):
        gateway._on_subscribe(
            gateway.client,
            None,
            mid,
            [mqtt.ReasonCode(mqtt.PacketTypes.SUBACK, identifier=1)],
            None,
        )
    assert gateway.wait_subscribed(0)
    assert gateway.connected
    assert not gateway._pending_subscribe_mids


def test_unknown_suback_cannot_authorize_connection(gateway):
    gateway._on_subscribe(
        gateway.client,
        None,
        99,
        [mqtt.ReasonCode(mqtt.PacketTypes.SUBACK, identifier=1)],
        None,
    )
    assert not gateway.wait_subscribed(0)


def test_reconnect_fence_runs_before_paho_clears_packet_queue(gateway, monkeypatch):
    gateway._connection_valid = True
    observed = []

    def base_reconnect(client):
        observed.append(gateway._connection_valid)
        return mqtt.MQTT_ERR_SUCCESS

    monkeypatch.setattr(mqtt.Client, "reconnect", base_reconnect)
    gateway.client.reconnect()
    assert observed == [False]


def test_ack_and_reconnect_fence_are_serialized(gateway, monkeypatch):
    entered, release, recovering = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    actions = []
    gateway._connection_valid = True
    gateway._generation = 5

    def ack(mid, qos):
        entered.set()
        assert release.wait(3)
        actions.append("old_ack")

    def reconnect(client):
        assert not gateway._connection_valid
        actions.append("new_socket")
        return 0

    monkeypatch.setattr(gateway.client, "ack", ack)
    monkeypatch.setattr(mqtt.Client, "reconnect", reconnect)

    def recover():
        recovering.set()
        gateway.client.reconnect()

    worker = threading.Thread(
        target=lambda: gateway.ack(SimpleNamespace(mid=42, qos=1), 5), daemon=True
    )
    network = threading.Thread(target=recover, daemon=True)
    try:
        worker.start()
        assert entered.wait(1)
        network.start()
        assert recovering.wait(1)
    finally:
        release.set()
        worker.join(2)
        if network.ident:
            network.join(2)
    assert not worker.is_alive() and not network.is_alive()
    assert actions == ["old_ack", "new_socket"]


@pytest.mark.parametrize("codes", [[], [0], [128], [1, 1]])
def test_required_subscription_must_grant_exactly_qos1(gateway, monkeypatch, codes):
    connect_without_network(gateway, monkeypatch)()
    gateway._on_subscribe(
        gateway.client,
        None,
        1,
        [mqtt.ReasonCode(mqtt.PacketTypes.SUBACK, identifier=code) for code in codes],
        None,
    )
    assert not gateway._connection_valid
    assert not gateway.wait_subscribed(0)


def test_subscription_timeout_revokes_acks_and_does_not_claim(gateway, monkeypatch):
    connect_without_network(gateway, monkeypatch)()
    gateway.publish_claimed_commands()
    assert gateway.api_client.requests == []
    gateway._subscribe_deadline = 1.0
    gateway._check_subscription_timeout()
    assert not gateway._connection_valid
    assert not gateway._pending_subscribe_mids
    assert not gateway.connected


@pytest.mark.parametrize("missing", ["subscribed", "supervisorAlive"])
def test_process_health_requires_subscriptions_and_supervisor(tmp_path, missing):
    import time

    payload = dict(
        updatedAt=time.time(),
        connected=True,
        subscribed=True,
        workersAlive=True,
        commandWorkerAlive=True,
        supervisorAlive=True,
    )
    payload[missing] = False
    path = tmp_path / "health.json"
    path.write_text(json.dumps(payload))
    result = subprocess.run(
        [sys.executable, "-m", "app.file_healthcheck", "gateway", str(path)], timeout=5
    )
    assert result.returncode == 1
