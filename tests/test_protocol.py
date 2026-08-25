from datetime import datetime, timezone

from app.protocol import Heartbeat, canonical_digest
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

