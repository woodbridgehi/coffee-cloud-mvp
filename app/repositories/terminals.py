from __future__ import annotations

from typing import Any


class TerminalRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def find(self, identifier: str, *, for_update: bool = False) -> dict[str, Any] | None:
        suffix = " for update" if for_update else ""
        return self.connection.execute(
            f"""select * from terminal
                  where device_id=%s or serial_number=%s
                  order by case when device_id=%s then 0 else 1 end
                  limit 1{suffix}""",
            (identifier, identifier, identifier),
        ).fetchone()

    def snapshot(self, terminal_id: int, snapshot_type: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "select payload_json from terminal_snapshot where terminal_id=%s and snapshot_type=%s",
            (terminal_id, snapshot_type),
        ).fetchone()
        return row["payload_json"] if row else None

    def snapshot_row(self, terminal_id: int, snapshot_type: str) -> dict[str, Any] | None:
        return self.connection.execute(
            "select * from terminal_snapshot where terminal_id=%s and snapshot_type=%s",
            (terminal_id, snapshot_type),
        ).fetchone()

    def snapshot_summaries(self, terminal_id: int) -> list[dict[str, Any]]:
        return self.connection.execute(
            "select snapshot_type,version,received_at from terminal_snapshot where terminal_id=%s",
            (terminal_id,),
        ).fetchall()

    def list_with_counts(self) -> list[dict[str, Any]]:
        return self.connection.execute(
            """select t.*,
                      (select count(*) from heartbeat_inbox h where h.terminal_id=t.id) as heartbeat_count,
                      (select count(*) from terminal_event e where e.terminal_id=t.id) as event_count,
                      (select count(*) from terminal_command c where c.terminal_id=t.id) as command_count,
                      (select count(*) from sales_order o where o.terminal_id=t.id
                         and o.status in ('QUEUED','DISPATCHED','ACCEPTED','MAKING')) as active_order_count
                 from terminal t order by t.created_at desc,t.serial_number"""
        ).fetchall()

    def find_with_counts(self, identifier: str) -> dict[str, Any] | None:
        return self.connection.execute(
            """select t.*,
                      (select count(*) from heartbeat_inbox h where h.terminal_id=t.id) as heartbeat_count,
                      (select count(*) from terminal_event e where e.terminal_id=t.id) as event_count,
                      (select count(*) from terminal_command c where c.terminal_id=t.id) as command_count,
                      (select count(*) from sales_order o where o.terminal_id=t.id
                         and o.status in ('QUEUED','DISPATCHED','ACCEPTED','MAKING')) as active_order_count
                 from terminal t where t.device_id=%s or t.serial_number=%s
                 order by case when t.device_id=%s then 0 else 1 end limit 1""",
            (identifier, identifier, identifier),
        ).fetchone()

    def insert_pending(self, *, device_id: str, serial_number: str, instance_id: str | None, store_id: str | None) -> dict[str, Any]:
        return self.connection.execute(
            """insert into terminal(device_id,serial_number,instance_id,store_id,lifecycle_status)
                 values(%s,%s,%s,%s,'PENDING_ACTIVATION') returning *""",
            (device_id, serial_number, instance_id, store_id),
        ).fetchone()

    def upsert_bootstrap(
        self, *, device_id: str, serial_number: str, instance_id: str | None, store_id: str | None
    ) -> dict[str, Any]:
        return self.connection.execute(
            """insert into terminal(device_id,serial_number,instance_id,store_id)
                 values(%s,%s,%s,%s)
                 on conflict(device_id) do update set
                   serial_number=excluded.serial_number,instance_id=excluded.instance_id,
                   store_id=excluded.store_id,updated_at=now()
                 returning *""",
            (device_id, serial_number, instance_id, store_id),
        ).fetchone()

    def complete_onboarding_profile(self, terminal_id: int, profile: dict[str, Any]) -> dict[str, Any]:
        """Fill deployment metadata exactly once; administrator-provided values always win."""
        return self.connection.execute(
            """update terminal set
                   device_name=coalesce(device_name,%s),
                   store_id=coalesce(store_id,%s),
                   store_name=coalesce(store_name,%s),
                   store_description=coalesce(store_description,%s),
                   city_code=coalesce(city_code,%s),
                   timezone=coalesce(timezone,%s),
                   profile_source=coalesce(profile_source,'DEVICE_ONBOARDING'),
                   profile_completed_at=coalesce(profile_completed_at,now()),
                   updated_at=now()
                 where id=%s returning *""",
            (
                profile["deviceName"], profile["storeId"], profile["storeName"],
                profile["storeDescription"], profile["cityCode"], profile["timezone"], terminal_id,
            ),
        ).fetchone()

    def update_lifecycle(self, terminal_id: int, status: str) -> dict[str, Any]:
        return self.connection.execute(
            "update terminal set lifecycle_status=%s,updated_at=now() where id=%s returning *",
            (status, terminal_id),
        ).fetchone()
