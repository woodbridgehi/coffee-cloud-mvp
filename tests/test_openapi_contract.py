import os


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
    assert "/api/v1/orders/{order_id}/payments" in paths
    assert "/api/v1/payments/{payment_id}" in paths
    assert "/api/v1/payments/callback/alipay" in paths
    assert "/api/v1/payments/{payment_id}/refund" in paths
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


def test_real_terminal_event_task_id_is_read_from_nested_payload() -> None:
    assert event_task_id({"payload": {"taskId": "task-real"}}) == "task-real"
    assert event_task_id({"taskId": "task-legacy"}) == "task-legacy"


def test_admin_page_is_a_fleet_dashboard() -> None:
    from app.main import ADMIN_HTML

    assert "设备总览" in ADMIN_HTML
    assert "登记新设备" in ADMIN_HTML
    assert "/api/v1/admin/devices" in ADMIN_HTML
    assert "setInterval(loadDevices,10000)" in ADMIN_HTML
