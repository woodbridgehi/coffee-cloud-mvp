from __future__ import annotations

import uuid
from typing import Any

from psycopg.types.json import Jsonb


class AdjudicationRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def find(self, order_id: uuid.UUID, key: str) -> dict[str, Any] | None:
        return self.connection.execute(
            "select * from order_adjudication where order_id=%s and idempotency_key=%s",
            (order_id, key),
        ).fetchone()

    def insert(
        self,
        order_id: uuid.UUID,
        task_id: str,
        key: str,
        digest: str,
        response: dict[str, Any],
    ) -> None:
        self.connection.execute(
            """insert into order_adjudication(order_id,task_id,idempotency_key,request_digest,response_json)
                 values(%s,%s,%s,%s,%s)""",
            (order_id, task_id, key, digest, Jsonb(response)),
        )
