from __future__ import annotations

import hashlib
import hmac


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def derive_order_access_token(secret: str, device_id: str, idempotency_key: str) -> str:
    message = f"order-access:v1:{device_id}:{idempotency_key}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def tokens_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def bearer_token(value: str | None) -> str | None:
    if not value or not value.startswith("Bearer "):
        return None
    token = value[7:].strip()
    return token or None
