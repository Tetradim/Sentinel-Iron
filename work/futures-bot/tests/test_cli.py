import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from futures_bot.application.live_trading import LIVE_TRADING_ACTIVATION
from futures_bot.cli import main
from futures_bot.domain.orders import BrokerOrder
from futures_bot.domain.portfolio import AccountSnapshot, Position


def _route_for(broker: object):
    return SimpleNamespace(execution=broker)


def _set_valid_ibkr_env(monkeypatch):
    monkeypatch.setenv("BROKER_ENV", "paper")
    monkeypatch.setenv("IBKR_HOST", "127.0.0.1")
    monkeypatch.setenv("IBKR_PORT", "7497")
    monkeypatch.setenv("IBKR_CLIENT_ID", "101")


def _set_valid_tradestation_env(monkeypatch):
    monkeypatch.setenv("BROKER_ENV", "paper")
    monkeypatch.setenv("TRADESTATION_ACCESS_TOKEN", "secret-token")
    monkeypatch.setenv("TRADESTATION_ACCOUNT_ID", "SIM12345")


def _set_valid_ninjatrader_env(monkeypatch):
    monkeypatch.setenv("BROKER_ENV", "paper")
    monkeypatch.setenv("NINJATRADER_REST_URL", "https://api.ninjatrader.example/v1")
    monkeypatch.setenv("NINJATRADER_WS_URL", "wss://stream.ninjatrader.example/v1")
    monkeypatch.setenv("NINJATRADER_ACCESS_TOKEN", "secret-token")
    monkeypatch.setenv("NINJATRADER_ACCOUNT_ID", "SIM12345")


def _set_valid_optimus_env(monkeypatch):
    monkeypatch.setenv("BROKER_ENV", "paper")
    monkeypatch.setenv("OPTIMUS_ROUTE", "rithmic")
    monkeypatch.setenv("OPTIMUS_USERNAME", "secret-user")
    monkeypatch.setenv("OPTIMUS_PASSWORD", "secret-password")
    monkeypatch.setenv("OPTIMUS_ACCOUNT_ID", "SIM12345")


