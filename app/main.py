from __future__ import annotations

import logging
import json
import io
import secrets
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
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb
import qrcode

from .database import Database
from .command_state import (
    ACKED, CREATED, DELIVERING, EXECUTING, EXPIRED, PUBLISHED, TERMINAL_STATES,
    decide_transition, event_state, result_state,
)
from .protocol import (
    ActivationCodeRequest, ActivationRequest, AdminDeviceCreateRequest, CommandCreateRequest, CommandResult,
    CredentialRotationRequest, DeviceEvent, Heartbeat, PaymentCreateRequest, PublicOrderCreateRequest,
    RefundCreateRequest, Snapshot, TaskAck,
    canonical_digest, utc_now,
)
from .order_logic import ACTIVE_ORDER_STATUSES, TERMINAL_ORDER_STATUSES, device_progress, order_state_for_event, public_menu
from .security import derive_order_access_token, hash_token, tokens_equal
from .settings import Settings, get_settings
from .payment_providers import AlipayProvider, MockPaymentProvider, PaymentProvider, PaymentRequest, RefundRequest
from .payment_service import apply_paid_callback, callback_event_id, enqueue_outbox, transition_payment, transition_refund
from .emqx_provisioner import EmqxProvisioner


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


def issue_mqtt_credential(terminal: dict[str, Any]) -> dict[str, Any]:
    password = secrets.token_urlsafe(36)
    credential_id = uuid.uuid4()
    with database.connect() as connection:
        version = connection.execute(
            "select coalesce(max(version),0)+1 as version from mqtt_credential where terminal_id=%s",
            (terminal["id"],),
        ).fetchone()["version"]
        connection.execute(
            """insert into mqtt_credential(id,terminal_id,username,secret_hash,version,status)
                 values(%s,%s,%s,%s,%s,'PENDING_PROVISION')""",
            (credential_id, terminal["id"], terminal["device_id"], hash_token(password), version),
        )
    status_value = "PENDING_PROVISION"
    provisioner = emqx_provisioner()
    if provisioner:
        try:
            provisioner.provision_device(terminal["device_id"], password)
            with database.connect() as connection:
                connection.execute(
                    "update mqtt_credential set status='REVOKED',revoked_at=now() where terminal_id=%s and status='ACTIVE' and id<>%s",
                    (terminal["id"], credential_id),
                )
                connection.execute(
                    "update mqtt_credential set status='ACTIVE',broker_synced_at=now() where id=%s", (credential_id,)
                )
            status_value = "ACTIVE"
        except Exception:
            logger.exception("MQTT credential broker provisioning failed device=%s", terminal["device_id"])
    return {
        "credentialId": str(credential_id), "version": version, "status": status_value,
        "username": terminal["device_id"], "password": password,
        "host": "mqtt-api.woodbridge.top", "port": 8883, "tls": True,
        "warning": "MQTT password is returned once and must not be logged",
    }


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

device_bearer = HTTPBearer(auto_error=False, scheme_name="deviceBearer")
admin_bearer = HTTPBearer(auto_error=False, scheme_name="adminBearer")


def require_admin(credentials: Annotated[HTTPAuthorizationCredentials | None, Security(admin_bearer)] = None) -> None:
    token = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else None
    if token is None or not tokens_equal(token, settings.admin_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid admin credential")


def require_gateway(x_gateway_token: Annotated[str | None, Header(alias="X-Gateway-Token")] = None) -> None:
    if x_gateway_token is None or not tokens_equal(x_gateway_token, settings.internal_gateway_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid gateway credential")


def authenticate_device(device_id: str, header_device: str | None, token: str | None) -> dict[str, Any]:
    if header_device != device_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="device identity mismatch")
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing device credential")
    with database.connect() as connection:
        row = connection.execute(
            """
            select t.*, c.id as credential_db_id, c.credential_id, c.version as credential_version,
                   c.status as credential_status
              from terminal t
              join terminal_credential c on c.terminal_id=t.id
             where t.device_id=%s and c.token_hash=%s
               and (c.status='ACTIVE' or (c.status='GRACE' and c.grace_expires_at > now()))
               and (c.not_before is null or c.not_before <= now())
               and (c.expires_at is null or c.expires_at > now())
            """,
            (device_id, hash_token(token)),
        ).fetchone()
        if row is not None:
            connection.execute("update terminal_credential set last_used_at=now() where id=%s", (row["credential_db_id"],))
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid device credential")
    return row


def require_device(
    device_id: str,
    x_device_id: Annotated[str | None, Header(alias="X-Device-Id")] = None,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(device_bearer)] = None,
) -> dict[str, Any]:
    token = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else None
    return authenticate_device(device_id, x_device_id, token)


DeviceIdentity = Annotated[dict[str, Any], Depends(require_device)]
AdminAuth = Annotated[None, Depends(require_admin)]
GatewayAuth = Annotated[None, Depends(require_gateway)]


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        database.ping()
    except Exception:
        logger.exception("health dependency check failed")
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ok", "version": SERVICE_VERSION, "database": "ok", "time": iso(utc_now())}


@app.get("/")
def root() -> dict[str, Any]:
    return {"service": "coffee-cloud-mvp", "version": SERVICE_VERSION, "health": "/health"}


@app.get("/order", response_class=FileResponse, include_in_schema=False)
@app.get("/order/status", response_class=FileResponse, include_in_schema=False)
def public_order_page() -> Path:
    return PUBLIC_DIR / "order.html"


def find_terminal(connection: Any, identifier: str, *, for_update: bool = False) -> dict[str, Any]:
    suffix = " for update" if for_update else ""
    row = connection.execute(
        f"select * from terminal where device_id=%s or serial_number=%s{suffix}",
        (identifier, identifier),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="device not found")
    return row


def credential_payload(row: dict[str, Any], *, duplicate: bool = False) -> dict[str, Any]:
    return {
        "credentialId": str(row["credential_id"]),
        "version": row["version"],
        "status": row["status"],
        "notBefore": iso(row.get("not_before")),
        "expiresAt": iso(row.get("expires_at")),
        "graceExpiresAt": iso(row.get("grace_expires_at")),
        "duplicate": duplicate,
    }


@app.post("/api/v1/admin/devices/{identifier}/activation-codes", tags=["device-identity"])
def create_activation_code(
    identifier: str,
    payload: ActivationCodeRequest,
    _: AdminAuth,
) -> dict[str, Any]:
    ttl = payload.ttlSeconds or settings.activation_ttl_seconds
    activation_code = secrets.token_urlsafe(24)
    activation_id = uuid.uuid4()
    expires_at = utc_now() + timedelta(seconds=ttl)
    with database.connect() as connection:
        terminal = find_terminal(connection, identifier, for_update=True)
        connection.execute(
            "update terminal_activation set status='CANCELLED' where terminal_id=%s and status='PENDING'",
            (terminal["id"],),
        )
        connection.execute(
            """insert into terminal_activation(
                   activation_id, terminal_id, code_hash, max_attempts, expires_at)
                 values(%s,%s,%s,%s,%s)""",
            (activation_id, terminal["id"], hash_token(activation_code), settings.activation_max_attempts, expires_at),
        )
    return {
        "activationId": str(activation_id),
        "deviceId": terminal["device_id"],
        "activationCode": activation_code,
        "expiresAt": iso(expires_at),
        "warning": "activationCode is returned once and must not be logged",
    }


@app.post("/api/v1/device-activations", tags=["device-identity"])
def activate_device(payload: ActivationRequest) -> dict[str, Any]:
    code_hash = hash_token(payload.activationCode)
    new_token_hash = hash_token(payload.deviceToken)
    now = utc_now()
    with database.connect() as connection:
        terminal = find_terminal(connection, payload.deviceId, for_update=True)
        activation = connection.execute(
            """select * from terminal_activation
                 where terminal_id=%s and code_hash=%s
                 order by id desc limit 1 for update""",
            (terminal["id"], code_hash),
        ).fetchone()
        if activation is None:
            pending = connection.execute(
                """select * from terminal_activation
                     where terminal_id=%s and status='PENDING'
                     order by id desc limit 1 for update""",
                (terminal["id"],),
            ).fetchone()
            if pending:
                attempts = pending["attempt_count"] + 1
                next_status = "LOCKED" if attempts >= pending["max_attempts"] else "PENDING"
                connection.execute(
                    "update terminal_activation set attempt_count=%s,status=%s where id=%s",
                    (attempts, next_status, pending["id"]),
                )
            raise HTTPException(status_code=401, detail="invalid or expired activation code")
        if activation["status"] == "CONSUMED":
            credential = connection.execute(
                "select * from terminal_credential where id=%s",
                (activation["consumed_credential_id"],),
            ).fetchone()
            if credential and tokens_equal(credential["token_hash"].strip(), new_token_hash):
                return {"deviceId": terminal["device_id"], **credential_payload(credential, duplicate=True)}
            raise HTTPException(status_code=409, detail="activation code already consumed")
        if activation["status"] != "PENDING" or activation["expires_at"] <= now:
            if activation["status"] == "PENDING":
                connection.execute("update terminal_activation set status='EXPIRED' where id=%s", (activation["id"],))
            raise HTTPException(status_code=401, detail="invalid or expired activation code")
        collision = connection.execute("select id from terminal_credential where token_hash=%s", (new_token_hash,)).fetchone()
        if collision:
            raise HTTPException(status_code=409, detail="credential token already registered")
        version = connection.execute(
            "select coalesce(max(version),0)+1 as version from terminal_credential where terminal_id=%s",
            (terminal["id"],),
        ).fetchone()["version"]
        grace_expires_at = now + timedelta(seconds=settings.credential_grace_seconds)
        connection.execute(
            """update terminal_credential
                  set status='GRACE', grace_expires_at=%s
                where terminal_id=%s and status='ACTIVE'""",
            (grace_expires_at, terminal["id"]),
        )
        credential = connection.execute(
            """insert into terminal_credential(
                   terminal_id,token_hash,credential_id,version,not_before,status)
                 values(%s,%s,%s,%s,%s,'ACTIVE') returning *""",
            (terminal["id"], new_token_hash, uuid.uuid4(), version, now),
        ).fetchone()
        connection.execute(
            """update terminal_activation
                  set status='CONSUMED',consumed_at=%s,consumed_credential_id=%s
                where id=%s""",
            (now, credential["id"], activation["id"]),
        )
        connection.execute("update terminal set lifecycle_status='ACTIVE', updated_at=%s where id=%s", (now, terminal["id"]))
    mqtt_credential = issue_mqtt_credential(terminal)
    return {"deviceId": terminal["device_id"], **credential_payload(credential), "mqttCredential": mqtt_credential}


@app.post("/api/v1/devices/{device_id}/mqtt-credentials/rotate", tags=["device-identity"])
def rotate_mqtt_credential(device_id: str, identity: DeviceIdentity) -> dict[str, Any]:
    credential = issue_mqtt_credential(identity)
    return {"deviceId": identity["device_id"], "mqttCredential": credential}


