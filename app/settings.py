from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(alias="DATABASE_URL")
    db_pool_min_size: int = Field(default=2, alias="DB_POOL_MIN_SIZE", ge=1, le=64)
    db_pool_max_size: int = Field(default=10, alias="DB_POOL_MAX_SIZE", ge=1, le=128)
    db_pool_timeout_seconds: float = Field(default=10, alias="DB_POOL_TIMEOUT_SECONDS", ge=1, le=120)
    telemetry_history_mode: Literal["latest", "audit"] = Field(default="latest", alias="TELEMETRY_HISTORY_MODE")
    device_id: str = Field(default="coffee-bot-002", alias="DEVICE_ID")
    device_serial_number: str = Field(default="002", alias="DEVICE_SERIAL_NUMBER")
    device_instance_id: str = Field(default="instance-coffee-bot-002", alias="DEVICE_INSTANCE_ID")
    device_store_id: str = Field(default="store-demo-taipei-02", alias="DEVICE_STORE_ID")
    bootstrap_device_enabled: bool = Field(default=False, alias="BOOTSTRAP_DEVICE_ENABLED")
    device_token: str | None = Field(default=None, alias="DEVICE_TOKEN", min_length=24)
    admin_token: str = Field(alias="ADMIN_TOKEN", min_length=24)
    activation_ttl_seconds: int = Field(default=600, alias="ACTIVATION_TTL_SECONDS", ge=60, le=86400)
    activation_max_attempts: int = Field(default=5, alias="ACTIVATION_MAX_ATTEMPTS", ge=1, le=20)
    credential_grace_seconds: int = Field(default=300, alias="CREDENTIAL_GRACE_SECONDS", ge=0, le=86400)
    offline_threshold_seconds: int = Field(default=30, alias="OFFLINE_THRESHOLD_SECONDS", ge=5, le=3600)
    offline_scan_seconds: int = Field(default=2, alias="OFFLINE_SCAN_SECONDS", ge=1, le=60)
    public_base_url: str = Field(default="https://coffee-api.woodbridge.top", alias="PUBLIC_BASE_URL")
    public_order_queue_limit: int = Field(default=20, alias="PUBLIC_ORDER_QUEUE_LIMIT", ge=1, le=500)
    default_product_price_minor: int = Field(default=100, alias="DEFAULT_PRODUCT_PRICE_MINOR", ge=1)
    payment_default_provider: str = Field(default="mock", alias="PAYMENT_DEFAULT_PROVIDER")
    public_payment_mode: str = Field(default="TEST_FREE", alias="PUBLIC_PAYMENT_MODE")
    allow_mock_payment: bool = Field(default=False, alias="ALLOW_MOCK_PAYMENT")
    payment_currency: str = Field(default="CNY", alias="PAYMENT_CURRENCY", min_length=3, max_length=3)
    payment_reconcile_seconds: int = Field(default=30, alias="PAYMENT_RECONCILE_SECONDS", ge=5, le=3600)
    alipay_gateway: str = Field(default="https://openapi-sandbox.dl.alipaydev.com/gateway.do", alias="ALIPAY_GATEWAY")
    alipay_app_id: str | None = Field(default=None, alias="ALIPAY_APP_ID")
    alipay_app_private_key_file: str | None = Field(default=None, alias="ALIPAY_APP_PRIVATE_KEY_FILE")
    alipay_public_key_file: str | None = Field(default=None, alias="ALIPAY_PUBLIC_KEY_FILE")
    alipay_timeout_seconds: float = Field(default=15, alias="ALIPAY_TIMEOUT_SECONDS", ge=3, le=60)
    internal_gateway_token: str = Field(default="development-gateway-token-change-before-deploy", alias="INTERNAL_GATEWAY_TOKEN", min_length=24)
    outbox_scan_seconds: float = Field(default=0.5, alias="OUTBOX_SCAN_SECONDS", ge=0.1, le=60)
    command_publish_lease_seconds: int = Field(default=30, alias="COMMAND_PUBLISH_LEASE_SECONDS", ge=5, le=300)
    command_ack_timeout_seconds: int = Field(default=30, alias="COMMAND_ACK_TIMEOUT_SECONDS", ge=5, le=3600)
    command_start_timeout_seconds: int = Field(default=60, alias="COMMAND_START_TIMEOUT_SECONDS", ge=5, le=3600)
    production_timeout_grace_seconds: int = Field(default=120, alias="PRODUCTION_TIMEOUT_GRACE_SECONDS", ge=0, le=86400)
    emqx_management_url: str | None = Field(default=None, alias="EMQX_MANAGEMENT_URL")
    emqx_dashboard_username: str | None = Field(default=None, alias="EMQX_DASHBOARD_USERNAME")
    emqx_dashboard_password: str | None = Field(default=None, alias="EMQX_DASHBOARD_PASSWORD")
    order_access_secret: str | None = Field(default=None, alias="ORDER_ACCESS_SECRET", min_length=32)
    service_host: str = Field(default="127.0.0.1", alias="SERVICE_HOST")
    service_port: int = Field(default=8788, alias="SERVICE_PORT", ge=1, le=65535)
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
