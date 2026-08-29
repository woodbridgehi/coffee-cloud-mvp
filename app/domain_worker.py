"""Run singleton background domain work outside the horizontally scaled API service."""
from __future__ import annotations

import logging
import json
import os
import signal
import threading
import time
from pathlib import Path

from .main import (
    background_worker_service,
    database,
    device_identity_service,
    domain_worker,
    offline_monitor,
    telemetry_cache,
)


logger = logging.getLogger("coffee-domain-worker")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
HEALTH_FILE = Path(os.getenv("WORKER_HEALTH_FILE", "/tmp/domain-worker.json"))


def write_health() -> None:
    payload = {
        "updatedAt": time.time(),
        "workers": domain_worker.health_snapshot(),
        "offline": {
            "alive": offline_monitor.thread.is_alive(),
            "lastSuccessAt": offline_monitor.last_success_at,
            "lastError": offline_monitor.last_error,
        },
    }
    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = HEALTH_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    temporary.replace(HEALTH_FILE)


def main() -> None:
    stop_event = threading.Event()

    def stop(_signal: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    offline_started = False
    domain_started = False
    database.initialize(run_migrations=False)
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
        write_health()
        while not stop_event.wait(5):
            write_health()
    finally:
        if domain_started:
            domain_worker.stop()
        if offline_started:
            offline_monitor.stop()
        telemetry_cache.close()
        database.close()


if __name__ == "__main__":
    main()
