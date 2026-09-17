from __future__ import annotations

from typing import Any


class DispatchRepository:
    """Durable, coalescing requests to dispatch a terminal's next queued job."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def enqueue(self, terminal_id: int, reason: str) -> None:
        self.connection.execute(
            """insert into terminal_dispatch_request(terminal_id,reason)
                 values(%s,%s)
                 on conflict (terminal_id) do update
                    set reason=excluded.reason, requested_at=now(), revision=terminal_dispatch_request.revision+1,
                        status=case when terminal_dispatch_request.status='PROCESSING'
                                    then 'PROCESSING' else 'PENDING' end,
                        next_attempt_at=now(), last_error=null""",
            (terminal_id, reason[:120]),
        )

    def repair_missing(self, limit: int) -> int:
        """Rebuild lost wakeups without changing any existing revision or lease."""
        rows = self.connection.execute(
            """insert into terminal_dispatch_request(terminal_id,reason)
               select distinct j.terminal_id,'queued-order-recovery'
                 from production_job j join sales_order o on o.id=j.order_id
                where j.status='QUEUED' and o.status='QUEUED'
                  and not exists (select 1 from terminal_dispatch_request r
                                  where r.terminal_id=j.terminal_id)
                order by j.terminal_id limit %s
               on conflict (terminal_id) do nothing returning terminal_id""",
            (limit,),
        ).fetchall()
        return len(rows)

    def claim(self, worker_id: str) -> dict[str, Any] | None:
        request = self.connection.execute(
            """select * from terminal_dispatch_request
                 where (status in ('PENDING','RETRY') and next_attempt_at<=now())
                    or (status='PROCESSING' and locked_until<now())
                 order by requested_at for update skip locked limit 1"""
        ).fetchone()
        if not request:
            return None
        return self.connection.execute(
            """update terminal_dispatch_request set status='PROCESSING',locked_by=%s,
                 locked_until=now()+interval '30 seconds' where terminal_id=%s returning *""",
            (worker_id, request["terminal_id"]),
        ).fetchone()

    def complete(self, terminal_id: int, revision: int) -> None:
        # A request raised while this one was being processed increments revision,
        # so it remains queued for the following dispatch pass.
        deleted = self.connection.execute(
            "delete from terminal_dispatch_request where terminal_id=%s and revision=%s returning terminal_id",
            (terminal_id, revision),
        ).fetchone()
        if deleted is None:
            self.connection.execute(
                """update terminal_dispatch_request set status='PENDING',next_attempt_at=now(),
                     locked_by=null,locked_until=null
                     where terminal_id=%s and status='PROCESSING'""",
                (terminal_id,),
            )

    def retry(self, terminal_id: int, revision: int, error: str) -> None:
        retried = self.connection.execute(
            """update terminal_dispatch_request set status='RETRY',attempt_count=attempt_count+1,
                 next_attempt_at=now()+(least(30,power(2,least(attempt_count+1,5)))::text||' seconds')::interval,
                 last_error=%s,locked_by=null,locked_until=null
                 where terminal_id=%s and revision=%s returning terminal_id""",
            (error[:1000], terminal_id, revision),
        ).fetchone()
        if retried is None:
            self.connection.execute(
                """update terminal_dispatch_request set status='PENDING',next_attempt_at=now(),
                     last_error=%s,locked_by=null,locked_until=null
                     where terminal_id=%s and status='PROCESSING'""",
                (error[:1000], terminal_id),
            )
