from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.protocol import AdminDeviceCreateRequest, DeviceOnboardingProfile, Heartbeat, canonical_digest
from app.security import bearer_token, hash_token, tokens_equal


def test_canonical_digest_is_stable() -> None:
    assert canonical_digest({"b": 2, "a": 1}) == canonical_digest({"a": 1, "b": 2})


def test_heartbeat_accepts_planned_message_fields() -> None:
    heartbeat = Heartbeat(
        deviceId="coffee-bot-002",
        messageId="hb-1",
        bootId="boot-1",
        sequence=1,
        deviceStatus="IDLE",
        sentAt=datetime.now(timezone.utc),
    )
    assert heartbeat.sequence == 1


def test_token_helpers() -> None:
    assert bearer_token("Bearer secret") == "secret"
    assert bearer_token("Basic secret") is None
    assert tokens_equal(hash_token("secret"), hash_token("secret"))
    assert not tokens_equal(hash_token("secret"), hash_token("other"))


def test_new_device_identity_and_onboarding_profile_are_constrained() -> None:
    device = AdminDeviceCreateRequest(deviceId="coffee-bot-003", serialNumber="CB-2026-003")
    assert device.deviceId == "coffee-bot-003"
    profile = DeviceOnboardingProfile(
        deviceName="浦东体验店 03 号机", storeId="store-cn-sh-001", storeName="浦东体验店",
        storeDescription="咖啡机器人体验门店", cityCode="CN-SH", timezone="Asia/Shanghai",
    )
    assert profile.cityCode == "CN-SH"
    with pytest.raises(ValidationError):
        AdminDeviceCreateRequest(deviceId="coffee-bot-x", serialNumber="003")
    with pytest.raises(ValidationError):
        DeviceOnboardingProfile(
            deviceName="测试", storeId="store-cn-sh-001", storeName="测试", cityCode="CN-SH",
            timezone="Asia/Taipei",
        )

