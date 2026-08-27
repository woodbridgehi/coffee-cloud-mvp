from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable

from ..db import UnitOfWork
from ..protocol import AdminDeviceCreateRequest, utc_now
from ..repositories import OrderRepository, TerminalRepository
from .errors import ServiceError
from .presenters import iso


class AdminOperationsService:
    def __init__(
        self, uow: UnitOfWork, *, offline_threshold_seconds: int,
        refresh_offline_status: Callable[[], None],
    ) -> None:
        self.uow = uow
        self.offline_threshold_seconds = offline_threshold_seconds
        self.refresh_offline_status = refresh_offline_status

    def device_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        cutoff = utc_now() - timedelta(seconds=self.offline_threshold_seconds)
        online = bool(row["last_heartbeat_at"] and row["last_heartbeat_at"] >= cutoff)
        return {
            "deviceId": row["device_id"], "serialNumber": row["serial_number"],
            "instanceId": row["instance_id"], "storeId": row["store_id"],
            "lifecycleStatus": row["lifecycle_status"], "online": online,
            "connectionStatus": "online" if online else "offline",
            "hasEverConnected": bool(row["last_connected_at"] or row["last_seen_at"]),
            "registeredAt": iso(row["created_at"]), "lastSeenAt": iso(row["last_seen_at"]),
            "lastHeartbeatAt": iso(row["last_heartbeat_at"]),
            "lastConnectedAt": iso(row["last_connected_at"]),
            "softwareVersion": row["software_version"], "activeBootId": row["active_boot_id"],
            "lastSequence": row["last_sequence"], "reportedStatus": row["reported_status"],
            "lastErrorSummary": row["last_error_summary"],
            "heartbeatCount": int(row.get("heartbeat_count", 0)),
            "eventCount": int(row.get("event_count", 0)),
            "commandCount": int(row.get("command_count", 0)),
            "activeOrderCount": int(row.get("active_order_count", 0)),
            "offlineThresholdSeconds": self.offline_threshold_seconds,
        }

    def register_device(self, payload: AdminDeviceCreateRequest) -> dict[str, Any]:
        with self.uow.transaction() as connection:
            terminals = TerminalRepository(connection)
            existing = terminals.find(payload.deviceId) or terminals.find(payload.serialNumber)
            if existing:
                if existing["device_id"] == payload.deviceId and existing["serial_number"] == payload.serialNumber:
                    return {"duplicate": True, **self.device_payload(existing)}
                raise ServiceError(409, "deviceId or serialNumber already exists")
            row = terminals.insert_pending(
                device_id=payload.deviceId, serial_number=payload.serialNumber,
                instance_id=payload.instanceId, store_id=payload.storeId,
            )
        return {"duplicate": False, **self.device_payload(row)}

    def device(self, identifier: str) -> dict[str, Any]:
        self.refresh_offline_status()
        with self.uow.transaction() as connection:
            terminals = TerminalRepository(connection)
            row = terminals.find_with_counts(identifier)
            if row is None:
                raise ServiceError(404, "device not found")
            snapshots = terminals.snapshot_summaries(row["id"])
        return {
            **self.device_payload(row),
            "snapshots": {
                item["snapshot_type"]: {"version": item["version"], "receivedAt": iso(item["received_at"])}
                for item in snapshots
            },
        }

    def devices(self) -> dict[str, Any]:
        self.refresh_offline_status()
        with self.uow.transaction() as connection:
            rows = TerminalRepository(connection).list_with_counts()
        return {"devices": [self.device_payload(row) for row in rows], "serverTime": iso(utc_now())}

    def inventory(self, identifier: str) -> dict[str, Any]:
        with self.uow.transaction() as connection:
            terminals = TerminalRepository(connection)
            terminal = terminals.find(identifier)
            if terminal is None:
                raise ServiceError(404, "device not found")
            row = terminals.snapshot_row(terminal["id"], "inventory")
        if not row:
            return {"deviceId": terminal["device_id"], "available": False, "materials": []}
        return {
            "deviceId": terminal["device_id"], "available": True,
            "receivedAt": iso(row["received_at"]), **row["payload_json"],
        }

    def capabilities(self, identifier: str) -> dict[str, Any]:
        with self.uow.transaction() as connection:
            terminals = TerminalRepository(connection)
            terminal = terminals.find(identifier)
            if terminal is None:
                raise ServiceError(404, "device not found")
            row = terminals.snapshot_row(terminal["id"], "capabilities")
        if not row:
            return {"deviceId": terminal["device_id"], "available": False, "recipes": []}
        return {
            "deviceId": terminal["device_id"], "available": True,
            "receivedAt": iso(row["received_at"]), **row["payload_json"],
        }

    def update_lifecycle(self, identifier: str, status: str) -> dict[str, Any]:
        with self.uow.transaction() as connection:
            terminals = TerminalRepository(connection)
            terminal = terminals.find(identifier, for_update=True)
            if terminal is None:
                raise ServiceError(404, "device not found")
            if terminal["lifecycle_status"] == "PENDING":
                raise ServiceError(409, "pending device must complete activation first")
            row = terminals.update_lifecycle(terminal["id"], status)
        return self.device_payload(row)

    def orders(
        self, *, device_id: str | None, order_status: str | None, limit: int
    ) -> dict[str, Any]:
        with self.uow.transaction() as connection:
            rows = OrderRepository(connection).list_admin(
                device_id=device_id, order_status=order_status, limit=limit
            )
        return {
            "orders": [
                {
                    "orderId": str(row["id"]), "orderNo": row["order_no"],
                    "deviceId": row["device_id"], "storeId": row["store_id"],
                    "status": row["status"], "productName": row["product_name"],
                    "paymentMode": row["payment_mode"], "paymentStatus": row["payment_status"],
                    "totalAmountMinor": row["total_amount_minor"], "currency": row["currency"],
                    "productionStatus": row["production_status"],
                    "progress": row["progress"], "currentStepName": row["current_step_name"],
                    "failureCode": row["failure_code"], "failureMessage": row["failure_message"],
                    "manualReviewRequired": bool(row["manual_review_required"]),
                    "holdReason": row["hold_reason"], "createdAt": iso(row["created_at"]),
                    "updatedAt": iso(row["updated_at"]),
                }
                for row in rows
            ],
            "serverTime": iso(utc_now()),
        }
