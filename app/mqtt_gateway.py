from __future__ import annotations

import json
import logging
import os
import queue
import ssl
import threading
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

import httpx
import paho.mqtt.client as mqtt


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("coffee-mqtt-gateway")
logging.getLogger("httpx").setLevel(logging.WARNING)
HTTP_BASE = os.getenv("DEVICE_API_BASE_URL", "http://127.0.0.1:8788").rstrip("/")
GATEWAY_TOKEN = os.environ["INTERNAL_GATEWAY_TOKEN"]
# Stable by default: the MQTT client id is the gateway session identity. A
# random default would discard the broker-side session (and every queued
# QoS1 uplink) on each restart. Multi-instance deployments MUST configure a
# unique, stable MQTT_GATEWAY_ID per gateway process.
DEFAULT_GATEWAY_ID = "coffee-mqtt-gateway-v1"
GATEWAY_ID = os.getenv("MQTT_GATEWAY_ID", DEFAULT_GATEWAY_ID)
MQTT_HOST = os.getenv("MQTT_HOST", "mqtt-api.woodbridge.top")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_USERNAME = os.environ["MQTT_USERNAME"]
MQTT_PASSWORD = os.environ["MQTT_PASSWORD"]
SESSION_EXPIRY_SECONDS = int(os.getenv("MQTT_SESSION_EXPIRY_SECONDS", "604800"))
CLAIM_SECONDS = float(os.getenv("MQTT_COMMAND_CLAIM_SECONDS", "1"))
QUEUE_CAPACITY = max(100, int(os.getenv("MQTT_GATEWAY_QUEUE_CAPACITY", "10000")))
WORKER_COUNT = max(1, min(32, int(os.getenv("MQTT_GATEWAY_WORKERS", "4"))))
TELEMETRY_BATCH_SIZE = max(1, min(500, int(os.getenv("MQTT_TELEMETRY_BATCH_SIZE", "100"))))
TELEMETRY_BATCH_WAIT_SECONDS = max(0.01, min(1.0, float(os.getenv("MQTT_TELEMETRY_BATCH_WAIT_SECONDS", "0.1"))))
HEALTH_FILE = Path(os.getenv("GATEWAY_HEALTH_FILE", "/tmp/mqtt-gateway.json"))
SUPERVISOR_INTERVAL_SECONDS = float(os.getenv("MQTT_SUPERVISOR_INTERVAL_SECONDS", "0.5"))
RECONNECT_BACKOFF_MAX_SECONDS = 60.0
SUBSCRIBE_TIMEOUT_SECONDS = max(1.0, min(60.0, float(os.getenv("MQTT_SUBSCRIBE_TIMEOUT_SECONDS", "10"))))


