from __future__ import annotations

import logging
import json
import io
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Annotated
from urllib.parse import quote
from urllib.parse import parse_qsl

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Security, status
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
import qrcode

from .database import Database
from .protocol import (
    ActivationCodeRequest, ActivationRequest, AdminDeviceCreateRequest, AdminOperatorCreateRequest,
    CITY_OPTIONS,
    AdminOperatorUpdateRequest, AdminTokenCreateRequest, CommandCreateRequest, CommandResult,
    CredentialRotationRequest, DeviceEvent, Heartbeat, PaymentCreateRequest, PublicOrderCreateRequest,
    RefundCreateRequest, Snapshot, TaskAck, DeviceLifecycleUpdateRequest,
)
from .security import tokens_equal
from .settings import get_settings
from .payment_providers import AlipayProvider, MockPaymentProvider, PaymentProvider
from .emqx_provisioner import EmqxProvisioner
from .db import UnitOfWork
from .services.admin_operations import AdminOperationsService
from .services.device_messages import DeviceMessageService
from .services.device_identity import DeviceIdentityService
from .services.commands import CommandService
from .services.command_state import transition_command as service_transition_command
from .services.mqtt_gateway import MqttGatewayService
from .services.system import SystemService
from .services.errors import ServiceError
from .services.payments import PaymentApplicationService
from .services.public_orders import PublicOrderService
from .services.admin_access import AdminAccessService
from .services.production import ProductionService
from .services.background_worker import BackgroundWorkerService


SERVICE_VERSION = "0.4.0"
logger = logging.getLogger("coffee-cloud-mvp")
settings = get_settings()
database = Database(settings.database_url)
mock_payment_provider = MockPaymentProvider()


def payment_provider(name: str) -> PaymentProvider:
    normalized = name.lower()
    if normalized == "mock":
        return mock_payment_provider
    if normalized != "alipay":
        raise HTTPException(status_code=422, detail="unsupported payment provider")
    if not all((settings.alipay_app_id, settings.alipay_app_private_key_file, settings.alipay_public_key_file)):
        raise HTTPException(status_code=503, detail="Alipay provider is not configured")
    try:
        private_key = Path(settings.alipay_app_private_key_file).read_text(encoding="utf-8")
        public_key = Path(settings.alipay_public_key_file).read_text(encoding="utf-8")
        return AlipayProvider(
            app_id=settings.alipay_app_id or "", app_private_key=private_key,
            alipay_public_key=public_key, gateway=settings.alipay_gateway,
            timeout_seconds=settings.alipay_timeout_seconds,
        )
    except OSError as exc:
        logger.error("payment key file unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="Alipay key material is unavailable") from exc


def emqx_provisioner() -> EmqxProvisioner | None:
    if not all((settings.emqx_management_url, settings.emqx_dashboard_username, settings.emqx_dashboard_password)):
        return None
    return EmqxProvisioner(
        settings.emqx_management_url or "", settings.emqx_dashboard_username or "",
        settings.emqx_dashboard_password or "",
    )


def iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def order_url(device_id: str) -> str:
    base = settings.public_base_url.rstrip("/")
    return f"{base}/order?device_id={quote(device_id, safe='')}"


class OfflineMonitor:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="offline-monitor", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=settings.offline_scan_seconds + 2)

    def scan_once(self) -> None:
        background_worker_service.offline_scan_once()

    def _run(self) -> None:
        while not self.stop_event.wait(settings.offline_scan_seconds):
            try:
                self.scan_once()
            except Exception:
                logger.exception("offline monitor failed")


offline_monitor = OfflineMonitor()


class DomainWorker:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="domain-worker", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=3)

    def _run(self) -> None:
        last_watchdog = 0.0
        while not self.stop_event.wait(settings.outbox_scan_seconds):
            try:
                background_worker_service.process_business_outbox_batch()
                background_worker_service.reconcile_payment_once()
                background_worker_service.process_refund_batch()
                now = time.monotonic()
                if now - last_watchdog >= min(10, settings.offline_scan_seconds):
                    background_worker_service.watchdog_scan_once()
                    last_watchdog = now
            except Exception:
                logger.exception("domain worker iteration failed")


