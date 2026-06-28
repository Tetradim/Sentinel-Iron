from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from futures_bot.ports.audit import AuditLogPort


@dataclass(frozen=True)
class KillSwitchState:
    active: bool
    reason: str | None
    updated_at: datetime | None

    @classmethod
    def inactive(cls) -> KillSwitchState:
        return cls(active=False, reason=None, updated_at=None)

    def __post_init__(self) -> None:
        if self.active and not self.reason:
            raise ValueError("active kill switch state requires reason")
        if self.reason is not None and not self.reason.strip():
            raise ValueError("kill switch reason cannot be blank")
        if self.updated_at is not None and self.updated_at.tzinfo is None:
            raise ValueError("updated_at must be timezone-aware")


class KillSwitchStorePort(Protocol):
    def load(self) -> KillSwitchState:
        """Load the persisted operator kill-switch state."""

    def save(self, state: KillSwitchState) -> None:
        """Persist the operator kill-switch state."""


class KillSwitchService:
    def __init__(self, store: KillSwitchStorePort, audit_log: AuditLogPort) -> None:
        self._store = store
        self._audit_log = audit_log

    def status(self) -> KillSwitchState:
        return self._store.load()

    def activate(self, reason: str, timestamp: datetime) -> KillSwitchState:
        reason_text = reason.strip()
        if not reason_text:
            raise ValueError("kill switch reason is required")

        state = KillSwitchState(active=True, reason=reason_text, updated_at=timestamp)
        self._store.save(state)
        self._audit_log.append(
            {
                "type": "kill_switch_activated",
                "timestamp": timestamp.isoformat(),
                "reason": reason_text,
            }
        )
        return state

    def clear(self, timestamp: datetime) -> KillSwitchState:
        previous_state = self._store.load()
        state = KillSwitchState(active=False, reason=None, updated_at=timestamp)
        self._store.save(state)
        self._audit_log.append(
            {
                "type": "kill_switch_cleared",
                "timestamp": timestamp.isoformat(),
                "previous_reason": previous_state.reason,
            }
        )
        return state
