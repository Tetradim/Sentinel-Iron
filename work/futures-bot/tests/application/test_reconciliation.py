from decimal import Decimal

import pytest

from futures_bot.application.reconciliation import ReconcilePositionsUseCase
from futures_bot.domain.portfolio import Position
from futures_bot.ports.audit import InMemoryAuditLog


def _position(instrument_id: str, quantity: int) -> Position:
    return Position(
        instrument_id=instrument_id,
        quantity=quantity,
        average_price=Decimal("5000.00"),
    )


def test_matching_broker_and_internal_positions_approve_trading():
    audit_log = InMemoryAuditLog()
    use_case = ReconcilePositionsUseCase(audit_log=audit_log)

    result = use_case.execute(
        internal_positions={"ES-202609-CME": _position("ES-202609-CME", 2)},
        broker_positions=[_position("ES-202609-CME", 2)],
    )

    assert result.positions_reconciled is True
    assert result.mismatches == ()
    assert audit_log.events[-1]["positions_reconciled"] is True


def test_missing_internal_position_for_broker_position_rejects_trading():
    audit_log = InMemoryAuditLog()
    use_case = ReconcilePositionsUseCase(audit_log=audit_log)

    result = use_case.execute(
        internal_positions={},
        broker_positions=[_position("ES-202609-CME", 1)],
    )

    assert result.positions_reconciled is False
    assert result.mismatches == ("missing internal position for ES-202609-CME",)


def test_quantity_mismatch_rejects_trading():
    audit_log = InMemoryAuditLog()
    use_case = ReconcilePositionsUseCase(audit_log=audit_log)

    result = use_case.execute(
        internal_positions={"ES-202609-CME": _position("ES-202609-CME", 2)},
        broker_positions=[_position("ES-202609-CME", -1)],
    )

    assert result.positions_reconciled is False
    assert result.mismatches == ("quantity mismatch for ES-202609-CME: internal=2 broker=-1",)


def test_in_memory_audit_log_records_immutable_event_dictionaries():
    audit_log = InMemoryAuditLog()
    event = {"type": "risk_decision", "approved": False}

    audit_log.append(event)
    event["approved"] = True

    recorded = audit_log.events[0]
    assert recorded["approved"] is False
    with pytest.raises(TypeError):
        recorded["approved"] = True
