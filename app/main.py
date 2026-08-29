from __future__ import annotations

import logging
import json
import io
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Annotated
from urllib.parse import quote
from urllib.parse import parse_qsl

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Security, status
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from psycopg.types.json import Jsonb
import qrcode

from .database import Database
from .command_state import (
    ACKED, CREATED, DELIVERING, EXECUTING, EXPIRED, PUBLISHED, TERMINAL_STATES,
    decide_transition, event_state, result_state,
)
from .protocol import (
    ActivationCodeRequest, ActivationRequest, AdminDeviceCreateRequest, AdminOperatorCreateRequest,
    CITY_OPTIONS,
    AdminOperatorUpdateRequest, AdminTokenCreateRequest, CommandCreateRequest, CommandResult,
    CredentialRotationRequest, DeviceEvent, Heartbeat, PaymentCreateRequest, PublicOrderCreateRequest,
    RefundCreateRequest, Snapshot, TaskAck, DeviceLifecycleUpdateRequest,
    canonical_digest, utc_now,
)
from .order_logic import TERMINAL_ORDER_STATUSES, device_progress, order_state_for_event
from .security import derive_order_access_token, hash_token, tokens_equal
from .settings import get_settings
from .payment_providers import AlipayProvider, MockPaymentProvider, PaymentProvider, PaymentRequest, RefundRequest
from .payment_service import apply_paid_callback, callback_event_id, enqueue_outbox, transition_payment, transition_refund
from .emqx_provisioner import EmqxProvisioner
from .db import UnitOfWork
from .services.admin_operations import AdminOperationsService
from .services.device_messages import DeviceMessageService
from .services.device_identity import DeviceIdentityService
from .services.commands import CommandService
from .services.mqtt_gateway import MqttGatewayService
from .services.system import SystemService
from .services.errors import ServiceError
from .services.order_state import transition_order
from .services.payments import PaymentApplicationService
from .services.public_orders import PublicOrderService
from .services.admin_access import AdminAccessService


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


def provision_device() -> None:
    if not settings.bootstrap_device_enabled:
        return
    if not settings.device_token:
        raise RuntimeError("DEVICE_TOKEN is required when BOOTSTRAP_DEVICE_ENABLED=true")
    token_hash = hash_token(settings.device_token)
    with database.connect() as connection:
        row = connection.execute(
            """
            insert into terminal(device_id, serial_number, instance_id, store_id)
            values (%s, %s, %s, %s)
            on conflict(device_id) do update set
              serial_number = excluded.serial_number,
              instance_id = excluded.instance_id,
              store_id = excluded.store_id,
              updated_at = now()
            returning id
            """,
            (settings.device_id, settings.device_serial_number, settings.device_instance_id, settings.device_store_id),
        ).fetchone()
        existing = connection.execute("select id from terminal_credential where token_hash=%s", (token_hash,)).fetchone()
        if existing is None:
            version = connection.execute(
                "select coalesce(max(version),0)+1 as version from terminal_credential where terminal_id=%s",
                (row["id"],),
            ).fetchone()["version"]
            connection.execute(
                """insert into terminal_credential(
                       terminal_id, token_hash, credential_id, version, not_before, status)
                     values (%s, %s, %s, %s, now(), 'ACTIVE')""",
                (row["id"], token_hash, uuid.uuid4(), version),
            )


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
        cutoff = utc_now() - timedelta(seconds=settings.offline_threshold_seconds)
        with database.connect() as connection:
            connection.execute(
                """update terminal_credential set status='EXPIRED'
                     where (status='GRACE' and grace_expires_at <= now())
                        or (status='ACTIVE' and expires_at is not null and expires_at <= now())"""
            )
            connection.execute(
                """
                update terminal
                   set connection_status='offline', updated_at=now()
                 where connection_status <> 'offline'
                   and (last_heartbeat_at is null or last_heartbeat_at < %s)
                """,
                (cutoff,),
            )
            expired_commands = connection.execute(
                """select * from terminal_command where status='CREATED'
                     and expires_at is not null and expires_at <= now() for update skip locked"""
            ).fetchall()
            for command in expired_commands:
                updated, _ = transition_command(connection, command, EXPIRED, "timeout-monitor", reason="command delivery deadline exceeded")
                expire_order_for_command(connection, updated)

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
                process_business_outbox_batch()
                reconcile_payment_once()
                process_refund_batch()
                now = time.monotonic()
                if now - last_watchdog >= min(10, settings.offline_scan_seconds):
                    watchdog_scan_once()
                    last_watchdog = now
            except Exception:
                logger.exception("domain worker iteration failed")


