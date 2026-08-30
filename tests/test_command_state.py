import pytest

from app.command_state import (
    ACKED, CREATED, DELIVERING, EXECUTING, FAILED, SUCCEEDED,
    decide_transition, event_state, result_state,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (CREATED, DELIVERING),
        (CREATED, SUCCEEDED),  # authenticated completion can precede PUBACK receipt
        (DELIVERING, ACKED),
        (DELIVERING, EXECUTING),
        (DELIVERING, SUCCEEDED),
        (ACKED, EXECUTING),
        (EXECUTING, SUCCEEDED),
    ],
)
def test_legal_command_transitions(current: str, target: str) -> None:
    assert decide_transition(current, target).allowed


def test_duplicate_transition_is_idempotent() -> None:
    decision = decide_transition(ACKED, ACKED)
    assert decision.allowed
    assert decision.duplicate


@pytest.mark.parametrize(
    ("current", "target"),
    [(ACKED, DELIVERING), (SUCCEEDED, EXECUTING), (FAILED, SUCCEEDED)],
)
def test_illegal_or_terminal_regression_is_rejected(current: str, target: str) -> None:
    assert not decide_transition(current, target).allowed


def test_protocol_values_map_to_canonical_states() -> None:
    assert result_state("completed") == SUCCEEDED
    assert result_state("unexpected") == FAILED
    assert event_state("task.started") == EXECUTING
    assert event_state("telemetry.updated") is None
