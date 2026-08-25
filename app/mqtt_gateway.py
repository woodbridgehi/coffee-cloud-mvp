from __future__ import annotations

import json
import logging
import os
import queue
import ssl
import time
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

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


def api(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = {"X-Gateway-Token": GATEWAY_TOKEN, "Accept": "application/json"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload, ensure_ascii=False).encode()
    request = Request(HTTP_BASE + path, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=8) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        if 400 <= exc.code < 500 and exc.code not in {401, 403, 408, 429}:
            raise ValueError(f"cloud rejected gateway operation: HTTP {exc.code} {detail[:300]}") from exc
        raise ConnectionError(f"cloud API HTTP {exc.code}") from exc
    except URLError as exc:
        raise ConnectionError(f"cloud API unavailable: {exc.reason}") from exc


class Gateway:
    def __init__(self) -> None:
        self.inbox: queue.Queue[tuple[mqtt.MQTTMessage, int]] = queue.Queue(maxsize=10000)
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
        try:
            self.inbox.put_nowait((message, 0))
        except queue.Full:
            log.error("MQTT gateway inbox full; disconnecting so QoS1 can redeliver")
            self.client.disconnect()

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
        api("POST", "/api/v1/internal/mqtt/messages", {"topic": message.topic, "envelope": envelope})

    def publish_claimed_commands(self) -> None:
        query = urlencode({"gateway_id": GATEWAY_ID, "limit": 100})
        response = api("GET", f"/api/v1/internal/device-commands/claim?{query}")
        for command in response.get("commands") or []:
            outbox_id = command["outboxId"]
            try:
                info = self.client.publish(
                    command["topic"], json.dumps(command["envelope"], ensure_ascii=False), qos=1, retain=False,
                )
                info.wait_for_publish(timeout=8)
                if not info.is_published():
                    raise ConnectionError("MQTT command PUBACK timed out")
                api("POST", f"/api/v1/internal/device-commands/{outbox_id}/published", {"gatewayId": GATEWAY_ID})
            except Exception as exc:
                try:
                    api("POST", f"/api/v1/internal/device-commands/{outbox_id}/retry", {
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
        next_claim = 0.0
        try:
            while True:
                try:
                    message, attempt = self.inbox.get(timeout=0.05)
                    try:
                        self.process(message)
                        self.ack(message)
                    except ValueError as exc:
                        log.error("non-retryable MQTT uplink rejected topic=%s: %s", message.topic, exc)
                        self.ack(message)
                    except (ConnectionError, OSError) as exc:
                        delay = min(30.0, 2 ** min(attempt, 5))
                        log.warning("MQTT uplink retry in %.1fs: %s", delay, exc)
                        time.sleep(delay)
                        self.inbox.put((message, attempt + 1))
                except queue.Empty:
                    pass
                if self.connected and time.monotonic() >= next_claim:
                    try:
                        self.publish_claimed_commands()
                        next_claim = time.monotonic() + CLAIM_SECONDS
                    except (ConnectionError, OSError) as exc:
                        log.warning("command outbox unavailable: %s", exc)
                        next_claim = time.monotonic() + 2
                    except ValueError as exc:
                        log.error("command outbox rejected: %s", exc)
                        next_claim = time.monotonic() + 5
        finally:
            self.client.disconnect()
            self.client.loop_stop()


if __name__ == "__main__":
    Gateway().run()
