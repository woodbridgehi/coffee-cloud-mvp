from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb


class CommandRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def claim(self, gateway_id: str, limit: int, lease_seconds: int) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """select o.* from command_outbox o
                 where ((o.status in ('PENDING','RETRY') and o.next_attempt_at<=now())
                    or (o.status='PUBLISHING' and o.locked_until<now()))
                 order by o.created_at for update skip locked limit %s""", (limit,)
        ).fetchall()
        return [self.connection.execute(
            """update command_outbox set status='PUBLISHING',attempt_count=attempt_count+1,
                 locked_by=%s,locked_until=now()+(%s::text||' seconds')::interval where id=%s returning *""",
            (gateway_id, lease_seconds, row["id"]),
        ).fetchone() for row in rows]

    def outbox(self, outbox_id: Any) -> dict[str, Any] | None:
        return self.connection.execute(
            "select * from command_outbox where id=%s for update", (outbox_id,)
        ).fetchone()

    def mark_published(self, outbox_id: Any) -> None:
        self.connection.execute(
            """update command_outbox set status='PUBLISHED',published_at=now(),locked_by=null,
                 locked_until=null,last_error=null where id=%s""", (outbox_id,)
        )

    def mark_retry(self, outbox_id: Any, error: str) -> None:
        self.connection.execute(
            """update command_outbox set status='RETRY',next_attempt_at=now()+
                 (least(60,power(2,least(attempt_count,6)))::text||' seconds')::interval,
                 last_error=%s,locked_by=null,locked_until=null where id=%s""", (error, outbox_id)
        )

    def by_db_id(self, command_id: int) -> dict[str, Any] | None:
        return self.connection.execute(
            "select * from terminal_command where id=%s for update", (command_id,)
        ).fetchone()

    def set_published_at(self, command_id: int) -> None:
        self.connection.execute(
            "update terminal_command set published_at=coalesce(published_at,now()) where id=%s", (command_id,)
        )

    def by_idempotency(self, terminal_id: int, key: str) -> dict[str, Any] | None:
        return self.connection.execute(
            "select * from terminal_command where terminal_id=%s and idempotency_key=%s for update",
            (terminal_id, key),
        ).fetchone()

    def insert(
        self, *, terminal_id: int, message_id: str, command_type: str, payload: dict[str, Any],
        digest: str, expires_at: Any = None, idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return self.connection.execute(
            """insert into terminal_command(
                   terminal_id,message_id,command_type,payload_json,idempotency_key,payload_digest,expires_at)
                 values(%s,%s,%s,%s,%s,%s,%s) returning *""",
            (terminal_id, message_id, command_type, Jsonb(payload), idempotency_key, digest, expires_at),
        ).fetchone()

    def insert_initial_transition(self, command_id: int, actor: str, reason: str, payload: dict[str, Any]) -> None:
        self.connection.execute(
            """insert into terminal_command_transition(
                   command_id,revision,from_status,to_status,actor,reason,payload_json)
                 values(%s,0,null,'CREATED',%s,%s,%s)""",
            (command_id, actor, reason, Jsonb(payload)),
        )

    def find(self, terminal_id: int, message_id: str) -> dict[str, Any] | None:
        return self.connection.execute(
            "select * from terminal_command where terminal_id=%s and message_id=%s",
            (terminal_id, message_id),
        ).fetchone()

    def transitions(self, command_id: int) -> list[dict[str, Any]]:
        return self.connection.execute(
            "select * from terminal_command_transition where command_id=%s order by revision", (command_id,)
        ).fetchall()