domain_worker = DomainWorker()


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    device_identity_service.bootstrap_device()
    background_worker_service.reconcile_stored_command_events()
    background_worker_service.reconcile_stored_order_events()
    offline_monitor.scan_once()
    offline_monitor.start()
    domain_worker.start()
    try:
        yield
    finally:
        domain_worker.stop()
        offline_monitor.stop()


app = FastAPI(
    title="Coffee Cloud MVP",
    version=SERVICE_VERSION,
    description="咖啡终端设备激活、凭证、心跳、命令与状态验证 API。",
    lifespan=lifespan,
)
PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"
app.mount("/assets", StaticFiles(directory=PUBLIC_DIR), name="public-assets")


@app.exception_handler(ServiceError)
async def service_error_handler(_: Request, exc: ServiceError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.middleware("http")
async def disable_public_order_cache(request: Request, call_next: Any) -> Response:
    request.state.request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    if request.url.path in {"/order", "/order/status", "/admin", "/assets/order.js"} \
            or request.url.path.startswith("/api/v1/admin/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


def request_id(request: Request) -> str:
    return str(request.state.request_id)

device_bearer = HTTPBearer(auto_error=False, scheme_name="deviceBearer")
admin_bearer = HTTPBearer(auto_error=False, scheme_name="adminBearer")


def require_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(admin_bearer)] = None,
) -> dict[str, Any]:
    token = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else None
    return admin_access_service.authenticate(token)


def require_dashboard_read(principal: Annotated[dict[str, Any], Depends(require_admin)]) -> dict[str, Any]:
    return admin_access_service.require(principal, "dashboard.read")


def require_devices_read(principal: Annotated[dict[str, Any], Depends(require_admin)]) -> dict[str, Any]:
    return admin_access_service.require(principal, "devices.read")


def require_devices_manage(principal: Annotated[dict[str, Any], Depends(require_admin)]) -> dict[str, Any]:
    return admin_access_service.require(principal, "devices.manage")


def require_orders_read(principal: Annotated[dict[str, Any], Depends(require_admin)]) -> dict[str, Any]:
    return admin_access_service.require(principal, "orders.read")


def require_commands_execute(principal: Annotated[dict[str, Any], Depends(require_admin)]) -> dict[str, Any]:
    return admin_access_service.require(principal, "commands.execute")


def require_refunds_manage(principal: Annotated[dict[str, Any], Depends(require_admin)]) -> dict[str, Any]:
    return admin_access_service.require(principal, "refunds.manage")


def require_access_read(principal: Annotated[dict[str, Any], Depends(require_admin)]) -> dict[str, Any]:
    return admin_access_service.require(principal, "access.read")


def require_access_manage(principal: Annotated[dict[str, Any], Depends(require_admin)]) -> dict[str, Any]:
    return admin_access_service.require(principal, "access.manage")


def require_audit_read(principal: Annotated[dict[str, Any], Depends(require_admin)]) -> dict[str, Any]:
    return admin_access_service.require(principal, "audit.read")


def require_gateway(x_gateway_token: Annotated[str | None, Header(alias="X-Gateway-Token")] = None) -> None:
    if x_gateway_token is None or not tokens_equal(x_gateway_token, settings.internal_gateway_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid gateway credential")


def authenticate_device(device_id: str, header_device: str | None, token: str | None) -> dict[str, Any]:
    return device_identity_service.authenticate(device_id, header_device, token)


def require_device(
    device_id: str,
    x_device_id: Annotated[str | None, Header(alias="X-Device-Id")] = None,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(device_bearer)] = None,
) -> dict[str, Any]:
    token = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else None
    return authenticate_device(device_id, x_device_id, token)


