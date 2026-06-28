from datetime import datetime, timezone
import json

import pytest


NOW = datetime(2026, 6, 28, 15, 5, tzinfo=timezone.utc)


def _store_class():
    try:
        from futures_bot.storage.kill_switch import JsonKillSwitchStore
    except ModuleNotFoundError:
        pytest.fail("expected JsonKillSwitchStore to exist")

    return JsonKillSwitchStore


def _state_class():
    try:
        from futures_bot.application.kill_switch import KillSwitchState
    except ModuleNotFoundError:
        pytest.fail("expected KillSwitchState to exist")

    return KillSwitchState


def test_json_kill_switch_store_returns_inactive_state_when_file_is_missing(tmp_path):
    store = _store_class()(tmp_path / "state" / "kill_switch.json")

    assert store.load() == _state_class().inactive()


def test_json_kill_switch_store_persists_and_reloads_active_state(tmp_path):
    KillSwitchState = _state_class()
    path = tmp_path / "state" / "kill_switch.json"
    store = _store_class()(path)
    state = KillSwitchState(active=True, reason="operator halt", updated_at=NOW)

    store.save(state)

    assert store.load() == state
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "active": True,
        "reason": "operator halt",
        "updated_at": "2026-06-28T15:05:00+00:00",
    }


def test_json_kill_switch_store_persists_cleared_state(tmp_path):
    KillSwitchState = _state_class()
    path = tmp_path / "nested" / "kill_switch.json"
    store = _store_class()(path)
    state = KillSwitchState(active=False, reason=None, updated_at=NOW)

    store.save(state)

    assert path.exists()
    assert store.load() == state


def test_json_kill_switch_store_rejects_malformed_state(tmp_path):
    path = tmp_path / "kill_switch.json"
    path.write_text('{"active":true}', encoding="utf-8")
    store = _store_class()(path)

    with pytest.raises(ValueError, match="invalid kill switch state"):
        store.load()
