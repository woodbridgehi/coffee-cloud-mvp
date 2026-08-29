from __future__ import annotations

import json
from typing import Any

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
        self.connection.executemany(
            """update terminal set connection_status=coalesce(%s,connection_status),
                 last_seen_at=coalesce(%s::timestamptz,last_seen_at),
                 last_heartbeat_at=coalesce(%s::timestamptz,last_heartbeat_at),
                 reported_status=coalesce(%s,reported_status),updated_at=now() where id=%s""",
            rows,
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
                payload.get("remainingSeconds"), device_revision, device_revision,
                device_revision, int(state["terminalId"]), str(task_id),
            ))
        if progress_rows:
            self.connection.executemany(
                """update production_job set progress=%s,step_progress=%s,
                     current_step_id=coalesce(%s,current_step_id),current_step_name=coalesce(%s,current_step_name),
                     elapsed_seconds=coalesce(%s,elapsed_seconds),remaining_seconds=coalesce(%s,remaining_seconds),
                     last_device_revision=greatest(last_device_revision,coalesce(%s,last_device_revision)),
                     revision=revision+1,updated_at=now()
                     where terminal_id=%s and task_id=%s
                       and (coalesce(%s,-1) < 0 or last_device_revision <= %s)""",
                progress_rows,
            )