class SessionMqttClient(mqtt.Client):
    """Fence before Paho clears packets/changes sockets, including auto-retry.

    on_pre_connect alone is too late: Paho has already cleared _out_packet.
    This hook does not hold an application lock over blocking socket I/O.
    """
    before_reconnect: Callable[[], None] | None = None

    def reconnect(self) -> mqtt.MQTTErrorCode:
        if self.before_reconnect is not None:
            self.before_reconnect()
        return super().reconnect()


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
    """Multi-device MQTT 5.0 gateway.

    Connection lifecycle contract (B1.1):

    - Stable client id (``MQTT_GATEWAY_ID``), persistent session
      (``clean_start=False`` + non-zero session expiry): QoS1 uplinks queued
      by the broker while the gateway is down are redelivered after restart.
    - A single supervisor thread restores the network loop after it dies
      (backpressure disconnect, subscribe failure). Paho retries transient
      socket failures and initial connects inside its own loop; the supervisor
      only steps in when that loop is gone. Callbacks never join/reconnect.
    - Received messages carry the connection generation; ``ack`` refuses MIDs
      from a stale generation so an old connection can never settle a
      different message reusing the same MID on a new connection.
    - ``shutdown()`` is idempotent and preserves the broker session. A dead
      worker/command thread makes ``monitor_once``/``run`` fail the health
      file and exit non-zero so the container restarts under supervision.
    """

    def __init__(self, api_client: GatewayApiClient | None = None, client: mqtt.Client | None = None) -> None:
        self.api_client = api_client if api_client is not None else GatewayApiClient()
        self.worker_count = WORKER_COUNT
        per_worker_capacity = max(1, QUEUE_CAPACITY // self.worker_count)
        # Inbox items are (message, retry attempt, connection generation).
        self.inboxes: list[queue.Queue[tuple[mqtt.MQTTMessage, int, int]]] = [
            queue.Queue(maxsize=per_worker_capacity) for _ in range(self.worker_count)
        ]
        self.stop_event = threading.Event()
        self.worker_threads: list[threading.Thread] = []
        self.command_thread: threading.Thread | None = None
        self.supervisor_thread: threading.Thread | None = None
        self._generation = 0
        self._connection_valid = False
        # Paho ACK may synchronously call on_disconnect on a write error when
        # its loop is absent. Re-entry must be allowed; no join under this lock.
        self._generation_lock = threading.RLock()
        self.backpressure_disconnects = 0
        self._connected = threading.Event()
        self._subscribed = threading.Event()
        self._pending_subscribe_mids: set[int] = set()
        self._subscribe_deadline = 0.0
        self._shutdown_lock = threading.Lock()
        self._shutdown_done = False
        self._reconnect_lock = threading.Lock()
        self.client = client if client is not None else self._default_client()
        self._wire_client(self.client)

    # ------------------------------------------------------------------
    # Client construction / wiring
    # ------------------------------------------------------------------
    def _default_client(self) -> mqtt.Client:
        client = SessionMqttClient(mqtt.CallbackAPIVersion.VERSION2, client_id=GATEWAY_ID, protocol=mqtt.MQTTv5)
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)
        return client

    def _wire_client(self, client: mqtt.Client) -> None:
        client.reconnect_delay_set(1, 60)
        client.manual_ack_set(True)
        client.on_connect = self.on_connect
        client.on_disconnect = self.on_disconnect
        client.on_message = self.on_message
        client.on_subscribe = self._on_subscribe
        client.on_pre_connect = self._on_pre_connect
        if isinstance(client, SessionMqttClient):
            client.before_reconnect = self._invalidate_connection

    # ------------------------------------------------------------------
    # Connection state
    # ------------------------------------------------------------------
    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    @property
    def generation(self) -> int:
        return self._generation

    @generation.setter
    def generation(self, value: int) -> None:
        self._generation = value

    def on_connect(self, client: mqtt.Client, _userdata: object, flags: Any, reason: Any, _properties: Any) -> None:
        self._invalidate_connection()
        if self.stop_event.is_set():
            self._disconnect()
            return
        if reason.is_failure:
            log.error("MQTT CONNECT rejected for id=%s: %s", GATEWAY_ID, reason)
            return
        session_present = bool(getattr(flags, "session_present", False))
        if not session_present:
            log.warning(
                "MQTT session not present for id=%s; broker may have dropped queued QoS1 uplinks", GATEWAY_ID
            )
        with self._generation_lock:
            self._generation += 1
            # ACKs for resumed-session traffic are allowed before SUBACK;
            # publication/readiness is separately gated on all subscriptions.
            self._connection_valid = True
            self._subscribe_deadline = time.monotonic() + SUBSCRIBE_TIMEOUT_SECONDS
        for topic, qos in (("v1/devices/+/up", 1), ("v1/devices/+/presence", 1), ("v1/devices/+/state", 1)):
            result, mid = client.subscribe(topic, qos=qos)
            if result != mqtt.MQTT_ERR_SUCCESS:
                log.error(
                    "subscribe failed for %s: %s; dropping connection for supervisor recovery",
                    topic, mqtt.error_string(result),
                )
                self._disconnect()
                return
            with self._generation_lock:
                self._pending_subscribe_mids.add(mid)
        log.info(
            "MQTT CONNACK received; awaiting subscriptions id=%s generation=%s sessionPresent=%s",
            GATEWAY_ID, self._generation, session_present,
        )

    def on_disconnect(self, _client: mqtt.Client, _userdata: object, _flags: Any, reason: Any, _properties: Any) -> None:
        self._invalidate_connection()
        log.warning("MQTT gateway disconnected id=%s: %s", GATEWAY_ID, reason)

    def _invalidate_connection(self) -> None:
        with self._generation_lock:
            self._connection_valid = False
            self._connected.clear()
            self._subscribed.clear()
            self._pending_subscribe_mids.clear()
            self._subscribe_deadline = 0.0

    def _on_pre_connect(self, _client: mqtt.Client, _userdata: object) -> None:
        self._invalidate_connection()

    def _disconnect(self) -> None:
        self._invalidate_connection()
        self.client.disconnect()

    def _on_subscribe(self, _client: mqtt.Client, _userdata: object, mid: int, reasons: Any, _properties: Any) -> None:
        with self._generation_lock:
            if not self._connection_valid or mid not in self._pending_subscribe_mids or self.stop_event.is_set():
                return
            failed = len(reasons) != 1 or any(reason.is_failure or reason.value != 1 for reason in reasons)
            if not failed:
                self._pending_subscribe_mids.remove(mid)
                if not self._pending_subscribe_mids:
                    self._subscribe_deadline = 0.0
                    self._subscribed.set()
                    self._connected.set()
        if failed:
            log.error("required QoS1 subscription rejected/downgraded mid=%s reasons=%s", mid, reasons)
            self._disconnect()

    def _check_subscription_timeout(self) -> None:
        with self._generation_lock:
            expired = self._subscribe_deadline and time.monotonic() >= self._subscribe_deadline
        if expired:
            log.error("MQTT SUBACK timed out; reconnecting")
            self._disconnect()

    def wait_subscribed(self, timeout: float) -> bool:
        return self._subscribed.wait(timeout)

    def on_message(self, _client: mqtt.Client, _userdata: object, message: mqtt.MQTTMessage) -> None:
        try:
            shard = self._shard_for(message)
            self.inboxes[shard].put_nowait((message, 0, self._generation))
        except queue.Full:
            self.backpressure_disconnects += 1
            log.error("MQTT gateway inbox full; disconnecting so QoS1 can redeliver")
            self._disconnect()
        except Exception:
            log.exception("unexpected error dispatching MQTT message topic=%s", message.topic)
            self._disconnect()  # unacknowledged message must be redelivered

    def _shard_for(self, message: mqtt.MQTTMessage) -> int:
        parts = message.topic.split("/")
        device_id = parts[2] if len(parts) >= 3 else message.topic
        return hash(device_id) % self.worker_count

    def ack(self, message: mqtt.MQTTMessage, generation: int) -> None:
        with self._generation_lock:
            # Serialise the validity check with the ACK send itself: a
            # concurrent reconnect fence/on_disconnect cannot slip
            # between "check" and "send" and smuggle a stale MID onto a
            # new connection. Invalidating on disconnect makes even a
            # matching generation number powerless once the socket is gone.
            if not self._connection_valid or generation != self._generation:
                log.debug(
                    "ignoring stale generation ACK mid=%s gen=%s current=%s valid=%s",
                    message.mid, generation, self._generation, self._connection_valid,
                )
                return
            if message.qos:
                self.client.ack(message.mid, message.qos)

    # ------------------------------------------------------------------
    # Connection supervision
    # ------------------------------------------------------------------
    def _loop_thread(self) -> threading.Thread | None:
        thread = getattr(self.client, "_thread", None)
        return thread if thread is not None and thread.is_alive() else None

    def _supervise(self) -> None:
        failures = 0
        next_retry_at = 0.0
        while not self.stop_event.wait(SUPERVISOR_INTERVAL_SECONDS):
            self._check_subscription_timeout()
            if self._loop_thread() is not None:
                # The network loop is alive: either healthy or retrying on
                # its own (initial connect, transient socket failures).
                # A live loop is the source of truth; a stale `connected`
                # flag from a crashed loop must never mask recovery.
                if self.connected:
                    failures = 0
                    next_retry_at = 0.0
                continue
            if time.monotonic() < next_retry_at:
                continue
            self._recover_once()
            failures += 1
            next_retry_at = time.monotonic() + min(
                RECONNECT_BACKOFF_MAX_SECONDS, 1.0 * (2 ** min(failures - 1, 6))
            )

    def _recover_once(self) -> None:
        """Restore the network loop after it died. Runs on the supervisor
        thread only; rechecks shutdown after reconnect() so a close racing
        the reconnect never leaves a fresh connection or loop behind."""
        with self._reconnect_lock:
            if self.stop_event.is_set():
                return
            self._invalidate_connection()
            log.warning("MQTT network loop is dead; supervisor restoring connection id=%s", GATEWAY_ID)
            try:
                self.client.loop_stop()
            except Exception:  # pragma: no cover - paho defensive
                pass
            result = mqtt.MQTT_ERR_CONN_REFUSED
            try:
                result = self.client.reconnect()
            except (OSError, ValueError) as exc:
                log.warning("MQTT supervisor reconnect failed: %s", exc)
            if self.stop_event.is_set():
                log.warning("shutdown raced the reconnect; discarding restored connection")
                try:
                    self._disconnect()
                except Exception:  # pragma: no cover - paho defensive
                    pass
                return
            if result == mqtt.MQTT_ERR_SUCCESS:
                self.client.loop_start()

    # ------------------------------------------------------------------
    # Uplink processing
    # ------------------------------------------------------------------
    def _message_body(self, message: mqtt.MQTTMessage) -> dict[str, Any]:
        try:
            envelope = json.loads(message.payload)
        except json.JSONDecodeError as exc:
            raise ValueError("MQTT payload is not valid JSON") from exc
        if not isinstance(envelope, dict):
            raise ValueError("MQTT payload must be an object")
        return {"topic": message.topic, "envelope": envelope}

    @staticmethod
    def _is_batchable_telemetry(body: dict[str, Any]) -> bool:
        topic = str(body["topic"])
        envelope = body["envelope"]
        if topic.endswith("/presence") or topic.endswith("/state") or envelope.get("type") == "heartbeat":
            return True
        payload = envelope.get("payload")
        return envelope.get("type") == "event" and isinstance(payload, dict) and payload.get("type") in {
            "task.progress",
        }

    def _process_body(self, body: dict[str, Any]) -> None:
        self.api_client.request("POST", "/api/v1/internal/mqtt/messages", body)

    def _process_batch(self, bodies: list[dict[str, Any]]) -> None:
        response = self.api_client.request("POST", "/api/v1/internal/mqtt/messages/batch", {"messages": bodies})
        accepted = response.get("accepted")
        rejected = response.get("rejected")
        if not isinstance(accepted, list) or not isinstance(rejected, list):
            raise ConnectionError("cloud API returned an invalid telemetry batch response")
        settled = {item for item in accepted if isinstance(item, int)}
        settled.update(item.get("index") for item in rejected if isinstance(item, dict) and isinstance(item.get("index"), int))
        if settled != set(range(len(bodies))):
            raise ConnectionError("cloud API did not settle every telemetry batch message")

    def _retry(
        self, inbox: queue.Queue[tuple[mqtt.MQTTMessage, int, int]], items: list[tuple[mqtt.MQTTMessage, int, int]],
        worker_id: int, exc: Exception,
    ) -> None:
        attempt = max(item[1] for item in items)
        delay = min(30.0, 2 ** min(attempt, 5))
        log.warning("MQTT uplink retry count=%s in %.1fs worker=%s: %s", len(items), delay, worker_id, exc)
        if not self.stop_event.wait(delay):
            self._requeue_after_retry(inbox, items)

    def _requeue_after_retry(
        self, inbox: queue.Queue[tuple[mqtt.MQTTMessage, int, int]], items: list[tuple[mqtt.MQTTMessage, int, int]],
    ) -> None:
        """Requeue failed uplinks with attempt+1 (so backoff grows) while
        preserving the connection generation for ACK isolation."""
        for message, attempt, generation in items:
            try:
                inbox.put((message, attempt + 1, generation), timeout=1)
            except queue.Full:
                log.error("MQTT gateway retry queue full; disconnecting")
                self._disconnect()
                return

    def _process_one(
        self, inbox: queue.Queue[tuple[mqtt.MQTTMessage, int, int]], message: mqtt.MQTTMessage, attempt: int,
        worker_id: int, generation: int, body: dict[str, Any] | None = None,
    ) -> None:
        try:
            self._process_body(body or self._message_body(message))
            self.ack(message, generation)
        except ValueError as exc:
            log.error("non-retryable MQTT uplink rejected topic=%s: %s", message.topic, exc)
            self.ack(message, generation)
        except (ConnectionError, OSError) as exc:
            self._retry(inbox, [(message, attempt, generation)], worker_id, exc)

    def _worker_loop(self, inbox: queue.Queue[tuple[mqtt.MQTTMessage, int, int]], worker_id: int) -> None:
        log.info("MQTT uplink worker started id=%s", worker_id)
        while not self.stop_event.is_set():
            try:
                message, attempt, generation = inbox.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                try:
                    body = self._message_body(message)
                except ValueError as exc:
                    log.error("non-retryable MQTT uplink rejected topic=%s: %s", message.topic, exc)
                    self.ack(message, generation)
                    continue
                if not self._is_batchable_telemetry(body):
                    self._process_one(inbox, message, attempt, worker_id, generation, body)
                    continue

                batch = [(message, attempt, generation, body)]
                deadline = time.monotonic() + TELEMETRY_BATCH_WAIT_SECONDS
                deferred: tuple[mqtt.MQTTMessage, int, int, dict[str, Any]] | None = None
                while len(batch) < TELEMETRY_BATCH_SIZE:
                    try:
                        next_message, next_attempt, next_generation = inbox.get(timeout=max(0.0, deadline - time.monotonic()))
                    except queue.Empty:
                        break
                    try:
                        next_body = self._message_body(next_message)
                    except ValueError as exc:
                        log.error("non-retryable MQTT uplink rejected topic=%s: %s", next_message.topic, exc)
                        self.ack(next_message, next_generation)
                        inbox.task_done()
                        continue
                    if not self._is_batchable_telemetry(next_body):
                        deferred = (next_message, next_attempt, next_generation, next_body)
                        break
                    batch.append((next_message, next_attempt, next_generation, next_body))
                try:
                    self._process_batch([item[3] for item in batch])
                    for batch_message, _, batch_generation, _ in batch:
                        self.ack(batch_message, batch_generation)
                except ValueError as exc:
                    log.error("non-retryable MQTT telemetry batch rejected: %s", exc)
                    for batch_message, _, batch_generation, _ in batch:
                        self.ack(batch_message, batch_generation)
                except (ConnectionError, OSError) as exc:
                    self._retry(
                        inbox,
                        [(batch_message, batch_attempt, batch_generation) for batch_message, batch_attempt, batch_generation, _ in batch],
                        worker_id, exc,
                    )
                finally:
                    # The outer finally settles the first queue item; these are
                    # the extra items drained into this micro-batch.
                    for _ in batch[1:]:
                        inbox.task_done()
                if deferred:
                    deferred_message, deferred_attempt, deferred_generation, deferred_body = deferred
                    try:
                        self._process_one(
                            inbox, deferred_message, deferred_attempt, worker_id, deferred_generation, deferred_body
                        )
                    finally:
                        inbox.task_done()
            finally:
                inbox.task_done()

    # ------------------------------------------------------------------
    # Process lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        properties = mqtt.Properties(mqtt.PacketTypes.CONNECT)
        properties.SessionExpiryInterval = SESSION_EXPIRY_SECONDS
        self.client.connect_async(
            MQTT_HOST, MQTT_PORT, keepalive=30,
            clean_start=False, properties=properties,
        )
        self.client.loop_start()
        self._start_workers()
        self.supervisor_thread = threading.Thread(
            target=self._supervise, name=f"mqtt-gateway-supervisor-{GATEWAY_ID}", daemon=True
        )
        self.supervisor_thread.start()
        self.command_thread = threading.Thread(target=self._command_loop, name="mqtt-command-publisher", daemon=True)
        self.command_thread.start()

    def shutdown(self) -> None:
        with self._shutdown_lock:
            if self._shutdown_done:
                return
            self._shutdown_done = True
        self.stop_event.set()
        self._invalidate_connection()
        # Take the reconnect lock so a supervisor reconnect in flight either
        # observes stop_event and tears its fresh connection down, or we tear
        # it down here; shutdown returns with no new connection or loop left.
        with self._reconnect_lock:
            try:
                self._disconnect()
            except Exception:  # pragma: no cover - paho defensive
                pass
            try:
                self.client.loop_stop()
            except Exception:  # pragma: no cover - paho defensive
                pass
        with self._generation_lock:
            self._connection_valid = False
        self._connected.clear()
        for thread in self.worker_threads:
            thread.join(timeout=2)
        if self.command_thread:
            self.command_thread.join(timeout=2)
        if self.supervisor_thread:
            self.supervisor_thread.join(timeout=3)
        self.api_client.close()

    def monitor_once(self) -> int:
        """Return 0 while every critical thread is alive, else 1 (after writing a failing health file)."""
        workers_alive = bool(self.worker_threads) and all(thread.is_alive() for thread in self.worker_threads)
        command_alive = bool(self.command_thread and self.command_thread.is_alive())
        supervisor_alive = bool(self.supervisor_thread and self.supervisor_thread.is_alive())
        if not (workers_alive and command_alive and supervisor_alive):
            log.critical(
                "gateway critical thread died (workers=%s command=%s supervisor=%s); failing health and exiting for restart",
                workers_alive, command_alive, supervisor_alive,
            )
            self._write_health()
            return 1
        return 0

    def _start_workers(self) -> None:
        for index, inbox in enumerate(self.inboxes):
            thread = threading.Thread(
                target=self._worker_loop, args=(inbox, index), name=f"mqtt-uplink-{index}", daemon=True
            )
            self.worker_threads.append(thread)
            thread.start()

    def _write_health(self) -> None:
        payload = {
            "updatedAt": time.time(),
            "connected": self.connected,
            "subscribed": self._subscribed.is_set(),
            "workersAlive": bool(self.worker_threads) and all(thread.is_alive() for thread in self.worker_threads),
            "commandWorkerAlive": bool(self.command_thread and self.command_thread.is_alive()),
            "supervisorAlive": bool(self.supervisor_thread and self.supervisor_thread.is_alive()),
            "connectionGeneration": self._generation,
            "backpressureDisconnects": self.backpressure_disconnects,
            "queueDepth": sum(inbox.qsize() for inbox in self.inboxes),
        }
        HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = HEALTH_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        temporary.replace(HEALTH_FILE)

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
        if not self.connected:
            return
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

    def run(self) -> int:
        self.start()
        exit_code = 0
        try:
            while not self.stop_event.wait(1.0):
                if self.monitor_once() != 0:
                    exit_code = 1
                    break
                self._write_health()
        finally:
            self.shutdown()
            self._write_health()
        return exit_code


if __name__ == "__main__":
    raise SystemExit(Gateway().run())
