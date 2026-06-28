from datetime import datetime, timezone

import pytest

from futures_bot.ports.audit import InMemoryAuditLog


NOW = datetime(2026, 6, 28, 15, 5, tzinfo=timezone.utc)


def _service_classes():
    try:
        from futures_bot.application.kill_switch import KillSwitchService, KillSwitchState
    except ModuleNotFoundError:
        pytest.fail("expected kill switch application module to exist")

    return KillSwitchService, KillSwitchState


class InMemoryKillSwitchStore:
    def __init__(self, state):
        self.state = state
        self.saved_states = []

    def load(self):
        return self.state

    def save(self, state):
        self.state = state
        self.saved_states.append(state)


def test_kill_switch_activate_persists_state_and_audits_event():
    KillSwitchService, KillSwitchState = _service_classes()
    store = InMemoryKillSwitchStore(KillSwitchState.inactive())
    audit_log = InMemoryAuditLog()
    service = KillSwitchService(store=store, audit_log=audit_log)

    state = service.activate(reason="operator halt before news release", timestamp=NOW)

    assert state == KillSwitchState(
        active=True,
        reason="operator halt before news release",
        updated_at=NOW,
    )
    assert store.saved_states == [state]
    assert audit_log.events == (
        {
            "type": "kill_switch_activated",
            "timestamp": "2026-06-28T15:05:00+00:00",
            "reason": "operator halt before news release",
        },
    )


def test_kill_switch_activate_requires_reason():
    KillSwitchService, KillSwitchState = _service_classes()
    service = KillSwitchService(
        store=InMemoryKillSwitchStore(KillSwitchState.inactive()),
        audit_log=InMemoryAuditLog(),
    )

    with pytest.raises(ValueError, match="kill switch reason is required"):
        service.activate(reason="  ", timestamp=NOW)


def test_kill_switch_clear_persists_inactive_state_and_audits_event():
    KillSwitchService, KillSwitchState = _service_classes()
    active_state = KillSwitchState(
        active=True,
        reason="operator halt before news release",
        updated_at=NOW,
    )
    store = InMemoryKillSwitchStore(active_state)
    audit_log = InMemoryAuditLog()
    service = KillSwitchService(store=store, audit_log=audit_log)

    cleared = service.clear(timestamp=NOW)

    assert cleared == KillSwitchState(active=False, reason=None, updated_at=NOW)
    assert store.saved_states == [cleared]
    assert audit_log.events == (
        {
            "type": "kill_switch_cleared",
            "timestamp": "2026-06-28T15:05:00+00:00",
            "previous_reason": "operator halt before news release",
        },
    )


def test_kill_switch_status_loads_persisted_state():
    KillSwitchService, KillSwitchState = _service_classes()
    active_state = KillSwitchState(active=True, reason="operator halt", updated_at=NOW)
    service = KillSwitchService(
        store=InMemoryKillSwitchStore(active_state),
        audit_log=InMemoryAuditLog(),
    )

    assert service.status() == active_state
