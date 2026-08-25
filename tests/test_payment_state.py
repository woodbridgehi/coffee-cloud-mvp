from app.payment_state import (
    decide_payment_transition, decide_refund_transition,
)


def test_payment_state_never_moves_backwards() -> None:
    assert decide_payment_transition("CREATED", "PENDING").allowed
    assert decide_payment_transition("PENDING", "PAID").allowed
    assert decide_payment_transition("PAID", "PENDING").allowed is False
    assert decide_payment_transition("REFUNDED", "PAID").allowed is False
    assert decide_payment_transition("PAID", "PAID").duplicate


def test_refund_unknown_can_be_reconciled_without_creating_a_second_refund() -> None:
    assert decide_refund_transition("PROCESSING", "UNKNOWN").allowed
    assert decide_refund_transition("UNKNOWN", "PROCESSING").allowed
    assert decide_refund_transition("SUCCEEDED", "PROCESSING").allowed is False
