from __future__ import annotations

from datetime import datetime
from typing import Any


def iso(value: datetime | str | None) -> str | None:
    if isinstance(value, str):
        return value.replace("+00:00", "Z")
    return value.isoformat().replace("+00:00", "Z") if value else None


def payment_payload(payment: dict[str, Any]) -> dict[str, Any]:
    return {
        "paymentId": str(payment["id"]), "orderId": str(payment["order_id"]),
        "provider": payment["provider"], "merchantPaymentNo": payment["merchant_payment_no"],
        "status": payment["status"], "revision": payment["revision"],
        "amountMinor": payment["amount_minor"], "currency": payment["currency"],
        "qrCode": payment["qr_code"], "createdAt": iso(payment["created_at"]),
        "updatedAt": iso(payment["updated_at"]), "paidAt": iso(payment["paid_at"]),
    }
