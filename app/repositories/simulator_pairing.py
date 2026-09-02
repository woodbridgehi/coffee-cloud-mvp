from __future__ import annotations

from typing import Any


class SimulatorPairingRepository:
    """Persistence operations for development-only simulator pairing."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def device_id_available(self, device_id: str) -> bool:
        return self.connection.execute("select 1 from terminal where device_id=%s", (device_id,)).fetchone() is None

    def create_terminal(self, device_id: str, serial_number: str) -> dict[str, Any]:
        return self.connection.execute(
            """insert into terminal(device_id,serial_number,lifecycle_status,provisioning_status,device_identity_kind)
                 values(%s,%s,'PENDING_ACTIVATION','PAIRING_PENDING','SIMULATOR_SOFTWARE') returning *""",
            (device_id, serial_number),
        ).fetchone()

    def ensure_initial_ownership(self, terminal_id: int) -> None:
        self.connection.execute(
            """insert into merchant_device_ownership(terminal_id,tenant_id,store_id,version)
                 select id,tenant_id,merchant_store_id,ownership_version from terminal where id=%s
                 on conflict (terminal_id,version) do nothing""",
            (terminal_id,),
        )

    def identity(self, terminal_id: int) -> dict[str, Any] | None:
        return self.connection.execute(
            "select * from device_bootstrap_identity where terminal_id=%s for update", (terminal_id,)
        ).fetchone()

    def create_identity(self, terminal_id: int, public_pem: str, fingerprint: str, now: Any) -> None:
        self.connection.execute(
            """insert into device_bootstrap_identity(terminal_id,public_key_pem,public_key_fingerprint,last_verified_at)
                 values(%s,%s,%s,%s)""",
            (terminal_id, public_pem, fingerprint, now),
        )

    def verify_identity(self, terminal_id: int, now: Any) -> None:
        self.connection.execute("update device_bootstrap_identity set last_verified_at=%s where terminal_id=%s", (now, terminal_id))

    def cancel_pending(self, terminal_id: int) -> None:
        self.connection.execute("update device_pairing_session set status='CANCELLED' where terminal_id=%s and status='PENDING'", (terminal_id,))

    def mark_pairing_pending(self, terminal_id: int, now: Any) -> None:
        self.connection.execute(
            """update terminal set lifecycle_status='PENDING_ACTIVATION',provisioning_status='PAIRING_PENDING',
                   device_identity_kind='SIMULATOR_SOFTWARE',updated_at=%s where id=%s""", (now, terminal_id)
        )

    def create_session(self, session_id: Any, terminal_id: int, code_hash: str, expires_at: Any) -> None:
        self.connection.execute(
            """insert into device_pairing_session(id,terminal_id,pairing_code_hash,status,expires_at)
                 values(%s,%s,%s,'PENDING',%s)""", (session_id, terminal_id, code_hash, expires_at)
        )

    def session(self, session_id: Any, serial_number: str, *, for_update: bool) -> dict[str, Any] | None:
        suffix = " for update" if for_update else ""
        return self.connection.execute(
            f"""select p.*,t.*,i.public_key_pem,i.public_key_fingerprint
                  from device_pairing_session p join terminal t on t.id=p.terminal_id
                  join device_bootstrap_identity i on i.terminal_id=t.id
                 where p.id=%s and t.serial_number=%s{suffix}""", (session_id, serial_number)
        ).fetchone()

    def expire(self, session_id: Any) -> None:
        self.connection.execute("update device_pairing_session set status='EXPIRED' where id=%s", (session_id,))

    def credential_for_token(self, terminal_id: int, token_hash: str) -> dict[str, Any] | None:
        return self.connection.execute(
            "select * from terminal_credential where terminal_id=%s and token_hash=%s for update", (terminal_id, token_hash)
        ).fetchone()

    def provisioned_credential(self, credential_id: int | None, terminal_id: int) -> dict[str, Any] | None:
        return self.connection.execute(
            "select * from terminal_credential where id=%s and terminal_id=%s for update", (credential_id, terminal_id)
        ).fetchone()

    def mark_provisioned(self, terminal_id: int, session_id: Any, credential_id: int, now: Any) -> dict[str, Any]:
        terminal = self.connection.execute(
            "update terminal set provisioning_status='PROVISIONED',updated_at=%s where id=%s returning *", (now, terminal_id)
        ).fetchone()
        self.connection.execute(
            """update device_pairing_session set status='PROVISIONED',provisioned_at=coalesce(provisioned_at,%s),
                   provisioned_credential_id=coalesce(provisioned_credential_id,%s) where id=%s""",
            (now, credential_id, session_id),
        )
        return terminal
