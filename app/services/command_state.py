from __future__ import annotations

from typing import Any

from ..command_state import TERMINAL_STATES, decide_transition
from ..repositories import CommandRepository
from ..protocol import utc_now
from .errors import ServiceError


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
            raise ServiceError(409, decision.reason)
        return command, False
    updated = CommandRepository(connection).transition(
        command, target, actor, reason=reason, payload=payload, now_at=utc_now()
    )
    return updated, False
