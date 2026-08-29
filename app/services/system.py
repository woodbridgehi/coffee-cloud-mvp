from __future__ import annotations

import logging
import threading
import time

from ..db import UnitOfWork
from ..protocol import utc_now
from ..repositories import SystemRepository
from .errors import ServiceError
from .presenters import iso


class SystemService:
    def __init__(self, uow: UnitOfWork, version: str, logger: logging.Logger) -> None:
        self.uow = uow
        self.version = version
        self.logger = logger
        self._readiness_lock = threading.Lock()
        self._readiness_checked_at: float | None = None
        self._readiness_ok = False

    def health(self) -> dict[str, str]:
        """Cheap process liveness check; it must never consume a database connection."""
        return {"status": "ok", "version": self.version, "time": iso(utc_now()) or ""}

    def readiness(self) -> dict[str, str]:
        """Dependency readiness check with a short cache to avoid probe stampedes."""
        with self._readiness_lock:
            now = time.monotonic()
            if self._readiness_checked_at is None or now - self._readiness_checked_at >= 5.0:
                try:
                    with self.uow.transaction() as connection:
                        SystemRepository(connection).ping()
                except Exception as exc:
                    self._readiness_ok = False
                    self._readiness_checked_at = now
                    self.logger.exception("readiness dependency check failed")
                    raise ServiceError(503, "database unavailable") from exc
                self._readiness_ok = True
                self._readiness_checked_at = now
            if not self._readiness_ok:
                raise ServiceError(503, "database unavailable")
        return {"status": "ready", "version": self.version, "database": "ok", "time": iso(utc_now()) or ""}
