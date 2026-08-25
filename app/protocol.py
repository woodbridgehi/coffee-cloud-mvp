from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

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


class ActivationRequest(BaseModel):
    deviceId: str = Field(min_length=1, max_length=128)
    activationCode: str = Field(min_length=12, max_length=256)
    deviceToken: str = Field(min_length=32, max_length=512)


class ActivationCodeRequest(BaseModel):
    ttlSeconds: int | None = Field(default=None, ge=60, le=86400)


class AdminDeviceCreateRequest(BaseModel):
    deviceId: str = Field(min_length=1, max_length=128)
    serialNumber: str = Field(min_length=1, max_length=128)
    instanceId: str | None = Field(default=None, max_length=160)
    storeId: str | None = Field(default=None, max_length=160)


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
    accepted: bool
    reason: str | None = Field(default=None, max_length=500)


class CommandResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str = Field(min_length=1, max_length=64)
    detail: dict[str, Any] = Field(default_factory=dict)


class PublicOrderCreateRequest(BaseModel):
    recipeId: str = Field(min_length=1, max_length=160)
    recipeVersion: str = Field(min_length=1, max_length=64)
    quantity: Literal[1] = 1
    paymentMode: Literal["TEST_FREE"] = "TEST_FREE"
