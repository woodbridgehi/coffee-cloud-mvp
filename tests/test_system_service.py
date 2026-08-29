from __future__ import annotations

from contextlib import contextmanager
import logging

from app.services.system import SystemService


class FakeConnection:
    def execute(self, *_args, **_kwargs):
        return self

    def fetchone(self):
        return (1,)


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.transactions = 0

    @contextmanager
    def transaction(self):
        self.transactions += 1
        yield FakeConnection()


def test_liveness_does_not_touch_database_and_readiness_is_cached() -> None:
    uow = FakeUnitOfWork()
    service = SystemService(uow, "test", logging.getLogger("test"))

    assert service.health()["status"] == "ok"
    assert uow.transactions == 0

    assert service.readiness()["database"] == "ok"
    assert service.readiness()["database"] == "ok"
    assert uow.transactions == 1
