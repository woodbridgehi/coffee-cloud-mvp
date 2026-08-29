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

    def claim(self, worker_id: str) -> dict[str, Any] | None:
        request = self.connection.execute(
            """select * from terminal_dispatch_request
                 where status in ('PENDING','RETRY') and next_attempt_at<=now()
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
        self.connection.execute(
            "delete from terminal_dispatch_request where terminal_id=%s and revision=%s",
            (terminal_id, revision),
        )

    def retry(self, terminal_id: int, revision: int, error: str) -> None:
        self.connection.execute(
            """update terminal_dispatch_request set status='RETRY',attempt_count=attempt_count+1,
                 next_attempt_at=now()+(least(30,power(2,least(attempt_count+1,5)))::text||' seconds')::interval,
                 last_error=%s,locked_by=null,locked_until=null
                 where terminal_id=%s and revision=%s""",
            (error[:1000], terminal_id, revision),
        )
