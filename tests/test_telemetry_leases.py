import logging
import os
import uuid

import pytest
from redis.exceptions import ConnectionError
from app.telemetry import TelemetryCache


@pytest.fixture
def cache():
    url = os.getenv("TEST_REDIS_URL")
    if not url:
        pytest.skip("TEST_REDIS_URL is not configured")
    cache = TelemetryCache(url, online_ttl_seconds=120, logger=logging.getLogger("test"))
    prefix = "audit-leases:" + uuid.uuid4().hex
    cache._dirty_key = lambda: prefix + ":dirty"
    cache._lease_keys = lambda: (prefix + ":dirty", prefix + ":processing", prefix + ":tokens")
    cache._state_key = lambda device: prefix + ":state:" + device
    cache.start()
    try:
        yield cache
    finally:
        keys = list(cache.client.scan_iter(prefix + "*"))
        if keys:
            cache.client.delete(*keys)
        cache.close()


def seed(cache, status="online"):
    assert cache._write("device", {"terminalId": "1", "connectionStatus": status})


def test_crash_after_claim_is_reclaimed_and_old_ack_cannot_release_new_lease(cache):
    seed(cache)
    first = cache.claim_dirty(10)
    assert len(first) == 1 and cache.claim_dirty(10) == []
    cache.client.zadd(cache._lease_keys()[1], {"device": 0})
    second = cache.claim_dirty(10)
    assert second[0][1]["_leaseToken"] != first[0][1]["_leaseToken"]
    cache.settle_dirty(first)
    assert cache.client.zcard(cache._lease_keys()[1]) == 1
    cache.settle_dirty(second)
    assert cache.client.zcard(cache._lease_keys()[1]) == 0


def test_update_during_flush_survives_ack_and_sql_failure_can_retry(cache):
    seed(cache)
    first = cache.claim_dirty(1)
    seed(cache, "offline")
    assert cache.claim_dirty(1) == []
    cache.settle_dirty(first)
    second = cache.claim_dirty(1)
    assert second[0][1]["connectionStatus"] == "offline"
    cache.settle_dirty(second, retry=True)
    assert len(cache.claim_dirty(1)) == 1


def test_read_failure_after_atomic_claim_keeps_recoverable_lease(cache, monkeypatch):
    seed(cache)
    with monkeypatch.context() as patch:
        def fail(*args, **kwargs):
            raise ConnectionError("injected after claim")
        patch.setattr(cache.client, "pipeline", fail)
        assert cache.claim_dirty(1) == []
    assert cache.client.zcard(cache._lease_keys()[1]) == 1
    cache.client.zadd(cache._lease_keys()[1], {"device": 0})
    assert len(cache.claim_dirty(1)) == 1
