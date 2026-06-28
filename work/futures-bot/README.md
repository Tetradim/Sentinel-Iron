# Futures Bot

Production-oriented futures trading bot core.

This project is being built safety-first. The current slice provides tested domain models, pre-trade risk controls, broker-facing ports, IBKR configuration validation, reconciliation logic, immutable audit events, and conservative operator CLI commands.

It does not yet submit live orders. That is intentional. Live order submission should only be added after broker connection lifecycle, order acknowledgement handling, fill handling, cancellation, reconciliation, and audit trails are implemented and tested against a real broker API.

## Install

From the project directory:

```powershell
cd work/futures-bot
python -m pip install -e ".[dev]"
```

Run tests:

```powershell
python -m pytest tests -v
```

## Broker Environment

Paper and live are real broker environments. There is no fake demo broker path in the core.

Required IBKR environment variables:

```powershell
$env:BROKER_ENV = "paper"   # paper or live
$env:IBKR_HOST = "127.0.0.1"
$env:IBKR_PORT = "7497"
$env:IBKR_CLIENT_ID = "101"
```

Common IBKR defaults:

- TWS paper: `7497`
- TWS live: `7496`
- IB Gateway paper/live ports depend on local gateway configuration

## Commands

Validate broker configuration:

```powershell
futures-bot config-check
```

Attempt reconciliation:

```powershell
futures-bot reconcile
```

The current implementation reports that no live broker adapter is wired yet.

Attempt flatten:

```powershell
futures-bot flatten --confirm FLATTEN-LIVE-POSITIONS
```

The command requires explicit confirmation text and still refuses to submit orders until a live broker adapter is wired.

## Current Safety Controls

The pre-trade risk engine rejects orders when:

- the kill switch is active
- positions are not reconciled
- account data is stale
- market data is stale
- order quantity exceeds the configured limit
- resulting position exceeds the configured limit
- estimated margin usage exceeds the configured limit
- the contract is past the last safe trade date
- client order ID has already been used
- limit price is outside the configured price collar

## Next Adapter Targets

Broker adapter implementation order:

1. IBKR via TWS or IB Gateway
2. TradeStation
3. NinjaTrader
4. Optimus Futures through the selected route, such as Rithmic, CQG, Trading Technologies, CTS, or Firetip

Each adapter must implement the same broker port and must not leak broker SDK types into the domain or application layers.

## Strategy Roadmap

No strategy can bypass broker ports, reconciliation, risk checks, or audit logging. The first strategy target is diversified futures trend following with volatility targeting after live broker lifecycle handling is in place.