DeviceIdentity = Annotated[dict[str, Any], Depends(require_device)]
AdminAuth = Annotated[dict[str, Any], Depends(require_admin)]
DashboardRead = Annotated[dict[str, Any], Depends(require_dashboard_read)]
DevicesRead = Annotated[dict[str, Any], Depends(require_devices_read)]
DevicesManage = Annotated[dict[str, Any], Depends(require_devices_manage)]
OrdersRead = Annotated[dict[str, Any], Depends(require_orders_read)]
CommandsExecute = Annotated[dict[str, Any], Depends(require_commands_execute)]
RefundsManage = Annotated[dict[str, Any], Depends(require_refunds_manage)]
AccessRead = Annotated[dict[str, Any], Depends(require_access_read)]
AccessManage = Annotated[dict[str, Any], Depends(require_access_manage)]
AuditRead = Annotated[dict[str, Any], Depends(require_audit_read)]
GatewayAuth = Annotated[None, Depends(require_gateway)]


@app.get("/health")
def health() -> dict[str, Any]:
    return system_service.health()


@app.get("/")
def root() -> dict[str, Any]:
    return {"service": "coffee-cloud-mvp", "version": SERVICE_VERSION, "health": "/health"}


@app.get("/order", response_class=FileResponse, include_in_schema=False)
@app.get("/order/status", response_class=FileResponse, include_in_schema=False)
def public_order_page() -> Path:
    return PUBLIC_DIR / "order.html"


@app.post("/api/v1/admin/devices/{identifier}/activation-codes", tags=["device-identity"])
def create_activation_code(
    identifier: str,
    payload: ActivationCodeRequest,
    principal: DevicesManage,
    request: Request,
) -> dict[str, Any]:
    result = device_identity_service.create_activation_code(identifier, payload.ttlSeconds)
    admin_access_service.audit(
        principal, "device.activation_code.create", "terminal", result["deviceId"],
        {"activationId": result["activationId"], "expiresAt": result["expiresAt"]},
        request_id(request),
    )
    return result


@app.get("/api/v1/device-onboarding/options", tags=["device-identity"])
def onboarding_options() -> dict[str, Any]:
    return {
        "cities": [
            {"code": code, "name": value["name"], "timezone": value["timezone"]}
            for code, value in CITY_OPTIONS.items()
        ],
        "deviceNumber": {"minLength": 3, "maxLength": 6, "deviceIdPrefix": "coffee-bot-"},
        "serialNumber": {"prefix": "CB-", "yearMin": 2025, "yearMax": 2035},
    }


@app.post("/api/v1/device-activations", tags=["device-identity"])
def activate_device(payload: ActivationRequest) -> dict[str, Any]:
    return device_identity_service.activate(
        payload.deviceId, payload.activationCode, payload.deviceToken, payload.profile, payload.serialNumber
    )


@app.post("/api/v1/devices/{device_id}/mqtt-credentials/rotate", tags=["device-identity"])
def rotate_mqtt_credential(device_id: str, identity: DeviceIdentity) -> dict[str, Any]:
    credential = device_identity_service.issue_mqtt_credential(identity)
    return {"deviceId": identity["device_id"], "mqttCredential": credential}


@app.post("/api/v1/admin/devices/{identifier}/mqtt-credentials/revoke", tags=["device-identity"])
def revoke_mqtt_credential(identifier: str, principal: DevicesManage, request: Request) -> dict[str, Any]:
    result = device_identity_service.revoke_mqtt(identifier)
    admin_access_service.audit(
        principal, "device.mqtt_credentials.revoke", "terminal", result["deviceId"], result,
        request_id(request),
    )
    return result


