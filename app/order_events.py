"""Per-process fanout of durable SQL and ephemeral Redis notifications."""
from __future__ import annotations

import asyncio
import logging
import threading
from collections import defaultdict

import psycopg
from redis import Redis

from .live_progress import PROGRESS_CHANNEL, progress_key

PROGRESS_CHANGED = 1
ORDER_CHANGED = 2
Subscription = tuple[asyncio.AbstractEventLoop, asyncio.Queue[int]]


class OrderEventBroker:
    def __init__(self, database_url: str, *, logger: logging.Logger, redis_url: str | None = None) -> None:
        self.database_url = database_url
        self.redis_url = redis_url
        self.logger = logger
        self.stop_event = threading.Event()
        self.postgres_connected = threading.Event()
        self.redis_connected = threading.Event()
        self.threads: list[threading.Thread] = []
        self.lock = threading.Lock()
        self.subscribers: dict[str, set[Subscription]] = defaultdict(set)
        self.progress_subscribers: dict[str, set[Subscription]] = defaultdict(set)
        self.progress_keys: dict[asyncio.Queue[int], str] = {}

    def start(self) -> None:
        self.stop_event.clear()
        self.threads = [threading.Thread(target=self._run, name="order-sse-listener", daemon=True)]
        if self.redis_url:
            self.threads.append(threading.Thread(target=self._redis_run, name="progress-sse-listener", daemon=True))
        for thread in self.threads:
            thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=3)
        self.postgres_connected.clear()
        self.redis_connected.clear()

    def subscribe(self, order_id: str, loop: asyncio.AbstractEventLoop) -> asyncio.Queue[int]:
        queue: asyncio.Queue[int] = asyncio.Queue(maxsize=1)
        with self.lock:
            self.subscribers[order_id].add((loop, queue))
        return queue

    def watch_progress(self, queue: asyncio.Queue[int], device_id: str, task_id: str) -> None:
        key = progress_key(device_id, task_id)
        with self.lock:
            if self.progress_keys.get(queue) == key:
                return
            self._remove_progress(queue)
            self.progress_keys[queue] = key
            self.progress_subscribers[key].add((asyncio.get_running_loop(), queue))

    def _remove_progress(self, queue: asyncio.Queue[int]) -> None:
        key = self.progress_keys.pop(queue, None)
        if key:
            entries = {entry for entry in self.progress_subscribers[key] if entry[1] is not queue}
            if entries:
                self.progress_subscribers[key] = entries
            else:
                self.progress_subscribers.pop(key, None)

    def unsubscribe(self, order_id: str, queue: asyncio.Queue[int]) -> None:
        with self.lock:
            entries = self.subscribers.get(order_id, set())
            entries = {entry for entry in entries if entry[1] is not queue}
            if entries:
                self.subscribers[order_id] = entries
            else:
                self.subscribers.pop(order_id, None)
            self._remove_progress(queue)

    def subscriber_count(self) -> int:
        with self.lock:
            return sum(len(entries) for entries in self.subscribers.values())

    @staticmethod
    def _offer(queue: asyncio.Queue[int], flags: int) -> None:
        # A progress burst must not erase a pending SQL refresh.
        if not queue.empty():
            flags |= queue.get_nowait()
        queue.put_nowait(flags)

    def _send(self, subscribers: tuple[Subscription, ...], flags: int) -> None:
        for loop, queue in subscribers:
            try:
                loop.call_soon_threadsafe(self._offer, queue, flags)
            except RuntimeError:
                pass  # Event loop already disconnected.

    def _publish(self, order_id: str) -> None:
        with self.lock:
            subscribers = tuple(self.subscribers.get(order_id, ()))
        self._send(subscribers, ORDER_CHANGED)

    def _publish_progress(self, key: str) -> None:
        with self.lock:
            subscribers = tuple(self.progress_subscribers.get(key, ()))
        self._send(subscribers, PROGRESS_CHANGED)

    def _resync(self, flags: int) -> None:
        with self.lock:
            subscribers = tuple(entry for entries in self.subscribers.values() for entry in entries)
        self._send(subscribers, flags)

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                with psycopg.connect(self.database_url, autocommit=True, connect_timeout=2) as connection:
                    connection.execute("listen coffee_order_updates")
                    self.postgres_connected.set()
                    self.logger.info("order SSE PostgreSQL listener connected")
                    self._resync(ORDER_CHANGED)
                    while not self.stop_event.is_set():
                        for notification in connection.notifies(timeout=1, stop_after=100):
                            self._publish(notification.payload)
            except Exception as exc:
                self.postgres_connected.clear()
                self.logger.warning("order SSE listener reconnecting after error: %s", exc)
                self.stop_event.wait(1)

    def _redis_run(self) -> None:
        while not self.stop_event.is_set():
            try:
                with Redis.from_url(self.redis_url, decode_responses=True,
                                    socket_connect_timeout=1, socket_timeout=2) as client:
                    with client.pubsub() as subscription:
                        subscription.subscribe(PROGRESS_CHANNEL)
                        while not self.stop_event.is_set():
                            message = subscription.get_message(timeout=1)
                            if not message:
                                continue
                            if message["type"] == "subscribe":
                                self.redis_connected.set()
                                self.logger.info("progress SSE Redis listener connected")
                                # Pub/Sub has no replay. Includes automatic resubscriptions.
                                self._resync(PROGRESS_CHANGED)
                            elif message["type"] == "message":
                                self._publish_progress(str(message["data"]))
            except Exception as exc:
                self.redis_connected.clear()
                self.logger.warning("progress SSE listener reconnecting after error: %s", exc)
                self.stop_event.wait(1)
