from __future__ import annotations

import uuid
from typing import Any

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

    def refunded_total(self, payment_id: uuid.UUID) -> int:
        row = self.connection.execute(
            """select coalesce(sum(amount_minor),0) as total from refund
                 where payment_id=%s and status='SUCCEEDED'""",
            (payment_id,),
        ).fetchone()
        return int(row["total"])

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
    ) -> dict[str, Any]:
        return self.connection.execute(
            """insert into refund(id,payment_id,provider,merchant_refund_no,idempotency_key,
                   request_digest,status,amount_minor,reason)
                 values(%s,%s,%s,%s,%s,%s,'REQUESTED',%s,%s) returning *""",
            (
                refund_id, payment["id"], payment["provider"], merchant_refund_no,
                idempotency_key, request_digest, amount_minor, reason,
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