domain_worker = DomainWorker()


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    provision_device()
    reconcile_stored_command_events()
    reconcile_stored_order_events()
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


def transition_command(
    connection: Any,
    command: dict[str, Any],
    target: str,
    actor: str,
    *,
    reason: str | None = None,
    payload: dict[str, Any] | None = None,
    strict: bool = True,
) -> tuple[dict[str, Any], bool]:
    decision = decide_transition(command["status"], target)
    if decision.duplicate:
        return command, True
    if not decision.allowed:
        if strict:
            raise HTTPException(status_code=409, detail=decision.reason)
        return command, False
    revision = command["revision"] + 1
    now = utc_now()
    completed_at = now if target in TERMINAL_STATES else command.get("completed_at")
    delivered_at = now if target in {DELIVERING, PUBLISHED} and not command.get("delivered_at") else command.get("delivered_at")
    acked_at = now if target == ACKED and not command.get("acked_at") else command.get("acked_at")
    executing_at = now if target == EXECUTING and not command.get("executing_at") else command.get("executing_at")
    updated = connection.execute(
        """update terminal_command set
               status=%s,revision=%s,last_transition_at=%s,delivered_at=%s,
               acked_at=%s,executing_at=%s,completed_at=%s,
               result_json=case when %s::jsonb is null then result_json else %s::jsonb end
             where id=%s returning *""",
        (target, revision, now, delivered_at, acked_at, executing_at, completed_at,
         Jsonb(payload) if payload is not None else None,
         Jsonb(payload) if payload is not None else None,
         command["id"]),
    ).fetchone()
    connection.execute(
        """insert into terminal_command_transition(
               command_id,revision,from_status,to_status,actor,reason,payload_json)
             values(%s,%s,%s,%s,%s,%s,%s)""",
        (command["id"], revision, command["status"], target, actor, reason,
         Jsonb(payload) if payload is not None else None),
    )
    return updated, False


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
    direct = body.get("taskId")
    nested = body.get("payload")
    value = direct or (nested.get("taskId") if isinstance(nested, dict) else None)
    return value if isinstance(value, str) and value else None


def reconcile_command_event(
    connection: Any,
    terminal_id: int,
    body: dict[str, Any],
    event_type: str,
) -> dict[str, Any] | None:
    target = event_state(event_type)
    task_id = event_task_id(body)
    if not target or not task_id:
        return None
    command = connection.execute(
        """select * from terminal_command
             where terminal_id=%s and payload_json->>'taskId'=%s
             order by id desc limit 1 for update""",
        (terminal_id, task_id),
    ).fetchone()
    if command is None:
        return None
    updated, duplicate = transition_command(
        connection, command, target, "device-event",
        reason=event_type, payload=body, strict=False,
    )
    return {
        "messageId": updated["message_id"], "status": updated["status"],
        "revision": updated["revision"], "duplicate": duplicate,
    }


def reconcile_stored_command_events() -> None:
    with database.connect() as connection:
        events_to_reconcile = connection.execute(
            """select terminal_id,event_type,payload_json from terminal_event
                 where event_type in ('task.started','task.succeeded','task.failed','task.cancelled')
                 order by received_at,id"""
        ).fetchall()
        for item in events_to_reconcile:
            reconcile_command_event(connection, item["terminal_id"], item["payload_json"], item["event_type"])


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


def snapshot_payload(connection: Any, terminal_id: int, snapshot_type: str) -> dict[str, Any] | None:
    row = connection.execute(
        "select payload_json from terminal_snapshot where terminal_id=%s and snapshot_type=%s",
        (terminal_id, snapshot_type),
    ).fetchone()
    return row["payload_json"] if row else None


def expire_order_for_command(connection: Any, command: dict[str, Any]) -> None:
    job = connection.execute(
        "select * from production_job where command_id=%s for update", (command["id"],)
    ).fetchone()
    if not job or job["status"] not in {"DISPATCHED", "QUEUED"}:
        return
    connection.execute(
        """update production_job set status='EXPIRED',revision=revision+1,
             failure_json=%s,completed_at=now(),updated_at=now() where id=%s""",
        (Jsonb({"code": "COMMAND_EXPIRED", "messageId": command["message_id"]}), job["id"]),
    )
    order = connection.execute("select * from sales_order where id=%s for update", (job["order_id"],)).fetchone()
    connection.execute(
        "update sales_order set failure_code='COMMAND_EXPIRED',failure_message='设备未在时限内接收制作指令' where id=%s",
        (order["id"],),
    )
    transition_order(connection, order, "EXPIRED", "timeout-monitor", reason="device command expired")


