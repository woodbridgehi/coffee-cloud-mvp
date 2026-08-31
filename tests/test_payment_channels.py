"""Channel switches must preserve keys, callback identity and historical routing."""
import os
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

os.environ.setdefault("DATABASE_URL", "postgresql://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("ADMIN_TOKEN", "test-admin-token-at-least-24-characters")

from app import main
from app.services.payments import PaymentApplicationService


def keys(tmp_path, name):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = tmp_path / (name + "-private.pem")
    public = tmp_path / (name + "-public.pem")
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    public.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    return str(private), str(public)


def test_factory_keeps_sandbox_and_simulator_keys_separate(tmp_path, monkeypatch):
    old_private, old_public = keys(tmp_path, "old")
    new_private, new_public = keys(tmp_path, "new")
    settings = SimpleNamespace(
        alipay_app_id="sandbox-app", alipay_gateway="https://sandbox.test/gateway.do",
        alipay_app_private_key_file=old_private, alipay_public_key_file=old_public,
        alipay_mock_app_id="simulator-app", alipay_mock_gateway="https://mock.test/gateway.do",
        alipay_mock_app_private_key_file=new_private, alipay_mock_public_key_file=new_public,
        alipay_timeout_seconds=15,
    )
    monkeypatch.setattr(main, "settings", settings)
    old = main.payment_provider("alipay")
    new = main.payment_provider("alipay_mock")
    assert (old.app_id, new.app_id) == ("sandbox-app", "simulator-app")
    assert old.gateway != new.gateway and new.name == "alipay_mock"
    values = {"app_id": "simulator-app", "out_trade_no": "same-order-no", "total_amount": "1.00"}
    values["sign"] = new._sign(values)
    values["sign_type"] = "RSA2"
    assert new.verify_and_parse_callback(values)["app_id"] == "simulator-app"
    with pytest.raises(ValueError, match="invalid Alipay callback signature"):
        old.verify_and_parse_callback(values)
    settings.alipay_mock_public_key_file = None
    with pytest.raises(main.HTTPException) as exc:
        main.payment_provider("alipay_mock")
    assert exc.value.status_code == 503  # never fall back to sandbox keys
    assert main.payment_provider("alipay").app_id == "sandbox-app"


@pytest.mark.parametrize("channel", ["alipay", "alipay_mock"])
def test_callback_records_exact_channel_and_rejects_wrong_or_missing_app(monkeypatch, channel):
    class Uow:
        @contextmanager
        def transaction(self):
            yield object()

    settings = SimpleNamespace(alipay_app_id="old-app", alipay_mock_app_id="new-app")
    calls = []
    selected = []
    def factory(name):
        selected.append(name)
        return SimpleNamespace(verify_and_parse_callback=lambda values: dict(values))
    def record(connection, **kwargs):
        calls.append(kwargs)
        return {}, False
    monkeypatch.setattr("app.services.payments.apply_paid_callback", record)
    service = PaymentApplicationService(Uow(), settings, provider_factory=factory, mock_provider=None)
    app_id = getattr(settings, channel + "_app_id")
    values = dict(app_id=app_id, notify_id="same-notify-id", trade_status="TRADE_SUCCESS")
    assert service.alipay_callback(values, provider_name=channel) == "success"
    assert calls[0]["provider"] == channel and selected == [channel]
    for bad_app in ("other-app", "", None):
        assert service.alipay_callback({**values, "app_id": bad_app}, provider_name=channel) == "failure"
    assert len(calls) == 1


def test_simulator_callback_is_routed_separately(monkeypatch):
    from fastapi.testclient import TestClient
    calls = []
    monkeypatch.setattr(main.payment_application_service, "alipay_callback",
                        lambda values, **kwargs: calls.append((values, kwargs)) or "success")
    client = TestClient(main.app)
    assert client.post("/api/v1/payments/callback/alipay_mock", data={"app_id": "new"}).text == "success"
    assert client.post("/api/v1/payments/callback/alipay", data={"app_id": "old"}).text == "success"
    assert calls == [({"app_id": "new"}, {"provider_name": "alipay_mock"}), ({"app_id": "old"}, {})]


def test_retry_created_intent_uses_stored_channel_after_default_switch(monkeypatch):
    from app.protocol import PaymentCreateRequest, canonical_digest
    from app.payment_providers import ProviderResult
    from app.services import payments as module
    from uuid import uuid4

    payload = PaymentCreateRequest()
    row = dict(id=uuid4(), provider="alipay", status="CREATED", merchant_payment_no="old-intent",
               amount_minor=100, currency="CNY", subject="old order",
               request_digest=canonical_digest(payload.model_dump(mode="json")))
    repository = SimpleNamespace(
        find_idempotent=lambda *args: row, find=lambda *args, **kwargs: row,
        save_provider_result=lambda *args: row, schedule_reconciliation=lambda *args: None,
    )
    monkeypatch.setattr(module, "PaymentRepository", lambda connection: repository)
    monkeypatch.setattr(module, "payment_payload", lambda current: {"provider": current["provider"]})
    monkeypatch.setattr(module, "transition_payment", lambda *args, **kwargs: (row, False))
    monkeypatch.setattr(PaymentApplicationService, "_authenticate_order", staticmethod(lambda *args, **kwargs: {"payment_mode": "ONLINE"}))
    selected, requests = [], []
    def create(request):
        requests.append(request)
        return ProviderResult("PENDING")
    def factory(name):
        selected.append(name)
        return SimpleNamespace(query_payment=lambda no: ProviderResult("NOT_FOUND"), create_payment=create)
    class Uow:
        @contextmanager
        def transaction(self):
            yield object()
    settings = SimpleNamespace(payment_default_provider="alipay_mock", public_base_url="https://merchant.test", payment_reconcile_seconds=30)
    service = PaymentApplicationService(Uow(), settings, provider_factory=factory, mock_provider=None)
    result = service.create(uuid4(), payload, "order-token", "same-key")
    assert result == {"provider": "alipay", "duplicate": True}
    assert selected == ["alipay"]
    assert requests[0].notify_url == "https://merchant.test/api/v1/payments/callback/alipay"
