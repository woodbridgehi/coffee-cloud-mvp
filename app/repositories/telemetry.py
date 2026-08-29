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
        progress_rows = []
        for _, state in snapshots:
            raw = state.get("progressPayload")
            if not raw:
                continue
            event = json.loads(raw)
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            task_id = payload.get("taskId")
            if not task_id:
                continue
            overall = payload.get("overallProgress", payload.get("progress"))
            step = payload.get("stepProgress", payload.get("progress"))
            if overall is None or step is None:
                continue
            device_revision = payload.get("taskRevision")
            progress_rows.append((
                max(0.0, min(1.0, float(overall))), max(0.0, min(1.0, float(step))),
                payload.get("stepId"), payload.get("stepName"), payload.get("elapsedSeconds"),
                payload.get("remainingSeconds"), device_revision,
                int(state["terminalId"]), str(task_id), device_revision, device_revision,
            ))
        if progress_rows:
            values = sql.SQL(",").join([
                sql.SQL("(%s::double precision,%s::double precision,%s::text,%s::text,"
                        "%s::double precision,%s::double precision,%s::bigint,%s::bigint,%s::text,%s::bigint,%s::bigint)")
                for _ in progress_rows
            ])
            self.connection.execute(
                sql.SQL("""update production_job as target set
                       progress=incoming.progress,step_progress=incoming.step_progress,
                       current_step_id=coalesce(incoming.step_id,target.current_step_id),
                       current_step_name=coalesce(incoming.step_name,target.current_step_name),
                       elapsed_seconds=coalesce(incoming.elapsed_seconds,target.elapsed_seconds),
                       remaining_seconds=coalesce(incoming.remaining_seconds,target.remaining_seconds),
                       last_device_revision=greatest(target.last_device_revision,
                           coalesce(incoming.device_revision,target.last_device_revision)),
                       revision=target.revision+1,updated_at=now()
                     from (values {}) as incoming(
                       progress,step_progress,step_id,step_name,elapsed_seconds,remaining_seconds,
                       device_revision,terminal_id,task_id,guard_revision,compare_revision)
                    where target.terminal_id=incoming.terminal_id and target.task_id=incoming.task_id
                      and (coalesce(incoming.guard_revision,-1)<0
                           or target.last_device_revision<=incoming.compare_revision)""").format(values),
                tuple(value for row in progress_rows for value in row),
            )
