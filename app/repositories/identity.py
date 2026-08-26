from __future__ import annotations

from typing import Any
import uuid

from psycopg.types.json import Jsonb


class IdentityRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def cancel_pending_activations(self, terminal_id: int) -> None:
        self.connection.execute(
            "update terminal_activation set status='CANCELLED' where terminal_id=%s and status='PENDING'",
            (terminal_id,),
        )

    def create_activation(self, values: tuple[Any, ...]) -> None:
        self.connection.execute(
            """insert into terminal_activation(
                   activation_id,terminal_id,code_hash,max_attempts,expires_at)
                 values(%s,%s,%s,%s,%s)""",
            values,
        )

    def activation_by_code(self, terminal_id: int, code_hash: str) -> dict[str, Any] | None:
        return self.connection.execute(
            """select * from terminal_activation where terminal_id=%s and code_hash=%s
                 order by id desc limit 1 for update""",
            (terminal_id, code_hash),
        ).fetchone()

    def pending_activation(self, terminal_id: int) -> dict[str, Any] | None:
        return self.connection.execute(
            """select * from terminal_activation where terminal_id=%s and status='PENDING'
                 order by id desc limit 1 for update""",
            (terminal_id,),
        ).fetchone()

    def record_failed_attempt(self, activation_id: int, attempts: int, status: str) -> None:
        self.connection.execute(
            "update terminal_activation set attempt_count=%s,status=%s where id=%s",
            (attempts, status, activation_id),
        )

    def expire_activation(self, activation_id: int) -> None:
        self.connection.execute("update terminal_activation set status='EXPIRED' where id=%s", (activation_id,))

    def consume_activation(self, activation_id: int, credential_db_id: int, now: Any) -> None:
        self.connection.execute(
            """update terminal_activation set status='CONSUMED',consumed_at=%s,
                 consumed_credential_id=%s where id=%s""",
            (now, credential_db_id, activation_id),
        )

    def credential_by_id(self, credential_db_id: int, *, for_update: bool = False) -> dict[str, Any] | None:
        suffix = " for update" if for_update else ""
        return self.connection.execute(
            f"select * from terminal_credential where id=%s{suffix}", (credential_db_id,)
        ).fetchone()

    def token_exists(self, token_hash: str) -> bool:
        return self.connection.execute(
            "select 1 from terminal_credential where token_hash=%s", (token_hash,)
        ).fetchone() is not None

    def next_http_version(self, terminal_id: int) -> int:
        return self.connection.execute(
            "select coalesce(max(version),0)+1 as version from terminal_credential where terminal_id=%s",
            (terminal_id,),
        ).fetchone()["version"]

    def grace_active_http_credentials(self, terminal_id: int, expires_at: Any) -> None:
        self.connection.execute(
            """update terminal_credential set status='GRACE',grace_expires_at=%s
                 where terminal_id=%s and status='ACTIVE'""",
            (expires_at, terminal_id),
        )

    def grace_http_credential(self, credential_db_id: int, expires_at: Any) -> None:
        self.connection.execute(
            "update terminal_credential set status='GRACE',grace_expires_at=%s where id=%s",
            (expires_at, credential_db_id),
        )

    def create_http_credential(
        self, *, terminal_id: int, token_hash: str, version: int, now: Any,
        rotated_from_id: int | None = None,
    ) -> dict[str, Any]:
        return self.connection.execute(
            """insert into terminal_credential(
                   terminal_id,token_hash,credential_id,version,not_before,status,rotated_from_id)
                 values(%s,%s,%s,%s,%s,'ACTIVE',%s) returning *""",
            (terminal_id, token_hash, uuid.uuid4(), version, now, rotated_from_id),
        ).fetchone()

    def activate_terminal(self, terminal_id: int, now: Any) -> None:
        self.connection.execute(
            "update terminal set lifecycle_status='ACTIVE',updated_at=%s where id=%s", (now, terminal_id)
        )

    def rotation_request(self, terminal_id: int, key: str) -> dict[str, Any] | None:
        return self.connection.execute(
            "select * from credential_rotation_request where terminal_id=%s and idempotency_key=%s for update",
            (terminal_id, key),
        ).fetchone()

    def save_rotation_request(
        self, terminal_id: int, key: str, digest: str, old_id: int, new_id: int, response: dict[str, Any]
    ) -> None:
        self.connection.execute(
            """insert into credential_rotation_request(
                   terminal_id,idempotency_key,request_digest,old_credential_id,new_credential_id,response_json)
                 values(%s,%s,%s,%s,%s,%s)""",
            (terminal_id, key, digest, old_id, new_id, Jsonb(response)),
        )

    def list_http_credentials(self, terminal_id: int) -> list[dict[str, Any]]:
        return self.connection.execute(
            "select * from terminal_credential where terminal_id=%s order by version desc", (terminal_id,)
        ).fetchall()

    def http_credential(self, terminal_id: int, credential_id: Any) -> dict[str, Any] | None:
        return self.connection.execute(
            "select * from terminal_credential where terminal_id=%s and credential_id=%s",
            (terminal_id, credential_id),
        ).fetchone()

    def revoke_http_credential(self, terminal_id: int, credential_id: Any) -> dict[str, Any] | None:
        return self.connection.execute(
            """update terminal_credential set status='REVOKED',revoked_at=now(),grace_expires_at=null
                 where terminal_id=%s and credential_id=%s and status<>'REVOKED' returning *""",
            (terminal_id, credential_id),
        ).fetchone()

    def next_mqtt_version(self, terminal_id: int) -> int:
        return self.connection.execute(
            "select coalesce(max(version),0)+1 as version from mqtt_credential where terminal_id=%s",
            (terminal_id,),
        ).fetchone()["version"]

    def create_pending_mqtt(self, credential_id: Any, terminal: dict[str, Any], secret_hash: str, version: int) -> None:
        self.connection.execute(
            """insert into mqtt_credential(id,terminal_id,username,secret_hash,version,status)
                 values(%s,%s,%s,%s,%s,'PENDING_PROVISION')""",
            (credential_id, terminal["id"], terminal["device_id"], secret_hash, version),
        )

    def activate_mqtt(self, terminal_id: int, credential_id: Any) -> None:
        self.connection.execute(
            "update mqtt_credential set status='REVOKED',revoked_at=now() where terminal_id=%s and status='ACTIVE' and id<>%s",
            (terminal_id, credential_id),
        )
        self.connection.execute(
            "update mqtt_credential set status='ACTIVE',broker_synced_at=now() where id=%s", (credential_id,)
        )

    def revoke_mqtt(self, terminal_id: int) -> int:
        return len(self.connection.execute(
            """update mqtt_credential set status='REVOKED',revoked_at=coalesce(revoked_at,now())
                 where terminal_id=%s and status<>'REVOKED' returning id""",
            (terminal_id,),
        ).fetchall())

    def authenticate(self, device_id: str, token_hash: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            """select t.*,c.id as credential_db_id,c.credential_id,c.version as credential_version,
                      c.status as credential_status from terminal t join terminal_credential c on c.terminal_id=t.id
                 where t.device_id=%s and c.token_hash=%s
                   and (c.status='ACTIVE' or (c.status='GRACE' and c.grace_expires_at>now()))
                   and (c.not_before is null or c.not_before<=now())
                   and (c.expires_at is null or c.expires_at>now())""",
            (device_id, token_hash),
        ).fetchone()
        if row:
            self.connection.execute(
                "update terminal_credential set last_used_at=now() where id=%s", (row["credential_db_id"],)
            )
        return row
