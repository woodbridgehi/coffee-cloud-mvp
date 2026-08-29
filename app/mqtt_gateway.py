from __future__ import annotations

import json
import logging
import os
import queue
import ssl
import threading
import time
import uuid
from typing import Any
from urllib.parse import urlencode

import httpx
import paho.mqtt.client as mqtt


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("coffee-mqtt-gateway")
HTTP_BASE = os.getenv("DEVICE_API_BASE_URL", "http://127.0.0.1:8788").rstrip("/")
GATEWAY_TOKEN = os.environ["INTERNAL_GATEWAY_TOKEN"]
GATEWAY_ID = os.getenv("MQTT_GATEWAY_ID", f"gateway-{uuid.uuid4()}")
MQTT_HOST = os.getenv("MQTT_HOST", "mqtt-api.woodbridge.top")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_USERNAME = os.environ["MQTT_USERNAME"]
MQTT_PASSWORD = os.environ["MQTT_PASSWORD"]
CLAIM_SECONDS = float(os.getenv("MQTT_COMMAND_CLAIM_SECONDS", "1"))
QUEUE_CAPACITY = max(100, int(os.getenv("MQTT_GATEWAY_QUEUE_CAPACITY", "10000")))
WORKER_COUNT = max(1, min(32, int(os.getenv("MQTT_GATEWAY_WORKERS", "4"))))


class GatewayApiClient:
    """Thread-safe keep-alive HTTP client shared by gateway workers."""

    def __init__(self) -> None:
        self.client = httpx.Client(
            base_url=HTTP_BASE,
            headers={"X-Gateway-Token": GATEWAY_TOKEN, "Accept": "application/json"},
            timeout=8.0,
            limits=httpx.Limits(max_connections=max(16, WORKER_COUNT * 4), max_keepalive_connections=max(8, WORKER_COUNT * 2)),
        )

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = self.client.request(method, path, json=payload)
            if response.status_code >= 400:
                detail = response.text
                if 400 <= response.status_code < 500 and response.status_code not in {401, 403, 408, 429}:
                    raise ValueError(
                        f"cloud rejected gateway operation: HTTP {response.status_code} {detail[:300]}"
                    )
                raise ConnectionError(f"cloud API HTTP {response.status_code}")
            raw = response.content
            return json.loads(raw) if raw else {}
        except ValueError:
            raise
        except httpx.RequestError as exc:
            raise ConnectionError(f"cloud API unavailable: {exc}") from exc

    def close(self) -> None:
        self.client.close()


