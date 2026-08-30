from __future__ import annotations

import json
from typing import Any

from psycopg import sql
from psycopg.types.json import Jsonb


class TelemetryRepository:
    """Applies coalesced hot-state snapshots in one database round trip batch."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def apply_snapshots(self, snapshots: list[tuple[str, dict[str, str]]]) -> None:
        rows = []
        for _, state in snapshots:
            rows.append((
                state.get("connectionStatus"), state.get("lastSeenAt"), state.get("lastHeartbeatAt"),
                Jsonb(json.loads(state["reportedStatus"])) if state.get("reportedStatus") else None,
                int(state["terminalId"]),
            ))
        if rows:
            values = sql.SQL(",").join([
                sql.SQL("(%s::text,%s::timestamptz,%s::timestamptz,%s::jsonb,%s::bigint)")
                for _ in rows
            ])
            self.connection.execute(
                sql.SQL("""update terminal as target set
                       connection_status=coalesce(incoming.connection_status,target.connection_status),
                       last_seen_at=coalesce(incoming.last_seen_at,target.last_seen_at),
                       last_heartbeat_at=coalesce(incoming.last_heartbeat_at,target.last_heartbeat_at),
                       reported_status=coalesce(incoming.reported_status,target.reported_status),updated_at=now()
                     from (values {}) as incoming(
                       connection_status,last_seen_at,last_heartbeat_at,reported_status,terminal_id)
                    where target.id=incoming.terminal_id""").format(values),
                tuple(value for row in rows for value in row),
            )
        # Legacy progressPayload fields may remain in existing Redis hashes.
        # Deliberately ignore them: live progress is never persisted by this worker.
