from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from ..database import Database


class UnitOfWork:
    """Owns application transaction boundaries without exposing them to routes."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        with self.database.connect() as connection:
            yield connection
