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
        return self.connection.execute(
            """select * from terminal_command where status='CREATED'
                 and expires_at is not null and expires_at <= now() for update skip locked"""
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

    def watchdog_rows(self, ack_timeout: int, start_timeout: int, grace_seconds: int) -> list[dict[str, Any]]:
        return self.connection.execute(
            """select c.*,j.id as job_id,j.order_id,j.status as job_status,j.planned_duration_seconds,
                      j.started_at as job_started_at
                 from terminal_command c join production_job j on j.command_id=c.id
                where (c.status in ('DELIVERING','PUBLISHED') and coalesce(c.published_at,c.delivered_at) is not null
                       and coalesce(c.published_at,c.delivered_at) < now()-(%s::text||' seconds')::interval)
                   or (c.status='ACKED' and c.acked_at < now()-(%s::text||' seconds')::interval)
                   or (c.status='EXECUTING' and j.started_at is not null
                       and j.started_at + ((coalesce(j.planned_duration_seconds,300)+%s)::text||' seconds')::interval < now())
                for update skip locked""",
            (ack_timeout, start_timeout, grace_seconds),
        ).fetchall()

    def mark_job_hold(self, job_id: Any) -> None:
        self.connection.execute(
            """update production_job set status='HOLD',hold_reason='DEVICE_OUTCOME_UNKNOWN',
                 manual_review_required=true,revision=revision+1,updated_at=now() where id=%s""",
            (job_id,),
        )
