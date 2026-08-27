from __future__ import annotations

import uuid
from typing import Any

from psycopg.types.json import Jsonb


class AdminAccessRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def authenticate(self, token_hash: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            """select o.*,t.id as token_id,t.label as token_label,t.expires_at,t.last_used_at
                 from admin_api_token t join admin_operator o on o.id=t.operator_id
                where t.token_hash=%s and t.status='ACTIVE' and o.status='ACTIVE'
                  and (t.expires_at is null or t.expires_at>now())""",
            (token_hash,),
        ).fetchone()
        if row:
            self.connection.execute(
                "update admin_api_token set last_used_at=now() where id=%s", (row["token_id"],)
            )
        return row

    def list_operators(self) -> list[dict[str, Any]]:
        return self.connection.execute(
            """select o.*,
                      count(t.id) filter(where t.status='ACTIVE' and (t.expires_at is null or t.expires_at>now())) as active_token_count,
                      max(t.last_used_at) as last_used_at
                 from admin_operator o left join admin_api_token t on t.operator_id=o.id
                group by o.id order by o.created_at"""
        ).fetchall()

    def operator(self, operator_id: uuid.UUID, *, for_update: bool = False) -> dict[str, Any] | None:
        suffix = " for update" if for_update else ""
        return self.connection.execute(
            f"select * from admin_operator where id=%s{suffix}", (operator_id,)
        ).fetchone()

    def create_operator(self, operator_id: uuid.UUID, display_name: str, role: str) -> dict[str, Any]:
        return self.connection.execute(
            "insert into admin_operator(id,display_name,role) values(%s,%s,%s) returning *",
            (operator_id, display_name, role),
        ).fetchone()

    def update_operator(
        self, operator_id: uuid.UUID, display_name: str, role: str, status: str
    ) -> dict[str, Any]:
        return self.connection.execute(
            """update admin_operator set display_name=%s,role=%s,status=%s,updated_at=now()
                 where id=%s returning *""",
            (display_name, role, status, operator_id),
        ).fetchone()

    def list_tokens(self, operator_id: uuid.UUID) -> list[dict[str, Any]]:
        return self.connection.execute(
            """select id,label,status,expires_at,last_used_at,created_at,revoked_at
                 from admin_api_token where operator_id=%s order by created_at desc""",
            (operator_id,),
        ).fetchall()

    def create_token(
        self, token_id: uuid.UUID, operator_id: uuid.UUID, token_hash: str,
        label: str, expires_at: Any,
    ) -> dict[str, Any]:
        return self.connection.execute(
            """insert into admin_api_token(id,operator_id,token_hash,label,expires_at)
                 values(%s,%s,%s,%s,%s) returning *""",
            (token_id, operator_id, token_hash, label, expires_at),
        ).fetchone()

    def revoke_token(self, operator_id: uuid.UUID, token_id: uuid.UUID) -> dict[str, Any] | None:
        return self.connection.execute(
            """update admin_api_token set status='REVOKED',revoked_at=coalesce(revoked_at,now())
                 where id=%s and operator_id=%s returning *""",
            (token_id, operator_id),
        ).fetchone()

    def write_audit(
        self, principal: dict[str, Any], action: str, resource_type: str,
        resource_id: str | None, detail: dict[str, Any], request_id: str | None,
    ) -> None:
        self.connection.execute(
            """insert into audit_log(
                   actor_type,actor_id,actor_name,action,resource_type,resource_id,request_id,detail_json)
                 values(%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                principal["actorType"], principal["actorId"], principal["displayName"],
                action, resource_type, resource_id, request_id, Jsonb(detail),
            ),
        )

    def list_audit(
        self, *, limit: int, action: str | None, resource_type: str | None
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if action:
            clauses.append("action=%s")
            params.append(action)
        if resource_type:
            clauses.append("resource_type=%s")
            params.append(resource_type)
        where = " where " + " and ".join(clauses) if clauses else ""
        params.append(limit)
        return self.connection.execute(
            f"select * from audit_log{where} order by created_at desc limit %s", params
        ).fetchall()

    def dashboard_summary(self) -> dict[str, Any]:
        return self.connection.execute(
            """select
                 (select count(*) from terminal) as devices_total,
                 (select count(*) from terminal where connection_status='online') as devices_online,
                 (select count(*) from terminal where lifecycle_status<>'ACTIVE') as devices_restricted,
                 (select count(*) from sales_order where created_at>=date_trunc('day',now())) as orders_today,
                 (select count(*) from sales_order where status='READY' and created_at>=date_trunc('day',now())) as ready_today,
                 (select count(*) from sales_order where status in ('FAILED','HOLD','EXPIRED') and created_at>=date_trunc('day',now())) as exceptions_today,
                 (select count(*) from production_job where manual_review_required) as manual_reviews,
                 (select count(*) from refund where status in ('REQUESTED','PROCESSING','UNKNOWN')) as pending_refunds,
                 (select count(*) from business_outbox where status in ('PENDING','RETRY')) as pending_business_events,
                 (select count(*) from command_outbox where status in ('PENDING','RETRY','PUBLISHING')) as pending_commands"""
        ).fetchone()
