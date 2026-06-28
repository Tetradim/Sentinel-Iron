from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Mapping

from futures_bot.domain.portfolio import Position


class JsonPositionStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def load(self) -> Mapping[str, Position]:
        if not self.path.exists():
            raise ValueError("internal position state file does not exist")

        try:
            raw_value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("invalid internal position state") from exc

        if not isinstance(raw_value, list):
            raise ValueError("invalid internal position state")

        positions: dict[str, Position] = {}
        for record_value in raw_value:
            position = self._decode_position(record_value)
            if position.instrument_id in positions:
                raise ValueError(f"duplicate internal position: {position.instrument_id}")
            positions[position.instrument_id] = position
        return positions

    def save(self, positions: Mapping[str, Position]) -> None:
        payload = [
            {
                "instrument_id": position.instrument_id,
                "quantity": position.quantity,
                "average_price": str(position.average_price),
            }
            for position in sorted(positions.values(), key=lambda item: item.instrument_id)
        ]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )

    def _decode_position(self, value: object) -> Position:
        if not isinstance(value, dict):
            raise ValueError("invalid internal position record")

        try:
            instrument_id = value["instrument_id"]
            quantity = value["quantity"]
            average_price = value["average_price"]
            if not isinstance(instrument_id, str):
                raise TypeError
            if not isinstance(quantity, int):
                raise TypeError
            position = Position(
                instrument_id=instrument_id,
                quantity=quantity,
                average_price=Decimal(str(average_price)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid internal position record") from exc

        return position