@app.post("/api/v1/devices/{device_id}/credentials/rotate", tags=["device-identity"])
def rotate_credential(
    device_id: str,
    payload: CredentialRotationRequest,
    identity: DeviceIdentity,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    return device_identity_service.rotate_http(
        identity, device_id, payload.newToken, idempotency_key, payload.model_dump(mode="json")
    )


@app.get("/api/v1/admin/devices/{identifier}/credentials", tags=["device-identity"])
def list_credentials(identifier: str, _: DevicesRead) -> dict[str, Any]:
    return device_identity_service.list_http(identifier)


@app.post("/api/v1/admin/devices/{identifier}/credentials/{credential_id}/revoke", tags=["device-identity"])
def revoke_credential(
    identifier: str, credential_id: uuid.UUID, principal: DevicesManage, request: Request
) -> dict[str, Any]:
    result = device_identity_service.revoke_http(identifier, credential_id)
    admin_access_service.audit(
        principal, "device.http_credential.revoke", "terminal", result["deviceId"],
        {"credentialId": str(credential_id)}, request_id(request),
    )
    return result


@app.post("/api/v1/devices/{device_id}/heartbeat")
def heartbeat(device_id: str, payload: Heartbeat, identity: DeviceIdentity) -> dict[str, Any]:
    return device_message_service.heartbeat(device_id, payload, identity)


@app.get("/api/v1/devices/{device_id}/commands")
def commands(
    device_id: str,
    identity: DeviceIdentity,
    after: str = "",
    limit: int = Query(default=10, ge=1, le=100),
) -> dict[str, Any]:
    return device_message_service.commands(identity, after, limit)


@app.put("/api/v1/devices/{device_id}/capabilities")
def capabilities(device_id: str, payload: Snapshot, identity: DeviceIdentity) -> dict[str, Any]:
    body = payload.model_dump(mode="json")
    return device_message_service.snapshot(
        identity, "capabilities", body, str(body.get("capabilityVersion") or "")
    )


@app.put("/api/v1/devices/{device_id}/inventory")
def inventory(device_id: str, payload: Snapshot, identity: DeviceIdentity) -> dict[str, Any]:
    body = payload.model_dump(mode="json")
    return device_message_service.snapshot(
        identity, "inventory", body, str(body.get("version") or body.get("inventoryVersion") or "")
    )


@app.post("/api/v1/devices/{device_id}/events")
def events(device_id: str, payload: DeviceEvent, identity: DeviceIdentity) -> dict[str, Any]:
    return device_message_service.event(device_id, payload, identity)


def event_task_id(body: dict[str, Any]) -> str | None:
    """Compatibility export for integrations that imported this parser from app.main."""
    return ProductionService.event_task_id(body)


@app.get("/api/v1/devices/{device_id}/display-config")
def display_config(device_id: str, identity: DeviceIdentity) -> dict[str, Any]:
    return {"qrUrl": order_url(identity["device_id"])}


@app.post("/api/v1/tasks/{task_id}/ack", tags=["device-commands"])
def task_ack(
    task_id: str,
    payload: TaskAck,
    x_device_id: Annotated[str | None, Header(alias="X-Device-Id")] = None,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(device_bearer)] = None,
) -> dict[str, Any]:
    token = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else None
    identity = authenticate_device(x_device_id or "", x_device_id, token)
    body = payload.model_dump(mode="json", exclude_none=True)
    return apply_task_ack(identity, task_id, body)


def apply_task_ack(identity: dict[str, Any], task_id: str, body: dict[str, Any]) -> dict[str, Any]:
    return device_message_service.task_ack(identity, task_id, body)


@app.post("/api/v1/devices/{device_id}/commands/{message_id}/result")
def command_result(
    device_id: str, message_id: str, payload: CommandResult, identity: DeviceIdentity
) -> dict[str, Any]:
    return device_message_service.command_result(identity, message_id, payload)


@app.post("/api/v1/internal/mqtt/messages", tags=["device-platform"], include_in_schema=False)
async def ingest_mqtt_message(request: Request, _: GatewayAuth) -> dict[str, Any]:
    return mqtt_gateway_service.ingest(await request.json())