def reconcile_order_ack(connection: Any, terminal_id: int, task_id: str, body: dict[str, Any]) -> dict[str, Any] | None:
    row = connection.execute(
        """select j.*,o.status as order_status,o.id as sales_order_id
             from production_job j join sales_order o on o.id=j.order_id
             where j.terminal_id=%s and j.task_id=%s for update""",
        (terminal_id, task_id),
    ).fetchone()
    if not row:
        return None
    order = connection.execute("select * from sales_order where id=%s for update", (row["sales_order_id"],)).fetchone()
    if body.get("accepted"):
        connection.execute(
            """update production_job set status='ACCEPTED',revision=revision+1,
                 accepted_at=coalesce(accepted_at,now()),updated_at=now() where id=%s""",
            (row["id"],),
        )
        order = transition_order(connection, order, "ACCEPTED", "device-ack", reason="device reserved recipe and materials", payload=body)
    else:
        reason = body.get("reasonCode") or body.get("reason") or "DEVICE_REJECTED"
        connection.execute(
            """update production_job set status='REJECTED',revision=revision+1,failure_json=%s,
                 completed_at=now(),updated_at=now() where id=%s""",
            (Jsonb(body), row["id"]),
        )
        connection.execute(
            "update sales_order set failure_code=%s,failure_message=%s where id=%s",
            (reason, "设备未接受制作任务", order["id"]),
        )
        order = transition_order(connection, order, "FAILED", "device-ack", reason=reason, payload=body)
        dispatch_next_order(connection, terminal_id)
    return {"orderId": str(order["id"]), "status": order["status"]}


