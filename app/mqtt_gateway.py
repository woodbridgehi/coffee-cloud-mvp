from __future__ import annotations

import json
import logging
import os
import queue
import ssl
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import paho.mqtt.client as mqtt


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("coffee-mqtt-gateway")
DEVICE_ID = os.environ["DEVICE_ID"]
DEVICE_TOKEN = os.environ["DEVICE_TOKEN"]
HTTP_BASE = os.getenv("DEVICE_API_BASE_URL", "http://127.0.0.1:8788").rstrip("/")
MQTT_HOST = os.getenv("MQTT_HOST", "mqtt-api.woodbridge.top")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_USERNAME = os.environ["MQTT_USERNAME"]
MQTT_PASSWORD = os.environ["MQTT_PASSWORD"]
POLL_SECONDS = float(os.getenv("MQTT_COMMAND_POLL_SECONDS", "1"))


def api(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {DEVICE_TOKEN}", "X-Device-Id": DEVICE_ID, "Accept": "application/json"}
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
        if 400 <= exc.code < 500 and exc.code not in {401, 403, 429}:
            raise ValueError(f"device API rejected MQTT message: HTTP {exc.code} {detail[:300]}") from exc
        raise ConnectionError(f"device API HTTP {exc.code}") from exc
    except URLError as exc:
        raise ConnectionError(f"device API unavailable: {exc.reason}") from exc


class Gateway:
    def __init__(self) -> None:
        self.inbox: queue.Queue[tuple[mqtt.MQTTMessage, int]] = queue.Queue(maxsize=1000)
        self.connected = False
        self.cursor = ""
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="coffee-cloud-gateway", protocol=mqtt.MQTTv5)
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
            client.subscribe(topic, qos=qos)
        self.connected = True
        self.cursor = ""  # replay all still-delivering commands after every gateway reconnect
        log.info("MQTT gateway connected")

    def on_disconnect(self, _client: mqtt.Client, _userdata: object, _flags: Any, reason: Any, _properties: Any) -> None:
        self.connected = False
        log.warning("MQTT gateway disconnected: %s", reason)

    def on_message(self, _client: mqtt.Client, _userdata: object, message: mqtt.MQTTMessage) -> None:
        try:
            self.inbox.put_nowait((message, 0))
        except queue.Full:
            log.error("MQTT gateway inbox full; reconnect required for QoS1 redelivery")
            self.client.disconnect()

    def ack(self, message: mqtt.MQTTMessage) -> None:
        if message.qos:
            self.client.ack(message.mid, message.qos)

    def process(self, message: mqtt.MQTTMessage) -> None:
        value = json.loads(message.payload)
        if message.topic.endswith(("/presence", "/state")):
            return
        if value.get("deviceId") != DEVICE_ID:
            raise ValueError(f"unsupported device identity: {value.get('deviceId')}")
        kind, payload = value.get("type"), value.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("MQTT envelope payload must be an object")
        if kind == "heartbeat":
            api("POST", f"/api/v1/devices/{quote(DEVICE_ID)}/heartbeat", payload)
        elif kind == "event":
            api("POST", f"/api/v1/devices/{quote(DEVICE_ID)}/events", payload)
        elif kind == "command_result":
            if payload.get("commandType") == "MAKE_DRINK":
                api("POST", f"/api/v1/tasks/{quote(str(payload.get('taskId') or 'unknown'))}/ack", payload)
            else:
                api("POST", f"/api/v1/devices/{quote(DEVICE_ID)}/commands/{quote(str(payload.get('messageId')))}/result", payload)
        else:
            raise ValueError(f"unsupported MQTT uplink type: {kind}")

    def poll_commands(self) -> None:
        query = urlencode({"after": self.cursor, "limit": 100})
        response = api("GET", f"/api/v1/devices/{quote(DEVICE_ID)}/commands?{query}")
        commands = response.get("commands") or []
        for command in commands:
            envelope = {
                "schema": "coffee.mqtt-envelope.v1", "messageId": command.get("messageId"),
                "deviceId": DEVICE_ID, "type": "command", "payload": command,
            }
            info = self.client.publish(
                f"v1/devices/{DEVICE_ID}/down", json.dumps(envelope, ensure_ascii=False), qos=1, retain=False
            )
            info.wait_for_publish(timeout=8)
            if not info.is_published():
                raise ConnectionError("MQTT command PUBACK timed out")
        self.cursor = str(response.get("nextCursor") or self.cursor)

    def run(self) -> None:
        properties = mqtt.Properties(mqtt.PacketTypes.CONNECT)
        properties.SessionExpiryInterval = 604800
        self.client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30, clean_start=mqtt.MQTT_CLEAN_START_FIRST_ONLY, properties=properties)
        self.client.loop_start()
        next_poll = 0.0
        try:
            while True:
                try:
                    message, attempt = self.inbox.get(timeout=0.1)
                    try:
                        self.process(message)
                        self.ack(message)
                    except ValueError as exc:
                        log.error("non-retryable uplink rejected: %s", exc)
                        self.ack(message)
                    except (ConnectionError, OSError) as exc:
                        delay = min(30.0, 2 ** min(attempt, 5))
                        log.warning("uplink retry in %.1fs: %s", delay, exc)
                        time.sleep(delay)
                        self.inbox.put((message, attempt + 1))
                except queue.Empty:
                    pass
                if self.connected and time.monotonic() >= next_poll:
                    try:
                        self.poll_commands()
                        next_poll = time.monotonic() + POLL_SECONDS
                    except (ConnectionError, OSError) as exc:
                        log.warning("command poll failed: %s", exc)
                        next_poll = time.monotonic() + 2
                    except ValueError as exc:
                        log.error("command poll permanently rejected: %s", exc)
                        next_poll = time.monotonic() + 30
        finally:
            self.client.disconnect(); self.client.loop_stop()


if __name__ == "__main__":
    Gateway().run()
