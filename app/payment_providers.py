from __future__ import annotations

import base64
import json
import re
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


@dataclass(frozen=True)
class PaymentRequest:
    merchant_payment_no: str
    amount_minor: int
    currency: str
    subject: str
    notify_url: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderResult:
    status: str
    provider_trade_no: str | None = None
    qr_code: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RefundRequest:
    merchant_payment_no: str
    merchant_refund_no: str
    amount_minor: int
    reason: str
    provider_trade_no: str | None = None


class PaymentProvider(ABC):
    name: str

    @abstractmethod
    def create_payment(self, request: PaymentRequest) -> ProviderResult: ...

    @abstractmethod
    def query_payment(self, merchant_payment_no: str) -> ProviderResult: ...

    @abstractmethod
    def close_payment(self, merchant_payment_no: str) -> ProviderResult: ...

    @abstractmethod
    def refund(self, request: RefundRequest) -> ProviderResult: ...

    @abstractmethod
    def query_refund(self, request: RefundRequest) -> ProviderResult: ...

    @abstractmethod
    def verify_and_parse_callback(self, values: dict[str, str]) -> dict[str, Any]: ...


class MockPaymentProvider(PaymentProvider):
    """Thread-safe test provider. State is deliberately process-local and never a business fact source."""

    name = "mock"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._payments: dict[str, ProviderResult] = {}

    def create_payment(self, request: PaymentRequest) -> ProviderResult:
        with self._lock:
            return self._payments.setdefault(
                request.merchant_payment_no,
                ProviderResult("PENDING", qr_code=f"mock://pay/{request.merchant_payment_no}"),
            )

    def set_paid(self, merchant_payment_no: str, provider_trade_no: str | None = None) -> ProviderResult:
        result = ProviderResult("PAID", provider_trade_no or f"mock-{merchant_payment_no}")
        with self._lock:
            self._payments[merchant_payment_no] = result
        return result

    def query_payment(self, merchant_payment_no: str) -> ProviderResult:
        with self._lock:
            return self._payments.get(merchant_payment_no, ProviderResult("PENDING", qr_code=f"mock://pay/{merchant_payment_no}"))

    def close_payment(self, merchant_payment_no: str) -> ProviderResult:
        result = ProviderResult("CLOSED")
        with self._lock:
            self._payments[merchant_payment_no] = result
        return result

    def refund(self, request: RefundRequest) -> ProviderResult:
        return ProviderResult("REFUNDED", provider_trade_no=request.provider_trade_no, raw={"refundNo": request.merchant_refund_no})

    def query_refund(self, request: RefundRequest) -> ProviderResult:
        return ProviderResult("REFUNDED", provider_trade_no=request.provider_trade_no, raw={"refundNo": request.merchant_refund_no})

    def verify_and_parse_callback(self, values: dict[str, str]) -> dict[str, Any]:
        if values.get("mock_signature") != "accepted-for-tests-only":
            raise ValueError("invalid mock callback signature")
        return dict(values)


