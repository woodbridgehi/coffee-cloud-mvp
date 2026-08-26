from __future__ import annotations

import logging

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

    def health(self) -> dict[str, str]:
        try:
            with self.uow.transaction() as connection:
                SystemRepository(connection).ping()
        except Exception as exc:
            self.logger.exception("health dependency check failed")
            raise ServiceError(503, "database unavailable") from exc
        return {"status": "ok", "version": self.version, "database": "ok", "time": iso(utc_now()) or ""}