class Gateway:
    def __init__(self) -> None:
        self.api_client = GatewayApiClient()
        self.worker_count = WORKER_COUNT
        per_worker_capacity = max(1, QUEUE_CAPACITY // self.worker_count)
        self.inboxes = [queue.Queue[tuple[mqtt.MQTTMessage, int]](maxsize=per_worker_capacity) for _ in range(self.worker_count)]
        self.stop_event = threading.Event()
        self.worker_threads: list[threading.Thread] = []
        self.command_thread: threading.Thread | None = None
        self.connected = False
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=GATEWAY_ID, protocol=mqtt.MQTTv5)
        self.client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        self.client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)
        self.client.reconnect_delay_set(1, 60)
        self.client.manual_ack_set(True)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message

    def on_connect(self, client: mqtt.Client, _userdata: object, _flags: Any, reason: Any, _properties: Any) -> None:
        if reason.is_failure:
            log.error("MQTT CONNECT rejected: %s", reason)
            return
        for topic, qos in (("v1/devices/+/up", 1), ("v1/devices/+/presence", 1), ("v1/devices/+/state", 1)):
            result, _ = client.subscribe(topic, qos=qos)
            if result != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(f"subscription failed for {topic}: {mqtt.error_string(result)}")
        self.connected = True
        log.info("multi-device MQTT gateway connected id=%s", GATEWAY_ID)

    def on_disconnect(self, _client: mqtt.Client, _userdata: object, _flags: Any, reason: Any, _properties: Any) -> None:
        self.connected = False
        log.warning("MQTT gateway disconnected: %s", reason)

    def on_message(self, _client: mqtt.Client, _userdata: object, message: mqtt.MQTTMessage) -> None:
        shard = self._shard_for(message)
        try:
            self.inboxes[shard].put_nowait((message, 0))
        except queue.Full:
            log.error("MQTT gateway inbox full; disconnecting so QoS1 can redeliver")
            self.client.disconnect()

    def _shard_for(self, message: mqtt.MQTTMessage) -> int:
        parts = message.topic.split("/")
        device_id = parts[2] if len(parts) >= 3 else message.topic
        return hash(device_id) % self.worker_count

    def ack(self, message: mqtt.MQTTMessage) -> None:
        if message.qos:
            self.client.ack(message.mid, message.qos)

    def process(self, message: mqtt.MQTTMessage) -> None:
        try:
            envelope = json.loads(message.payload)
        except json.JSONDecodeError as exc:
            raise ValueError("MQTT payload is not valid JSON") from exc
        if not isinstance(envelope, dict):
            raise ValueError("MQTT payload must be an object")
        self.api_client.request(
            "POST", "/api/v1/internal/mqtt/messages", {"topic": message.topic, "envelope": envelope}
        )

    def _worker_loop(self, inbox: queue.Queue[tuple[mqtt.MQTTMessage, int]], worker_id: int) -> None:
        log.info("MQTT uplink worker started id=%s", worker_id)
        while not self.stop_event.is_set():
            try:
                message, attempt = inbox.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                try:
                    self.process(message)
                    self.ack(message)
                except ValueError as exc:
                    log.error("non-retryable MQTT uplink rejected topic=%s: %s", message.topic, exc)
                    self.ack(message)
                except (ConnectionError, OSError) as exc:
                    delay = min(30.0, 2 ** min(attempt, 5))
                    log.warning("MQTT uplink retry in %.1fs worker=%s: %s", delay, worker_id, exc)
                    if not self.stop_event.wait(delay):
                        try:
                            inbox.put((message, attempt + 1), timeout=1)
                        except queue.Full:
                            log.error("MQTT gateway retry queue full; disconnecting")
                            self.client.disconnect()
            finally:
                inbox.task_done()

    def _start_workers(self) -> None:
        for index, inbox in enumerate(self.inboxes):
            thread = threading.Thread(
                target=self._worker_loop, args=(inbox, index), name=f"mqtt-uplink-{index}", daemon=True
            )
            self.worker_threads.append(thread)
            thread.start()

    def _command_loop(self) -> None:
        next_claim = 0.0
        while not self.stop_event.wait(0.05):
            if not self.connected or time.monotonic() < next_claim:
                continue
            try:
                self.publish_claimed_commands()
                next_claim = time.monotonic() + CLAIM_SECONDS
            except (ConnectionError, OSError) as exc:
                log.warning("command outbox unavailable: %s", exc)
                next_claim = time.monotonic() + 2
            except ValueError as exc:
                log.error("command outbox rejected: %s", exc)
                next_claim = time.monotonic() + 5

    def publish_claimed_commands(self) -> None:
        query = urlencode({"gateway_id": GATEWAY_ID, "limit": 100})
        response = self.api_client.request("GET", f"/api/v1/internal/device-commands/claim?{query}")
        for command in response.get("commands") or []:
            outbox_id = command["outboxId"]
            try:
                info = self.client.publish(
                    command["topic"], json.dumps(command["envelope"], ensure_ascii=False), qos=1, retain=False,
                )
                info.wait_for_publish(timeout=8)
                if not info.is_published():
                    raise ConnectionError("MQTT command PUBACK timed out")
                self.api_client.request(
                    "POST", f"/api/v1/internal/device-commands/{outbox_id}/published", {"gatewayId": GATEWAY_ID}
                )
            except Exception as exc:
                try:
                    self.api_client.request("POST", f"/api/v1/internal/device-commands/{outbox_id}/retry", {
                        "gatewayId": GATEWAY_ID, "error": f"{type(exc).__name__}: {exc}",
                    })
                except Exception:
                    log.exception("failed to release command publish lease outbox=%s", outbox_id)
                raise

    def run(self) -> None:
        properties = mqtt.Properties(mqtt.PacketTypes.CONNECT)
        properties.SessionExpiryInterval = 604800
        self.client.connect_async(
            MQTT_HOST, MQTT_PORT, keepalive=30,
            clean_start=mqtt.MQTT_CLEAN_START_FIRST_ONLY, properties=properties,
        )
        self.client.loop_start()
        self._start_workers()
        self.command_thread = threading.Thread(target=self._command_loop, name="mqtt-command-publisher", daemon=True)
        self.command_thread.start()
        try:
            while not self.stop_event.wait(1.0):
                pass
        finally:
            self.stop_event.set()
            self.client.disconnect()
            self.client.loop_stop()
            for thread in self.worker_threads:
                thread.join(timeout=2)
            if self.command_thread:
                self.command_thread.join(timeout=2)
            self.api_client.close()


if __name__ == "__main__":
    Gateway().run()
