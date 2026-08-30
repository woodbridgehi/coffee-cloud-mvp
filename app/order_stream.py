"""Dual-channel SSE: SQL refreshes only on durable events, Redis on progress."""
from __future__ import annotations

import asyncio
import json
import uuid

from starlette.concurrency import run_in_threadpool

from .order_events import ORDER_CHANGED, OrderEventBroker
from .order_logic import TERMINAL_ORDER_STATUSES
from .services.public_orders import PublicOrderService


async def order_stream(broker: OrderEventBroker, service: PublicOrderService,
                       order_id: uuid.UUID, access_token: str | None):
    queue = broker.subscribe(str(order_id), asyncio.get_running_loop())

    async def refresh_order():
        snapshot = await run_in_threadpool(service.get, order_id, access_token, include_progress=False)
        job = snapshot.get("production")
        if job:
            broker.watch_progress(queue, snapshot["deviceId"], job["taskId"])
        # Register both subscriptions before the final Redis read to close the gap.
        return await run_in_threadpool(service.with_live_progress, snapshot)

    try:
        snapshot = await refresh_order()
        while True:
            yield f"event: order\ndata: {json.dumps(snapshot, default=str, separators=(',', ':'))}\n\n"
            if snapshot["status"] in TERMINAL_ORDER_STATUSES:
                return
            while True:
                try:
                    flags = await asyncio.wait_for(queue.get(), timeout=15)
                    break
                except TimeoutError:
                    yield ": keepalive\n\n"
            await asyncio.sleep(0.05)
            while not queue.empty():
                flags |= queue.get_nowait()
            if flags & ORDER_CHANGED:
                snapshot = await refresh_order()
            else:
                # No SQL query or transaction on the progress notification path.
                snapshot = await run_in_threadpool(service.with_live_progress, snapshot)
    finally:
        broker.unsubscribe(str(order_id), queue)