def reconcile_order_event(
    connection: Any,
    terminal_id: int,
    body: dict[str, Any],
    event_type: str,
) -> dict[str, Any] | None:
    task_id = event_task_id(body)
    if not task_id:
        return None
    row = connection.execute(
        """select j.*,o.id as sales_order_id from production_job j
             join sales_order o on o.id=j.order_id
             where j.terminal_id=%s and j.task_id=%s for update""",
        (terminal_id, task_id),
    ).fetchone()
    if not row:
        return None
    event_payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
    device_revision = event_payload.get("taskRevision")
    if isinstance(device_revision, int) and device_revision < int(row.get("last_device_revision") or 0):
        return {"orderId": str(row["sales_order_id"]), "status": "STALE", "duplicate": True}
    if event_type in {"task.progress", "step.started", "step.completed"}:
        if row["status"] in {"SUCCEEDED", "FAILED", "REJECTED", "CANCELLED", "EXPIRED", "HOLD"}:
            return {"orderId": str(row["sales_order_id"]), "status": "STALE_TERMINAL", "duplicate": True}
        progress, step_progress = device_progress(
            event_payload, float(row["progress"] or 0), float(row.get("step_progress") or 0)
        )
        connection.execute(
            """update production_job set progress=%s,step_progress=%s,
                 current_step_id=coalesce(%s,current_step_id),current_step_name=coalesce(%s,current_step_name),
                 elapsed_seconds=coalesce(%s,elapsed_seconds),remaining_seconds=coalesce(%s,remaining_seconds),
                 last_device_revision=greatest(last_device_revision,coalesce(%s,last_device_revision)),
                 revision=revision+1,updated_at=now() where id=%s""",
            (progress, step_progress,
             event_payload.get("stepId"), event_payload.get("stepName") or body.get("message"),
             event_payload.get("elapsedSeconds"), event_payload.get("remainingSeconds"), device_revision, row["id"]),
        )
        return {"orderId": str(row["sales_order_id"]), "status": "PROGRESS"}
    mapped = order_state_for_event(event_type)
    if not mapped:
        return None
    order_status, job_status = mapped
    order = connection.execute("select * from sales_order where id=%s for update", (row["sales_order_id"],)).fetchone()
    planned = event_payload.get("plannedDurationSeconds")
    steps = event_payload.get("stepPlan") or event_payload.get("stepDurations")
    failure = event_payload.get("failure") or ({"code": event_payload.get("reasonCode"), "details": event_payload.get("details")} if event_type == "task.rejected" else None)
    progress = 1.0 if event_type == "task.succeeded" else float(event_payload.get("overallProgress", row["progress"] or 0))
    step_progress = 1.0 if event_type == "task.succeeded" else float(event_payload.get("stepProgress", row.get("step_progress") or 0))
    elapsed_seconds = planned if event_type == "task.succeeded" and planned is not None else event_payload.get("elapsedSeconds")
    remaining_seconds = 0.0 if event_type == "task.succeeded" else event_payload.get("remainingSeconds")
    accepted_at = utc_now() if job_status == "ACCEPTED" and not row.get("accepted_at") else row.get("accepted_at")
    started_at = utc_now() if job_status == "EXECUTING" and not row.get("started_at") else row.get("started_at")
    completed_at = utc_now() if job_status in {"SUCCEEDED", "FAILED", "CANCELLED", "REJECTED"} else row.get("completed_at")
    connection.execute(
        """update production_job set status=%s,progress=%s,step_progress=%s,
             planned_duration_seconds=coalesce(%s,planned_duration_seconds),
             step_durations=coalesce(%s::jsonb,step_durations),failure_json=coalesce(%s,failure_json),
             elapsed_seconds=coalesce(%s,elapsed_seconds),remaining_seconds=coalesce(%s,remaining_seconds),
             last_device_revision=greatest(last_device_revision,coalesce(%s,last_device_revision)),
             revision=revision+1,accepted_at=%s,started_at=%s,completed_at=%s,updated_at=now() where id=%s""",
        (job_status, progress, step_progress, planned, Jsonb(steps) if steps is not None else None, Jsonb(failure) if failure else None,
         elapsed_seconds, remaining_seconds, device_revision, accepted_at, started_at, completed_at, row["id"]),
    )
    if failure:
        failure_code = failure.get("code") or failure.get("errorCode") or "PRODUCTION_FAILED"
        connection.execute(
            "update sales_order set failure_code=%s,failure_message=%s where id=%s",
            (failure_code, body.get("message") or "制作失败", order["id"]),
        )
    order = transition_order(connection, order, order_status, "device-event", reason=event_type, payload=body)
    if order_status == "FAILED" and event_type in {"task.failed", "task.rejected"}:
        create_automatic_refund_record(connection, order, row, event_type)
    if order_status in TERMINAL_ORDER_STATUSES:
        dispatch_next_order(connection, terminal_id)
    return {"orderId": str(order["id"]), "status": order["status"]}


def create_automatic_refund_record(
    connection: Any, order: dict[str, Any], job: dict[str, Any], reason: str,
) -> dict[str, Any] | None:
    payment = connection.execute(
        "select * from payment where order_id=%s and status in ('PAID','PARTIALLY_REFUNDED') order by paid_at desc limit 1 for update",
        (order["id"],),
    ).fetchone()
    if not payment:
        return None
    key = f"production:{job['id']}:automatic-refund"
    existing = connection.execute(
        "select * from refund where payment_id=%s and idempotency_key=%s", (payment["id"], key)
    ).fetchone()
    if existing:
        return existing
    request_body = {"amountMinor": payment["amount_minor"], "reason": reason}
    refund = connection.execute(
        """insert into refund(id,payment_id,provider,merchant_refund_no,idempotency_key,
               request_digest,status,amount_minor,reason,next_attempt_at)
             values(%s,%s,%s,%s,%s,%s,'REQUESTED',%s,%s,now()) returning *""",
        (uuid.uuid4(), payment["id"], payment["provider"], f"R{uuid.uuid4().hex[:24].upper()}",
         key, canonical_digest(request_body), payment["amount_minor"], f"production failure: {reason}"),
    ).fetchone()
    transition_payment(connection, payment, "REFUNDING", actor="production-service", payload={"refundId": str(refund["id"])})
    connection.execute("update sales_order set payment_status='REFUNDING',updated_at=now() where id=%s", (order["id"],))
    return refund


def reconcile_stored_order_events() -> None:
    with database.connect() as connection:
        rows = connection.execute(
            """select terminal_id,event_type,payload_json from terminal_event
                 where event_type like 'task.%' or event_type like 'step.%'
                 order by received_at,id"""
        ).fetchall()
        for row in rows:
            reconcile_order_event(connection, row["terminal_id"], row["payload_json"], row["event_type"])


