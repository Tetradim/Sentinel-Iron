# Futures Bot

Production-oriented futures trading bot core.

This project is being built safety-first. The current slice provides tested domain models, pre-trade risk controls, pre-broker risk decision auditing, broker connection lifecycle handling, broker-facing order submission orchestration, broker configuration validation, reconciliation logic, immutable audit events, durable JSONL audit storage, and conservative operator CLI commands.

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

Required TradeStation environment variables:

```powershell
$env:BROKER_ENV = "paper"   # paper or live
$env:TRADESTATION_ACCESS_TOKEN = "..."
$env:TRADESTATION_ACCOUNT_ID = "SIM12345"
```

TradeStation defaults:

- Paper: `https://sim-api.tradestation.com/v3`
- Live: `https://api.tradestation.com/v3`
- Override with `TRADESTATION_BASE_URL` when routing through a controlled proxy.

Required NinjaTrader environment variables:

```powershell
$env:BROKER_ENV = "paper"   # paper or live
$env:NINJATRADER_REST_URL = "https://..."
$env:NINJATRADER_WS_URL = "wss://..."
$env:NINJATRADER_ACCESS_TOKEN = "..."
$env:NINJATRADER_ACCOUNT_ID = "SIM12345"
```

NinjaTrader REST and WebSocket URLs are explicit because deployments and broker access paths can differ.

Required Optimus Futures environment variables:

```powershell
$env:BROKER_ENV = "paper"   # paper or live
$env:OPTIMUS_ROUTE = "rithmic"
$env:OPTIMUS_USERNAME = "..."
$env:OPTIMUS_PASSWORD = "..."
$env:OPTIMUS_ACCOUNT_ID = "SIM12345"
```

Supported Optimus execution routes are `rithmic`, `cqg`, `tt`, `cts`, `firetip`, `gain`, `oak`, and `qst`. Use `OPTIMUS_API_URL` only when routing through a controlled HTTP bridge for the selected execution provider. Use `OPTIMUS_APP_NAME` to identify the bot session to that bridge or route adapter.

## Commands

Validate broker configuration:

```powershell
futures-bot config-check
futures-bot config-check --broker ibkr
futures-bot config-check --broker tradestation
futures-bot config-check --broker ninjatrader
futures-bot config-check --broker optimus
```

When `--broker` is omitted, the command uses `BROKER` and falls back to `ibkr`. The command prints non-secret connection details and never prints broker tokens.

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
- order intent, market snapshot, position, and risk context instrument IDs do not match
- order quantity exceeds the configured limit
- market quote is not two-sided
- market quote is crossed
- bid/ask spread exceeds the configured limit
- recent order count reaches the configured rate limit window
- resulting position exceeds the configured limit
- estimated order notional exceeds the configured limit
- estimated resulting position notional exceeds the configured limit
- estimated margin usage exceeds the configured limit
- estimated maintenance margin usage exceeds the configured limit
- estimated initial margin exceeds broker-reported buying power
- realized daily loss reaches the configured limit
- the contract is past the last safe trade date
- client order ID has already been used
- limit price is not aligned to the contract tick size
- limit price is outside the configured price collar

Pre-trade risk checks can be run through `futures_bot.application.risk_check.RiskCheckService`. It returns the same `RiskDecision` as the risk engine and appends a `risk_decision` audit event with timestamp, account ID, client order ID, instrument ID, side, quantity, order type, limit price, approval status, rejection reason, and detail before broker submission.

Broker adapters can be connected through `futures_bot.application.broker_connection.BrokerConnectionService`. It accepts only real broker environments (`paper` or `live`), calls the configured adapter, retrieves account and position state after connection, records `broker_connected` audit events, and records `broker_connection_failed` when adapters raise `futures_bot.ports.broker.BrokerConnectionError`.

Trading readiness can be evaluated through `futures_bot.application.trading_readiness.TradingReadinessService`. It blocks trading when the broker is disconnected, account state is missing or stale, or positions are not reconciled, and records a `trading_readiness` audit event for each evaluation before order submission is allowed.

Readiness-gated order entry should flow through `futures_bot.application.order_gateway.OrderGatewayService`. It refuses new orders when the latest readiness result is negative, writes an `order_submission_blocked` audit event with the readiness reason, and only then delegates ready orders into the audited submission service.

Approved order intents can be submitted through `futures_bot.application.order_submission.OrderSubmissionService`. It always runs the audited risk check first, blocks rejected orders before the broker port is called, converts approved intents into `BrokerOrder` values, submits them through the configured broker adapter, and audits blocked, submitted, and broker-rejected handoffs.

Broker adapters should raise `futures_bot.ports.broker.BrokerSubmissionError` when the broker, exchange, or route rejects a submitted order synchronously. The submission service records a rejected lifecycle with the broker reason and optional broker error code instead of leaving the order in an ambiguous pending state.

Open order cancels can be requested through `futures_bot.application.order_cancellation.OrderCancellationService`. It validates the order lifecycle can move to pending cancel, calls the configured broker adapter, records `order_cancel_requested` audit events for accepted cancel requests, and records `order_cancel_failed` events when adapters raise `futures_bot.ports.broker.BrokerCancellationError`.

Broker adapters can publish order acknowledgements, fills, cancellations, and asynchronous rejects as `futures_bot.ports.broker.BrokerOrderUpdate` values. `futures_bot.application.order_updates.OrderUpdateService` applies those updates to `OrderLifecycle` and appends `order_update_applied` audit events with account ID, client order ID, broker order ID, instrument ID, update type, resulting status, incremental fill quantity, cumulative filled quantity, reject reason, and broker error code.

Audit events can be persisted with `futures_bot.storage.audit.JsonlAuditLog`. It appends one JSON object per line, creates parent directories when needed, stores a copy of each event, and replays immutable event snapshots for diagnostics.

## Next Adapter Targets

Broker adapter implementation order:

1. IBKR via TWS or IB Gateway
2. TradeStation
3. NinjaTrader
4. Optimus Futures through the selected route, such as Rithmic, CQG, Trading Technologies, CTS, or Firetip

Each adapter must implement the same broker port and must not leak broker SDK types into the domain or application layers.

## Strategy Roadmap

No strategy can bypass broker ports, reconciliation, risk checks, or audit logging. The first strategy target is diversified futures trend following with volatility targeting after live broker lifecycle handling is in place.
