import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.payment_providers import AlipayProvider, MockPaymentProvider, PaymentRequest, RefundRequest


def test_mock_provider_uses_stable_merchant_numbers_for_idempotency() -> None:
    provider = MockPaymentProvider()
    request = PaymentRequest("merchant-1", 100, "CNY", "coffee", "https://example.test/callback")
    first = provider.create_payment(request)
    second = provider.create_payment(request)
    assert first == second
    paid = provider.set_paid("merchant-1")
    assert provider.query_payment("merchant-1").status == "PAID"
    refund = provider.refund(RefundRequest("merchant-1", "refund-1", 100, "failed", paid.provider_trade_no))
    assert refund.status == "REFUNDED"
    assert provider.query_refund(RefundRequest("merchant-1", "refund-1", 100, "failed")).status == "REFUNDED"


def test_alipay_callback_rsa2_verification_excludes_sign_type() -> None:
    app_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    alipay_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = app_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public_pem = alipay_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    provider = AlipayProvider(
        app_id="app", app_private_key=private_pem, alipay_public_key=public_pem,
        gateway="https://example.test/gateway",
    )
    values = {"app_id": "app", "out_trade_no": "merchant-1", "trade_status": "TRADE_SUCCESS", "sign_type": "RSA2"}
    text = "&".join(f"{key}={value}" for key, value in sorted(values.items()) if key != "sign_type")
    values["sign"] = base64.b64encode(
        alipay_key.sign(text.encode(), padding.PKCS1v15(), hashes.SHA256())
    ).decode()
    assert provider.verify_and_parse_callback(values)["out_trade_no"] == "merchant-1"
    values["trade_status"] = "TRADE_CLOSED"
    with pytest.raises(ValueError):
        provider.verify_and_parse_callback(values)


def test_alipay_provider_parses_gbk_sandbox_response(monkeypatch: pytest.MonkeyPatch) -> None:
    app_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    alipay_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    provider = AlipayProvider(
        app_id="app",
        app_private_key=app_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode(),
        alipay_public_key=alipay_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode(),
        gateway="https://example.test/gateway",
    )
    response_key = "alipay_trade_query_response"
    signed_text = json.dumps(
        {"code": "10000", "msg": "成功", "trade_status": "WAIT_BUYER_PAY"},
        ensure_ascii=False, separators=(",", ":"),
    )
    signature = base64.b64encode(
        alipay_key.sign(signed_text.encode("gbk"), padding.PKCS1v15(), hashes.SHA256())
    ).decode()
    raw = f'{{"{response_key}":{signed_text},"sign":"{signature}"}}'.encode("gbk")

    class Response:
        text = raw.decode("gbk")
        encoding = "gbk"

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr("app.payment_providers.httpx.post", lambda *args, **kwargs: Response())
    assert provider.query_payment("merchant-1").status == "PENDING"


def test_gateway_source_has_no_single_device_runtime_configuration() -> None:
    source = open("app/mqtt_gateway.py", encoding="utf-8").read()
    assert 'os.environ["DEVICE_ID"]' not in source
    assert 'os.environ["DEVICE_TOKEN"]' not in source
    assert "v1/devices/+/up" in source


def test_gateway_is_multi_device_and_uses_device_scoped_downlink_topics() -> None:
    source = open("app/mqtt_gateway.py", encoding="utf-8").read()
    production_source = open("app/services/production.py", encoding="utf-8").read()
    assert '"v1/devices/+/up"' in source
    assert '"v1/devices/+/presence"' in source
    assert '"v1/devices/+/state"' in source
    assert '"topic"]' in source
    assert "v1/devices/{terminal_device_id}/down" in production_source
