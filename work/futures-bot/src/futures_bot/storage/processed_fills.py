from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping


class JsonlProcessedFillStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def contains(self, broker_execution_id: str) -> bool:
        self._validate_fill_id(broker_execution_id)
        return broker_execution_id in self._load_fill_ids()

    def append(self, broker_execution_id: str) -> None:
        self._validate_fill_id(broker_execution_id)
        if broker_execution_id in self._load_fill_ids():
            raise ValueError("processed fill was already recorded")

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as state_file:
            state_file.write(
                json.dumps(
                    {"broker_execution_id": broker_execution_id},
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            state_file.write("\n")

    def _load_fill_ids(self) -> frozenset[str]:
        if not self.path.exists():
            return frozenset()

        fill_ids: set[str] = set()
        with self.path.open(encoding="utf-8") as state_file:
            for line in state_file:
                if not line.strip():
                    continue
                fill_id = self._decode_record(json.loads(line))
                fill_ids.add(fill_id)
        return frozenset(fill_ids)

    def _decode_record(self, value: object) -> str:
        if not isinstance(value, Mapping):
            raise ValueError("invalid processed fill record")

        broker_execution_id = value.get("broker_execution_id")
        if not isinstance(broker_execution_id, str) or not broker_execution_id:
            raise ValueError("invalid processed fill record")
        return broker_execution_id

    def _validate_fill_id(self, broker_execution_id: str) -> None:
        if not broker_execution_id:
            raise ValueError("broker_execution_id is required")