@app.get("/api/v1/internal/device-commands/claim", tags=["device-platform"], include_in_schema=False)
def claim_device_commands(
    _: GatewayAuth,
    gateway_id: str = Query(min_length=1, max_length=160),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    return command_service.claim(gateway_id, limit)


@app.post("/api/v1/internal/device-commands/{outbox_id}/published", tags=["device-platform"], include_in_schema=False)
async def mark_device_command_published(outbox_id: uuid.UUID, request: Request, _: GatewayAuth) -> dict[str, Any]:
    body = await request.json()
    return command_service.published(outbox_id, str(body.get("gatewayId") or ""))


@app.post("/api/v1/internal/device-commands/{outbox_id}/retry", tags=["device-platform"], include_in_schema=False)
async def retry_device_command(outbox_id: uuid.UUID, request: Request, _: GatewayAuth) -> dict[str, Any]:
    body = await request.json()
    return command_service.retry(
        outbox_id, str(body.get("gatewayId") or ""), str(body.get("error") or "publish failed")
    )


@app.post("/api/v1/admin/devices/{identifier}/commands", tags=["admin-commands"], status_code=201)
def admin_create_command(
    identifier: str,
    payload: CommandCreateRequest,
    principal: CommandsExecute,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    result = command_service.create_admin(identifier, payload, idempotency_key)
    admin_access_service.audit(
        principal, "device.command.create", "terminal", identifier,
        {"messageId": result["messageId"], "type": payload.type, "duplicate": result["duplicate"]},
        request_id(request),
    )
    return result


@app.get("/api/v1/admin/devices/{identifier}/commands/{message_id}", tags=["admin-commands"])
def admin_get_command(identifier: str, message_id: str, _: DevicesRead) -> dict[str, Any]:
    return command_service.get_admin(identifier, message_id)


@app.post("/api/v1/devices/{device_id}/debug/orders")
async def debug_order(device_id: str, request: Request, identity: DeviceIdentity) -> dict[str, Any]:
    body = await request.json()
    return command_service.create_debug_order(identity, body.get("recipeId"))


@app.post("/api/v1/devices/{device_id}/debug/commands")
async def debug_command(device_id: str, request: Request, identity: DeviceIdentity) -> dict[str, Any]:
    body = await request.json()
    return command_service.create_debug_command(identity, body.get("action"))


@app.patch("/api/v1/devices/{device_id}/debug/overrides")
async def debug_overrides(device_id: str, request: Request, identity: DeviceIdentity) -> dict[str, Any]:
    return command_service.debug_overrides(identity, await request.json())


unit_of_work = UnitOfWork(database)
system_service = SystemService(unit_of_work, SERVICE_VERSION, logger)
admin_access_service = AdminAccessService(unit_of_work, settings)
device_identity_service = DeviceIdentityService(
    unit_of_work, settings=settings, provisioner_factory=emqx_provisioner, logger=logger
)
production_service = ProductionService(settings, payment_provider=payment_provider)
background_worker_service = BackgroundWorkerService(
    unit_of_work, settings, payment_provider=payment_provider, production=production_service,
)
public_order_service = PublicOrderService(
    unit_of_work, settings,
    dispatch_next_order=production_service.dispatch_next_order,
    payment_provider=payment_provider,
)
payment_application_service = PaymentApplicationService(
    unit_of_work, settings,
    provider_factory=payment_provider,
    mock_provider=mock_payment_provider,
)
admin_operations_service = AdminOperationsService(
    unit_of_work,
    offline_threshold_seconds=settings.offline_threshold_seconds,
    refresh_offline_status=offline_monitor.scan_once,
)
device_message_service = DeviceMessageService(
    unit_of_work,
    dispatch_next_order=production_service.dispatch_next_order,
    transition_command=service_transition_command,
    expire_order_for_command=production_service.expire_order_for_command,
    reconcile_command_event=production_service.reconcile_command_event,
    reconcile_order_event=production_service.reconcile_order_event,
    reconcile_order_ack=production_service.reconcile_order_ack,
    order_url=order_url,
)
command_service = CommandService(
    unit_of_work,
    lease_seconds=settings.command_publish_lease_seconds,
    transition_command=service_transition_command,
)
mqtt_gateway_service = MqttGatewayService(
    unit_of_work,
    logger=logger,
    heartbeat=device_message_service.heartbeat,
    event=device_message_service.event,
    task_ack=device_message_service.task_ack,
    command_result=device_message_service.command_result,
)


@app.get("/api/v1/public/devices/{identifier}/menu", tags=["public-orders"])
def get_public_menu(identifier: str) -> dict[str, Any]:
    return public_order_service.menu(identifier)


@app.post("/api/v1/public/devices/{identifier}/orders", tags=["public-orders"], status_code=201)
def create_public_order(
    identifier: str,
    payload: PublicOrderCreateRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    return public_order_service.create(identifier, payload, idempotency_key)


@app.post("/api/v1/orders/{order_id}/payments", tags=["payments"], status_code=201)
def create_payment(
    order_id: uuid.UUID,
    payload: PaymentCreateRequest,
    access_token: Annotated[str | None, Header(alias="X-Order-Access-Token")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    return payment_application_service.create(order_id, payload, access_token, idempotency_key)


@app.get("/api/v1/payments/{payment_id}", tags=["payments"])
def get_payment(
    payment_id: uuid.UUID,
    access_token: Annotated[str | None, Header(alias="X-Order-Access-Token")] = None,
) -> dict[str, Any]:
    return payment_application_service.get(payment_id, access_token)


@app.get("/api/v1/payments/{payment_id}/qr", tags=["payments"], response_class=Response)
def get_payment_qr(
    payment_id: uuid.UUID,
    access_token: Annotated[str | None, Header(alias="X-Order-Access-Token")] = None,
) -> Response:
    image = qrcode.make(payment_application_service.qr_value(payment_id, access_token))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return Response(output.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


@app.post("/api/v1/payments/callback/alipay", tags=["payments"], response_class=PlainTextResponse)
async def alipay_callback(request: Request) -> str:
    values = dict(parse_qsl((await request.body()).decode("utf-8"), keep_blank_values=True))
    return payment_application_service.alipay_callback(values)


@app.post("/api/v1/payments/callback/mock", tags=["payments"], include_in_schema=False)
async def mock_payment_callback(request: Request, _: AccessManage) -> dict[str, Any]:
    return payment_application_service.mock_callback(await request.json())


@app.post("/api/v1/payments/{payment_id}/refund", tags=["payments"], status_code=202)
def create_refund(
    payment_id: uuid.UUID,
    payload: RefundCreateRequest,
    principal: RefundsManage,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    result = payment_application_service.refund(payment_id, payload, idempotency_key)
    admin_access_service.audit(
        principal, "payment.refund.create", "payment", str(payment_id),
        {"refundId": result.get("refundId"), "amountMinor": payload.amountMinor, "reason": payload.reason},
        request_id(request),
    )
    return result


@app.get("/api/v1/public/orders/{order_id}", tags=["public-orders"])
def get_public_order(
    order_id: uuid.UUID,
    access_token: Annotated[str | None, Header(alias="X-Order-Access-Token")] = None,
) -> dict[str, Any]:
    return public_order_service.get(order_id, access_token)


@app.post("/api/v1/public/orders/{order_id}/cancel", tags=["public-orders"])
def cancel_public_order(
    order_id: uuid.UUID,
    access_token: Annotated[str | None, Header(alias="X-Order-Access-Token")] = None,
) -> dict[str, Any]:
    return public_order_service.cancel(order_id, access_token)


@app.post("/api/v1/admin/devices", tags=["device-identity"], status_code=201)
def register_admin_device(
    payload: AdminDeviceCreateRequest, principal: DevicesManage, request: Request
) -> dict[str, Any]:
    result = admin_operations_service.register_device(payload)
    admin_access_service.audit(
        principal, "device.register", "terminal", result["deviceId"],
        {"serialNumber": payload.serialNumber, "storeId": payload.storeId, "duplicate": result["duplicate"]},
        request_id(request),
    )
    return result


@app.get("/api/v1/admin/devices/{identifier}")
def admin_device(identifier: str, _: DevicesRead) -> dict[str, Any]:
    return admin_operations_service.device(identifier)


@app.get("/api/v1/admin/devices")
def admin_devices(_: DevicesRead) -> dict[str, Any]:
    return admin_operations_service.devices()


@app.get("/api/v1/admin/devices/{identifier}/inventory", tags=["admin-operations"])
def admin_device_inventory(identifier: str, _: DevicesRead) -> dict[str, Any]:
    return admin_operations_service.inventory(identifier)


@app.get("/api/v1/admin/orders", tags=["admin-operations"])
def admin_orders(
    _: OrdersRead,
    device_id: str | None = Query(default=None, alias="deviceId"),
    order_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    return admin_operations_service.orders(
        device_id=device_id, order_status=order_status, limit=limit
    )


@app.get("/api/v1/admin/session", tags=["admin-access"])
def admin_session(principal: AdminAuth) -> dict[str, Any]:
    return admin_access_service.session(principal)


@app.get("/api/v1/admin/dashboard", tags=["admin-operations"])
def admin_dashboard(_: DashboardRead) -> dict[str, Any]:
    return admin_access_service.dashboard()


@app.get("/api/v1/admin/devices/{identifier}/capabilities", tags=["admin-operations"])
def admin_device_capabilities(identifier: str, _: DevicesRead) -> dict[str, Any]:
    return admin_operations_service.capabilities(identifier)


@app.patch("/api/v1/admin/devices/{identifier}/lifecycle", tags=["admin-operations"])
def admin_update_device_lifecycle(
    identifier: str, payload: DeviceLifecycleUpdateRequest,
    principal: DevicesManage, request: Request,
) -> dict[str, Any]:
    result = admin_operations_service.update_lifecycle(identifier, payload.status)
    admin_access_service.audit(
        principal, "device.lifecycle.update", "terminal", result["deviceId"],
        {"status": payload.status, "reason": payload.reason}, request_id(request),
    )
    return result


@app.get("/api/v1/admin/operators", tags=["admin-access"])
def admin_operators(_: AccessRead) -> dict[str, Any]:
    return admin_access_service.list_operators()


@app.post("/api/v1/admin/operators", tags=["admin-access"], status_code=201)
def admin_create_operator(
    payload: AdminOperatorCreateRequest, principal: AccessManage, request: Request,
) -> dict[str, Any]:
    result = admin_access_service.create_operator(payload.displayName, payload.role)
    admin_access_service.audit(
        principal, "admin.operator.create", "admin_operator", result["operatorId"],
        {"displayName": payload.displayName, "role": payload.role}, request_id(request),
    )
    return result


@app.patch("/api/v1/admin/operators/{operator_id}", tags=["admin-access"])
def admin_update_operator(
    operator_id: uuid.UUID, payload: AdminOperatorUpdateRequest,
    principal: AccessManage, request: Request,
) -> dict[str, Any]:
    result = admin_access_service.update_operator(
        operator_id, display_name=payload.displayName, role=payload.role, status=payload.status
    )
    admin_access_service.audit(
        principal, "admin.operator.update", "admin_operator", str(operator_id),
        payload.model_dump(mode="json", exclude_none=True), request_id(request),
    )
    return result


@app.get("/api/v1/admin/operators/{operator_id}/tokens", tags=["admin-access"])
def admin_operator_tokens(operator_id: uuid.UUID, _: AccessRead) -> dict[str, Any]:
    return admin_access_service.list_tokens(operator_id)


@app.post("/api/v1/admin/operators/{operator_id}/tokens", tags=["admin-access"], status_code=201)
def admin_create_operator_token(
    operator_id: uuid.UUID, payload: AdminTokenCreateRequest,
    principal: AccessManage, request: Request,
) -> dict[str, Any]:
    result = admin_access_service.create_token(operator_id, payload.label, payload.expiresAt)
    admin_access_service.audit(
        principal, "admin.token.create", "admin_operator", str(operator_id),
        {"tokenId": result["tokenId"], "label": payload.label, "expiresAt": result["expiresAt"]},
        request_id(request),
    )
    return result


@app.delete("/api/v1/admin/operators/{operator_id}/tokens/{token_id}", tags=["admin-access"])
def admin_revoke_operator_token(
    operator_id: uuid.UUID, token_id: uuid.UUID,
    principal: AccessManage, request: Request,
) -> dict[str, Any]:
    result = admin_access_service.revoke_token(operator_id, token_id)
    admin_access_service.audit(
        principal, "admin.token.revoke", "admin_operator", str(operator_id),
        {"tokenId": str(token_id)}, request_id(request),
    )
    return result


@app.get("/api/v1/admin/audit-logs", tags=["admin-audit"])
def admin_audit_logs(
    _: AuditRead,
    limit: int = Query(default=100, ge=1, le=500),
    action: str | None = Query(default=None, max_length=160),
    resource_type: str | None = Query(default=None, max_length=80),
) -> dict[str, Any]:
    return admin_access_service.audit_logs(
        limit=limit, action=action, resource_type=resource_type
    )


@app.get("/admin", response_class=FileResponse, include_in_schema=False)
def admin_page() -> Path:
    return PUBLIC_DIR / "admin.html"