class AlipayProvider(PaymentProvider):
    name = "alipay"

    def __init__(
        self,
        *,
        app_id: str,
        app_private_key: str,
        alipay_public_key: str,
        gateway: str,
        timeout_seconds: float = 8.0,
    ) -> None:
        self.app_id = app_id
        self.gateway = gateway
        self.timeout_seconds = timeout_seconds
        self.private_key = serialization.load_pem_private_key(app_private_key.encode(), password=None)
        self.public_key = serialization.load_pem_public_key(alipay_public_key.encode())

    @staticmethod
    def _amount(amount_minor: int) -> str:
        return str((Decimal(amount_minor) / Decimal(100)).quantize(Decimal("0.01")))

    @staticmethod
    def _signing_text(values: dict[str, Any]) -> str:
        return "&".join(f"{key}={value}" for key, value in sorted(values.items()) if value not in (None, "") and key != "sign")

    def _sign(self, values: dict[str, Any]) -> str:
        signature = self.private_key.sign(self._signing_text(values).encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
        return base64.b64encode(signature).decode("ascii")

    def _request(
        self,
        method: str,
        biz_content: dict[str, Any],
        common_params: dict[str, Any] | None = None,
        accepted_sub_codes: set[str] | None = None,
    ) -> dict[str, Any]:
        values: dict[str, Any] = {
            "app_id": self.app_id,
            "method": method,
            "format": "JSON",
            "charset": "utf-8",
            "sign_type": "RSA2",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "version": "1.0",
            "biz_content": json.dumps(biz_content, ensure_ascii=False, separators=(",", ":")),
            **(common_params or {}),
        }
        values["sign"] = self._sign(values)
        response = httpx.post(self.gateway, data=values, timeout=self.timeout_seconds)
        response.raise_for_status()
        response_key = method.replace(".", "_") + "_response"
        # The newer Alipay sandbox gateway may respond as text/html;charset=GBK.
        # Parse response.text so httpx honours the declared charset; Response.json()
        # assumes UTF-8 for raw JSON bytes and fails when messages contain Chinese.
        raw_text = response.text
        body = json.loads(raw_text)
        response_signature = body.get("sign")
        match = re.search(rf'"{re.escape(response_key)}"\s*:\s*', raw_text)
        if not response_signature or not match:
            raise RuntimeError(f"Alipay {method} response is missing signature material")
        _, end = json.JSONDecoder().raw_decode(raw_text[match.end():])
        signed_text = raw_text[match.end():match.end() + end]
        try:
            response_charset = response.encoding or "utf-8"
            self.public_key.verify(
                base64.b64decode(response_signature), signed_text.encode(response_charset),
                padding.PKCS1v15(), hashes.SHA256(),
            )
        except Exception as exc:
            raise RuntimeError(f"Alipay {method} response signature verification failed") from exc
        result = body.get(response_key) or {}
        if result.get("code") != "10000" and result.get("sub_code") not in (accepted_sub_codes or set()):
            raise RuntimeError(f"Alipay {method} failed: {result.get('sub_code') or result.get('code')} {result.get('sub_msg') or result.get('msg')}")
        return result

    def create_payment(self, request: PaymentRequest) -> ProviderResult:
        if request.currency != "CNY":
            raise ValueError("AlipayProvider currently requires CNY")
        raw = self._request("alipay.trade.precreate", {
            "out_trade_no": request.merchant_payment_no,
            "total_amount": self._amount(request.amount_minor),
            "subject": request.subject[:256],
        }, {"notify_url": request.notify_url})
        return ProviderResult("PENDING", raw.get("trade_no"), raw.get("qr_code"), raw)

    def query_payment(self, merchant_payment_no: str) -> ProviderResult:
        raw = self._request(
            "alipay.trade.query", {"out_trade_no": merchant_payment_no},
            accepted_sub_codes={"ACQ.TRADE_NOT_EXIST"},
        )
        if raw.get("sub_code") == "ACQ.TRADE_NOT_EXIST":
            return ProviderResult("NOT_FOUND", raw=raw)
        status = {"TRADE_SUCCESS": "PAID", "TRADE_FINISHED": "PAID", "WAIT_BUYER_PAY": "PENDING", "TRADE_CLOSED": "CLOSED"}.get(raw.get("trade_status"), "FAILED")
        return ProviderResult(status, raw.get("trade_no"), raw=raw)

    def close_payment(self, merchant_payment_no: str) -> ProviderResult:
        raw = self._request(
            "alipay.trade.close", {"out_trade_no": merchant_payment_no},
            accepted_sub_codes={"ACQ.TRADE_NOT_EXIST"},
        )
        return ProviderResult("CLOSED", raw.get("trade_no"), raw=raw)

    def refund(self, request: RefundRequest) -> ProviderResult:
        raw = self._request("alipay.trade.refund", {
            "out_trade_no": request.merchant_payment_no,
            "refund_amount": self._amount(request.amount_minor),
            "refund_reason": request.reason[:256],
            "out_request_no": request.merchant_refund_no,
        })
        status = "REFUNDED" if str(raw.get("fund_change", "Y")).upper() == "Y" else "REFUNDING"
        return ProviderResult(status, raw.get("trade_no"), raw=raw)

    def query_refund(self, request: RefundRequest) -> ProviderResult:
        try:
            raw = self._request("alipay.trade.fastpay.refund.query", {
                "out_trade_no": request.merchant_payment_no,
                "out_request_no": request.merchant_refund_no,
            })
        except RuntimeError as exc:
            if "TRADE_NOT_EXIST" in str(exc):
                return ProviderResult("NOT_FOUND", provider_trade_no=request.provider_trade_no)
            raise
        refunded = bool(raw.get("refund_amount") or raw.get("refund_detail_item_list"))
        return ProviderResult("REFUNDED" if refunded else "PENDING", raw.get("trade_no"), raw=raw)

    def verify_and_parse_callback(self, values: dict[str, str]) -> dict[str, Any]:
        signature = values.get("sign")
        if not signature or values.get("sign_type", "RSA2") != "RSA2":
            raise ValueError("missing or unsupported Alipay callback signature")
        signed_values = {key: value for key, value in values.items() if key not in {"sign", "sign_type"}}
        try:
            self.public_key.verify(base64.b64decode(signature), self._signing_text(signed_values).encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
        except Exception as exc:
            raise ValueError("invalid Alipay callback signature") from exc
        return dict(values)


def encode_form(values: dict[str, str]) -> bytes:
    return urlencode(values).encode("utf-8")
