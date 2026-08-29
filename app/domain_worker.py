"""Run singleton background domain work outside the horizontally scaled API service."""
from __future__ import annotations

import logging
import signal
import threading

from .main import (
    background_worker_service,
    database,
    device_identity_service,
    domain_worker,
    offline_monitor,
    telemetry_cache,
)


logger = logging.getLogger("coffee-domain-worker")


def main() -> None:
    stop_event = threading.Event()

    def stop(_signal: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    offline_started = False
    domain_started = False
    database.initialize()
    telemetry_cache.start()
    try:
        device_identity_service.bootstrap_device()
        background_worker_service.reconcile_stored_command_events()
        background_worker_service.reconcile_stored_order_events()
        offline_monitor.scan_once()
        offline_monitor.start()
        offline_started = True
        domain_worker.start()
        domain_started = True
        logger.info("singleton domain worker started")
        stop_event.wait()
    finally:
        if domain_started:
            domain_worker.stop()
        if offline_started:
            offline_monitor.stop()
        telemetry_cache.close()
        database.close()


if __name__ == "__main__":
    main()
