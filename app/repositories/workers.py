from __future__ import annotations

from typing import Any


class WorkerRepository:
    """Database operations used by background workers."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def expire_credentials(self) -> None:
        self.connection.execute(
            """update terminal_credential set status='EXPIRED'
                 where (status='GRACE' and grace_expires_at <= now())
                    or (status='ACTIVE' and expires_at is not null and expires_at <= now())"""
        )

    def mark_offline(self, cutoff: Any) -> None:
        self.connection.execute(
            """update terminal set connection_status='offline', updated_at=now()
                 where connection_status <> 'offline'
                   and (last_heartbeat_at is null or last_heartbeat_at < %s)""",
            (cutoff,),
        )

    def expired_commands(self) -> list[dict[str, Any]]:
        """Read-only, bounded and deterministic expiry candidates.

        Locking happens per command inside the expiry entry under the domain
        lock order (order -> job -> command -> outbox); this scan must never
        hold command locks itself.
        """
        return self.connection.execute(
            """select * from terminal_command where status='CREATED'
                 and expires_at is not null and expires_at <= now()
                order by id limit 200"""
        ).fetchall()

    def claim_business_event(self, worker_id: str) -> dict[str, Any] | None:
        event = self.connection.execute(
            """select * from business_outbox
                 where status in ('PENDING','RETRY') and next_attempt_at<=now()
                 order by created_at for update skip locked limit 1"""
        ).fetchone()
        if not event:
            return None
        return self.connection.execute(
            """update business_outbox set status='PROCESSING',locked_by=%s,
                 locked_until=now()+interval '30 seconds' where id=%s returning *""",
            (worker_id, event["id"]),
        ).fetchone()

    def claim_business_events(self, worker_id: str, limit: int) -> list[dict[str, Any]]:
        """Claim a batch while keeping row-level locking safe across workers."""
        return self.connection.execute(
            """with selected as (
                   select id from business_outbox
                    where status in ('PENDING','RETRY') and next_attempt_at<=now()
                    order by created_at for update skip locked limit %s
                 )
                 update business_outbox as event
                    set status='PROCESSING',locked_by=%s,
                        locked_until=now()+interval '30 seconds'
                   from selected
                  where event.id=selected.id
               returning event.*""",
            (limit, worker_id),
        ).fetchall()

    def mark_business_processed(self, event_id: Any) -> None:
        self.connection.execute(
            """update business_outbox set status='PROCESSED',processed_at=now(),
                 locked_by=null,locked_until=null where id=%s""", (event_id,)
        )

    def mark_business_retry(self, event_id: Any, error: str) -> None:
        self.connection.execute(
            """update business_outbox set status='RETRY',attempt_count=attempt_count+1,
                 next_attempt_at=now()+(least(300,power(2,least(attempt_count+1,8)))::text||' seconds')::interval,
                 last_error=%s,locked_by=null,locked_until=null where id=%s""",
            (error[:1000], event_id),
        )

    def claim_payment(self, reconcile_seconds: int) -> dict[str, Any] | None:
        payment = self.connection.execute(
            """select * from payment where status in ('CREATED','PENDING')
                 and (next_reconcile_at is null or next_reconcile_at<=now())
                 order by created_at for update skip locked limit 1"""
        ).fetchone()
        if not payment:
            return None
        self.connection.execute(
            "update payment set next_reconcile_at=now()+(%s::text||' seconds')::interval where id=%s",
            (reconcile_seconds, payment["id"]),
        )
        return payment

    def claim_refund(self) -> dict[str, Any] | None:
        return self.connection.execute(
            """select * from refund where status in ('REQUESTED','UNKNOWN','PROCESSING')
                 and (next_attempt_at is null or next_attempt_at<=now())
                 order by created_at for update skip locked limit 1"""
        ).fetchone()

    def mark_refund_attempt(self, refund_id: Any, *, set_processing_delay: bool = False) -> None:
        if set_processing_delay:
            self.connection.execute(
                "update refund set next_attempt_at=now()+interval '30 seconds' where id=%s",
                (refund_id,),
            )
        self.connection.execute(
            "update refund set attempt_count=attempt_count+1,next_attempt_at=now()+interval '30 seconds' where id=%s",
            (refund_id,),
        )

    def watchdog_rows(self, ack_timeout: int, start_timeout: int, grace_seconds: int, wait_timeout: int = 900) -> list[dict[str, Any]]:
        return self.connection.execute(
            """select c.*,j.id as job_id,j.order_id,j.status as job_status,j.planned_duration_seconds,
                      j.started_at as job_started_at
                 from terminal_command c join production_job j on j.command_id=c.id
                where (c.status in ('DELIVERING','PUBLISHED') and coalesce(c.published_at,c.delivered_at) is not null
                       and coalesce(c.published_at,c.delivered_at) < now()-(%s::text||' seconds')::interval)
                   or (c.status='ACKED' and c.acked_at < now()-(%s::text||' seconds')::interval)
                   or (c.status='EXECUTING' and j.status='EXECUTING'
                       and j.updated_at + ((coalesce(j.remaining_seconds,j.planned_duration_seconds,300)+%s)::text||' seconds')::interval < now())
                   or (j.status in ('PAUSED','RETRY_WAIT') and j.updated_at < now()-(%s::text||' seconds')::interval)
                order by j.order_id limit 200""",
            (ack_timeout, start_timeout, grace_seconds, wait_timeout),
        ).fetchall()

    def mark_job_hold(self, job_id: Any) -> None:
        self.connection.execute(
            """update production_job set status='HOLD',hold_reason='DEVICE_OUTCOME_UNKNOWN',
                 manual_review_required=true,revision=revision+1,updated_at=now() where id=%s""",
            (job_id,),
        )

    def cleanup_history(
        self, *, heartbeat_days: int, mqtt_days: int, event_days: int,
        outbox_days: int, audit_days: int, limit: int = 5000,
    ) -> dict[str, int]:
        statements = {
            "heartbeat": ("heartbeat_inbox", "received_at", "true", heartbeat_days),
            "mqtt": ("mqtt_inbox", "received_at", "status='PROCESSED'", mqtt_days),
            "events": ("terminal_event", "received_at", "true", event_days),
            "businessOutbox": ("business_outbox", "processed_at", "status='PROCESSED'", outbox_days),
            "commandOutbox": ("command_outbox", "published_at", "status='PUBLISHED'", outbox_days),
            "audit": ("audit_log", "created_at", "true", audit_days),
        }
        deleted: dict[str, int] = {}
        for name, (table, timestamp, predicate, days) in statements.items():
            cursor = self.connection.execute(
                f"""with expired as (
                       select ctid from {table} where {predicate}
                         and {timestamp}<now()-(%s::text||' days')::interval limit %s
                     ) delete from {table} target using expired where target.ctid=expired.ctid""",
                (days, limit),
            )
            deleted[name] = max(0, cursor.rowcount)
        return deleted