@app.post("/api/v1/admin/devices/{identifier}/mqtt-credentials/revoke", tags=["device-identity"])
def revoke_mqtt_credential(identifier: str, _: AdminAuth) -> dict[str, Any]:
    with database.connect() as connection:
        terminal = find_terminal(connection, identifier, for_update=True)
        changed = connection.execute(
            """update mqtt_credential set status='REVOKED',revoked_at=coalesce(revoked_at,now())
                 where terminal_id=%s and status<>'REVOKED' returning id""", (terminal["id"],)
        ).fetchall()
    provisioner = emqx_provisioner()
    broker_status = "NOT_CONFIGURED"
    if provisioner:
        try:
            provisioner.revoke_device(terminal["device_id"])
            broker_status = "REVOKED"
        except Exception as exc:
            logger.exception("MQTT credential broker revoke failed device=%s", terminal["device_id"])
            broker_status = f"RETRY_REQUIRED:{type(exc).__name__}"
    return {"deviceId": terminal["device_id"], "revokedCredentials": len(changed), "brokerStatus": broker_status}


@app.post("/api/v1/devices/{device_id}/credentials/rotate", tags=["device-identity"])
def rotate_credential(
    device_id: str,
    payload: CredentialRotationRequest,
    identity: DeviceIdentity,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    if not idempotency_key or len(idempotency_key) > 160:
        raise HTTPException(status_code=400, detail="Idempotency-Key is required and must be <= 160 characters")
    new_token_hash = hash_token(payload.newToken)
    request_digest = canonical_digest(payload.model_dump(mode="json"))
    now = utc_now()
    grace_expires_at = now + timedelta(seconds=settings.credential_grace_seconds)
    with database.connect() as connection:
        existing = connection.execute(
            "select * from credential_rotation_request where terminal_id=%s and idempotency_key=%s for update",
            (identity["id"], idempotency_key),
        ).fetchone()
        if existing:
            if existing["request_digest"].strip() != request_digest:
                raise HTTPException(status_code=409, detail="Idempotency-Key payload conflict")
            return {**existing["response_json"], "duplicate": True}
        old_credential = connection.execute(
            "select * from terminal_credential where id=%s for update",
            (identity["credential_db_id"],),
        ).fetchone()
        if old_credential is None:
            raise HTTPException(status_code=401, detail="credential no longer exists")
        if tokens_equal(old_credential["token_hash"].strip(), new_token_hash):
            raise HTTPException(status_code=400, detail="new credential must differ from current credential")
        if connection.execute("select 1 from terminal_credential where token_hash=%s", (new_token_hash,)).fetchone():
            raise HTTPException(status_code=409, detail="credential token already registered")
        version = connection.execute(
            "select coalesce(max(version),0)+1 as version from terminal_credential where terminal_id=%s",
            (identity["id"],),
        ).fetchone()["version"]
        connection.execute(
            "update terminal_credential set status='GRACE',grace_expires_at=%s where id=%s",
            (grace_expires_at, old_credential["id"]),
        )
        credential = connection.execute(
            """insert into terminal_credential(
                   terminal_id,token_hash,credential_id,version,not_before,status,rotated_from_id)
                 values(%s,%s,%s,%s,%s,'ACTIVE',%s) returning *""",
            (identity["id"], new_token_hash, uuid.uuid4(), version, now, old_credential["id"]),
        ).fetchone()
        response = {
            "deviceId": device_id,
            **credential_payload(credential),
            "previousCredentialGraceExpiresAt": iso(grace_expires_at),
        }
        connection.execute(
            """insert into credential_rotation_request(
                   terminal_id,idempotency_key,request_digest,old_credential_id,new_credential_id,response_json)
                 values(%s,%s,%s,%s,%s,%s)""",
            (identity["id"], idempotency_key, request_digest, old_credential["id"], credential["id"], Jsonb(response)),
        )
    return response


@app.get("/api/v1/admin/devices/{identifier}/credentials", tags=["device-identity"])
def list_credentials(identifier: str, _: AdminAuth) -> dict[str, Any]:
    with database.connect() as connection:
        terminal = find_terminal(connection, identifier)
        rows = connection.execute(
            "select * from terminal_credential where terminal_id=%s order by version desc",
            (terminal["id"],),
        ).fetchall()
    return {"deviceId": terminal["device_id"], "credentials": [credential_payload(row) for row in rows]}


@app.post("/api/v1/admin/devices/{identifier}/credentials/{credential_id}/revoke", tags=["device-identity"])
def revoke_credential(identifier: str, credential_id: uuid.UUID, _: AdminAuth) -> dict[str, Any]:
    with database.connect() as connection:
        terminal = find_terminal(connection, identifier)
        before = connection.execute(
            "select * from terminal_credential where terminal_id=%s and credential_id=%s",
            (terminal["id"], credential_id),
        ).fetchone()
        if before is None:
            raise HTTPException(status_code=404, detail="credential not found")
        duplicate = before["status"] == "REVOKED"
        credential = connection.execute(
            """update terminal_credential set status='REVOKED',revoked_at=now(),grace_expires_at=null
                 where terminal_id=%s and credential_id=%s and status <> 'REVOKED' returning *""",
            (terminal["id"], credential_id),
        ).fetchone()
        if credential is None:
            credential = before
    return {"deviceId": terminal["device_id"], **credential_payload(credential, duplicate=duplicate)}


@app.post("/api/v1/devices/{device_id}/heartbeat")
def heartbeat(device_id: str, payload: Heartbeat, identity: DeviceIdentity) -> dict[str, Any]:
    if payload.deviceId != device_id:
        raise HTTPException(status_code=400, detail="payload deviceId mismatch")
    body = payload.model_dump(mode="json", exclude_none=True)
    digest = canonical_digest(body)
    message_id = payload.messageId or f"legacy:{digest}"
    received_at = utc_now()
    disposition = "ACCEPTED"
    with database.connect() as connection:
        existing = connection.execute(
            "select payload_digest, disposition from heartbeat_inbox where terminal_id=%s and message_id=%s",
            (identity["id"], message_id),
        ).fetchone()
        if existing:
            if existing["payload_digest"].strip() != digest:
                raise HTTPException(status_code=409, detail="messageId payload conflict")
            connection.execute(
                "update terminal set connection_status='online', last_seen_at=%s, last_heartbeat_at=%s, updated_at=%s where id=%s",
                (received_at, received_at, received_at, identity["id"]),
            )
            dispatch_next_order(connection, identity["id"])
            return {"ok": True, "duplicate": True, "disposition": existing["disposition"], "receivedAt": iso(received_at), "qrUrl": order_url(identity["device_id"])}

        current_boot = identity.get("active_boot_id")
        last_sequence = identity.get("last_sequence")
        out_of_order = bool(payload.bootId and current_boot == payload.bootId and payload.sequence is not None and last_sequence is not None and payload.sequence <= last_sequence)
        if out_of_order:
            disposition = "OUT_OF_ORDER"
        try:
            connection.execute(
                """
                insert into heartbeat_inbox(terminal_id, message_id, payload_digest, boot_id, sequence, occurred_at, received_at, disposition, payload_json)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (identity["id"], message_id, digest, payload.bootId, payload.sequence, payload.sentAt, received_at, disposition, Jsonb(body)),
            )
        except UniqueViolation as exc:
            raise HTTPException(status_code=409, detail="bootId/sequence conflict") from exc

        connected_at = identity.get("last_connected_at") or received_at
        if identity.get("connection_status") != "online" or current_boot != payload.bootId:
            connected_at = received_at
        if out_of_order:
            connection.execute(
                """
                update terminal set connection_status='online', last_seen_at=%s,
                  last_heartbeat_at=%s, last_connected_at=%s, updated_at=%s where id=%s
                """,
                (received_at, received_at, connected_at, received_at, identity["id"]),
            )
        else:
            reported_status = {
                "deviceStatus": payload.deviceStatus,
                "currentTaskId": body.get("currentTaskId"),
                "currentTaskState": body.get("currentTaskState"),
                "currentTaskRevision": body.get("currentTaskRevision"),
                "deliveries": body.get("deliveries"),
                "sentAt": body.get("sentAt"),
            }
            connection.execute(
                """
                update terminal set connection_status='online', last_seen_at=%s,
                  last_heartbeat_at=%s, last_connected_at=%s, active_boot_id=%s,
                  last_sequence=%s, instance_id=coalesce(%s, instance_id),
                  store_id=coalesce(%s, store_id), software_version=%s,
                  capability_version=%s, inventory_version=%s,
                  reported_status=%s, updated_at=%s where id=%s
                """,
                (received_at, received_at, connected_at, payload.bootId, payload.sequence,
                 payload.instanceId, payload.storeId, payload.appVersion,
                 body.get("capabilityVersion"), body.get("inventoryVersion"),
                 Jsonb(reported_status), received_at, identity["id"]),
            )
        dispatch_next_order(connection, identity["id"])
    return {"ok": True, "duplicate": False, "disposition": disposition, "receivedAt": iso(received_at), "qrUrl": order_url(identity["device_id"])}


@app.get("/api/v1/devices/{device_id}/commands")
def commands(device_id: str, identity: DeviceIdentity, after: str = "", limit: int = Query(default=10, ge=1, le=100)) -> dict[str, Any]:
    try:
        cursor = int(after) if after else 0
    except ValueError:
        cursor = 0
    with database.connect() as connection:
        rows = connection.execute(
            "select * from terminal_command where terminal_id=%s and id>%s order by id limit %s for update",
            (identity["id"], cursor, limit),
        ).fetchall()
        deliverable: list[dict[str, Any]] = []
        for row in rows:
            cursor = row["id"]
            if row["expires_at"] and row["expires_at"] <= utc_now() and row["status"] not in TERMINAL_STATES:
                updated, _ = transition_command(connection, row, EXPIRED, "cloud", reason="command expired before delivery")
                expire_order_for_command(connection, updated)
                continue
            if row["status"] == CREATED:
                row, _ = transition_command(connection, row, DELIVERING, "cloud", reason="device polled command")
            if row["status"] in {DELIVERING, PUBLISHED}:
                deliverable.append(row["payload_json"])
    return {"commands": deliverable, "nextCursor": str(cursor)}


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


def save_snapshot(identity: dict[str, Any], snapshot_type: str, payload: dict[str, Any], version: str | None) -> dict[str, Any]:
    if payload.get("deviceId") != identity["device_id"]:
        raise HTTPException(status_code=400, detail="payload deviceId mismatch")
    with database.connect() as connection:
        connection.execute(
            """
            insert into terminal_snapshot(terminal_id,snapshot_type,version,payload_json)
            values(%s,%s,%s,%s)
            on conflict(terminal_id,snapshot_type) do update set
              version=excluded.version,payload_json=excluded.payload_json,received_at=now()
            """,
            (identity["id"], snapshot_type, version, Jsonb(payload)),
        )
    return {"ok": True, "receivedAt": iso(utc_now())}


@app.put("/api/v1/devices/{device_id}/capabilities")
def capabilities(device_id: str, payload: Snapshot, identity: DeviceIdentity) -> dict[str, Any]:
    body = payload.model_dump(mode="json")
    return save_snapshot(identity, "capabilities", body, str(body.get("capabilityVersion") or ""))


@app.put("/api/v1/devices/{device_id}/inventory")
def inventory(device_id: str, payload: Snapshot, identity: DeviceIdentity) -> dict[str, Any]:
    body = payload.model_dump(mode="json")
    return save_snapshot(identity, "inventory", body, str(body.get("version") or body.get("inventoryVersion") or ""))


@app.post("/api/v1/devices/{device_id}/events")
def events(device_id: str, payload: DeviceEvent, identity: DeviceIdentity) -> dict[str, Any]:
    if payload.deviceId != device_id:
        raise HTTPException(status_code=400, detail="payload deviceId mismatch")
    body = payload.model_dump(mode="json")
    digest = canonical_digest(body)
    with database.connect() as connection:
        existing = connection.execute("select payload_digest from terminal_event where terminal_id=%s and event_id=%s", (identity["id"], payload.eventId)).fetchone()
        if existing:
            if existing["payload_digest"].strip() != digest:
                raise HTTPException(status_code=409, detail="eventId payload conflict")
            command_transition = reconcile_command_event(connection, identity["id"], body, payload.type)
            return {"ok": True, "duplicate": True, "commandTransition": command_transition, "orderTransition": {"duplicate": True}}
        connection.execute(
            """insert into terminal_event(terminal_id,event_id,boot_id,sequence,event_type,occurred_at,payload_digest,payload_json)
               values(%s,%s,%s,%s,%s,%s,%s,%s)""",
            (identity["id"], payload.eventId, payload.bootId, payload.sequence, payload.type, payload.occurredAt, digest, Jsonb(body)),
        )
        command_transition = reconcile_command_event(connection, identity["id"], body, payload.type)
        order_transition = reconcile_order_event(connection, identity["id"], body, payload.type)
    return {"ok": True, "duplicate": False, "commandTransition": command_transition, "orderTransition": order_transition}


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
    with database.connect() as connection:
        command = connection.execute(
            "select * from terminal_command where terminal_id=%s and message_id=%s for update",
            (identity["id"], body.get("messageId")),
        ).fetchone()
        if command is None or command["payload_json"].get("taskId") != task_id:
            raise HTTPException(status_code=404, detail="task command not found")
        target = ACKED if body.get("accepted") else "REJECTED"
        if target == ACKED and command["status"] in {ACKED, EXECUTING, *TERMINAL_STATES}:
            return {
                "ok": True, "duplicate": True, "stale": command["status"] != ACKED,
                "taskId": task_id, "deviceId": identity["device_id"],
                "commandStatus": command["status"], "revision": command["revision"],
            }
        updated, duplicate = transition_command(
            connection, command, target, "device-ack", reason=body.get("reason") or body.get("reasonCode"), payload=body,
        )
        reconcile_order_ack(connection, identity["id"], task_id, body)
    return {
        "ok": True, "duplicate": duplicate, "stale": False,
        "taskId": task_id, "deviceId": identity["device_id"],
        "commandStatus": updated["status"], "revision": updated["revision"],
    }


@app.post("/api/v1/devices/{device_id}/commands/{message_id}/result")
def command_result(device_id: str, message_id: str, payload: CommandResult, identity: DeviceIdentity) -> dict[str, Any]:
    body = payload.model_dump(mode="json")
    target = result_state(payload.status)
    with database.connect() as connection:
        command = connection.execute(
            "select * from terminal_command where terminal_id=%s and message_id=%s for update",
            (identity["id"], message_id),
        ).fetchone()
        if command is None:
            raise HTTPException(status_code=404, detail="command not found")
        updated, duplicate = transition_command(
            connection, command, target, "device-result", reason=payload.status, payload=body,
        )
    return {"ok": True, "duplicate": duplicate, "status": updated["status"], "revision": updated["revision"]}


@app.post("/api/v1/internal/mqtt/messages", tags=["device-platform"], include_in_schema=False)
async def ingest_mqtt_message(request: Request, _: GatewayAuth) -> dict[str, Any]:
    body = await request.json()
    topic = str(body.get("topic") or "")
    envelope = body.get("envelope")
    parts = topic.split("/")
    if len(parts) != 4 or parts[:2] != ["v1", "devices"] or parts[3] not in {"up", "state", "presence"}:
        raise HTTPException(status_code=422, detail="invalid MQTT uplink topic")
    topic_device = parts[2]
    if not isinstance(envelope, dict):
        raise HTTPException(status_code=422, detail="MQTT payload must be a JSON object")
    envelope_device = envelope.get("deviceId")
    payload = envelope.get("payload") if parts[3] == "up" else envelope
    payload_device = payload.get("deviceId") if isinstance(payload, dict) else None
    if envelope_device not in {None, topic_device} or payload_device != topic_device:
        logger.warning("MQTT identity mismatch topic=%s envelope=%s payload=%s", topic_device, envelope_device, payload_device)
        with database.connect() as connection:
            connection.execute(
                "insert into security_event(event_type,device_id,source,detail_json) values('MQTT_IDENTITY_MISMATCH',%s,'mqtt-gateway',%s)",
                (topic_device, Jsonb({"topic": topic, "envelopeDeviceId": envelope_device, "payloadDeviceId": payload_device})),
            )
        raise HTTPException(status_code=403, detail="MQTT device identity mismatch")
    message_type = str(envelope.get("type") or parts[3])
    message_id = str(envelope.get("messageId") or payload.get("eventId") or payload.get("messageId") or f"{parts[3]}:{canonical_digest(payload)}")
    digest = canonical_digest(envelope)
    boot_id = payload.get("bootId") if isinstance(payload, dict) else None
    sequence = payload.get("sequence") if isinstance(payload, dict) else None
    nested = payload.get("payload") if isinstance(payload, dict) and isinstance(payload.get("payload"), dict) else {}
    revision = nested.get("taskRevision") or payload.get("revision") if isinstance(payload, dict) else None
    with database.connect() as connection:
        terminal = connection.execute("select * from terminal where device_id=%s", (topic_device,)).fetchone()
        if not terminal:
            raise HTTPException(status_code=404, detail="device not registered")
        existing = connection.execute(
            "select * from mqtt_inbox where device_id=%s and message_id=%s for update", (topic_device, message_id)
        ).fetchone()
        if existing and existing["payload_digest"].strip() != digest:
            raise HTTPException(status_code=409, detail="MQTT messageId payload conflict")
        if existing and existing["status"] == "PROCESSED":
            return {"ok": True, "duplicate": True, "disposition": existing["disposition"]}
        if not existing:
            inserted = connection.execute(
                """insert into mqtt_inbox(device_id,topic,message_id,message_type,boot_id,sequence,revision,payload_digest,payload_json)
                     values(%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict do nothing returning id""",
                (topic_device, topic, message_id, message_type, boot_id, sequence, revision, digest, Jsonb(envelope)),
            ).fetchone()
            if not inserted:
                return {"ok": True, "duplicate": True, "disposition": "DUPLICATE_SEQUENCE"}

    identity = terminal
    try:
        if parts[3] == "presence":
            with database.connect() as connection:
                connection.execute(
                    """update terminal set connection_status=%s,last_seen_at=now(),
                         last_connected_at=case when %s='online' then coalesce(last_connected_at,now()) else last_connected_at end,
                         updated_at=now() where id=%s""",
                    ("online" if payload.get("online") else "offline", "online" if payload.get("online") else "offline", terminal["id"]),
                )
            result = {"ok": True}
        elif parts[3] == "state":
            with database.connect() as connection:
                connection.execute(
                    "update terminal set reported_status=%s,last_seen_at=now(),updated_at=now() where id=%s",
                    (Jsonb(payload), terminal["id"]),
                )
            result = {"ok": True}
        elif message_type == "heartbeat":
            result = heartbeat(topic_device, Heartbeat.model_validate(payload), identity)
        elif message_type == "event":
            result = events(topic_device, DeviceEvent.model_validate(payload), identity)
        elif message_type == "command_result":
            if payload.get("commandType") == "MAKE_DRINK":
                result = apply_task_ack(identity, str(payload.get("taskId") or ""), payload)
            else:
                result = command_result(
                    topic_device, str(payload.get("messageId") or ""),
                    CommandResult.model_validate(payload), identity,
                )
        else:
            raise HTTPException(status_code=422, detail="unsupported MQTT envelope type")
    except Exception as exc:
        with database.connect() as connection:
            connection.execute(
                "update mqtt_inbox set status='RETRY',error_message=%s where device_id=%s and message_id=%s",
                (str(exc)[:1000], topic_device, message_id),
            )
        raise
    with database.connect() as connection:
        connection.execute(
            """update mqtt_inbox set status='PROCESSED',disposition='APPLIED',processed_at=now(),error_message=null
                 where device_id=%s and message_id=%s""",
            (topic_device, message_id),
        )
    return {"ok": True, "duplicate": False, "result": result}


@app.get("/api/v1/internal/device-commands/claim", tags=["device-platform"], include_in_schema=False)
def claim_device_commands(
    _: GatewayAuth,
    gateway_id: str = Query(min_length=1, max_length=160),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    with database.connect() as connection:
        rows = connection.execute(
            """select o.* from command_outbox o
                 where ((o.status in ('PENDING','RETRY') and o.next_attempt_at<=now())
                    or (o.status='PUBLISHING' and o.locked_until<now()))
                 order by o.created_at for update skip locked limit %s""",
            (limit,),
        ).fetchall()
        claimed = []
        for row in rows:
            updated = connection.execute(
                """update command_outbox set status='PUBLISHING',attempt_count=attempt_count+1,
                     locked_by=%s,locked_until=now()+(%s::text||' seconds')::interval where id=%s returning *""",
                (gateway_id, settings.command_publish_lease_seconds, row["id"]),
            ).fetchone()
            claimed.append({
                "outboxId": str(updated["id"]), "topic": updated["topic"],
                "envelope": updated["envelope_json"], "attempt": updated["attempt_count"],
            })
    return {"commands": claimed}


@app.post("/api/v1/internal/device-commands/{outbox_id}/published", tags=["device-platform"], include_in_schema=False)
async def mark_device_command_published(outbox_id: uuid.UUID, request: Request, _: GatewayAuth) -> dict[str, Any]:
    body = await request.json()
    gateway_id = str(body.get("gatewayId") or "")
    with database.connect() as connection:
        outbox = connection.execute("select * from command_outbox where id=%s for update", (outbox_id,)).fetchone()
        if not outbox:
            raise HTTPException(status_code=404, detail="command outbox item not found")
        if outbox["status"] == "PUBLISHED":
            return {"ok": True, "duplicate": True}
        if outbox["status"] != "PUBLISHING" or outbox["locked_by"] != gateway_id:
            raise HTTPException(status_code=409, detail="command publish lease mismatch")
        connection.execute(
            """update command_outbox set status='PUBLISHED',published_at=now(),locked_by=null,locked_until=null,
                 last_error=null where id=%s""", (outbox_id,)
        )
        command = connection.execute("select * from terminal_command where id=%s for update", (outbox["command_id"],)).fetchone()
        if command["status"] in {CREATED, DELIVERING}:
            command, _ = transition_command(connection, command, PUBLISHED, "mqtt-gateway", reason="broker PUBACK")
        connection.execute("update terminal_command set published_at=coalesce(published_at,now()) where id=%s", (command["id"],))
    return {"ok": True, "duplicate": False}


@app.post("/api/v1/internal/device-commands/{outbox_id}/retry", tags=["device-platform"], include_in_schema=False)
async def retry_device_command(outbox_id: uuid.UUID, request: Request, _: GatewayAuth) -> dict[str, Any]:
    body = await request.json()
    gateway_id = str(body.get("gatewayId") or "")
    error = str(body.get("error") or "publish failed")[:1000]
    with database.connect() as connection:
        row = connection.execute("select * from command_outbox where id=%s for update", (outbox_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="command outbox item not found")
        if row["status"] == "PUBLISHED":
            return {"ok": True, "duplicate": True}
        if row["locked_by"] != gateway_id:
            raise HTTPException(status_code=409, detail="command publish lease mismatch")
        connection.execute(
            """update command_outbox set status='RETRY',next_attempt_at=now()+
                 (least(60,power(2,least(attempt_count,6)))::text||' seconds')::interval,
                 last_error=%s,locked_by=null,locked_until=null where id=%s""",
            (error, outbox_id),
        )
    return {"ok": True, "duplicate": False}


def create_command(identity: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    digest = canonical_digest(payload)
    with database.connect() as connection:
        row = connection.execute(
            """insert into terminal_command(
                   terminal_id,message_id,command_type,payload_json,payload_digest,expires_at)
                 values(%s,%s,%s,%s,%s,%s) returning *""",
            (identity["id"], payload["messageId"], payload["type"], Jsonb(payload), digest, payload.get("expiresAt")),
        )
        command = row.fetchone()
        connection.execute(
            """insert into terminal_command_transition(
                   command_id,revision,from_status,to_status,actor,reason,payload_json)
                 values(%s,0,null,'CREATED','debug-api','legacy debug command',%s)""",
            (command["id"], Jsonb(payload)),
        )
        enqueue_command_outbox(connection, command, identity)
    return payload


def command_payload(row: dict[str, Any], transitions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    result = {
        "messageId": row["message_id"],
        "deviceId": row.get("device_id"),
        "type": row["command_type"],
        "status": row["status"],
        "revision": row["revision"],
        "command": row["payload_json"],
        "result": row["result_json"],
        "createdAt": iso(row["created_at"]),
        "deliveredAt": iso(row["delivered_at"]),
        "ackedAt": iso(row["acked_at"]),
        "executingAt": iso(row["executing_at"]),
        "completedAt": iso(row["completed_at"]),
        "expiresAt": iso(row["expires_at"]),
    }
    if transitions is not None:
        result["transitions"] = [
            {
                "revision": item["revision"], "from": item["from_status"], "to": item["to_status"],
                "actor": item["actor"], "reason": item["reason"],
                "createdAt": iso(item["created_at"]), "payload": item["payload_json"],
            }
            for item in transitions
        ]
    return result


@app.post("/api/v1/admin/devices/{identifier}/commands", tags=["admin-commands"], status_code=201)
def admin_create_command(
    identifier: str,
    payload: CommandCreateRequest,
    _: AdminAuth,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    if not idempotency_key or len(idempotency_key) > 160:
        raise HTTPException(status_code=400, detail="Idempotency-Key is required and must be <= 160 characters")
    if payload.type == "MAKE_DRINK" and not all((payload.taskId, payload.orderId, payload.recipeId)):
        raise HTTPException(status_code=422, detail="MAKE_DRINK requires taskId, orderId and recipeId")
    expires_at = payload.expiresAt or (utc_now() + timedelta(minutes=5))
    if expires_at <= utc_now():
        raise HTTPException(status_code=422, detail="expiresAt must be in the future")
    request_body = payload.model_dump(mode="json", exclude_none=True)
    request_digest = canonical_digest(request_body)
    with database.connect() as connection:
        terminal = find_terminal(connection, identifier, for_update=True)
        existing = connection.execute(
            "select * from terminal_command where terminal_id=%s and idempotency_key=%s for update",
            (terminal["id"], idempotency_key),
        ).fetchone()
        if existing:
            if (existing["payload_digest"] or "").strip() != request_digest:
                raise HTTPException(status_code=409, detail="Idempotency-Key payload conflict")
            return {"duplicate": True, **command_payload(existing)}
        message_id = f"cmd-{uuid.uuid4()}"
        command = {
            **payload.payload,
            "messageId": message_id,
            "type": payload.type,
            "expiresAt": iso(expires_at),
        }
        for key, value in {
            "taskId": payload.taskId, "orderId": payload.orderId,
            "recipeId": payload.recipeId, "recipeVersion": payload.recipeVersion,
            "action": payload.action,
        }.items():
            if value is not None:
                command[key] = value
        row = connection.execute(
            """insert into terminal_command(
                   terminal_id,message_id,command_type,payload_json,idempotency_key,payload_digest,expires_at)
                 values(%s,%s,%s,%s,%s,%s,%s) returning *""",
            (terminal["id"], message_id, payload.type, Jsonb(command), idempotency_key, request_digest, expires_at),
        ).fetchone()
        connection.execute(
            """insert into terminal_command_transition(
                   command_id,revision,from_status,to_status,actor,reason,payload_json)
                 values(%s,0,null,'CREATED','admin-api','command created',%s)""",
            (row["id"], Jsonb(command)),
        )
        enqueue_command_outbox(connection, row, terminal)
    return {"duplicate": False, **command_payload(row)}


@app.get("/api/v1/admin/devices/{identifier}/commands/{message_id}", tags=["admin-commands"])
def admin_get_command(identifier: str, message_id: str, _: AdminAuth) -> dict[str, Any]:
    with database.connect() as connection:
        terminal = find_terminal(connection, identifier)
        row = connection.execute(
            "select * from terminal_command where terminal_id=%s and message_id=%s",
            (terminal["id"], message_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="command not found")
        transitions = connection.execute(
            "select * from terminal_command_transition where command_id=%s order by revision",
            (row["id"],),
        ).fetchall()
    return command_payload(row, transitions)


@app.post("/api/v1/devices/{device_id}/debug/orders")
async def debug_order(device_id: str, request: Request, identity: DeviceIdentity) -> dict[str, Any]:
    body = await request.json()
    command = {
        "messageId": f"cmd-{uuid.uuid4()}", "type": "MAKE_DRINK",
        "taskId": f"task-{uuid.uuid4()}", "orderId": f"debug-{uuid.uuid4()}",
        "recipeId": body.get("recipeId"), "expiresAt": iso(utc_now() + timedelta(minutes=5)),
    }
    create_command(identity, command)
    return {"ok": True, "command": command}


@app.post("/api/v1/devices/{device_id}/debug/commands")
async def debug_command(device_id: str, request: Request, identity: DeviceIdentity) -> dict[str, Any]:
    body = await request.json()
    command = {"messageId": f"cmd-{uuid.uuid4()}", "type": "DEBUG_COMMAND", "action": body.get("action")}
    create_command(identity, command)
    return {"ok": True, "command": command}


@app.patch("/api/v1/devices/{device_id}/debug/overrides")
async def debug_overrides(device_id: str, request: Request, identity: DeviceIdentity) -> dict[str, Any]:
    body = await request.json()
    return {"ok": True, "deviceId": identity["device_id"], "overrides": body}


def snapshot_payload(connection: Any, terminal_id: int, snapshot_type: str) -> dict[str, Any] | None:
    row = connection.execute(
        "select payload_json from terminal_snapshot where terminal_id=%s and snapshot_type=%s",
        (terminal_id, snapshot_type),
    ).fetchone()
    return row["payload_json"] if row else None


def transition_order(
    connection: Any,
    order: dict[str, Any],
    target: str,
    actor: str,
    *,
    reason: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if order["status"] == target:
        return order
    if order["status"] in TERMINAL_ORDER_STATUSES and not (order["status"] == "FAILED" and target == "REFUNDED"):
        return order
    revision = connection.execute(
        "select coalesce(max(revision),-1)+1 as revision from order_transition where order_id=%s",
        (order["id"],),
    ).fetchone()["revision"]
    now_at = utc_now()
    started_at = now_at if target == "MAKING" and not order.get("started_at") else order.get("started_at")
    completed_at = now_at if target in {"READY", "FAILED", "EXPIRED"} else order.get("completed_at")
    cancelled_at = now_at if target == "CANCELLED" else order.get("cancelled_at")
    updated = connection.execute(
        """update sales_order set status=%s,updated_at=%s,started_at=%s,completed_at=%s,cancelled_at=%s
             where id=%s returning *""",
        (target, now_at, started_at, completed_at, cancelled_at, order["id"]),
    ).fetchone()
    connection.execute(
        """insert into order_transition(order_id,revision,from_status,to_status,actor,reason,payload_json)
             values(%s,%s,%s,%s,%s,%s,%s)""",
        (order["id"], revision, order["status"], target, actor, reason, Jsonb(payload) if payload else None),
    )
    return updated


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


def public_order_payload(connection: Any, order: dict[str, Any]) -> dict[str, Any]:
    job = connection.execute("select * from production_job where order_id=%s", (order["id"],)).fetchone()
    payment = connection.execute(
        "select * from payment where order_id=%s order by created_at desc limit 1", (order["id"],)
    ).fetchone()
    transitions = connection.execute(
        "select * from order_transition where order_id=%s order by revision", (order["id"],)
    ).fetchall()
    queue_position = 0
    if order["status"] == "QUEUED":
        queue_position = connection.execute(
            """select count(*) as count from sales_order
                 where terminal_id=%s and status='QUEUED' and created_at <= %s""",
            (order["terminal_id"], order["created_at"]),
        ).fetchone()["count"]
    return {
        "orderId": str(order["id"]),
        "orderNo": order["order_no"],
        "deviceId": order.get("device_id"),
        "storeId": order.get("store_id"),
        "status": order["status"],
        "paymentMode": order["payment_mode"],
        "paymentStatus": order["payment_status"],
        "payment": payment_payload(payment) if payment else None,
        "totalAmountMinor": order["total_amount_minor"],
        "currency": order["currency"],
        "product": order["product_snapshot"],
        "queuePosition": int(queue_position),
        "failure": {"code": order["failure_code"], "message": order["failure_message"]} if order["failure_code"] else None,
        "production": {
            "taskId": job["task_id"], "status": job["status"],
            "progress": job["progress"], "overallProgress": job["progress"], "stepProgress": job["step_progress"],
            "currentStepId": job["current_step_id"], "currentStepName": job["current_step_name"],
            "plannedDurationSeconds": job["planned_duration_seconds"],
            "elapsedSeconds": job["elapsed_seconds"], "remainingSeconds": job["remaining_seconds"],
            "stepPlan": job["step_durations"], "stepDurations": job["step_durations"],
            "acceptedAt": iso(job["accepted_at"]), "startedAt": iso(job["started_at"]), "completedAt": iso(job["completed_at"]),
        } if job else None,
        "createdAt": iso(order["created_at"]), "updatedAt": iso(order["updated_at"]),
        "startedAt": iso(order["started_at"]), "completedAt": iso(order["completed_at"]),
        "timeline": [
            {"revision": item["revision"], "from": item["from_status"], "to": item["to_status"],
             "reason": item["reason"], "createdAt": iso(item["created_at"])} for item in transitions
        ],
    }


@app.get("/api/v1/public/devices/{identifier}/menu", tags=["public-orders"])
def get_public_menu(identifier: str) -> dict[str, Any]:
    with database.connect() as connection:
        terminal = find_terminal(connection, identifier)
        capabilities = snapshot_payload(connection, terminal["id"], "capabilities")
        inventory = snapshot_payload(connection, terminal["id"], "inventory")
    return {**public_menu(
        terminal, capabilities, inventory, settings.offline_threshold_seconds,
        settings.default_product_price_minor, settings.payment_currency, settings.public_payment_mode,
    ), "serverTime": iso(utc_now())}


@app.post("/api/v1/public/devices/{identifier}/orders", tags=["public-orders"], status_code=201)
def create_public_order(
    identifier: str,
    payload: PublicOrderCreateRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    if not idempotency_key or len(idempotency_key) > 160:
        raise HTTPException(status_code=400, detail="Idempotency-Key is required and must be <= 160 characters")
    if payload.paymentMode != settings.public_payment_mode:
        raise HTTPException(status_code=409, detail="payment mode changed; refresh the menu")
    request_body = payload.model_dump(mode="json")
    digest = canonical_digest(request_body)
    with database.connect() as connection:
        terminal = find_terminal(connection, identifier, for_update=True)
        access_token = derive_order_access_token(settings.order_access_secret or settings.admin_token, terminal["device_id"], idempotency_key)
        existing = connection.execute(
            "select o.*,t.device_id,t.store_id from sales_order o join terminal t on t.id=o.terminal_id where o.terminal_id=%s and o.idempotency_key=%s for update",
            (terminal["id"], idempotency_key),
        ).fetchone()
        if existing:
            if existing["request_digest"].strip() != digest:
                raise HTTPException(status_code=409, detail="Idempotency-Key payload conflict")
            return {**public_order_payload(connection, existing), "accessToken": access_token, "duplicate": True}
        capabilities = snapshot_payload(connection, terminal["id"], "capabilities")
        inventory = snapshot_payload(connection, terminal["id"], "inventory")
        menu = public_menu(
            terminal, capabilities, inventory, settings.offline_threshold_seconds,
            settings.default_product_price_minor, settings.payment_currency, settings.public_payment_mode,
        )
        product = next((item for item in menu["products"] if item["recipeId"] == payload.recipeId), None)
        if not product or product["recipeVersion"] != payload.recipeVersion:
            raise HTTPException(status_code=409, detail="recipe is missing or version changed; refresh the menu")
        if not product["available"]:
            raise HTTPException(status_code=409, detail={"code": "PRODUCT_UNAVAILABLE", "reasons": product["unavailableReasons"]})
        active_count = connection.execute(
            "select count(*) as count from sales_order where terminal_id=%s and status in ('QUEUED','DISPATCHED','ACCEPTED','MAKING')",
            (terminal["id"],),
        ).fetchone()["count"]
        if active_count >= settings.public_order_queue_limit:
            raise HTTPException(status_code=429, detail="device order queue is full")
        order_id = uuid.uuid4()
        task_id = f"task-{uuid.uuid4()}"
        order_no = f"C{utc_now().strftime('%m%d')}-{secrets.token_hex(3).upper()}"
        product_snapshot = {**product, "quantity": 1}
        order_status = "QUEUED" if payload.paymentMode == "TEST_FREE" else "CREATED"
        payment_status = "NOT_REQUIRED" if payload.paymentMode == "TEST_FREE" else "NOT_STARTED"
        order = connection.execute(
            """insert into sales_order(
                   id,order_no,terminal_id,access_token_hash,idempotency_key,request_digest,status,
                   payment_mode,payment_status,currency,total_amount_minor,
                   recipe_id,recipe_version,sku_code,product_name,product_snapshot)
                 values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *""",
            (order_id, order_no, terminal["id"], hash_token(access_token), idempotency_key, digest,
             order_status, payload.paymentMode, payment_status, product["currency"], product["priceMinor"],
             product["recipeId"], product["recipeVersion"], product["skuCode"], product["name"], Jsonb(product_snapshot)),
        ).fetchone()
        connection.execute(
            """insert into order_transition(order_id,revision,from_status,to_status,actor,reason,payload_json)
                 values(%s,0,null,%s,'public-api',%s,%s)""",
            (order_id, order_status,
             "test-free order accepted" if payload.paymentMode == "TEST_FREE" else "order created awaiting payment",
             Jsonb({"recipeId": payload.recipeId, "inventoryVersion": menu.get("inventoryVersion")})),
        )
        if payload.paymentMode == "TEST_FREE":
            connection.execute(
                """insert into production_job(id,task_id,order_id,terminal_id,status,planned_duration_seconds)
                     values(%s,%s,%s,%s,'QUEUED',%s)""",
                (uuid.uuid4(), task_id, order_id, terminal["id"], product.get("estimatedDurationSeconds")),
            )
            dispatch_next_order(connection, terminal["id"])
        created = connection.execute(
            "select o.*,t.device_id,t.store_id from sales_order o join terminal t on t.id=o.terminal_id where o.id=%s",
            (order_id,),
        ).fetchone()
        response = public_order_payload(connection, created)
    return {**response, "accessToken": access_token}


def authenticate_order(connection: Any, order_id: uuid.UUID, token: str | None, *, for_update: bool = False) -> dict[str, Any]:
    if not token:
        raise HTTPException(status_code=401, detail="missing order access token")
    suffix = " for update" if for_update else ""
    order = connection.execute(
        f"select o.*,t.device_id,t.store_id from sales_order o join terminal t on t.id=o.terminal_id where o.id=%s{suffix}",
        (order_id,),
    ).fetchone()
    if order is None or not tokens_equal(order["access_token_hash"].strip(), hash_token(token)):
        raise HTTPException(status_code=404, detail="order not found")
    return order


def payment_payload(payment: dict[str, Any]) -> dict[str, Any]:
    return {
        "paymentId": str(payment["id"]), "orderId": str(payment["order_id"]),
        "provider": payment["provider"], "merchantPaymentNo": payment["merchant_payment_no"],
        "status": payment["status"], "revision": payment["revision"],
        "amountMinor": payment["amount_minor"], "currency": payment["currency"],
        "qrCode": payment["qr_code"], "createdAt": iso(payment["created_at"]),
        "updatedAt": iso(payment["updated_at"]), "paidAt": iso(payment["paid_at"]),
    }


@app.post("/api/v1/orders/{order_id}/payments", tags=["payments"], status_code=201)
def create_payment(
    order_id: uuid.UUID,
    payload: PaymentCreateRequest,
    access_token: Annotated[str | None, Header(alias="X-Order-Access-Token")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    if not idempotency_key or len(idempotency_key) > 160:
        raise HTTPException(status_code=400, detail="Idempotency-Key is required and must be <= 160 characters")
    provider_name = (payload.provider or settings.payment_default_provider).lower()
    if provider_name == "mock" and not settings.allow_mock_payment:
        raise HTTPException(status_code=503, detail="mock payment provider is disabled")
    digest = canonical_digest(payload.model_dump(mode="json"))
    with database.connect() as connection:
        order = authenticate_order(connection, order_id, access_token, for_update=True)
        if order["payment_mode"] == "TEST_FREE":
            raise HTTPException(status_code=409, detail="test-free order does not require payment")
        existing = connection.execute(
            "select * from payment where order_id=%s and idempotency_key=%s for update",
            (order_id, idempotency_key),
        ).fetchone()
        if existing:
            if existing["request_digest"].strip() != digest:
                raise HTTPException(status_code=409, detail="Idempotency-Key payload conflict")
            if existing["status"] != "CREATED":
                return {**payment_payload(existing), "duplicate": True}
            payment = existing
        else:
            if order["payment_status"] in {"PAID", "REFUNDING", "REFUNDED"}:
                raise HTTPException(status_code=409, detail="order payment is already complete")
            payment_id = uuid.uuid4()
            merchant_no = f"C{utc_now().strftime('%Y%m%d%H%M%S')}{secrets.token_hex(5).upper()}"
            payment = connection.execute(
                """insert into payment(id,order_id,provider,merchant_payment_no,idempotency_key,
                       request_digest,status,amount_minor,currency,subject)
                     values(%s,%s,%s,%s,%s,%s,'CREATED',%s,%s,%s) returning *""",
                (payment_id, order_id, provider_name, merchant_no, idempotency_key, digest,
                 order["total_amount_minor"], order["currency"], order["product_name"]),
            ).fetchone()
            connection.execute(
                """insert into payment_event(payment_id,event_id,event_type,actor,payload_json)
                     values(%s,'created','payment.created','customer',%s)""",
                (payment_id, Jsonb(payload.model_dump(mode="json"))),
            )
            if order["status"] == "CREATED":
                transition_order(connection, order, "AWAITING_PAYMENT", "payment-service", reason="payment created")
            connection.execute(
                "update sales_order set payment_status='PENDING',updated_at=now() where id=%s", (order_id,)
            )

    provider = payment_provider(provider_name)
    request_value = PaymentRequest(
        merchant_payment_no=payment["merchant_payment_no"], amount_minor=payment["amount_minor"],
        currency=payment["currency"], subject=payment["subject"],
        notify_url=f"{settings.public_base_url.rstrip('/')}/api/v1/payments/callback/{provider_name}",
        metadata={"orderId": str(order_id)},
    )
    try:
        if payment["status"] == "CREATED":
            try:
                result = provider.query_payment(payment["merchant_payment_no"])
                if result.status == "NOT_FOUND" or (result.status == "FAILED" and provider_name == "mock"):
                    result = provider.create_payment(request_value)
            except Exception:
                result = provider.create_payment(request_value)
        else:
            result = provider.query_payment(payment["merchant_payment_no"])
    except Exception as exc:
        logger.warning("payment create/query failed payment=%s provider=%s: %s", payment["id"], provider_name, exc)
        raise HTTPException(status_code=502, detail="payment provider temporarily unavailable") from exc

    with database.connect() as connection:
        current = connection.execute("select * from payment where id=%s for update", (payment["id"],)).fetchone()
        connection.execute(
            "update payment set qr_code=coalesce(%s,qr_code),provider_trade_no=coalesce(%s,provider_trade_no),provider_response=%s,updated_at=now() where id=%s",
            (result.qr_code, result.provider_trade_no, Jsonb(result.raw), current["id"]),
        )
        current = connection.execute("select * from payment where id=%s", (current["id"],)).fetchone()
        if result.status == "PAID":
            values = {"merchant_payment_no": current["merchant_payment_no"], "amount_minor": str(current["amount_minor"]), "provider_trade_no": result.provider_trade_no or ""}
            current, _ = apply_paid_callback(
                connection, provider=provider_name,
                event_id=f"query-paid:{current['merchant_payment_no']}", values=values,
            )
        elif current["status"] == "CREATED":
            current, _ = transition_payment(connection, current, "PENDING", actor="payment-provider", payload=result.raw)
            connection.execute(
                "update payment set next_reconcile_at=now()+(%s::text||' seconds')::interval where id=%s",
                (settings.payment_reconcile_seconds, current["id"]),
            )
    return {**payment_payload(current), "duplicate": existing is not None}


def payment_with_order_auth(connection: Any, payment_id: uuid.UUID, token: str | None) -> dict[str, Any]:
    payment = connection.execute("select * from payment where id=%s", (payment_id,)).fetchone()
    if not payment:
        raise HTTPException(status_code=404, detail="payment not found")
    authenticate_order(connection, payment["order_id"], token)
    return payment


@app.get("/api/v1/payments/{payment_id}", tags=["payments"])
def get_payment(
    payment_id: uuid.UUID,
    access_token: Annotated[str | None, Header(alias="X-Order-Access-Token")] = None,
) -> dict[str, Any]:
    with database.connect() as connection:
        return payment_payload(payment_with_order_auth(connection, payment_id, access_token))


@app.get("/api/v1/payments/{payment_id}/qr", tags=["payments"], response_class=Response)
def get_payment_qr(
    payment_id: uuid.UUID,
    access_token: Annotated[str | None, Header(alias="X-Order-Access-Token")] = None,
) -> Response:
    with database.connect() as connection:
        payment = payment_with_order_auth(connection, payment_id, access_token)
    if not payment["qr_code"]:
        raise HTTPException(status_code=409, detail="payment QR code is not ready")
    image = qrcode.make(payment["qr_code"])
    output = io.BytesIO()
    image.save(output, format="PNG")
    return Response(output.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


@app.post("/api/v1/payments/callback/alipay", tags=["payments"], response_class=PlainTextResponse)
async def alipay_callback(request: Request) -> str:
    values = dict(parse_qsl((await request.body()).decode("utf-8"), keep_blank_values=True))
    try:
        parsed = payment_provider("alipay").verify_and_parse_callback(values)
        if parsed.get("app_id") and parsed.get("app_id") != settings.alipay_app_id:
            raise ValueError("Alipay callback app_id mismatch")
        if parsed.get("trade_status") not in {"TRADE_SUCCESS", "TRADE_FINISHED"}:
            return "success"
        with database.connect() as connection:
            apply_paid_callback(
                connection, provider="alipay", event_id=callback_event_id("alipay", parsed), values=parsed,
            )
        return "success"
    except (ValueError, HTTPException) as exc:
        logger.warning("Alipay callback rejected: %s", exc)
        return "failure"


@app.post("/api/v1/payments/callback/mock", tags=["payments"], include_in_schema=False)
async def mock_payment_callback(request: Request, _: AdminAuth) -> dict[str, Any]:
    if settings.payment_default_provider != "mock" or not settings.allow_mock_payment:
        raise HTTPException(status_code=404, detail="mock payment callback is disabled")
    values = await request.json()
    merchant_no = str(values.get("merchant_payment_no") or "")
    with database.connect() as connection:
        payment = connection.execute(
            "select * from payment where provider='mock' and merchant_payment_no=%s", (merchant_no,)
        ).fetchone()
        if not payment:
            raise HTTPException(status_code=404, detail="payment not found")
    result = mock_payment_provider.set_paid(merchant_no, str(values.get("provider_trade_no") or "") or None)
    callback_values = {
        "merchant_payment_no": merchant_no, "amount_minor": str(payment["amount_minor"]),
        "provider_trade_no": result.provider_trade_no or "",
    }
    with database.connect() as connection:
        updated, duplicate = apply_paid_callback(
            connection, provider="mock",
            event_id=str(values.get("event_id") or f"mock-paid:{merchant_no}"), values=callback_values,
        )
    return {**payment_payload(updated), "duplicate": duplicate}


@app.post("/api/v1/payments/{payment_id}/refund", tags=["payments"], status_code=202)
def create_refund(
    payment_id: uuid.UUID,
    payload: RefundCreateRequest,
    _: AdminAuth,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    if not idempotency_key or len(idempotency_key) > 160:
        raise HTTPException(status_code=400, detail="Idempotency-Key is required and must be <= 160 characters")
    digest = canonical_digest(payload.model_dump(mode="json"))
    with database.connect() as connection:
        payment = connection.execute("select * from payment where id=%s for update", (payment_id,)).fetchone()
        if not payment:
            raise HTTPException(status_code=404, detail="payment not found")
        if payment["status"] not in {"PAID", "REFUNDING", "PARTIALLY_REFUNDED"}:
            raise HTTPException(status_code=409, detail="payment is not refundable")
        existing = connection.execute(
            "select * from refund where payment_id=%s and idempotency_key=%s for update",
            (payment_id, idempotency_key),
        ).fetchone()
        if existing:
            if existing["request_digest"].strip() != digest:
                raise HTTPException(status_code=409, detail="Idempotency-Key payload conflict")
            if existing["status"] in {"PROCESSING", "SUCCEEDED"}:
                return {"refundId": str(existing["id"]), "status": existing["status"], "duplicate": True}
            refund = existing
        else:
            amount = payload.amountMinor or payment["amount_minor"]
            refunded = connection.execute(
                "select coalesce(sum(amount_minor),0) as total from refund where payment_id=%s and status='SUCCEEDED'",
                (payment_id,),
            ).fetchone()["total"]
            if amount + refunded > payment["amount_minor"]:
                raise HTTPException(status_code=409, detail="refund amount exceeds unrefunded payment amount")
            refund = connection.execute(
                """insert into refund(id,payment_id,provider,merchant_refund_no,idempotency_key,
                       request_digest,status,amount_minor,reason)
                     values(%s,%s,%s,%s,%s,%s,'REQUESTED',%s,%s) returning *""",
                (uuid.uuid4(), payment_id, payment["provider"], f"R{uuid.uuid4().hex[:24].upper()}",
                 idempotency_key, digest, amount, payload.reason),
            ).fetchone()
            transition_payment(connection, payment, "REFUNDING", actor="refund-service", payload={"refundId": str(refund["id"])})
            refund, _ = transition_refund(connection, refund, "PROCESSING")
            connection.execute("update refund set next_attempt_at=now()+interval '30 seconds' where id=%s", (refund["id"],))

    provider = payment_provider(payment["provider"])
    try:
        result = provider.refund(RefundRequest(
            merchant_payment_no=payment["merchant_payment_no"], merchant_refund_no=refund["merchant_refund_no"],
            amount_minor=refund["amount_minor"], reason=refund["reason"], provider_trade_no=payment["provider_trade_no"],
        ))
        target = "SUCCEEDED" if result.status == "REFUNDED" else "PROCESSING"
    except Exception as exc:
        logger.warning("refund outcome unknown refund=%s: %s", refund["id"], exc)
        result = None
        target = "UNKNOWN"
    with database.connect() as connection:
        current = connection.execute("select * from refund where id=%s for update", (refund["id"],)).fetchone()
        current, _ = transition_refund(connection, current, target, payload=result.raw if result else {"error": "provider outcome unknown"})
        if target == "UNKNOWN":
            connection.execute(
                "update refund set attempt_count=attempt_count+1,next_attempt_at=now()+interval '30 seconds' where id=%s", (current["id"],)
            )
        elif target == "PROCESSING":
            connection.execute(
                "update refund set attempt_count=greatest(attempt_count,1),next_attempt_at=now()+interval '30 seconds' where id=%s",
                (current["id"],),
            )
        elif target == "SUCCEEDED":
            current_payment = connection.execute("select * from payment where id=%s for update", (payment_id,)).fetchone()
            refunded = connection.execute(
                "select coalesce(sum(amount_minor),0) as total from refund where payment_id=%s and status='SUCCEEDED'", (payment_id,)
            ).fetchone()["total"]
            payment_target = "REFUNDED" if refunded >= current_payment["amount_minor"] else "PARTIALLY_REFUNDED"
            transition_payment(connection, current_payment, payment_target, actor="refund-provider", payload=result.raw if result else {})
            if payment_target == "REFUNDED":
                order = connection.execute("select * from sales_order where id=%s for update", (current_payment["order_id"],)).fetchone()
                connection.execute("update sales_order set payment_status='REFUNDED',updated_at=now() where id=%s", (order["id"],))
                if order["status"] == "FAILED":
                    transition_order(connection, order, "REFUNDED", "refund-provider", reason="full refund completed")
    return {"refundId": str(current["id"]), "paymentId": str(payment_id), "status": current["status"], "duplicate": existing is not None}


@app.get("/api/v1/public/orders/{order_id}", tags=["public-orders"])
def get_public_order(
    order_id: uuid.UUID,
    access_token: Annotated[str | None, Header(alias="X-Order-Access-Token")] = None,
) -> dict[str, Any]:
    with database.connect() as connection:
        order = authenticate_order(connection, order_id, access_token)
        return public_order_payload(connection, order)


@app.post("/api/v1/public/orders/{order_id}/cancel", tags=["public-orders"])
def cancel_public_order(
    order_id: uuid.UUID,
    access_token: Annotated[str | None, Header(alias="X-Order-Access-Token")] = None,
) -> dict[str, Any]:
    payment_to_close: dict[str, Any] | None = None
    with database.connect() as connection:
        order = authenticate_order(connection, order_id, access_token, for_update=True)
        if order["status"] not in {"CREATED", "AWAITING_PAYMENT", "QUEUED"}:
            raise HTTPException(status_code=409, detail="only unpaid or queued orders can be cancelled safely")
        if order["status"] in {"CREATED", "AWAITING_PAYMENT"}:
            payment_to_close = connection.execute(
                "select * from payment where order_id=%s and status in ('CREATED','PENDING') order by created_at desc limit 1 for update",
                (order_id,),
            ).fetchone()
        order = transition_order(connection, order, "CANCELLED", "customer", reason="cancelled before dispatch")
        connection.execute(
            "update production_job set status='CANCELLED',revision=revision+1,updated_at=now(),completed_at=now() where order_id=%s",
            (order_id,),
        )
    if payment_to_close:
        try:
            result = payment_provider(payment_to_close["provider"]).close_payment(payment_to_close["merchant_payment_no"])
            with database.connect() as connection:
                current = connection.execute("select * from payment where id=%s for update", (payment_to_close["id"],)).fetchone()
                if current["status"] in {"CREATED", "PENDING"}:
                    transition_payment(connection, current, "CLOSED", actor="customer-cancel", payload=result.raw)
                    connection.execute("update sales_order set payment_status='CLOSED',updated_at=now() where id=%s", (order_id,))
        except Exception as exc:
            logger.warning("payment close deferred after order cancellation payment=%s: %s", payment_to_close["id"], exc)
    with database.connect() as connection:
        order = authenticate_order(connection, order_id, access_token)
        return public_order_payload(connection, order)


def admin_device_payload(row: dict[str, Any]) -> dict[str, Any]:
    cutoff = utc_now() - timedelta(seconds=settings.offline_threshold_seconds)
    online = bool(row["last_heartbeat_at"] and row["last_heartbeat_at"] >= cutoff)
    return {
        "deviceId": row["device_id"], "serialNumber": row["serial_number"],
        "instanceId": row["instance_id"], "storeId": row["store_id"],
        "lifecycleStatus": row["lifecycle_status"],
        "online": online, "connectionStatus": "online" if online else "offline",
        "hasEverConnected": bool(row["last_connected_at"] or row["last_seen_at"]),
        "registeredAt": iso(row["created_at"]),
        "lastSeenAt": iso(row["last_seen_at"]), "lastHeartbeatAt": iso(row["last_heartbeat_at"]),
        "lastConnectedAt": iso(row["last_connected_at"]), "softwareVersion": row["software_version"],
        "activeBootId": row["active_boot_id"], "lastSequence": row["last_sequence"],
        "reportedStatus": row["reported_status"], "lastErrorSummary": row["last_error_summary"],
        "heartbeatCount": int(row.get("heartbeat_count", 0)),
        "eventCount": int(row.get("event_count", 0)),
        "commandCount": int(row.get("command_count", 0)),
        "activeOrderCount": int(row.get("active_order_count", 0)),
        "offlineThresholdSeconds": settings.offline_threshold_seconds,
    }


@app.post("/api/v1/admin/devices", tags=["device-identity"], status_code=201)
def register_admin_device(payload: AdminDeviceCreateRequest, _: AdminAuth) -> dict[str, Any]:
    with database.connect() as connection:
        existing = connection.execute(
            "select * from terminal where device_id=%s or serial_number=%s",
            (payload.deviceId, payload.serialNumber),
        ).fetchone()
        if existing:
            if existing["device_id"] == payload.deviceId and existing["serial_number"] == payload.serialNumber:
                return {"duplicate": True, **admin_device_payload(existing)}
            raise HTTPException(status_code=409, detail="deviceId or serialNumber already exists")
        row = connection.execute(
            """insert into terminal(device_id,serial_number,instance_id,store_id,lifecycle_status)
                 values(%s,%s,%s,%s,'PENDING_ACTIVATION') returning *""",
            (payload.deviceId, payload.serialNumber, payload.instanceId, payload.storeId),
        ).fetchone()
    return {"duplicate": False, **admin_device_payload(row)}


@app.get("/api/v1/admin/devices/{identifier}")
def admin_device(identifier: str, _: AdminAuth) -> dict[str, Any]:
    offline_monitor.scan_once()
    with database.connect() as connection:
        row = connection.execute("select * from terminal where device_id=%s or serial_number=%s", (identifier, identifier)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="device not found")
        heartbeat_count = connection.execute("select count(*) as count from heartbeat_inbox where terminal_id=%s", (row["id"],)).fetchone()["count"]
        event_count = connection.execute("select count(*) as count from terminal_event where terminal_id=%s", (row["id"],)).fetchone()["count"]
        command_count = connection.execute("select count(*) as count from terminal_command where terminal_id=%s", (row["id"],)).fetchone()["count"]
        active_order_count = connection.execute("select count(*) as count from sales_order where terminal_id=%s and status in ('QUEUED','DISPATCHED','ACCEPTED','MAKING')", (row["id"],)).fetchone()["count"]
        snapshot_rows = connection.execute("select snapshot_type,version,received_at from terminal_snapshot where terminal_id=%s", (row["id"],)).fetchall()
    return {**admin_device_payload({**row, "heartbeat_count": heartbeat_count, "event_count": event_count, "command_count": command_count, "active_order_count": active_order_count}), "snapshots": {item["snapshot_type"]: {"version": item["version"], "receivedAt": iso(item["received_at"])} for item in snapshot_rows}}


@app.get("/api/v1/admin/devices")
def admin_devices(_: AdminAuth) -> dict[str, Any]:
    offline_monitor.scan_once()
    with database.connect() as connection:
        rows = connection.execute(
            """select t.*,
                    (select count(*) from heartbeat_inbox h where h.terminal_id=t.id) as heartbeat_count,
                    (select count(*) from terminal_event e where e.terminal_id=t.id) as event_count,
                    (select count(*) from terminal_command c where c.terminal_id=t.id) as command_count,
                    (select count(*) from sales_order o where o.terminal_id=t.id and o.status in ('QUEUED','DISPATCHED','ACCEPTED','MAKING')) as active_order_count
                 from terminal t order by t.created_at desc, t.serial_number"""
        ).fetchall()
    return {"devices": [admin_device_payload(row) for row in rows], "serverTime": iso(utc_now())}


@app.get("/api/v1/admin/devices/{identifier}/inventory", tags=["admin-operations"])
def admin_device_inventory(identifier: str, _: AdminAuth) -> dict[str, Any]:
    with database.connect() as connection:
        terminal = find_terminal(connection, identifier)
        row = connection.execute(
            "select * from terminal_snapshot where terminal_id=%s and snapshot_type='inventory'",
            (terminal["id"],),
        ).fetchone()
    if not row:
        return {"deviceId": terminal["device_id"], "available": False, "materials": []}
    return {"deviceId": terminal["device_id"], "available": True, "receivedAt": iso(row["received_at"]), **row["payload_json"]}


@app.get("/api/v1/admin/orders", tags=["admin-operations"])
def admin_orders(
    _: AdminAuth,
    device_id: str | None = Query(default=None, alias="deviceId"),
    order_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    clauses: list[str] = []
    params: list[Any] = []
    if device_id:
        clauses.append("t.device_id=%s")
        params.append(device_id)
    if order_status:
        clauses.append("o.status=%s")
        params.append(order_status.upper())
    where = " where " + " and ".join(clauses) if clauses else ""
    params.append(limit)
    with database.connect() as connection:
        rows = connection.execute(
            f"""select o.*,t.device_id,t.store_id,j.task_id,j.status as production_status,
                       j.progress,j.current_step_name
                  from sales_order o join terminal t on t.id=o.terminal_id
                  left join production_job j on j.order_id=o.id
                  {where} order by o.created_at desc limit %s""",
            params,
        ).fetchall()
    return {"orders": [
        {"orderId": str(row["id"]), "orderNo": row["order_no"], "deviceId": row["device_id"],
         "storeId": row["store_id"], "status": row["status"], "productName": row["product_name"],
         "paymentMode": row["payment_mode"], "productionStatus": row["production_status"],
         "progress": row["progress"], "currentStepName": row["current_step_name"],
         "failureCode": row["failure_code"], "createdAt": iso(row["created_at"]), "updatedAt": iso(row["updated_at"])}
        for row in rows
    ], "serverTime": iso(utc_now())}


ADMIN_HTML = """<!doctype html>
<html lang=\"zh-CN\">
<head>
<meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>Coffee Cloud · 设备运营台</title>
<style>
:root{font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,\"Segoe UI\",sans-serif;color:#29231f;background:#f5f1ec;line-height:1.45}
*{box-sizing:border-box}body{margin:0}.shell{max-width:1440px;margin:auto;padding:28px 28px 56px}.topbar{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:28px}.brand{display:flex;align-items:center;gap:14px}.logo{width:44px;height:44px;border-radius:14px;background:#4c2f20;color:#fff;display:grid;place-items:center;font-size:23px;box-shadow:0 8px 20px #4c2f2030}.eyebrow{font-size:12px;letter-spacing:.13em;text-transform:uppercase;color:#9a7255;font-weight:800}.brand h1{font-size:25px;margin:1px 0 0;letter-spacing:-.03em}.session{display:flex;align-items:center;gap:10px}.input,.button{font:inherit;border:1px solid #d8cec4;border-radius:11px;padding:10px 13px;background:#fff;color:inherit}.input:focus{outline:3px solid #c9905d55;border-color:#b67a4b}.button{background:#4c2f20;color:#fff;border-color:#4c2f20;font-weight:700;cursor:pointer}.button.secondary{background:#fff;color:#4c2f20;border-color:#d8cec4}.button.ghost{background:transparent;color:#6b5546;border-color:transparent}.button:disabled{opacity:.55;cursor:not-allowed}.card{background:#fff;border:1px solid #e7ddd4;border-radius:18px;box-shadow:0 12px 32px #5036210d}.login{max-width:520px;margin:12vh auto;padding:34px}.login h2{margin:0 0 8px;font-size:26px}.muted{color:#887b72}.login-row{display:flex;gap:10px;margin-top:22px}.login-row .input{flex:1}.hidden{display:none!important}.dashboard-head{display:flex;justify-content:space-between;align-items:end;gap:20px;margin-bottom:18px}.dashboard-head h2{margin:0;font-size:27px;letter-spacing:-.035em}.refresh-note{font-size:13px;color:#887b72}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:18px}.stat{padding:18px 20px}.stat-label{font-size:13px;color:#887b72}.stat-value{font-size:30px;font-weight:800;margin-top:4px;letter-spacing:-.05em}.stat-value.green{color:#087f5b}.stat-value.red{color:#bd4034}.toolbar{padding:14px;display:flex;gap:10px;align-items:center;margin-bottom:14px}.toolbar .input{min-width:250px}.toolbar select{font:inherit}.toolbar-spacer{flex:1}.table-card{overflow:hidden}.table-scroll{overflow:auto}.devices{width:100%;border-collapse:collapse;min-width:860px}.devices th{text-align:left;font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:#95877d;background:#faf8f5;padding:13px 16px;border-bottom:1px solid #eee5dd;white-space:nowrap}.devices td{padding:15px 16px;border-bottom:1px solid #f0e9e3;vertical-align:middle;font-size:14px}.devices tbody tr{cursor:pointer;transition:background .15s}.devices tbody tr:hover,.devices tbody tr.selected{background:#fff8f1}.device-name{font-weight:750;color:#35271f}.device-sub{font-size:12px;color:#998d84;margin-top:2px}.badge{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:5px 9px;font-size:12px;font-weight:750}.badge:before{content:\"\";width:7px;height:7px;border-radius:50%;background:currentColor}.badge.online{color:#087f5b;background:#e8f6ef}.badge.offline{color:#9c5147;background:#fff0ec}.badge.pending{color:#9a6b22;background:#fff5d9}.empty{padding:42px;text-align:center;color:#95877d}.lower{display:grid;grid-template-columns:1.3fr .7fr;gap:18px;margin-top:18px}.detail,.register{padding:22px}.detail h3,.register h3{margin:0 0 16px}.detail-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}.detail-item{background:#faf8f5;border-radius:12px;padding:11px 13px}.detail-item label{display:block;color:#95877d;font-size:12px;margin-bottom:3px}.detail-item strong{font-size:14px;word-break:break-word}.detail pre{background:#28221e;color:#f7eee7;border-radius:12px;padding:14px;overflow:auto;font-size:12px;max-height:180px;margin:14px 0 0}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.form-grid .full{grid-column:1/-1}.form-actions{display:flex;gap:10px;margin-top:13px;align-items:center}.activation{margin-top:15px;background:#fff7df;border:1px solid #eed58f;border-radius:12px;padding:13px;font-size:13px}.activation code{display:block;word-break:break-all;margin:7px 0;font-size:14px;color:#6d451f}.error{color:#b7352d;font-size:13px;margin-top:9px}.ok{color:#087f5b;font-size:13px;margin-top:9px}@media(max-width:900px){.shell{padding:18px}.topbar{align-items:flex-start;flex-direction:column}.session{width:100%}.session .input{flex:1;min-width:0}.stats{grid-template-columns:repeat(2,1fr)}.lower{grid-template-columns:1fr}}@media(max-width:540px){.stats{gap:8px}.stat{padding:14px}.stat-value{font-size:25px}.toolbar{align-items:stretch;flex-direction:column}.toolbar .input{min-width:0}.toolbar-spacer{display:none}.login-row{flex-direction:column}.form-grid,.detail-grid{grid-template-columns:1fr}}
.stats{grid-template-columns:repeat(5,1fr)}
</style>
</head>
<body>
<main class=\"shell\">
  <header class=\"topbar\">
    <div class=\"brand\"><div class=\"logo\">☕</div><div><div class=\"eyebrow\">Coffee Cloud</div><h1>终端运营台</h1></div></div>
    <div id=\"session\" class=\"session hidden\"><span id=\"last-refresh\" class=\"refresh-note\"></span><button class=\"button ghost\" onclick=\"logout()\">退出</button></div>
  </header>

  <section id=\"login\" class=\"card login\">
    <div class=\"eyebrow\">Admin access</div><h2>登录设备运营台</h2>
    <p class=\"muted\">登录后查看全部已登记终端。Token 只保存在当前页面内存中，刷新页面后需要重新输入。</p>
    <div class=\"login-row\"><input id=\"token\" class=\"input\" type=\"password\" autocomplete=\"off\" placeholder=\"管理员 Token\"><button class=\"button\" onclick=\"login()\">登录</button></div>
    <div id=\"login-error\" class=\"error\"></div>
  </section>

  <section id=\"dashboard\" class=\"hidden\">
    <div class=\"dashboard-head\"><div><div class=\"eyebrow\">Fleet overview</div><h2>设备总览</h2></div><div id=\"server-time\" class=\"refresh-note\"></div></div>
    <div class=\"stats\"><div class=\"card stat\"><div class=\"stat-label\">已登记实例</div><div id=\"total\" class=\"stat-value\">-</div></div><div class=\"card stat\"><div class=\"stat-label\">当前在线</div><div id=\"online\" class=\"stat-value green\">-</div></div><div class=\"card stat\"><div class=\"stat-label\">当前离线</div><div id=\"offline\" class=\"stat-value red\">-</div></div><div class=\"card stat\"><div class=\"stat-label\">从未上线</div><div id=\"never\" class=\"stat-value\">-</div></div><div class=\"card stat\"><div class=\"stat-label\">进行中订单</div><div id=\"active-orders\" class=\"stat-value\">-</div></div></div>
    <div class=\"card toolbar\"><input id=\"search\" class=\"input\" placeholder=\"搜索设备、门店或实例\" oninput=\"renderTable()\"><select id=\"filter\" class=\"input\" onchange=\"renderTable()\"><option value=\"all\">全部状态</option><option value=\"online\">在线</option><option value=\"offline\">离线</option><option value=\"never\">从未上线</option></select><div class=\"toolbar-spacer\"></div><button class=\"button secondary\" onclick=\"loadDevices()\">刷新</button><button class=\"button\" onclick=\"toggleRegister()\">登记新设备</button></div>
    <div class=\"card table-card\"><div class=\"table-scroll\"><table class=\"devices\"><thead><tr><th>连接</th><th>设备</th><th>门店 / 实例</th><th>设备状态</th><th>最近心跳</th><th>历史记录</th></tr></thead><tbody id=\"device-rows\"></tbody></table></div></div>
    <h3 style=\"margin:25px 0 12px\">最近订单</h3><div class=\"card table-card\"><div class=\"table-scroll\"><table class=\"devices\"><thead><tr><th>订单</th><th>设备</th><th>饮品</th><th>状态</th><th>制作进度</th><th>创建时间</th></tr></thead><tbody id=\"order-rows\"></tbody></table></div></div>
    <div class=\"lower\"><section id=\"detail\" class=\"card detail\"><h3>选择一个设备</h3><p class=\"muted\">点击上方实例查看详细状态、版本和同步记录。</p></section><section id=\"register\" class=\"card register hidden\"><h3>登记新设备</h3><p class=\"muted\">登记后生成一次性激活码，交给对应的本地模拟器使用。</p><div class=\"form-grid\"><input id=\"new-device\" class=\"input\" placeholder=\"deviceId，例如 coffee-bot-003\"><input id=\"new-serial\" class=\"input\" placeholder=\"序列号，例如 003\"><input id=\"new-instance\" class=\"input\" placeholder=\"instanceId，可选\"><input id=\"new-store\" class=\"input\" placeholder=\"storeId，可选\"></div><div class=\"form-actions\"><button class=\"button\" onclick=\"registerDevice()\">登记并生成激活码</button><button class=\"button ghost\" onclick=\"toggleRegister()\">取消</button></div><div id=\"register-message\"></div></section></div>
  </section>
</main>
<script>
let adminToken='',devices=[],orders=[],selectedId='',refreshTimer=null;
const el=id=>document.getElementById(id);
const text=value=>value===null||value===undefined||value===''?'-':String(value);
const time=value=>value?new Date(value).toLocaleString('zh-CN',{hour12:false}):'-';
function setMessage(id,message,kind='error'){const node=el(id);node.textContent=message;node.className=kind}
async function api(path,options={}){const headers={'Accept':'application/json','Authorization':'Bearer '+adminToken,...(options.headers||{})};if(options.body){headers['Content-Type']='application/json'}const response=await fetch(path,{...options,headers});let data={};try{data=await response.json()}catch(_){ }if(!response.ok){throw new Error('HTTP '+response.status+(data.detail?': '+data.detail:''))}return data}
async function login(){const value=el('token').value.trim();if(!value){setMessage('login-error','请输入管理员 Token');return}adminToken=value;const loaded=await loadDevices();if(!loaded){adminToken='';return}el('login').classList.add('hidden');el('dashboard').classList.remove('hidden');el('session').classList.remove('hidden');el('token').value='';if(refreshTimer)clearInterval(refreshTimer);refreshTimer=setInterval(loadDevices,10000)}
function logout(){adminToken='';devices=[];selectedId='';if(refreshTimer)clearInterval(refreshTimer);el('dashboard').classList.add('hidden');el('session').classList.add('hidden');el('login').classList.remove('hidden');el('login-error').textContent='';el('token').focus()}
async function loadDevices(){try{const [data,orderData]=await Promise.all([api('/api/v1/admin/devices'),api('/api/v1/admin/orders?limit=50')]);devices=Array.isArray(data.devices)?data.devices:[];orders=Array.isArray(orderData.orders)?orderData.orders:[];el('server-time').textContent='服务时间：'+time(data.serverTime);el('last-refresh').textContent='每 10 秒自动刷新 · '+new Date().toLocaleTimeString('zh-CN',{hour12:false});el('total').textContent=devices.length;el('online').textContent=devices.filter(d=>d.online).length;el('offline').textContent=devices.filter(d=>!d.online&&d.hasEverConnected).length;el('never').textContent=devices.filter(d=>!d.hasEverConnected).length;el('active-orders').textContent=orders.filter(o=>['QUEUED','DISPATCHED','ACCEPTED','MAKING'].includes(o.status)).length;renderTable();renderOrders();if(selectedId){const selected=devices.find(d=>d.deviceId===selectedId);if(selected)renderDetail(selected)}return true}catch(error){if(adminToken)setMessage('login-error','加载失败：'+error.message);return false}}
function renderOrders(){const rows=el('order-rows');rows.replaceChildren();if(!orders.length){const row=document.createElement('tr');const cell=document.createElement('td');cell.colSpan=6;cell.className='empty';cell.textContent='还没有扫码订单';row.append(cell);rows.append(row);return}for(const order of orders){const row=document.createElement('tr');for(const value of [order.orderNo,order.deviceId,order.productName,order.status,Math.round((order.progress||0)*100)+'% '+text(order.currentStepName),time(order.createdAt)]){const cell=document.createElement('td');cell.textContent=text(value);row.append(cell)}rows.append(row)}}
function renderTable(){const query=el('search').value.trim().toLowerCase();const filter=el('filter').value;const rows=el('device-rows');rows.replaceChildren();const filtered=devices.filter(device=>{const hay=[device.deviceId,device.serialNumber,device.instanceId,device.storeId].join(' ').toLowerCase();const matches=!query||hay.includes(query);const status=filter==='online'?device.online:filter==='offline'?(!device.online&&device.hasEverConnected):filter==='never'?!device.hasEverConnected:true;return matches&&status});if(!filtered.length){const row=document.createElement('tr');const cell=document.createElement('td');cell.colSpan=6;cell.className='empty';cell.textContent=devices.length?'没有符合筛选条件的设备':'还没有登记设备';row.append(cell);rows.append(row);return}for(const device of filtered){const row=document.createElement('tr');if(device.deviceId===selectedId)row.className='selected';row.onclick=()=>selectDevice(device.deviceId);const status=document.createElement('td');const badge=document.createElement('span');badge.className='badge '+(device.online?'online':device.hasEverConnected?'offline':'pending');badge.textContent=device.online?'在线':device.hasEverConnected?'离线':'待激活';status.append(badge);const identity=document.createElement('td');identity.innerHTML='<div class=\"device-name\"></div><div class=\"device-sub\"></div>';identity.children[0].textContent=device.deviceId;identity.children[1].textContent='序列号 '+text(device.serialNumber);const location=document.createElement('td');location.innerHTML='<div></div><div class=\"device-sub\"></div>';location.children[0].textContent=text(device.storeId);location.children[1].textContent=text(device.instanceId);const state=document.createElement('td');const reported=device.reportedStatus||{};state.textContent=text(reported.deviceStatus||device.lifecycleStatus);const heartbeat=document.createElement('td');heartbeat.textContent=time(device.lastHeartbeatAt);const history=document.createElement('td');history.innerHTML='<div></div><div class=\"device-sub\"></div>';history.children[0].textContent=device.hasEverConnected?'最近上线 '+time(device.lastConnectedAt):'登记于 '+time(device.registeredAt);history.children[1].textContent='心跳 '+device.heartbeatCount+' · 事件 '+device.eventCount;row.append(status,identity,location,state,heartbeat,history);rows.append(row)}}
function selectDevice(deviceId){selectedId=deviceId;const device=devices.find(item=>item.deviceId===deviceId);if(device){renderTable();renderDetail(device)}}
async function renderDetail(device){const detail=el('detail');detail.replaceChildren();const title=document.createElement('h3');title.textContent=device.deviceId+' · '+text(device.storeId);detail.append(title);const grid=document.createElement('div');grid.className='detail-grid';const fields=[['连接',device.online?'在线':device.hasEverConnected?'离线':'待激活'],['生命周期',device.lifecycleStatus],['实例',device.instanceId],['序列号',device.serialNumber],['软件版本',device.softwareVersion],['最近心跳',time(device.lastHeartbeatAt)],['进行中订单',device.activeOrderCount],['消息统计','心跳 '+device.heartbeatCount+' · 事件 '+device.eventCount+' · 命令 '+device.commandCount]];for(const [label,value] of fields){const item=document.createElement('div');item.className='detail-item';const key=document.createElement('label');key.textContent=label;const val=document.createElement('strong');val.textContent=text(value);item.append(key,val);grid.append(item)}detail.append(grid);try{const inventory=await api('/api/v1/admin/devices/'+encodeURIComponent(device.deviceId)+'/inventory');if(selectedId!==device.deviceId)return;const heading=document.createElement('h3');heading.textContent='实时物料';heading.style.marginTop='22px';detail.append(heading);const pre=document.createElement('pre');pre.textContent=(inventory.materials||[]).map(m=>m.name+' · '+m.status+' · 可用 '+m.available+' / '+m.capacity+' '+m.unit).join('\\n')||'尚未收到物料快照';detail.append(pre)}catch(error){const note=document.createElement('p');note.className='error';note.textContent='物料读取失败：'+error.message;detail.append(note)}}
function toggleRegister(){el('register').classList.toggle('hidden');if(!el('register').classList.contains('hidden'))el('new-device').focus()}
async function registerDevice(){const deviceId=el('new-device').value.trim(),serialNumber=el('new-serial').value.trim();if(!deviceId||!serialNumber){setMessage('register-message','deviceId 和序列号必填');return}try{const registered=await api('/api/v1/admin/devices',{method:'POST',body:JSON.stringify({deviceId,serialNumber,instanceId:el('new-instance').value.trim()||null,storeId:el('new-store').value.trim()||null})});const activation=await api('/api/v1/admin/devices/'+encodeURIComponent(deviceId)+'/activation-codes',{method:'POST',body:'{}'});setMessage('register-message','设备已登记。激活码只显示这一次，请复制到安全的临时文件。','ok');const box=document.createElement('div');box.className='activation';const label=document.createElement('strong');label.textContent='一次性激活码（'+time(activation.expiresAt)+' 过期）';const code=document.createElement('code');code.textContent=activation.activationCode;const copy=document.createElement('button');copy.className='button secondary';copy.textContent='复制激活码';copy.onclick=()=>navigator.clipboard?.writeText(activation.activationCode);box.append(label,code,copy);el('register-message').append(box);await loadDevices();selectDevice(deviceId)}catch(error){setMessage('register-message','操作失败：'+error.message)}}
el('token').addEventListener('keydown',event=>{if(event.key==='Enter')login()});
</script>
</body></html>"""


@app.get("/admin", response_class=HTMLResponse)
def admin_page() -> str:
    return ADMIN_HTML
