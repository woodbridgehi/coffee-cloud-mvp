from __future__ import annotations

import json
import logging
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from redis import Redis
from redis.exceptions import RedisError


class TelemetryCache:
    """Best-effort hot state cache; PostgreSQL remains the source of truth for orders."""

    def __init__(self, url: str | None, *, online_ttl_seconds: int, logger: logging.Logger) -> None:
        self.url = url
        self.online_ttl_seconds = online_ttl_seconds
        self.logger = logger
        self.client: Redis | None = None
        self._local = threading.local()
        self._terminal_ids: dict[str, tuple[int, float]] = {}
        self._terminal_ids_lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def start(self) -> None:
        if not self.url:
            return
        try:
            client = Redis.from_url(self.url, decode_responses=True, socket_connect_timeout=0.5, socket_timeout=0.5)
            client.ping()
            self.client = client
            self.logger.info("telemetry Redis hot-state cache connected")
        except RedisError as exc:
            self.client = None
            self.logger.warning("telemetry Redis unavailable; using PostgreSQL fallback: %s", exc)

    def close(self) -> None:
        if self.client:
            self.client.close()
            self.client = None

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _state_key(device_id: str) -> str:
        return f"coffee:telemetry:device:{device_id}"

    @staticmethod
    def _terminal_key(device_id: str) -> str:
        return f"coffee:telemetry:terminal:{device_id}"

    @staticmethod
    def _online_key(device_id: str) -> str:
        return f"coffee:telemetry:online:{device_id}"

    @staticmethod
    def _dirty_key() -> str:
        return "coffee:telemetry:dirty"

    def terminal_id(self, device_id: str) -> int | None:
        with self._terminal_ids_lock:
            cached = self._terminal_ids.get(device_id)
            if cached and cached[1] > time.monotonic():
                return cached[0]
        if not self.client:
            return None
        try:
            value = self.client.get(self._terminal_key(device_id))
            terminal_id = int(value) if value is not None else None
            if terminal_id is not None:
                with self._terminal_ids_lock:
                    self._terminal_ids[device_id] = (terminal_id, time.monotonic() + 900)
            return terminal_id
        except (RedisError, ValueError) as exc:
            self.logger.warning("telemetry terminal cache read failed: %s", exc)
            return None

    def remember_terminal(self, device_id: str, terminal_id: int) -> None:
        with self._terminal_ids_lock:
            self._terminal_ids[device_id] = (terminal_id, time.monotonic() + 900)
        if not self.client:
            return
        try:
            self.client.set(self._terminal_key(device_id), terminal_id, ex=900)
        except RedisError as exc:
            self.logger.warning("telemetry terminal cache write failed: %s", exc)

    def _write(self, device_id: str, values: dict[str, str]) -> bool:
        if not self.client:
            return False
        buffer: dict[str, dict[str, str]] | None = getattr(self._local, "write_buffer", None)
        if buffer is not None:
            buffer.setdefault(device_id, {}).update(values)
            return True
        try:
            state_key = self._state_key(device_id)
            pipe = self.client.pipeline(transaction=False)
            pipe.hset(state_key, mapping=values)
            pipe.hincrby(state_key, "_revision", 1)
            result = pipe.execute()
            revision = int(result[-1])
            self.client.zadd(self._dirty_key(), {device_id: revision})
            return True
        except RedisError as exc:
            self.logger.warning("telemetry cache write failed; using PostgreSQL fallback: %s", exc)
            return False

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Coalesce one gateway HTTP batch into a single Redis pipeline."""
        if not self.client or getattr(self._local, "write_buffer", None) is not None:
            yield
            return
        buffer: dict[str, dict[str, str]] = {}
        self._local.write_buffer = buffer
        try:
            yield
            if not buffer:
                return
            pipe = self.client.pipeline(transaction=False)
            dirty_scores: dict[str, int] = {}
            score = time.time_ns()
            for offset, (device_id, values) in enumerate(buffer.items()):
                pipe.hset(self._state_key(device_id), mapping=values)
                pipe.hincrby(self._state_key(device_id), "_revision", 1)
                dirty_scores[device_id] = score + offset
            pipe.zadd(self._dirty_key(), dirty_scores)
            pipe.execute()
        except RedisError as exc:
            self.logger.warning("telemetry batch cache write failed: %s", exc)
            raise
        finally:
            del self._local.write_buffer

    def heartbeat(self, device_id: str, terminal_id: int, payload: dict[str, Any]) -> bool:
        timestamp = self._now()
        values = {
            "terminalId": str(terminal_id), "connectionStatus": "online",
            "lastSeenAt": timestamp, "lastHeartbeatAt": timestamp,
            "reportedStatus": json.dumps({
                "deviceStatus": payload.get("deviceStatus"), "currentTaskId": payload.get("currentTaskId"),
                "currentTaskState": payload.get("currentTaskState"), "currentTaskRevision": payload.get("currentTaskRevision"),
                "deliveries": payload.get("deliveries"), "sentAt": payload.get("sentAt"),
            }, separators=(",", ":")),
        }
        if not self._write(device_id, values):
            return False
        try:
            self.client.set(self._online_key(device_id), "1", ex=self.online_ttl_seconds)  # type: ignore[union-attr]
            return True
        except RedisError as exc:
            self.logger.warning("telemetry online TTL refresh failed: %s", exc)
            return False

    def state(self, device_id: str, terminal_id: int, payload: dict[str, Any]) -> bool:
        return self._write(device_id, {
            "terminalId": str(terminal_id), "lastSeenAt": self._now(),
            "reportedStatus": json.dumps(payload, separators=(",", ":")),
        })

    def progress(self, device_id: str, terminal_id: int, event: dict[str, Any]) -> bool:
        """Coalesce lossy production progress while preserving terminal lifecycle events."""
        return self._write(device_id, {
            "terminalId": str(terminal_id), "lastSeenAt": self._now(),
            "progressPayload": json.dumps(event, separators=(",", ":")),
        })

    def presence(self, device_id: str, terminal_id: int, online: bool) -> tuple[bool, bool]:
        if not self.client:
            return False, False
        try:
            was_online = bool(self.client.exists(self._online_key(device_id)))
            cached = self._write(device_id, {
                "terminalId": str(terminal_id), "connectionStatus": "online" if online else "offline",
                "lastSeenAt": self._now(),
            })
            if not cached:
                return False, was_online
            if online:
                self.client.set(self._online_key(device_id), "1", ex=self.online_ttl_seconds)
            else:
                self.client.delete(self._online_key(device_id))
            return True, was_online
        except RedisError as exc:
            self.logger.warning("telemetry presence cache failed: %s", exc)
            return False, False

    def claim_dirty(self, limit: int) -> list[tuple[str, dict[str, str]]]:
        if not self.client:
            return []
        try:
            claimed = self.client.zpopmin(self._dirty_key(), count=limit)
            device_ids = [str(item[0]) for item in claimed]
            if not device_ids:
                return []
            pipe = self.client.pipeline(transaction=False)
            for device_id in device_ids:
                pipe.hgetall(self._state_key(device_id))
            states = pipe.execute()
            return [(device_id, state) for device_id, state in zip(device_ids, states) if state.get("terminalId")]
        except RedisError as exc:
            self.logger.warning("telemetry dirty batch claim failed: %s", exc)
            return []

    def restore_dirty(self, device_ids: list[str]) -> None:
        if not self.client or not device_ids:
            return
        try:
            self.client.zadd(self._dirty_key(), {device_id: 0 for device_id in device_ids})
        except RedisError as exc:
            self.logger.error("telemetry dirty batch restore failed: %s", exc)

    def dirty_count(self) -> int:
        if not self.client:
            return 0
        try:
            return int(self.client.zcard(self._dirty_key()))
        except RedisError:
            return -1
