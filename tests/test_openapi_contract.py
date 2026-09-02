import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

os.environ.setdefault("DATABASE_URL", "postgresql://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("DEVICE_TOKEN", "test-device-token-at-least-24-characters")
os.environ.setdefault("ADMIN_TOKEN", "test-admin-token-at-least-24-characters")

from app.main import app, event_task_id  # noqa: E402


def test_openapi_exposes_identity_and_formal_command_contracts() -> None:
    schema = app.openapi()
    assert schema["info"]["version"] == "0.4.0"
    paths = schema["paths"]
    assert "/api/v1/device-activations" in paths
    assert "/api/v1/devices/{device_id}/credentials/rotate" in paths
    assert "/api/v1/admin/devices" in paths
    assert "/api/v1/admin/devices/{identifier}/commands" in paths
    assert "/api/v1/admin/devices/{identifier}/commands/{message_id}" in paths
    assert "/api/v1/public/devices/{identifier}/menu" in paths
    assert "/api/v1/public/devices/{identifier}/orders" in paths
    assert "/api/v1/public/orders/{order_id}" in paths
    assert "/api/v1/admin/devices/{identifier}/inventory" in paths
    assert "/api/v1/admin/orders" in paths
    assert "/api/v1/admin/orders/{order_id}/adjudication" in paths
    assert "/api/v1/orders/{order_id}/payments" in paths
    assert "/api/v1/payments/{payment_id}" in paths
    assert "/api/v1/payments/callback/alipay" in paths
    assert "/api/v1/payments/{payment_id}/refund" in paths
    assert "/api/v1/admin/session" in paths
    assert "/api/v1/admin/dashboard" in paths
    assert "/api/v1/admin/operators" in paths
    assert "/api/v1/admin/operators/{operator_id}/tokens" in paths
    assert "/api/v1/admin/audit-logs" in paths
    assert "/api/v1/admin/devices/{identifier}/lifecycle" in paths
    assert "/api/v1/admin/devices/{identifier}/capabilities" in paths
    schemes = schema["components"]["securitySchemes"]
    assert schemes["deviceBearer"]["scheme"] == "bearer"
    assert schemes["adminBearer"]["scheme"] == "bearer"


def test_rotation_and_formal_command_require_idempotency_header() -> None:
    schema = app.openapi()
    rotation_parameters = schema["paths"]["/api/v1/devices/{device_id}/credentials/rotate"]["post"]["parameters"]
    command_parameters = schema["paths"]["/api/v1/admin/devices/{identifier}/commands"]["post"]["parameters"]
    assert any(item["name"] == "Idempotency-Key" for item in rotation_parameters)
    assert any(item["name"] == "Idempotency-Key" for item in command_parameters)
    payment_parameters = schema["paths"]["/api/v1/orders/{order_id}/payments"]["post"]["parameters"]
    refund_parameters = schema["paths"]["/api/v1/payments/{payment_id}/refund"]["post"]["parameters"]
    assert any(item["name"] == "Idempotency-Key" for item in payment_parameters)
    assert any(item["name"] == "Idempotency-Key" for item in refund_parameters)
    adjudication = schema["paths"]["/api/v1/admin/orders/{order_id}/adjudication"]["post"]
    assert any(item["name"] == "Idempotency-Key" and item["required"] for item in adjudication["parameters"])
    assert adjudication["security"] == [{"adminBearer": []}]


def test_real_terminal_event_task_id_is_read_from_nested_payload() -> None:
    assert event_task_id({"payload": {"taskId": "task-real"}}) == "task-real"
    assert event_task_id({"taskId": "task-legacy"}) == "task-legacy"


def test_admin_page_is_a_fleet_dashboard() -> None:
    html = (ROOT / "public" / "admin.html").read_text(encoding="utf-8")
    script = (ROOT / "public" / "admin.js").read_text(encoding="utf-8")
    styles = (ROOT / "public" / "admin.css").read_text(encoding="utf-8")
    assert '/assets/admin.css' in html
    assert '/assets/admin.js' in html
    assert "运营总览" in script
    assert "登记设备" in script
    assert "/api/v1/admin/devices" in script
    assert "REFRESH_INTERVAL_MS" in script
    assert "/api/v1/admin/session" in script
    assert "cc-side" in styles
