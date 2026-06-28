import json

import pytest


def _store_class():
    try:
        from futures_bot.storage.processed_fills import JsonlProcessedFillStore
    except ModuleNotFoundError:
        pytest.fail("expected JsonlProcessedFillStore to exist")

    return JsonlProcessedFillStore


def test_jsonl_processed_fill_store_reports_missing_fill_as_unprocessed(tmp_path):
    store = _store_class()(tmp_path / "fills.jsonl")

    assert store.contains("exec-1") is False


def test_jsonl_processed_fill_store_appends_and_finds_fill_id(tmp_path):
    path = tmp_path / "state" / "processed_fills.jsonl"
    store = _store_class()(path)

    store.append("exec-1")

    assert store.contains("exec-1") is True
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "broker_execution_id": "exec-1",
    }


def test_jsonl_processed_fill_store_rejects_duplicate_fill_id(tmp_path):
    store = _store_class()(tmp_path / "processed_fills.jsonl")
    store.append("exec-1")

    with pytest.raises(ValueError, match="processed fill was already recorded"):
        store.append("exec-1")


def test_jsonl_processed_fill_store_rejects_malformed_records(tmp_path):
    path = tmp_path / "processed_fills.jsonl"
    path.write_text('{"wrong":"exec-1"}\n', encoding="utf-8")
    store = _store_class()(path)

    with pytest.raises(ValueError, match="invalid processed fill record"):
        store.contains("exec-1")
