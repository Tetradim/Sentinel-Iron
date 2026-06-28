from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Mapping

from futures_bot.application.kill_switch import KillSwitchState


class JsonKillSwitchStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def load(self) -> KillSwitchState:
        if not self.path.exists():
            return KillSwitchState.inactive()

        try:
            raw_value = json.loads(self.path.read_text(encoding="utf-8"))
            return self._decode_state(raw_value)
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            raise ValueError("invalid kill switch state") from exc

    def save(self, state: KillSwitchState) -> None:
        payload = self._encode_state(state)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )

    def _encode_state(self, state: KillSwitchState) -> Mapping[str, object]:
        if state.active and state.reason is None:
            raise ValueError("invalid kill switch state")
        if state.updated_at is not None and state.updated_at.tzinfo is None:
            raise ValueError("invalid kill switch state")

        return {
            "active": state.active,
            "reason": state.reason,
            "updated_at": state.updated_at.isoformat() if state.updated_at is not None else None,
        }

    def _decode_state(self, value: object) -> KillSwitchState:
        if not isinstance(value, dict):
            raise ValueError("invalid kill switch state")

        try:
            active = value["active"]
            reason = value["reason"]
            updated_at_value = value["updated_at"]
            if not isinstance(active, bool):
                raise TypeError
            if reason is not None and not isinstance(reason, str):
                raise TypeError
            if updated_at_value is not None and not isinstance(updated_at_value, str):
                raise TypeError

            updated_at = (
                datetime.fromisoformat(updated_at_value)
                if isinstance(updated_at_value, str)
                else None
            )
            state = KillSwitchState(
                active=active,
                reason=reason,
                updated_at=updated_at,
            )
            self._encode_state(state)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid kill switch state") from exc

        return state
