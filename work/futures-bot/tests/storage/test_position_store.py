from decimal import Decimal
import json

import pytest

from futures_bot.domain.portfolio import Position


def _store_class():
    try:
        from futures_bot.storage.positions import JsonPositionStore
    except ModuleNotFoundError:
        pytest.fail("expected JsonPositionStore to exist")

    return JsonPositionStore


def test_json_position_store_loads_position_mapping(tmp_path):
    path = tmp_path / "state" / "positions.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            [
                {
                    "instrument_id": "ES-202609-CME",
                    "quantity": 2,
                    "average_price": "5000.25",
                },
                {
                    "instrument_id": "NQ-202609-CME",
                    "quantity": -1,
                    "average_price": "18000.50",
                },
            ]
        ),
        encoding="utf-8",
    )
    store = _store_class()(path)

    assert store.load() == {
        "ES-202609-CME": Position("ES-202609-CME", 2, Decimal("5000.25")),
        "NQ-202609-CME": Position("NQ-202609-CME", -1, Decimal("18000.50")),
    }


def test_json_position_store_rejects_missing_state_file(tmp_path):
    store = _store_class()(tmp_path / "positions.json")

    with pytest.raises(ValueError, match="internal position state file does not exist"):
        store.load()


def test_json_position_store_rejects_duplicate_instruments(tmp_path):
    path = tmp_path / "positions.json"
    path.write_text(
        json.dumps(
            [
                {"instrument_id": "ES-202609-CME", "quantity": 1, "average_price": "5000"},
                {"instrument_id": "ES-202609-CME", "quantity": 2, "average_price": "5001"},
            ]
        ),
        encoding="utf-8",
    )
    store = _store_class()(path)

    with pytest.raises(ValueError, match="duplicate internal position"):
        store.load()


def test_json_position_store_rejects_malformed_records(tmp_path):
    path = tmp_path / "positions.json"
    path.write_text('[{"instrument_id":"ES-202609-CME"}]', encoding="utf-8")
    store = _store_class()(path)

    with pytest.raises(ValueError, match="invalid internal position record"):
        store.load()
