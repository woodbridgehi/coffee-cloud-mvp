from __future__ import annotations

import json

from app.repositories.dispatch import DispatchRepository
from app.repositories.telemetry import TelemetryRepository


class Cursor:
    def __init__(self, row=None) -> None:
        self.row = row

    def fetchone(self):
        return self.row


class RecordingConnection:
    def __init__(self, rows=None) -> None:
        self.rows = list(rows or [])
        self.calls: list[tuple[str, object]] = []
        self.batches: list[tuple[str, object]] = []

    def execute(self, sql: str, params=None):
        self.calls.append((sql, params))
        return Cursor(self.rows.pop(0) if self.rows else None)

    def executemany(self, sql: str, rows):
        materialized = list(rows)
        self.batches.append((sql, materialized))
        return Cursor()


def test_legacy_progress_payload_is_not_flushed_to_production_job() -> None:
    connection = RecordingConnection()
    TelemetryRepository(connection).apply_snapshots([(
        "coffee-bot-001",
        {
            "terminalId": "7",
            "progressPayload": json.dumps({
                "type": "task.progress",
                "payload": {
                    "taskId": "task-1", "taskRevision": 12,
                    "overallProgress": 0.5, "stepProgress": 0.25,
                },
            }),
        },
    )])

    assert len(connection.calls) == 1  # Terminal projection only, never production_job.
    assert "production_job" not in str(connection.calls[0][0])


def test_dispatch_claim_recovers_expired_processing_lease() -> None:
    connection = RecordingConnection()
    DispatchRepository(connection).claim("worker-1")
    assert "status='PROCESSING' and locked_until<now()" in connection.calls[0][0]


def test_dispatch_revision_race_requeues_newer_request() -> None:
    connection = RecordingConnection(rows=[None, None])
    DispatchRepository(connection).complete(7, 2)
    assert "set status='PENDING'" in connection.calls[1][0]
    assert connection.calls[1][1] == (7,)