def enqueue_command_outbox(connection: Any, command: dict[str, Any], terminal: dict[str, Any]) -> None:
    envelope = {
        "schema": "coffee.mqtt-envelope.v1", "messageId": command["message_id"],
        "deviceId": terminal["device_id"], "type": "command", "sentAt": iso(utc_now()),
        "payload": command["payload_json"],
    }
    connection.execute(
        """insert into command_outbox(id,command_id,terminal_id,topic,envelope_json)
             values(%s,%s,%s,%s,%s) on conflict(command_id) do nothing""",
        (uuid.uuid4(), command["id"], terminal["id"], f"v1/devices/{terminal['device_id']}/down", Jsonb(envelope)),
    )


def dispatch_next_order(connection: Any, terminal_id: int) -> dict[str, Any] | None:
    terminal = connection.execute("select * from terminal where id=%s for update", (terminal_id,)).fetchone()
    cutoff = utc_now() - timedelta(seconds=settings.offline_threshold_seconds)
    if not terminal.get("last_heartbeat_at") or terminal["last_heartbeat_at"] < cutoff or terminal.get("lifecycle_status") != "ACTIVE":
        return None
    active = connection.execute(
        """select 1 from production_job where terminal_id=%s
             and status in ('DISPATCHED','ACCEPTED','EXECUTING','HOLD','UNKNOWN') limit 1""",
        (terminal_id,),
    ).fetchone()
    if active:
        return None
    job = connection.execute(
        """select j.*,o.recipe_id,o.recipe_version,o.status as order_status
             from production_job j join sales_order o on o.id=j.order_id
             where j.terminal_id=%s and j.status='QUEUED' and o.status='QUEUED'
             order by j.created_at for update skip locked limit 1""",
        (terminal_id,),
    ).fetchone()
    if not job:
        return None
    expires_at = utc_now() + timedelta(minutes=10)
    message_id = f"cmd-{uuid.uuid4()}"
    command = {
        "messageId": message_id,
        "type": "MAKE_DRINK",
        "taskId": job["task_id"],
        "orderId": str(job["order_id"]),
        "recipeId": job["recipe_id"],
        "recipeVersion": job["recipe_version"],
        "expiresAt": iso(expires_at),
    }
    command_row = connection.execute(
        """insert into terminal_command(
               terminal_id,message_id,command_type,payload_json,idempotency_key,payload_digest,expires_at)
             values(%s,%s,'MAKE_DRINK',%s,%s,%s,%s) returning *""",
        (terminal_id, message_id, Jsonb(command), f"order:{job['order_id']}:make", canonical_digest(command), expires_at),
    ).fetchone()
    connection.execute(
        """insert into terminal_command_transition(
               command_id,revision,from_status,to_status,actor,reason,payload_json)
             values(%s,0,null,'CREATED','order-service','dispatch queued order',%s)""",
        (command_row["id"], Jsonb(command)),
    )
    enqueue_command_outbox(connection, command_row, terminal)
    connection.execute(
        "update production_job set command_id=%s,status='DISPATCHED',revision=revision+1,updated_at=now() where id=%s",
        (command_row["id"], job["id"]),
    )
    order = connection.execute("select * from sales_order where id=%s for update", (job["order_id"],)).fetchone()
    transition_order(connection, order, "DISPATCHED", "order-service", reason="device command created", payload={"messageId": message_id})
    return command


