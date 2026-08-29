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

    def public_view(self, order_id: uuid.UUID) -> dict[str, Any] | None:
        """Load the complete public status projection in one database statement."""
        return self.connection.execute(
            """select o.*,t.device_id,t.store_id,to_jsonb(j) as job_json,
                      (select to_jsonb(p) from payment p where p.order_id=o.id
                        order by p.created_at desc limit 1) as payment_json,
                      (select coalesce(jsonb_agg(to_jsonb(history) order by history.revision),'[]'::jsonb)
                         from order_transition history where history.order_id=o.id) as transitions_json,
                      case when o.status='QUEUED' then
                        (select count(*) from sales_order queued where queued.terminal_id=o.terminal_id
                          and queued.status='QUEUED' and queued.created_at<=o.created_at)
                      else 0 end as queue_position_value
                 from sales_order o join terminal t on t.id=o.terminal_id
                 left join production_job j on j.order_id=o.id
                where o.id=%s""",
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

    def insert_production_job(
        self, *, job_id: uuid.UUID, task_id: str, order_id: uuid.UUID, terminal_id: int,
        planned_duration_seconds: float | None,
    ) -> None:
        """Create the queued job produced by a successful payment event."""
        self.insert_test_free_job(
            job_id=job_id, task_id=task_id, order_id=order_id,
            terminal_id=terminal_id, planned_duration_seconds=planned_duration_seconds,
        )

    def job(self, order_id: uuid.UUID) -> dict[str, Any] | None:
        return self.connection.execute(
            "select * from production_job where order_id=%s", (order_id,)
        ).fetchone()

    def job_for_command(self, command_id: int, *, for_update: bool = False) -> dict[str, Any] | None:
        suffix = " for update" if for_update else ""
        return self.connection.execute(
            "select * from production_job where command_id=%s" + suffix, (command_id,)
        ).fetchone()

    def job_for_task(self, terminal_id: int, task_id: str, *, for_update: bool = False) -> dict[str, Any] | None:
        suffix = " for update" if for_update else ""
        return self.connection.execute(
            """select j.*,o.status as order_status,o.id as sales_order_id
                 from production_job j join sales_order o on o.id=j.order_id
                where j.terminal_id=%s and j.task_id=%s""" + suffix,
            (terminal_id, task_id),
        ).fetchone()

    def update_job_expired(self, job_id: uuid.UUID, failure: dict[str, Any]) -> None:
        self.connection.execute(
            """update production_job set status='EXPIRED',revision=revision+1,
                 failure_json=%s,completed_at=now(),updated_at=now() where id=%s""",
            (Jsonb(failure), job_id),
        )

    def update_job_acknowledged(self, job_id: uuid.UUID, *, accepted: bool, payload: dict[str, Any]) -> None:
        if accepted:
            self.connection.execute(
                """update production_job set status='ACCEPTED',revision=revision+1,
                     accepted_at=coalesce(accepted_at,now()),updated_at=now() where id=%s""",
                (job_id,),
            )
            return
        self.connection.execute(
            """update production_job set status='REJECTED',revision=revision+1,failure_json=%s,
                 completed_at=now(),updated_at=now() where id=%s""",
            (Jsonb(payload), job_id),
        )

    def update_job_progress(
        self, job_id: uuid.UUID, *, progress: float, step_progress: float,
        step_id: str | None, step_name: str | None, elapsed: float | None,
        remaining: float | None, device_revision: int | None,
    ) -> None:
        self.connection.execute(
            """update production_job set progress=%s,step_progress=%s,
                 current_step_id=coalesce(%s,current_step_id),current_step_name=coalesce(%s,current_step_name),
                 elapsed_seconds=coalesce(%s,elapsed_seconds),remaining_seconds=coalesce(%s,remaining_seconds),
                 last_device_revision=greatest(last_device_revision,coalesce(%s,last_device_revision)),
                 revision=revision+1,updated_at=now() where id=%s""",
            (progress, step_progress, step_id, step_name, elapsed, remaining, device_revision, job_id),
        )

    def update_job_terminal(
        self, job_id: uuid.UUID, *, status: str, progress: float, step_progress: float,
        planned: float | None, steps: Any, failure: dict[str, Any] | None,
        elapsed: float | None, remaining: float | None, device_revision: int | None,
        accepted_at: Any, started_at: Any, completed_at: Any,
    ) -> None:
        self.connection.execute(
            """update production_job set status=%s,progress=%s,step_progress=%s,
                 planned_duration_seconds=coalesce(%s,planned_duration_seconds),
                 step_durations=coalesce(%s::jsonb,step_durations),failure_json=coalesce(%s,failure_json),
                 elapsed_seconds=coalesce(%s,elapsed_seconds),remaining_seconds=coalesce(%s,remaining_seconds),
                 last_device_revision=greatest(last_device_revision,coalesce(%s,last_device_revision)),
                 revision=revision+1,accepted_at=%s,started_at=%s,completed_at=%s,updated_at=now() where id=%s""",
            (status, progress, step_progress, planned, Jsonb(steps) if steps is not None else None,
             Jsonb(failure) if failure else None, elapsed, remaining, device_revision,
             accepted_at, started_at, completed_at, job_id),
        )

    def terminal_for_update(self, terminal_id: int) -> dict[str, Any] | None:
        return self.connection.execute("select * from terminal where id=%s for update", (terminal_id,)).fetchone()

    def active_job_exists(self, terminal_id: int) -> bool:
        return self.connection.execute(
            """select 1 from production_job where terminal_id=%s
                 and status in ('DISPATCHED','ACCEPTED','EXECUTING','HOLD','UNKNOWN') limit 1""",
            (terminal_id,),
        ).fetchone() is not None

    def next_queued_job(self, terminal_id: int) -> dict[str, Any] | None:
        return self.connection.execute(
            """select j.*,o.recipe_id,o.recipe_version,o.status as order_status
                 from production_job j join sales_order o on o.id=j.order_id
                where j.terminal_id=%s and j.status='QUEUED' and o.status='QUEUED'
                order by j.created_at for update skip locked limit 1""",
            (terminal_id,),
        ).fetchone()

    def link_command(self, job_id: uuid.UUID, command_id: int) -> None:
        self.connection.execute(
            "update production_job set command_id=%s,status='DISPATCHED',revision=revision+1,updated_at=now() where id=%s",
            (command_id, job_id),
        )

    def stored_command_events(self) -> list[dict[str, Any]]:
        return self.connection.execute(
            """select terminal_id,event_type,payload_json from terminal_event
                 where event_type in ('task.started','task.succeeded','task.failed','task.cancelled')
                 order by received_at,id"""
        ).fetchall()

    def stored_order_events(self) -> list[dict[str, Any]]:
        return self.connection.execute(
            """select terminal_id,event_type,payload_json from terminal_event
                 where event_type like 'task.%' or event_type like 'step.%'
                 order by received_at,id"""
        ).fetchall()

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

    def update_payment_outcome(self, order_id: uuid.UUID, status: str) -> None:
        self.connection.execute(
            """update sales_order set payment_status=%s,
                 status=case when status in ('CREATED','AWAITING_PAYMENT') then 'CANCELLED' else status end,
                 updated_at=now() where id=%s""",
            (status, order_id),
        )

    def update_failure(self, order_id: uuid.UUID, code: str, message: str) -> None:
        self.connection.execute(
            "update sales_order set failure_code=%s,failure_message=%s,updated_at=now() where id=%s",
            (code, message, order_id),
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
                       j.progress,j.current_step_name,j.manual_review_required,j.hold_reason
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
