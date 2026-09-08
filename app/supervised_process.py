"""Exit the container after sustained failed health so Docker can restart it.

The supervisor is a separate process: a stuck child thread cannot stop its timer.
"""
from __future__ import annotations

import logging
import os
import random
import signal
import subprocess
import sys
import time
from pathlib import Path


class FailureWindow:
    def __init__(self, grace: float) -> None:
        self.grace = grace
        self.failed_at: float | None = None

    def expired(self, healthy: bool, now: float) -> bool:
        if healthy:
            self.failed_at = None
        elif self.failed_at is None:
            self.failed_at = now
        return self.failed_at is not None and now - self.failed_at >= self.grace


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"gateway", "domain"}:
        return 2
    kind = sys.argv[1]
    module = "app.mqtt_gateway" if kind == "gateway" else "app.domain_worker"
    filename = os.getenv("GATEWAY_HEALTH_FILE" if kind == "gateway" else "WORKER_HEALTH_FILE",
                         "/tmp/mqtt-gateway.json" if kind == "gateway" else "/tmp/domain-worker.json")
    Path(filename).unlink(missing_ok=True)
    child = subprocess.Popen([sys.executable, "-m", module], start_new_session=True)
    stopping = False

    def stop(signum, _frame):
        nonlocal stopping
        stopping = True
        if child.poll() is None:
            os.killpg(child.pid, signum)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    # A dependency hiccup must not immediately restart the whole fleet of services.
    window = FailureWindow(180 + random.uniform(0, 60))
    try:
        while child.poll() is None and not stopping:
            try:
                health = subprocess.run([sys.executable, "-m", "app.file_healthcheck", kind, filename],
                                        timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                healthy = health.returncode == 0
            except subprocess.TimeoutExpired:
                healthy = False
            if window.expired(healthy, time.monotonic()):
                logging.error("%s health failed continuously; exiting container for restart", kind)
                return 1
            time.sleep(5)
        return 0 if stopping else (child.returncode or 0)
    finally:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