def process_business_outbox_batch(limit: int = 20) -> int:
    processed = 0
    worker_id = f"domain-{uuid.uuid4()}"
    for _ in range(limit):
        event_id: uuid.UUID | None = None
        try:
            with database.connect() as connection:
                event = connection.execute(
                    """select * from business_outbox
                         where status in ('PENDING','RETRY') and next_attempt_at<=now()
                         order by created_at for update skip locked limit 1"""
                ).fetchone()
                if not event:
                    break
                event_id = event["id"]
                connection.execute(
                    "update business_outbox set status='PROCESSING',locked_by=%s,locked_until=now()+interval '30 seconds' where id=%s",
                    (worker_id, event["id"]),
                )
                if event["event_type"] == "payment.paid":
                    order_id = uuid.UUID(str(event["payload_json"]["orderId"]))
                    order = connection.execute("select * from sales_order where id=%s for update", (order_id,)).fetchone()
                    if order and order["payment_status"] == "PAID":
                        job = connection.execute("select * from production_job where order_id=%s", (order_id,)).fetchone()
                        if not job:
                            connection.execute(
                                """insert into production_job(id,task_id,order_id,terminal_id,status,planned_duration_seconds)
                                     values(%s,%s,%s,%s,'QUEUED',%s)""",
                                (uuid.uuid4(), f"task-{uuid.uuid4()}", order_id, order["terminal_id"],
                                 (order["product_snapshot"] or {}).get("estimatedDurationSeconds")),
                            )
                        if order["status"] == "PAID":
                            order = transition_order(connection, order, "QUEUED", "outbox-worker", reason="paid order queued")
                        dispatch_next_order(connection, order["terminal_id"])
                connection.execute(
                    "update business_outbox set status='PROCESSED',processed_at=now(),locked_by=null,locked_until=null where id=%s",
                    (event["id"],),
                )
                processed += 1
        except Exception as exc:
            logger.exception("business outbox event failed id=%s", event_id)
            if event_id is not None:
                with database.connect() as connection:
                    connection.execute(
                        """update business_outbox set status='RETRY',attempt_count=attempt_count+1,
                             next_attempt_at=now()+(least(300,power(2,least(attempt_count+1,8)))::text||' seconds')::interval,
                             last_error=%s,locked_by=null,locked_until=null where id=%s""",
                        (str(exc)[:1000], event_id),
                    )
    return processed


def reconcile_payment_once() -> int:
    with database.connect() as connection:
        payment = connection.execute(
            """select * from payment where status in ('CREATED','PENDING')
                 and (next_reconcile_at is null or next_reconcile_at<=now())
                 order by created_at for update skip locked limit 1"""
        ).fetchone()
        if not payment:
            return 0
        connection.execute(
            "update payment set next_reconcile_at=now()+(%s::text||' seconds')::interval where id=%s",
            (settings.payment_reconcile_seconds, payment["id"]),
        )
    try:
        result = payment_provider(payment["provider"]).query_payment(payment["merchant_payment_no"])
    except Exception as exc:
        logger.info("payment reconciliation deferred payment=%s: %s", payment["id"], exc)
        return 0
    with database.connect() as connection:
        current = connection.execute("select * from payment where id=%s for update", (payment["id"],)).fetchone()
        if current["status"] not in {"CREATED", "PENDING"}:
            return 1
        if result.status == "PAID":
            apply_paid_callback(
                connection, provider=current["provider"],
                event_id=f"reconcile-paid:{current['merchant_payment_no']}",
                values={
                    "merchant_payment_no": current["merchant_payment_no"],
                    "amount_minor": str(current["amount_minor"]),
                    "provider_trade_no": result.provider_trade_no or "",
                },
            )
        elif result.status in {"CLOSED", "FAILED"}:
            target = "CLOSED" if result.status == "CLOSED" else "FAILED"
            transition_payment(connection, current, target, actor="payment-reconciliation", payload=result.raw)
            connection.execute(
                "update sales_order set payment_status=%s,status=case when status in ('CREATED','AWAITING_PAYMENT') then 'CANCELLED' else status end,updated_at=now() where id=%s",
                (target, current["order_id"]),
            )
    return 1


