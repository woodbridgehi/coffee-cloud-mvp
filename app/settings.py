from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(alias="DATABASE_URL")
    device_id: str = Field(default="coffee-bot-002", alias="DEVICE_ID")
    device_serial_number: str = Field(default="002", alias="DEVICE_SERIAL_NUMBER")
    device_instance_id: str = Field(default="instance-coffee-bot-002", alias="DEVICE_INSTANCE_ID")
    device_store_id: str = Field(default="store-demo-taipei-02", alias="DEVICE_STORE_ID")
    device_token: str = Field(alias="DEVICE_TOKEN", min_length=24)
    admin_token: str = Field(alias="ADMIN_TOKEN", min_length=24)
    activation_ttl_seconds: int = Field(default=600, alias="ACTIVATION_TTL_SECONDS", ge=60, le=86400)
    activation_max_attempts: int = Field(default=5, alias="ACTIVATION_MAX_ATTEMPTS", ge=1, le=20)
    credential_grace_seconds: int = Field(default=300, alias="CREDENTIAL_GRACE_SECONDS", ge=0, le=86400)
    offline_threshold_seconds: int = Field(default=30, alias="OFFLINE_THRESHOLD_SECONDS", ge=5, le=3600)
    offline_scan_seconds: int = Field(default=2, alias="OFFLINE_SCAN_SECONDS", ge=1, le=60)
    public_base_url: str = Field(default="https://coffee-api.woodbridge.top", alias="PUBLIC_BASE_URL")
    public_order_queue_limit: int = Field(default=20, alias="PUBLIC_ORDER_QUEUE_LIMIT", ge=1, le=500)
    order_access_secret: str | None = Field(default=None, alias="ORDER_ACCESS_SECRET", min_length=32)
    service_host: str = Field(default="127.0.0.1", alias="SERVICE_HOST")
    service_port: int = Field(default=8788, alias="SERVICE_PORT", ge=1, le=65535)
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
