from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_digest(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class Heartbeat(BaseModel):
    model_config = ConfigDict(extra="allow")

    deviceId: str = Field(min_length=1, max_length=128)
    messageId: str | None = Field(default=None, min_length=1, max_length=160)
    bootId: str | None = Field(default=None, min_length=1, max_length=160)
    sequence: int | None = Field(default=None, ge=0)
    instanceId: str | None = Field(default=None, max_length=160)
    storeId: str | None = Field(default=None, max_length=160)
    deviceStatus: str = Field(default="UNKNOWN", max_length=64)
    appVersion: str | None = Field(default=None, max_length=64)
    sentAt: datetime | None = None

    @field_validator("sentAt")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("sentAt must include a timezone")
        return value


class Snapshot(BaseModel):
    model_config = ConfigDict(extra="allow")

    deviceId: str


class DeviceEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    eventId: str = Field(min_length=1, max_length=160)
    deviceId: str
    bootId: str | None = None
    sequence: int | None = Field(default=None, ge=0)
    occurredAt: datetime | None = None
    type: str = Field(min_length=1, max_length=160)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("payload")
    @classmethod
    def require_json_finite(cls, value: dict[str, Any]) -> dict[str, Any]:
        # JSONB rejects NaN/Infinity. Reject before opening an ingestion
        # transaction, including values nested in arbitrary event details.
        json.dumps(value, allow_nan=False)
        return value


DEVICE_ID_PATTERN = r"^coffee-bot-[0-9]{3,6}$"
SERIAL_NUMBER_PATTERN = r"^CB-[0-9]{4}-[0-9]{3,6}$"
STORE_ID_PATTERN = r"^store-[a-z0-9]+(?:-[a-z0-9]+)*-[0-9]{3,6}$"
CITY_OPTIONS: dict[str, dict[str, str]] = {
    "CN-BJ": {"name": "北京", "timezone": "Asia/Shanghai"},
    "CN-SH": {"name": "上海", "timezone": "Asia/Shanghai"},
    "CN-SZ": {"name": "深圳", "timezone": "Asia/Shanghai"},
    "CN-GZ": {"name": "广州", "timezone": "Asia/Shanghai"},
    "TW-TPE": {"name": "台北", "timezone": "Asia/Taipei"},
}


class DeviceOnboardingProfile(BaseModel):
    deviceName: str = Field(min_length=1, max_length=120)
    storeId: str = Field(min_length=1, max_length=160, pattern=STORE_ID_PATTERN)
    storeName: str = Field(min_length=1, max_length=120)
    storeDescription: str = Field(default="", max_length=300)
    cityCode: str = Field(min_length=1, max_length=32)
    timezone: str = Field(min_length=1, max_length=64)

    @field_validator("deviceName", "storeName", "storeDescription")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if value and not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("cityCode")
    @classmethod
    def validate_city(cls, value: str) -> str:
        if value not in CITY_OPTIONS:
            raise ValueError("unsupported cityCode")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str, info: Any) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("invalid IANA timezone") from exc
        city_code = info.data.get("cityCode")
        if city_code in CITY_OPTIONS and value != CITY_OPTIONS[city_code]["timezone"]:
            raise ValueError("timezone does not match cityCode")
        return value


class ActivationRequest(BaseModel):
    # Existing pre-format devices remain activatable; new devices are constrained at registration.
    deviceId: str = Field(min_length=1, max_length=128)
    # New first-boot onboarding supplies this and is checked against pre-registration.
    serialNumber: str | None = Field(default=None, max_length=128, pattern=SERIAL_NUMBER_PATTERN)
    activationCode: str = Field(min_length=12, max_length=256)
    deviceToken: str = Field(min_length=32, max_length=512)
    profile: DeviceOnboardingProfile | None = None


class ActivationCodeRequest(BaseModel):
    ttlSeconds: int | None = Field(default=None, ge=60, le=86400)


class AdminDeviceCreateRequest(BaseModel):
    deviceId: str = Field(min_length=1, max_length=128, pattern=DEVICE_ID_PATTERN)
    serialNumber: str = Field(min_length=1, max_length=128, pattern=SERIAL_NUMBER_PATTERN)
    instanceId: str | None = Field(default=None, max_length=160)
    storeId: str | None = Field(default=None, max_length=160, pattern=STORE_ID_PATTERN)


class CredentialRotationRequest(BaseModel):
    newToken: str = Field(min_length=32, max_length=512)


class CommandCreateRequest(BaseModel):
    type: Literal[
        "MAKE_DRINK", "DEBUG_COMMAND", "RELOAD_CONFIG", "INVENTORY_ADJUSTMENT",
        "CANCEL_TASK", "SYNC_CONFIG", "RESTART_APP",
    ]
    taskId: str | None = Field(default=None, min_length=1, max_length=160)
    orderId: str | None = Field(default=None, min_length=1, max_length=160)
    recipeId: str | None = Field(default=None, min_length=1, max_length=160)
    recipeVersion: str | None = Field(default=None, max_length=64)
    action: str | None = Field(default=None, max_length=160)
    expiresAt: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("expiresAt")
    @classmethod
    def require_expiry_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("expiresAt must include a timezone")
        return value


class TaskAck(BaseModel):
    model_config = ConfigDict(extra="allow")

    messageId: str = Field(min_length=1, max_length=160)
    accepted: bool = Field(strict=True)
    reason: str | None = Field(default=None, max_length=500)


class CommandResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str = Field(min_length=1, max_length=64)
    detail: dict[str, Any] = Field(default_factory=dict)


class PublicOrderCreateRequest(BaseModel):
    recipeId: str = Field(min_length=1, max_length=160)
    recipeVersion: str = Field(min_length=1, max_length=64)
    quantity: Literal[1] = 1
    paymentMode: Literal["ONLINE", "TEST_FREE"] = "ONLINE"


class OrderAdjudicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    taskId: str = Field(min_length=1, max_length=160)
    expectedRevision: int = Field(ge=0, strict=True)
    outcome: Literal["SUCCEEDED", "FAILED", "CANCELLED"]
    reason: str = Field(min_length=1, max_length=1000)


class PaymentCreateRequest(BaseModel):
    provider: Literal["alipay", "mock"] | None = None


class RefundCreateRequest(BaseModel):
    amountMinor: int | None = Field(default=None, ge=1)
    reason: str = Field(default="production failed", min_length=1, max_length=256)


class AdminOperatorCreateRequest(BaseModel):
    displayName: str = Field(min_length=1, max_length=120)
    role: Literal["VIEWER", "OPERATOR", "MANAGER", "OWNER"]


class AdminOperatorUpdateRequest(BaseModel):
    displayName: str | None = Field(default=None, min_length=1, max_length=120)
    role: Literal["VIEWER", "OPERATOR", "MANAGER", "OWNER"] | None = None
    status: Literal["ACTIVE", "SUSPENDED"] | None = None


class AdminTokenCreateRequest(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    expiresAt: datetime | None = None

    @field_validator("expiresAt")
    @classmethod
    def require_token_expiry_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("expiresAt must include a timezone")
        return value


class DeviceLifecycleUpdateRequest(BaseModel):
    status: Literal["ACTIVE", "SUSPENDED", "MAINTENANCE"]
    reason: str = Field(min_length=3, max_length=500)
