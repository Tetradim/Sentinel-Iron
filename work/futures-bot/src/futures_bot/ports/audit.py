from __future__ import annotations

from types import MappingProxyType
from typing import Mapping, Protocol


class AuditLogPort(Protocol):
    def append(self, event: Mapping[str, object]) -> None:
        """Append one immutable audit event."""


class InMemoryAuditLog:
    def __init__(self) -> None:
        self._events: list[Mapping[str, object]] = []

    def append(self, event: Mapping[str, object]) -> None:
        self._events.append(MappingProxyType(dict(event)))

    @property
    def events(self) -> tuple[Mapping[str, object], ...]:
        return tuple(self._events)
