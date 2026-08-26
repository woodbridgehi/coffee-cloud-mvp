from __future__ import annotations

from typing import Any


class SystemRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def ping(self) -> None:
        self.connection.execute("select 1").fetchone()
