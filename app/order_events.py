"""PostgreSQL-backed transaction notifications for public order SSE streams."""
from __future__ import annotations

import asyncio
import logging
import threading
from collections import defaultdict

import psycopg


class OrderEventBroker:
    def __init__(self, database_url: str, *, logger: logging.Logger) -> None:
        self.database_url = database_url
        self.logger = logger
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.subscribers: dict[str, set[tuple[asyncio.AbstractEventLoop, asyncio.Queue[None]]]] = defaultdict(set)

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, name="order-sse-listener", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)

    def subscribe(self, order_id: str, loop: asyncio.AbstractEventLoop) -> asyncio.Queue[None]:
        queue: asyncio.Queue[None] = asyncio.Queue(maxsize=1)
        with self.lock:
            self.subscribers[order_id].add((loop, queue))
        return queue

    def unsubscribe(self, order_id: str, queue: asyncio.Queue[None]) -> None:
        with self.lock:
            entries = self.subscribers.get(order_id, set())
            entries = {entry for entry in entries if entry[1] is not queue}
            if entries:
                self.subscribers[order_id] = entries
            else:
                self.subscribers.pop(order_id, None)

    def subscriber_count(self) -> int:
        with self.lock:
            return sum(len(entries) for entries in self.subscribers.values())

    @staticmethod
    def _offer(queue: asyncio.Queue[None]) -> None:
        if queue.empty():
            queue.put_nowait(None)

    def _publish(self, order_id: str) -> None:
        with self.lock:
            subscribers = tuple(self.subscribers.get(order_id, ()))
        for loop, queue in subscribers:
            loop.call_soon_threadsafe(self._offer, queue)

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                with psycopg.connect(self.database_url, autocommit=True) as connection:
                    connection.execute("listen coffee_order_updates")
                    self.logger.info("order SSE PostgreSQL listener connected")
                    while not self.stop_event.is_set():
                        for notification in connection.notifies(timeout=1, stop_after=100):
                            self._publish(notification.payload)
            except Exception as exc:
                self.logger.warning("order SSE listener reconnecting after error: %s", exc)
                self.stop_event.wait(1)