def test_config_check_exits_zero_for_valid_ibkr_config(monkeypatch, capsys):
    _set_valid_ibkr_env(monkeypatch)

    exit_code = main(["config-check"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "IBKR config ok: environment=paper host=127.0.0.1 port=7497 client_id=101" in captured.out


def test_config_check_accepts_explicit_ibkr_broker(monkeypatch, capsys):
    _set_valid_ibkr_env(monkeypatch)

    exit_code = main(["config-check", "--broker", "ibkr"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "IBKR config ok" in captured.out


def test_config_check_exits_zero_for_valid_tradestation_config(monkeypatch, capsys):
    _set_valid_tradestation_env(monkeypatch)

    exit_code = main(["config-check", "--broker", "tradestation"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert (
        "TradeStation config ok: "
        "environment=paper "
        "base_url=https://sim-api.tradestation.com/v3 "
        "account_id=SIM12345"
    ) in captured.out
    assert "secret-token" not in captured.out


def test_config_check_exits_zero_for_valid_ninjatrader_config(monkeypatch, capsys):
    _set_valid_ninjatrader_env(monkeypatch)

    exit_code = main(["config-check", "--broker", "ninjatrader"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert (
        "NinjaTrader config ok: "
        "environment=paper "
        "rest_url=https://api.ninjatrader.example/v1 "
        "websocket_url=wss://stream.ninjatrader.example/v1 "
        "account_id=SIM12345"
    ) in captured.out
    assert "secret-token" not in captured.out


def test_config_check_exits_zero_for_valid_optimus_config(monkeypatch, capsys):
    _set_valid_optimus_env(monkeypatch)

    exit_code = main(["config-check", "--broker", "optimus"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert (
        "Optimus config ok: "
        "environment=paper "
        "route=rithmic "
        "account_id=SIM12345 "
        "api_url=not-set"
    ) in captured.out
    assert "secret-user" not in captured.out
    assert "secret-password" not in captured.out


def test_config_check_uses_broker_environment_variable(monkeypatch, capsys):
    _set_valid_tradestation_env(monkeypatch)
    monkeypatch.setenv("BROKER", "tradestation")

    exit_code = main(["config-check"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "TradeStation config ok" in captured.out


class FakeBroker:
    def __init__(self) -> None:
        self.connected = False

    def connect(self) -> None:
        self.connected = True

    def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(
            account_id="SIM12345",
            equity=Decimal("100000"),
            initial_margin=Decimal("10000"),
            maintenance_margin=Decimal("8000"),
            buying_power=Decimal("50000"),
            timestamp=datetime(2026, 6, 28, 16, 0, tzinfo=timezone.utc),
        )

    def get_positions(self) -> tuple[Position, ...]:
        return (
            Position(
                instrument_id="@ESU26",
                quantity=1,
                average_price=Decimal("5000.25"),
            ),
        )

    def submit_order(self, order: BrokerOrder) -> str:
        raise NotImplementedError

    def cancel_order(self, broker_order_id: str) -> None:
        raise NotImplementedError


class FlattenBroker(FakeBroker):
    def __init__(self) -> None:
        super().__init__()
        self.submitted_orders: list[BrokerOrder] = []

    def get_positions(self) -> tuple[Position, ...]:
        return (
            Position(
                instrument_id="@ESU26",
                quantity=1,
                average_price=Decimal("5000.25"),
            ),
            Position(
                instrument_id="@NQU26",
                quantity=-2,
                average_price=Decimal("18000.25"),
            ),
        )

    def submit_order(self, order: BrokerOrder) -> str:
        self.submitted_orders.append(order)
        return f"flatten-{len(self.submitted_orders)}"


def test_broker_connect_uses_configured_broker_and_writes_audit_log(
    monkeypatch,
    tmp_path,
    capsys,
):
    _set_valid_tradestation_env(monkeypatch)
    broker = FakeBroker()

    def create_fake_route(name: str, env: object):
        assert name == "tradestation"
        return _route_for(broker)

    monkeypatch.setattr("futures_bot.cli_commands.broker.create_broker_route", create_fake_route)
    audit_log_path = tmp_path / "audit" / "broker.jsonl"

    exit_code = main(
        [
            "broker-connect",
            "--broker",
            "tradestation",
            "--audit-log",
            str(audit_log_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert broker.connected is True
    assert "broker connected: broker=tradestation account_id=SIM12345 positions=1" in captured.out
    assert "secret" not in captured.out
    assert "broker_connected" in audit_log_path.read_text(encoding="utf-8")


def test_broker_connect_reports_factory_errors(monkeypatch, capsys):
    def create_failing_route(name: str, env: object):
        raise ValueError(f"{name} broker adapter is not implemented yet")

    monkeypatch.setattr("futures_bot.cli_commands.broker.create_broker_route", create_failing_route)

    exit_code = main(["broker-connect", "--broker", "ibkr"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "ibkr broker adapter is not implemented yet" in captured.err


def test_config_check_rejects_unknown_broker(capsys):
    exit_code = main(["config-check", "--broker", "unknown"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "unsupported broker: unknown" in captured.err


def test_config_check_exits_nonzero_for_invalid_config(monkeypatch, capsys):
    _set_valid_ibkr_env(monkeypatch)
    monkeypatch.delenv("IBKR_HOST")

    exit_code = main(["config-check"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "IBKR_HOST is required" in captured.err


def test_reconcile_command_uses_configured_broker_and_writes_audit_log(
    monkeypatch,
    tmp_path,
    capsys,
):
    _set_valid_tradestation_env(monkeypatch)
    broker = FakeBroker()

    def create_fake_route(name: str, env: object):
        assert name == "tradestation"
        return _route_for(broker)

    monkeypatch.setattr("futures_bot.cli_commands.broker.create_broker_route", create_fake_route)
    internal_positions_path = tmp_path / "state" / "positions.json"
    internal_positions_path.parent.mkdir(parents=True)
    internal_positions_path.write_text(
        json.dumps(
            [
                {
                    "instrument_id": "@ESU26",
                    "quantity": 1,
                    "average_price": "5000.25",
                }
            ]
        ),
        encoding="utf-8",
    )
    audit_log_path = tmp_path / "audit" / "reconcile.jsonl"

    exit_code = main(
        [
            "reconcile",
            "--broker",
            "tradestation",
            "--internal-positions",
            str(internal_positions_path),
            "--audit-log",
            str(audit_log_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert broker.connected is True
    assert "positions reconciled: broker=tradestation broker_positions=1" in captured.out
    assert "position_reconciliation" in audit_log_path.read_text(encoding="utf-8")


def test_reconcile_command_reports_mismatches(monkeypatch, tmp_path, capsys):
    _set_valid_tradestation_env(monkeypatch)
    broker = FakeBroker()

    def create_fake_route(name: str, env: object):
        assert name == "tradestation"
        return _route_for(broker)

    monkeypatch.setattr("futures_bot.cli_commands.broker.create_broker_route", create_fake_route)
    internal_positions_path = tmp_path / "positions.json"
    internal_positions_path.write_text(
        json.dumps(
            [
                {
                    "instrument_id": "@ESU26",
                    "quantity": 2,
                    "average_price": "5000.25",
                }
            ]
        ),
        encoding="utf-8",
    )
    audit_log_path = tmp_path / "audit" / "reconcile-mismatch.jsonl"

    exit_code = main(
        [
            "reconcile",
            "--broker",
            "tradestation",
            "--internal-positions",
            str(internal_positions_path),
            "--audit-log",
            str(audit_log_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "positions not reconciled: quantity mismatch for @ESU26: internal=2 broker=1" in captured.err


def test_margin_schedules_validate_reports_valid_file(tmp_path, capsys):
    schedule_path = tmp_path / "state" / "margin_schedules.json"
    schedule_path.parent.mkdir(parents=True)
    schedule_path.write_text(
        json.dumps(
            [
                {
                    "expires_at": "2099-06-29T16:45:00+00:00",
                    "initial_margin_per_contract": "12000",
                    "instrument_id": "ES-202609-CME",
                    "maintenance_margin_per_contract": "10000",
                    "source": "FCM daily margin schedule 2099-06-28",
                }
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "margin-schedules",
            "--schedule-file",
            str(schedule_path),
            "validate",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "margin schedules valid: entries=1" in captured.out


def test_margin_schedules_validate_reports_missing_file(tmp_path, capsys):
    exit_code = main(
        [
            "margin-schedules",
            "--schedule-file",
            str(tmp_path / "missing.json"),
            "validate",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "margin schedule file does not exist" in captured.err


def test_margin_schedules_validate_reports_stale_schedule(tmp_path, capsys):
    schedule_path = tmp_path / "margin_schedules.json"
    schedule_path.write_text(
        json.dumps(
            [
                {
                    "expires_at": "2020-06-29T16:45:00+00:00",
                    "initial_margin_per_contract": "12000",
                    "instrument_id": "ES-202609-CME",
                    "maintenance_margin_per_contract": "10000",
                    "source": "stale FCM margin schedule",
                }
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "margin-schedules",
            "--schedule-file",
            str(schedule_path),
            "validate",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "margin schedule for ES-202609-CME expired at 2020-06-29T16:45:00+00:00" in captured.err


def test_instrument_catalog_validate_reports_valid_file(tmp_path, capsys):
    catalog_path = tmp_path / "state" / "instruments.json"
    catalog_path.parent.mkdir(parents=True)
    catalog_path.write_text(
        json.dumps([_instrument_catalog_record("ES-202609-CME")]),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "instrument-catalog",
            "--catalog-file",
            str(catalog_path),
            "validate",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "instrument catalog valid: entries=1" in captured.out


def test_instrument_catalog_validate_reports_missing_file(tmp_path, capsys):
    exit_code = main(
        [
            "instrument-catalog",
            "--catalog-file",
            str(tmp_path / "missing.json"),
            "validate",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "instrument catalog file does not exist" in captured.err


def test_instrument_catalog_validate_reports_unsafe_trading_day(tmp_path, capsys):
    catalog_path = tmp_path / "instruments.json"
    catalog_path.write_text(
        json.dumps([_instrument_catalog_record("ES-202609-CME")]),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "instrument-catalog",
            "--catalog-file",
            str(catalog_path),
            "validate",
            "--trading-day",
            "2026-09-15",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert (
        "instrument catalog contains non-tradable contracts for 2026-09-15: "
        "ES-202609-CME"
    ) in captured.err


def test_flatten_command_refuses_without_explicit_confirmation_text(capsys):
    exit_code = main(["flatten"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "flatten requires --confirm FLATTEN-LIVE-POSITIONS" in captured.err


def test_flatten_command_uses_configured_broker_and_writes_audit_log(
    monkeypatch,
    tmp_path,
    capsys,
):
    _set_valid_tradestation_env(monkeypatch)
    broker = FlattenBroker()

    def create_fake_route(name: str, env: object):
        assert name == "tradestation"
        return _route_for(broker)

    monkeypatch.setattr("futures_bot.cli_commands.broker.create_broker_route", create_fake_route)
    audit_log_path = tmp_path / "audit" / "flatten.jsonl"

    exit_code = main(
        [
            "flatten",
            "--broker",
            "tradestation",
            "--audit-log",
            str(audit_log_path),
            "--confirm",
            "FLATTEN-LIVE-POSITIONS",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert broker.connected is True
    assert [order.side.value for order in broker.submitted_orders] == ["sell", "buy"]
    assert [order.quantity for order in broker.submitted_orders] == [1, 2]
    assert "flatten submitted: broker=tradestation submitted=2 failed=0 skipped=0" in captured.out
    assert "position_flatten_completed" in audit_log_path.read_text(encoding="utf-8")


def test_flatten_command_blocks_live_environment_without_activation(
    monkeypatch,
    tmp_path,
    capsys,
):
    _set_valid_tradestation_env(monkeypatch)
    monkeypatch.setenv("BROKER_ENV", "live")
    route_created = False

    def create_fake_route(name: str, env: object):
        nonlocal route_created
        route_created = True
        return _route_for(FlattenBroker())

    monkeypatch.setattr("futures_bot.cli_commands.broker.create_broker_route", create_fake_route)
    audit_log_path = tmp_path / "audit.jsonl"

    exit_code = main(
        [
            "flatten",
            "--broker",
            "tradestation",
            "--audit-log",
            str(audit_log_path),
            "--confirm",
            "FLATTEN-LIVE-POSITIONS",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert route_created is False
    assert f"live trading requires activation token {LIVE_TRADING_ACTIVATION}" in captured.err
    audit_event = json.loads(audit_log_path.read_text(encoding="utf-8"))
    assert audit_event["type"] == "live_trading_blocked"
    assert audit_event["broker"] == "tradestation"
    assert audit_event["environment"] == "live"
    assert audit_event["reason"] == "live_trading_activation_required"


def test_flatten_command_allows_live_environment_with_activation(
    monkeypatch,
    tmp_path,
    capsys,
):
    _set_valid_tradestation_env(monkeypatch)
    monkeypatch.setenv("BROKER_ENV", "live")
    broker = FlattenBroker()

    def create_fake_route(name: str, env: object):
        assert name == "tradestation"
        return _route_for(broker)

    monkeypatch.setattr("futures_bot.cli_commands.broker.create_broker_route", create_fake_route)

    exit_code = main(
        [
            "flatten",
            "--broker",
            "tradestation",
            "--audit-log",
            str(tmp_path / "audit.jsonl"),
            "--confirm",
            "FLATTEN-LIVE-POSITIONS",
            "--live-trading-activation",
            LIVE_TRADING_ACTIVATION,
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert broker.submitted_orders
    assert "flatten submitted: broker=tradestation submitted=2 failed=0 skipped=0" in captured.out


def test_kill_switch_status_reports_inactive_when_state_file_is_missing(tmp_path, capsys):
    exit_code = main(
        [
            "kill-switch",
            "--state-file",
            str(tmp_path / "state" / "kill_switch.json"),
            "status",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "kill switch inactive" in captured.out


def test_kill_switch_activate_writes_state_and_audit_event(tmp_path, capsys):
    state_path = tmp_path / "state" / "kill_switch.json"
    audit_path = tmp_path / "audit" / "audit.jsonl"

    exit_code = main(
        [
            "kill-switch",
            "--state-file",
            str(state_path),
            "--audit-log",
            str(audit_path),
            "activate",
            "--reason",
            "operator halt before news release",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "kill switch active: reason=operator halt before news release" in captured.out
    assert json.loads(state_path.read_text(encoding="utf-8"))["active"] is True
    assert "operator halt before news release" in state_path.read_text(encoding="utf-8")
    assert "kill_switch_activated" in audit_path.read_text(encoding="utf-8")


def test_kill_switch_clear_writes_inactive_state_and_audit_event(tmp_path, capsys):
    state_path = tmp_path / "state" / "kill_switch.json"
    audit_path = tmp_path / "audit" / "audit.jsonl"
    main(
        [
            "kill-switch",
            "--state-file",
            str(state_path),
            "--audit-log",
            str(audit_path),
            "activate",
            "--reason",
            "operator halt before news release",
        ]
    )

    exit_code = main(
        [
            "kill-switch",
            "--state-file",
            str(state_path),
            "--audit-log",
            str(audit_path),
            "clear",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "kill switch inactive" in captured.out
    assert json.loads(state_path.read_text(encoding="utf-8"))["active"] is False
    assert "kill_switch_cleared" in audit_path.read_text(encoding="utf-8")


def _instrument_catalog_record(instrument_id: str) -> dict[str, object]:
    symbol, contract_month, exchange = instrument_id.split("-")
    return {
        "calendar": {
            "first_notice_date": None,
            "last_safe_trade_date": "2026-09-14",
            "last_trade_date": "2026-09-18",
        },
        "instrument_id": instrument_id,
        "spec": {
            "contract_month": contract_month,
            "currency": "USD",
            "exchange": exchange,
            "multiplier": "50",
            "settlement_type": "cash",
            "symbol": symbol,
            "tick_size": "0.25",
        },
    }
