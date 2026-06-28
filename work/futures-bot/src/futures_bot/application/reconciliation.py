from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from futures_bot.domain.portfolio import Position
from futures_bot.ports.audit import AuditLogPort


@dataclass(frozen=True)
class ReconciliationResult:
    positions_reconciled: bool
    mismatches: tuple[str, ...]


class ReconcilePositionsUseCase:
    def __init__(self, audit_log: AuditLogPort) -> None:
        self._audit_log = audit_log

    def execute(
        self,
        internal_positions: Mapping[str, Position],
        broker_positions: Iterable[Position],
    ) -> ReconciliationResult:
        mismatches: list[str] = []
        broker_position_by_instrument: dict[str, Position] = {}

        for broker_position in broker_positions:
            broker_position_by_instrument[broker_position.instrument_id] = broker_position
            internal_position = internal_positions.get(broker_position.instrument_id)
            if internal_position is None:
                mismatches.append(f"missing internal position for {broker_position.instrument_id}")
                continue
            if internal_position.quantity != broker_position.quantity:
                mismatches.append(
                    "quantity mismatch for "
                    f"{broker_position.instrument_id}: "
                    f"internal={internal_position.quantity} "
                    f"broker={broker_position.quantity}"
                )

        for internal_position in internal_positions.values():
            if (
                internal_position.quantity != 0
                and internal_position.instrument_id not in broker_position_by_instrument
            ):
                mismatches.append(f"missing broker position for {internal_position.instrument_id}")

        result = ReconciliationResult(
            positions_reconciled=not mismatches,
            mismatches=tuple(mismatches),
        )
        self._audit_log.append(
            {
                "type": "position_reconciliation",
                "positions_reconciled": result.positions_reconciled,
                "mismatches": result.mismatches,
            }
        )
        return result
