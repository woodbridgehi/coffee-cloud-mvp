from __future__ import annotations

import uuid
from typing import Any

from psycopg.types.json import Jsonb


class OrderRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    @staticmethod
    def _lock_suffix(for_update: bool) -> str:
        return " for update" if for_update else ""

    def find_with_terminal(self, order_id: uuid.UUID, *, for_update: bool = False) -> dict[str, Any] | None:
        return self.connection.execute(
            f"""select o.*,t.device_id,t.store_id from sales_order o
                  join terminal t on t.id=o.terminal_id where o.id=%s{self._lock_suffix(for_update)}""",
            (order_id,),
        ).fetchone()

    def find_idempotent(self, terminal_id: int, idempotency_key: str, *, for_update: bool = True) -> dict[str, Any] | None:
        return self.connection.execute(
            f"""select o.*,t.device_id,t.store_id from sales_order o
                  join terminal t on t.id=o.terminal_id
                 where o.terminal_id=%s and o.idempotency_key=%s{self._lock_suffix(for_update)}""",
            (terminal_id, idempotency_key),
        ).fetchone()

    def active_count(self, terminal_id: int) -> int:
        row = self.connection.execute(
            """select count(*) as count from sales_order where terminal_id=%s
                 and status in ('QUEUED','DISPATCHED','ACCEPTED','MAKING')""",
            (terminal_id,),
        ).fetchone()
        return int(row["count"])

    def insert(
        self,
        *,
        order_id: uuid.UUID,
        order_no: str,
        terminal_id: int,
        access_token_hash: str,
        idempotency_key: str,
        request_digest: str,
        order_status: str,
        payment_mode: str,
        payment_status: str,
        product: dict[str, Any],
    ) -> dict[str, Any]:
        return self.connection.execute(
            """insert into sales_order(
                   id,order_no,terminal_id,access_token_hash,idempotency_key,request_digest,status,
                   payment_mode,payment_status,currency,total_amount_minor,
                   recipe_id,recipe_version,sku_code,product_name,product_snapshot)
                 values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *""",
            (
                order_id, order_no, terminal_id, access_token_hash, idempotency_key, request_digest,
                order_status, payment_mode, payment_status, product["currency"], product["priceMinor"],
                product["recipeId"], product["recipeVersion"], product["skuCode"], product["name"],
                Jsonb(product),
            ),
        ).fetchone()

    def insert_initial_transition(
        self, order_id: uuid.UUID, status: str, reason: str, payload: dict[str, Any]
    ) -> None:
        self.connection.execute(
            """insert into order_transition(order_id,revision,from_status,to_status,actor,reason,payload_json)
                 values(%s,0,null,%s,'public-api',%s,%s)""",
            (order_id, status, reason, Jsonb(payload)),
        )

    def insert_test_free_job(
        self, *, job_id: uuid.UUID, task_id: str, order_id: uuid.UUID, terminal_id: int,
        planned_duration_seconds: float | None,
    ) -> None:
        self.connection.execute(
            """insert into production_job(id,task_id,order_id,terminal_id,status,planned_duration_seconds)
                 values(%s,%s,%s,%s,'QUEUED',%s)""",
            (job_id, task_id, order_id, terminal_id, planned_duration_seconds),
        )

    def job(self, order_id: uuid.UUID) -> dict[str, Any] | None:
        return self.connection.execute(
            "select * from production_job where order_id=%s", (order_id,)
        ).fetchone()

    def transitions(self, order_id: uuid.UUID) -> list[dict[str, Any]]:
        return self.connection.execute(
            "select * from order_transition where order_id=%s order by revision", (order_id,)
        ).fetchall()

    def queue_position(self, order: dict[str, Any]) -> int:
        if order["status"] != "QUEUED":
            return 0
        row = self.connection.execute(
            """select count(*) as count from sales_order
                 where terminal_id=%s and status='QUEUED' and created_at <= %s""",
            (order["terminal_id"], order["created_at"]),
        ).fetchone()
        return int(row["count"])

    def cancel_job(self, order_id: uuid.UUID) -> None:
        self.connection.execute(
            """update production_job set status='CANCELLED',revision=revision+1,
                 updated_at=now(),completed_at=now() where order_id=%s""",
            (order_id,),
        )

    def update_payment_status(self, order_id: uuid.UUID, status: str) -> None:
        self.connection.execute(
            "update sales_order set payment_status=%s,updated_at=now() where id=%s",
            (status, order_id),
        )

    def list_admin(
        self, *, device_id: str | None, order_status: str | None, limit: int
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if device_id:
            clauses.append("t.device_id=%s")
            params.append(device_id)
        if order_status:
            clauses.append("o.status=%s")
            params.append(order_status.upper())
        where = " where " + " and ".join(clauses) if clauses else ""
        params.append(limit)
        return self.connection.execute(
            f"""select o.*,t.device_id,t.store_id,j.task_id,j.status as production_status,
                       j.progress,j.current_step_name
                  from sales_order o join terminal t on t.id=o.terminal_id
                  left join production_job j on j.order_id=o.id
                  {where} order by o.created_at desc limit %s""",
            params,
        ).fetchall()

    def next_transition_revision(self, order_id: uuid.UUID) -> int:
        return self.connection.execute(
            "select coalesce(max(revision),-1)+1 as revision from order_transition where order_id=%s",
            (order_id,),
        ).fetchone()["revision"]

    def update_transition_state(
        self, order_id: uuid.UUID, target: str, now_at: Any,
        started_at: Any, completed_at: Any, cancelled_at: Any,
    ) -> dict[str, Any]:
        return self.connection.execute(
            """update sales_order set status=%s,updated_at=%s,started_at=%s,
                 completed_at=%s,cancelled_at=%s where id=%s returning *""",
            (target, now_at, started_at, completed_at, cancelled_at, order_id),
        ).fetchone()

    def insert_transition(
        self, order_id: uuid.UUID, revision: int, from_status: str, target: str,
        actor: str, reason: str | None, payload: dict[str, Any] | None,
    ) -> None:
        self.connection.execute(
            """insert into order_transition(order_id,revision,from_status,to_status,actor,reason,payload_json)
                 values(%s,%s,%s,%s,%s,%s,%s)""",
            (order_id, revision, from_status, target, actor, reason, Jsonb(payload) if payload else None),
        )
