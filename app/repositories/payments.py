from __future__ import annotations

import uuid
from typing import Any, Iterable

from psycopg.types.json import Jsonb


class PaymentRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    @staticmethod
    def _lock_suffix(for_update: bool) -> str:
        return " for update" if for_update else ""

    def find(self, payment_id: uuid.UUID, *, for_update: bool = False) -> dict[str, Any] | None:
        return self.connection.execute(
            f"select * from payment where id=%s{self._lock_suffix(for_update)}", (payment_id,)
        ).fetchone()

    def merchant_account(self, account_id: uuid.UUID, tenant_id: uuid.UUID | None = None) -> dict[str, Any] | None:
        row = self.connection.execute(
            'select id,tenant_id,provider,app_id,merchant_id,status from merchant_payment_account where id=%s',
            (account_id,),
        ).fetchone()
        return row if row and (tenant_id is None or row['tenant_id'] == tenant_id) else None

    def callback_account(self, provider: str, merchant_no: str | None) -> dict[str, Any] | None:
        return self.connection.execute(
            'select payment_account_id from payment where provider=%s and merchant_payment_no=%s',
            (provider, merchant_no),
        ).fetchone()

    def find_idempotent(
        self, order_id: uuid.UUID, idempotency_key: str, *, for_update: bool = True
    ) -> dict[str, Any] | None:
        return self.connection.execute(
            f"""select * from payment where order_id=%s and idempotency_key=%s
                  {self._lock_suffix(for_update)}""",
            (order_id, idempotency_key),
        ).fetchone()

    def latest_for_order(self, order_id: uuid.UUID) -> dict[str, Any] | None:
        return self.connection.execute(
            "select * from payment where order_id=%s order by created_at desc limit 1", (order_id,)
        ).fetchone()

    def latest_open_for_order(self, order_id: uuid.UUID, *, for_update: bool = False) -> dict[str, Any] | None:
        return self.connection.execute(
            f"""select * from payment where order_id=%s and status in ('CREATED','PENDING')
                  order by created_at desc limit 1{self._lock_suffix(for_update)}""",
            (order_id,),
        ).fetchone()

    def open_intents_for_order(self, order_id: uuid.UUID, *, for_update: bool = False) -> list[dict[str, Any]]:
        """All still-open intents; historical data may legitimately contain several."""
        return self.connection.execute(
            f"""select * from payment where order_id=%s and status in ('CREATED','PENDING')
                 order by created_at,id{self._lock_suffix(for_update)}""",
            (order_id,),
        ).fetchall()

    def display_for_order(self, order_id: uuid.UUID) -> dict[str, Any] | None:
        """Public projection payment: the primary paid payment if set, else the newest intent."""
        return self.connection.execute(
            """select p.* from payment p join sales_order o on o.id=p.order_id
                where p.order_id=%s
                order by (o.paid_payment_id is not distinct from p.id) desc, p.created_at desc
                limit 1""",
            (order_id,),
        ).fetchone()

    def paid_for_order(self, order_id: uuid.UUID) -> dict[str, Any] | None:
        return self.connection.execute(
            """select * from payment where order_id=%s and status in ('PAID','PARTIALLY_REFUNDED')
                 order by paid_at desc limit 1 for update""", (order_id,)
        ).fetchone()

    def find_mock_by_merchant_no(self, merchant_no: str) -> dict[str, Any] | None:
        return self.connection.execute(
            "select * from payment where provider='mock' and merchant_payment_no=%s", (merchant_no,)
        ).fetchone()

    def insert(
        self,
        *,
        payment_id: uuid.UUID,
        order: dict[str, Any],
        provider: str,
        merchant_no: str,
        idempotency_key: str,
        request_digest: str,
    ) -> dict[str, Any]:
        return self.connection.execute(
            """insert into payment(id,order_id,provider,merchant_payment_no,idempotency_key,
                   request_digest,status,amount_minor,currency,subject)
                 values(%s,%s,%s,%s,%s,%s,'CREATED',%s,%s,%s) returning *""",
            (
                payment_id, order["id"], provider, merchant_no, idempotency_key, request_digest,
                order["total_amount_minor"], order["currency"], order["product_name"],
            ),
        ).fetchone()

    def insert_created_event(self, payment_id: uuid.UUID, payload: dict[str, Any]) -> None:
        self.connection.execute(
            """insert into payment_event(payment_id,event_id,event_type,actor,payload_json)
                 values(%s,'created','payment.created','customer',%s)""",
            (payment_id, Jsonb(payload)),
        )

    def transition_payment(
        self, payment: dict[str, Any], target: str, *, actor: str, payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Persist one already-validated payment transition plus its audit event."""
        revision = int(payment["revision"]) + 1
        updated = self.connection.execute(
            """update payment set status=%s,revision=%s,updated_at=now(),
                 paid_at=case when %s='PAID' then coalesce(paid_at,now()) else paid_at end,
                 closed_at=case when %s in ('CLOSED','FAILED') then coalesce(closed_at,now()) else closed_at end
                 where id=%s returning *""",
            (target, revision, target, target, payment["id"]),
        ).fetchone()
        self.connection.execute(
            """insert into payment_event(payment_id,event_id,event_type,actor,payload_json)
                 values(%s,%s,%s,%s,%s)""",
            (payment["id"], f"transition:{revision}", f"payment.{target.lower()}", actor, Jsonb(payload or {})),
        )
        return updated

    def transition_refund(
        self, refund: dict[str, Any], target: str, payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Persist one already-validated refund transition."""
        return self.connection.execute(
            """update refund set status=%s,revision=revision+1,provider_response=coalesce(%s,provider_response),
                 updated_at=now(),completed_at=case when %s in ('SUCCEEDED','FAILED') then now() else completed_at end
                 where id=%s returning *""",
            (target, Jsonb(payload) if payload else None, target, refund["id"]),
        ).fetchone()

    def save_provider_result(self, payment_id: uuid.UUID, result: Any) -> dict[str, Any]:
        self.connection.execute(
            """update payment set qr_code=coalesce(%s,qr_code),
                 provider_trade_no=coalesce(%s,provider_trade_no),provider_response=%s,
                 updated_at=now() where id=%s""",
            (result.qr_code, result.provider_trade_no, Jsonb(result.raw), payment_id),
        )
        return self.find(payment_id)  # type: ignore[return-value]

    def schedule_reconciliation(self, payment_id: uuid.UUID, seconds: int) -> None:
        self.connection.execute(
            """update payment set next_reconcile_at=now()+(%s::text||' seconds')::interval
                 where id=%s""",
            (seconds, payment_id),
        )

    def find_refund_idempotent(
        self, payment_id: uuid.UUID, idempotency_key: str, *, for_update: bool = True
    ) -> dict[str, Any] | None:
        return self.connection.execute(
            f"""select * from refund where payment_id=%s and idempotency_key=%s
                  {self._lock_suffix(for_update)}""",
            (payment_id, idempotency_key),
        ).fetchone()

    def refunded_total(self, payment_id: uuid.UUID, *, statuses: Iterable[str] = ("SUCCEEDED",)) -> int:
        row = self.connection.execute(
            """select coalesce(sum(amount_minor),0) as total from refund
                 where payment_id=%s and status = any(%s)""",
            (payment_id, list(statuses)),
        ).fetchone()
        return int(row["total"])

    def inflight_refund_exists(self, payment_id: uuid.UUID) -> bool:
        return self.connection.execute(
            """select 1 from refund where payment_id=%s
                 and status in ('REQUESTED','PROCESSING','UNKNOWN') limit 1""",
            (payment_id,),
        ).fetchone() is not None

    def insert_refund(
        self,
        *,
        refund_id: uuid.UUID,
        payment: dict[str, Any],
        merchant_refund_no: str,
        idempotency_key: str,
        request_digest: str,
        amount_minor: int,
        reason: str,
        next_attempt_at: str = "now()",
    ) -> dict[str, Any]:
        return self.connection.execute(
            """insert into refund(id,payment_id,provider,merchant_refund_no,idempotency_key,
                   request_digest,status,amount_minor,reason,next_attempt_at)
                 values(%s,%s,%s,%s,%s,%s,'REQUESTED',%s,%s,%s) returning *""",
            (
                refund_id, payment["id"], payment["provider"], merchant_refund_no,
                idempotency_key, request_digest, amount_minor, reason, next_attempt_at,
            ),
        ).fetchone()

    def find_refund(self, refund_id: uuid.UUID, *, for_update: bool = False) -> dict[str, Any] | None:
        return self.connection.execute(
            f"select * from refund where id=%s{self._lock_suffix(for_update)}", (refund_id,)
        ).fetchone()

    def schedule_refund(self, refund_id: uuid.UUID, *, increment_attempt: bool = False) -> None:
        attempt_sql = "attempt_count=attempt_count+1," if increment_attempt else ""
        self.connection.execute(
            f"""update refund set {attempt_sql}next_attempt_at=now()+interval '30 seconds'
                  where id=%s""",
            (refund_id,),
        )

    def schedule_processing_refund(self, refund_id: uuid.UUID) -> None:
        self.connection.execute(
            """update refund set attempt_count=greatest(attempt_count,1),
                 next_attempt_at=now()+interval '30 seconds' where id=%s""",
            (refund_id,),
        )