def process_refund_batch() -> int:
    with database.connect() as connection:
        refund = connection.execute(
            """select * from refund where status in ('REQUESTED','UNKNOWN','PROCESSING')
                 and (next_attempt_at is null or next_attempt_at<=now())
                 order by created_at for update skip locked limit 1"""
        ).fetchone()
        if not refund:
            return 0
        payment = connection.execute("select * from payment where id=%s", (refund["payment_id"],)).fetchone()
        if refund["status"] != "PROCESSING":
            refund, _ = transition_refund(connection, refund, "PROCESSING")
            connection.execute("update refund set next_attempt_at=now()+interval '30 seconds' where id=%s", (refund["id"],))
        connection.execute(
            "update refund set attempt_count=attempt_count+1,next_attempt_at=now()+interval '30 seconds' where id=%s",
            (refund["id"],),
        )
    try:
        provider = payment_provider(payment["provider"])
        refund_request = RefundRequest(
            merchant_payment_no=payment["merchant_payment_no"], merchant_refund_no=refund["merchant_refund_no"],
            amount_minor=refund["amount_minor"], reason=refund["reason"], provider_trade_no=payment["provider_trade_no"],
        )
        result = provider.query_refund(refund_request) if int(refund["attempt_count"] or 0) > 0 else provider.refund(refund_request)
        if result.status == "NOT_FOUND":
            result = provider.refund(refund_request)
        target = "SUCCEEDED" if result.status == "REFUNDED" else "PROCESSING"
        provider_payload = result.raw
    except Exception as exc:
        logger.warning("refund reconciliation outcome unknown refund=%s: %s", refund["id"], exc)
        target = "UNKNOWN"
        provider_payload = {"error": f"{type(exc).__name__}: {exc}"}
    with database.connect() as connection:
        current = connection.execute("select * from refund where id=%s for update", (refund["id"],)).fetchone()
        current, _ = transition_refund(connection, current, target, payload=provider_payload)
        if target == "SUCCEEDED":
            current_payment = connection.execute("select * from payment where id=%s for update", (current["payment_id"],)).fetchone()
            refunded = connection.execute(
                "select coalesce(sum(amount_minor),0) as total from refund where payment_id=%s and status='SUCCEEDED'",
                (current_payment["id"],),
            ).fetchone()["total"]
            payment_target = "REFUNDED" if refunded >= current_payment["amount_minor"] else "PARTIALLY_REFUNDED"
            transition_payment(connection, current_payment, payment_target, actor="refund-reconciliation", payload=provider_payload)
            order = connection.execute("select * from sales_order where id=%s for update", (current_payment["order_id"],)).fetchone()
            connection.execute("update sales_order set payment_status=%s,updated_at=now() where id=%s", (payment_target, order["id"]))
            if payment_target == "REFUNDED" and order["status"] == "FAILED":
                transition_order(connection, order, "REFUNDED", "refund-reconciliation", reason="full refund completed")
        else:
            connection.execute(
                "update refund set next_attempt_at=now()+interval '30 seconds' where id=%s", (current["id"],)
            )
    return 1


def watchdog_scan_once() -> None:
    with database.connect() as connection:
        rows = connection.execute(
            """select c.*,j.id as job_id,j.order_id,j.status as job_status,j.planned_duration_seconds,
                      j.started_at as job_started_at
                 from terminal_command c join production_job j on j.command_id=c.id
                where (c.status in ('DELIVERING','PUBLISHED') and coalesce(c.published_at,c.delivered_at) is not null
                       and coalesce(c.published_at,c.delivered_at) < now()-(%s::text||' seconds')::interval)
                   or (c.status='ACKED' and c.acked_at < now()-(%s::text||' seconds')::interval)
                   or (c.status='EXECUTING' and j.started_at is not null
                       and j.started_at + ((coalesce(j.planned_duration_seconds,300)+%s)::text||' seconds')::interval < now())
                for update skip locked""",
            (settings.command_ack_timeout_seconds, settings.command_start_timeout_seconds,
             settings.production_timeout_grace_seconds),
        ).fetchall()
        for row in rows:
            command, _ = transition_command(
                connection, row, "UNKNOWN", "watchdog",
                reason="device outcome requires reconciliation", strict=False,
            )
            connection.execute(
                """update production_job set status='HOLD',hold_reason='DEVICE_OUTCOME_UNKNOWN',
                     manual_review_required=true,revision=revision+1,updated_at=now() where id=%s""",
                (row["job_id"],),
            )
            order = connection.execute("select * from sales_order where id=%s for update", (row["order_id"],)).fetchone()
            if order and order["status"] not in TERMINAL_ORDER_STATUSES:
                transition_order(connection, order, "HOLD", "watchdog", reason="device outcome unknown")


unit_of_work = UnitOfWork(database)
system_service = SystemService(unit_of_work, SERVICE_VERSION, logger)
admin_access_service = AdminAccessService(unit_of_work, settings)
device_identity_service = DeviceIdentityService(
    unit_of_work, settings=settings, provisioner_factory=emqx_provisioner, logger=logger
)
public_order_service = PublicOrderService(
    unit_of_work, settings,
    dispatch_next_order=dispatch_next_order,
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
    dispatch_next_order=dispatch_next_order,
    transition_command=transition_command,
    expire_order_for_command=expire_order_for_command,
    reconcile_command_event=reconcile_command_event,
    reconcile_order_event=reconcile_order_event,
    reconcile_order_ack=reconcile_order_ack,
    order_url=order_url,
)
command_service = CommandService(
    unit_of_work,
    lease_seconds=settings.command_publish_lease_seconds,
    enqueue_outbox=enqueue_command_outbox,
    transition_command=transition_command,
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
