from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb


class MqttGatewayRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def security_event(self, device_id: str, detail: dict[str, Any]) -> None:
        self.connection.execute(
            """insert into security_event(event_type,device_id,source,detail_json)
                 values('MQTT_IDENTITY_MISMATCH',%s,'mqtt-gateway',%s)""",
            (device_id, Jsonb(detail)),
        )

    def terminal(self, device_id: str) -> dict[str, Any] | None:
        return self.connection.execute("select * from terminal where device_id=%s", (device_id,)).fetchone()

    def inbox(self, device_id: str, message_id: str) -> dict[str, Any] | None:
        return self.connection.execute(
            "select * from mqtt_inbox where device_id=%s and message_id=%s for update",
            (device_id, message_id),
        ).fetchone()

    def insert_inbox(self, values: tuple[Any, ...]) -> bool:
        return self.connection.execute(
            """insert into mqtt_inbox(
                   device_id,topic,message_id,message_type,boot_id,sequence,revision,payload_digest,payload_json)
                 values(%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict do nothing returning id""",
            (*values[:-1], Jsonb(values[-1])),
        ).fetchone() is not None

    def presence(self, terminal_id: int, online: bool) -> None:
        status = "online" if online else "offline"
        self.connection.execute(
            """update terminal set connection_status=%s,last_seen_at=now(),
                 last_connected_at=case when %s='online' then coalesce(last_connected_at,now()) else last_connected_at end,
                 updated_at=now() where id=%s""", (status, status, terminal_id)
        )

    def state(self, terminal_id: int, payload: dict[str, Any]) -> None:
        self.connection.execute(
            "update terminal set reported_status=%s,last_seen_at=now(),updated_at=now() where id=%s",
            (Jsonb(payload), terminal_id),
        )

    def retry(self, device_id: str, message_id: str, error: str) -> None:
        self.connection.execute(
            "update mqtt_inbox set status='RETRY',error_message=%s where device_id=%s and message_id=%s",
            (error[:1000], device_id, message_id),
        )

    def processed(self, device_id: str, message_id: str) -> None:
        self.connection.execute(
            """update mqtt_inbox set status='PROCESSED',disposition='APPLIED',processed_at=now(),error_message=null
                 where device_id=%s and message_id=%s""", (device_id, message_id)
        )
