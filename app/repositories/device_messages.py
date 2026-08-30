from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb


class DeviceMessageRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def heartbeat(self, terminal_id: int, message_id: str) -> dict[str, Any] | None:
        return self.connection.execute(
            "select payload_digest,disposition from heartbeat_inbox where terminal_id=%s and message_id=%s",
            (terminal_id, message_id),
        ).fetchone()

    def insert_heartbeat(
        self, *, terminal_id: int, message_id: str, digest: str, body: dict[str, Any],
        boot_id: str | None, sequence: int | None, occurred_at: Any, received_at: Any,
        disposition: str,
    ) -> None:
        self.connection.execute(
            """insert into heartbeat_inbox(
                   terminal_id,message_id,payload_digest,boot_id,sequence,occurred_at,
                   received_at,disposition,payload_json)
                 values(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                terminal_id, message_id, digest, boot_id, sequence, occurred_at,
                received_at, disposition, Jsonb(body),
            ),
        )

    def touch_online(self, terminal_id: int, received_at: Any, connected_at: Any | None = None) -> None:
        if connected_at is None:
            self.connection.execute(
                """update terminal set connection_status='online',last_seen_at=%s,
                     last_heartbeat_at=%s,heartbeat_count=heartbeat_count+1,updated_at=%s where id=%s""",
                (received_at, received_at, received_at, terminal_id),
            )
            return
        self.connection.execute(
            """update terminal set connection_status='online',last_seen_at=%s,
             last_heartbeat_at=%s,last_connected_at=%s,heartbeat_count=heartbeat_count+1,updated_at=%s where id=%s""",
            (received_at, received_at, connected_at, received_at, terminal_id),
        )

    def update_from_heartbeat(
        self, *, terminal_id: int, received_at: Any, connected_at: Any, body: dict[str, Any],
        reported_status: dict[str, Any], boot_id: str | None, sequence: int | None,
    ) -> None:
        self.connection.execute(
            """update terminal set connection_status='online',last_seen_at=%s,
                 last_heartbeat_at=%s,last_connected_at=%s,active_boot_id=%s,last_sequence=%s,
                 heartbeat_count=heartbeat_count+1,
                 instance_id=coalesce(%s,instance_id),store_id=coalesce(%s,store_id),
                 software_version=%s,capability_version=%s,inventory_version=%s,
                 reported_status=%s,updated_at=%s where id=%s""",
            (
                received_at, received_at, connected_at, boot_id, sequence,
                body.get("instanceId"), body.get("storeId"), body.get("appVersion"),
                body.get("capabilityVersion"), body.get("inventoryVersion"),
                Jsonb(reported_status), received_at, terminal_id,
            ),
        )

    def commands_after(self, terminal_id: int, cursor: int, limit: int) -> list[dict[str, Any]]:
        return self.connection.execute(
            """select * from terminal_command where terminal_id=%s and id>%s
                 order by id limit %s""",
            (terminal_id, cursor, limit),
        ).fetchall()

    def upsert_snapshot(
        self, terminal_id: int, snapshot_type: str, version: str | None, payload: dict[str, Any]
    ) -> None:
        self.connection.execute(
            """insert into terminal_snapshot(terminal_id,snapshot_type,version,payload_json)
                 values(%s,%s,%s,%s)
                 on conflict(terminal_id,snapshot_type) do update set
                   version=excluded.version,payload_json=excluded.payload_json,received_at=now()""",
            (terminal_id, snapshot_type, version, Jsonb(payload)),
        )

    def event(self, terminal_id: int, event_id: str) -> dict[str, Any] | None:
        return self.connection.execute(
            "select payload_digest from terminal_event where terminal_id=%s and event_id=%s",
            (terminal_id, event_id),
        ).fetchone()

    def insert_event(
        self, *, terminal_id: int, event_id: str, boot_id: str | None, sequence: int | None,
        event_type: str, occurred_at: Any, digest: str, body: dict[str, Any],
    ) -> bool:
        row = self.connection.execute(
            """insert into terminal_event(
                   terminal_id,event_id,boot_id,sequence,event_type,occurred_at,payload_digest,payload_json)
                 values(%s,%s,%s,%s,%s,%s,%s,%s)
                 on conflict(terminal_id,event_id) do nothing returning id""",
            (terminal_id, event_id, boot_id, sequence, event_type, occurred_at, digest, Jsonb(body)),
        ).fetchone()
        return row is not None

    def command(self, terminal_id: int, message_id: str, *, for_update: bool = False) -> dict[str, Any] | None:
        suffix = " for update" if for_update else ""
        return self.connection.execute(
            f"select * from terminal_command where terminal_id=%s and message_id=%s{suffix}",
            (terminal_id, message_id),
        ).fetchone()
