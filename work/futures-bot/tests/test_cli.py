from futures_bot.cli import main


def _set_valid_ibkr_env(monkeypatch):
    monkeypatch.setenv("BROKER_ENV", "paper")
    monkeypatch.setenv("IBKR_HOST", "127.0.0.1")
    monkeypatch.setenv("IBKR_PORT", "7497")
    monkeypatch.setenv("IBKR_CLIENT_ID", "101")


def test_config_check_exits_zero_for_valid_ibkr_config(monkeypatch, capsys):
    _set_valid_ibkr_env(monkeypatch)

    exit_code = main(["config-check"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "IBKR config ok: environment=paper host=127.0.0.1 port=7497 client_id=101" in captured.out


def test_config_check_exits_nonzero_for_invalid_config(monkeypatch, capsys):
    _set_valid_ibkr_env(monkeypatch)
    monkeypatch.delenv("IBKR_HOST")

    exit_code = main(["config-check"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "IBKR_HOST is required" in captured.err


def test_reconcile_command_reports_no_broker_adapter_wired_yet(capsys):
    exit_code = main(["reconcile"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "No live broker adapter is wired for reconciliation yet." in captured.err


def test_flatten_command_refuses_without_explicit_confirmation_text(capsys):
    exit_code = main(["flatten"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "flatten requires --confirm FLATTEN-LIVE-POSITIONS" in captured.err
