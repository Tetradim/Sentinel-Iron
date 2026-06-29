# Futures Bot

Production-oriented futures trading bot core.

This project is being built safety-first. The current slice provides tested domain models, pre-trade risk controls, pre-broker risk decision auditing, broker connection lifecycle handling, broker-facing order submission orchestration, broker configuration validation, live-capable TradeStation, NinjaTrader, IBKR, and Optimus broker adapter boundaries, broker-backed reconciliation, fill-driven internal position accounting, immutable audit events, durable JSONL audit, instrument-catalog, position, order-activity, order-lifecycle, margin-schedule, and kill-switch storage, confirmed emergency position flattening, and conservative operator CLI commands.

It does not yet run autonomous strategy-driven live order entry. The current live-capable order submission surface is the explicit operator-confirmed emergency flatten command. Strategy-driven live order loops should only be added after broker connection lifecycle, order acknowledgement handling, fill handling, cancellation, reconciliation, persistent safety state, and audit trails are implemented and tested against a real broker API.

## Install

From the project directory:

```powershell
cd work/futures-bot
python -m pip install -e ".[dev]"
```

Install the optional IBKR TWS/Gateway transport:

```powershell
python -m pip install -e ".[ibkr]"
```

Run tests:

```powershell
python -m pytest tests -v
```

## Broker Environment

Paper and live are real broker environments. There is no fake demo broker path in the core. Commands that can submit orders in `BROKER_ENV=live` require an additional runtime activation token; credentials and command-specific confirmation text are not enough by themselves.

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

`futures_bot.brokers.ibkr.IbkrBroker` implements the broker port around a TWS or IB Gateway client contract. It maps IBKR account summary rows, position rows, next-valid order IDs, futures contracts, order payloads, cancel requests, what-if margin previews, and historical daily bars into shared broker and market-data ports. `futures_bot.brokers.ibkr.IbapiTwsClient` provides the concrete optional `ibapi` transport for TWS or IB Gateway callback flows, including `reqHistoricalData` daily bars.

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

`futures_bot.brokers.tradestation.TradeStationBroker` implements the broker port with bearer-token HTTP calls against the configured paper or live TradeStation base URL. It validates the configured account, fetches balances and positions, submits approved orders, requests order cancellation, and fetches normalized daily historical bars through TradeStation barcharts using the same application-layer risk, readiness, submission, cancellation, reconciliation, market-data, and audit services used by every broker.

Required NinjaTrader environment variables:

```powershell
$env:BROKER_ENV = "paper"   # paper or live
$env:NINJATRADER_REST_URL = "https://..."
$env:NINJATRADER_WS_URL = "wss://..."
$env:NINJATRADER_ACCESS_TOKEN = "..."
$env:NINJATRADER_ACCOUNT_ID = "SIM12345"
```

NinjaTrader REST and WebSocket URLs are explicit because deployments and broker access paths can differ. `futures_bot.brokers.ninjatrader.NinjaTraderBroker` implements the broker port with bearer-token HTTP calls against the configured REST URL. It validates the configured account, fetches account and position state, submits approved orders, and requests order cancellation through the same application-layer risk, readiness, submission, cancellation, reconciliation, and audit services used by every broker. Historical daily bars fail closed with `MarketDataError` until a deployment-specific, verified NinjaTrader data route is configured.

Required Optimus Futures environment variables:

```powershell
$env:BROKER_ENV = "paper"   # paper or live
$env:OPTIMUS_ROUTE = "rithmic"
$env:OPTIMUS_USERNAME = "..."
$env:OPTIMUS_PASSWORD = "..."
$env:OPTIMUS_ACCOUNT_ID = "SIM12345"
```

Supported Optimus execution routes are `rithmic`, `cqg`, `tt`, `cts`, `firetip`, `gain`, `oak`, and `qst`. `futures_bot.brokers.optimus.OptimusBroker` uses `OPTIMUS_API_URL` as a controlled HTTP bridge for the selected execution provider. It sends the selected route, app name, credentials, and account ID to that bridge, then maps account, position, order, and cancel responses into the shared broker port. Historical daily bars fail closed with `MarketDataError` until the controlled bridge exposes a verified route-specific historical data contract. Use `OPTIMUS_APP_NAME` to identify the bot session to that bridge or route adapter.

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

Connect to a configured broker and fetch account state without placing orders:

```powershell
$env:BROKER = "tradestation"
$env:BROKER_ENV = "paper"
futures-bot broker-connect --broker tradestation --audit-log data/audit.jsonl
futures-bot broker-connect --broker ibkr --audit-log data/audit.jsonl
futures-bot broker-connect --broker ninjatrader --audit-log data/audit.jsonl
futures-bot broker-connect --broker optimus --audit-log data/audit.jsonl
```

`broker-connect` currently supports TradeStation, IBKR, NinjaTrader, and Optimus. TradeStation and NinjaTrader use their configured paper or live HTTP base URLs. IBKR uses TWS or IB Gateway through the optional `ibapi` transport. Optimus uses the configured HTTP route bridge for the selected execution provider. These paths validate broker connectivity, fetch account and position state, write the broker connection audit event to the JSONL audit log, and never submit or cancel orders.

Inspect, activate, or clear the persistent operator kill switch:

```powershell
futures-bot kill-switch --state-file data/kill_switch.json status
futures-bot kill-switch --state-file data/kill_switch.json --audit-log data/audit.jsonl activate --reason "operator halt before news release"
futures-bot kill-switch --state-file data/kill_switch.json --audit-log data/audit.jsonl clear
```

When `--state-file` is omitted, the command uses `KILL_SWITCH_STATE_PATH` and falls back to `data/kill_switch.json`. The command writes `kill_switch_activated` and `kill_switch_cleared` audit events without broker credentials or other secrets.

Reconcile internal positions with the configured broker:

```powershell
futures-bot reconcile --broker tradestation --internal-positions data/internal_positions.json --audit-log data/audit.jsonl
futures-bot reconcile --broker ibkr --internal-positions data/internal_positions.json --audit-log data/audit.jsonl
futures-bot reconcile --broker ninjatrader --internal-positions data/internal_positions.json --audit-log data/audit.jsonl
futures-bot reconcile --broker optimus --internal-positions data/internal_positions.json --audit-log data/audit.jsonl
```

The internal position snapshot is a JSON array:

```json
[
  {"instrument_id": "ES-202609-CME", "quantity": 1, "average_price": "5000.25"},
  {"instrument_id": "NQ-202609-CME", "quantity": -2, "average_price": "18000.50"}
]
```

When `--internal-positions` is omitted, the command uses `INTERNAL_POSITIONS_PATH` and falls back to `data/internal_positions.json`. Missing or malformed internal state is treated as a configuration error. Position mismatches exit nonzero and record a `position_reconciliation` audit event.

Validate operator-supplied margin schedules before using them in rebalance risk contexts:

```powershell
futures-bot margin-schedules --schedule-file data/margin_schedules.json validate
```

When `--schedule-file` is omitted, the command uses `MARGIN_SCHEDULE_PATH` and falls back to `data/margin_schedules.json`. It loads the JSON schedule file, validates structure, duplicate instruments, Decimal margin values, timezone-aware expiries, and freshness, then exits nonzero before any broker call if the schedule is missing, malformed, or stale.

Validate operator-supplied futures instrument catalogs before using them in signal generation or rebalance risk contexts:

```powershell
futures-bot instrument-catalog --catalog-file data/instruments.json validate
futures-bot instrument-catalog --catalog-file data/instruments.json validate --trading-day 2026-09-14
```

When `--catalog-file` is omitted, the command uses `INSTRUMENT_CATALOG_PATH` and falls back to `data/instruments.json`. It loads the JSON catalog file, validates structure, duplicate instruments, Decimal multiplier and tick-size values, settlement types, and ISO first-notice, last-trade, and last-safe trade dates. When `--trading-day` is supplied, the command exits nonzero if any configured contract cannot trade on that date.

Attempt flatten:

```powershell
futures-bot flatten --broker tradestation --audit-log data/audit.jsonl --confirm FLATTEN-LIVE-POSITIONS
futures-bot flatten --broker ibkr --audit-log data/audit.jsonl --confirm FLATTEN-LIVE-POSITIONS
futures-bot flatten --broker ninjatrader --audit-log data/audit.jsonl --confirm FLATTEN-LIVE-POSITIONS
futures-bot flatten --broker optimus --audit-log data/audit.jsonl --confirm FLATTEN-LIVE-POSITIONS
```

When `BROKER_ENV=live`, add the live activation token in the same invocation:

```powershell
futures-bot flatten --broker tradestation --audit-log data/audit.jsonl --confirm FLATTEN-LIVE-POSITIONS --live-trading-activation ENABLE-LIVE-TRADING
```

The command requires exact explicit confirmation text. In live mode, it also requires exact live-trading activation before broker route construction; blocked live attempts write a `live_trading_blocked` audit event. After confirmation and any required live activation, it connects to the selected real broker environment, fetches current broker positions, skips flat positions, submits opposite-side market orders for nonzero positions, and writes `position_flatten_started`, `position_flatten_order_submitted`, `position_flatten_order_failed`, and `position_flatten_completed` audit events. If any flatten order is rejected synchronously by the broker or route, the command continues through remaining positions and exits nonzero after recording the failure.

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

The operator kill switch can be persisted with `futures_bot.storage.kill_switch.JsonKillSwitchStore` and controlled through `futures_bot.application.kill_switch.KillSwitchService`. Missing state files load as inactive. Activating the switch requires a non-empty operator reason, stores the active state, and appends a `kill_switch_activated` audit event. Clearing the switch stores an inactive state and appends a `kill_switch_cleared` audit event with the previous reason.

Broker adapters can be connected through `futures_bot.application.broker_connection.BrokerConnectionService`. It accepts only real broker environments (`paper` or `live`), calls the configured adapter, retrieves account and position state after connection, records `broker_connected` audit events, and records `broker_connection_failed` when adapters raise `futures_bot.ports.broker.BrokerConnectionError`.

Trading readiness can be evaluated through `futures_bot.application.trading_readiness.TradingReadinessService`. It blocks trading when the broker is disconnected, account state is missing or stale, or positions are not reconciled, and records a `trading_readiness` audit event for each evaluation before order submission is allowed.

Market data adapters can provide quotes through `futures_bot.ports.market_data.MarketDataPort`. `futures_bot.application.market_data.MarketDataSnapshotService` fetches `MarketSnapshot` values, rejects instrument mismatches before they enter risk checks, records successful quote snapshots, and records `market_data_snapshot_failed` events when adapters raise `MarketDataError`.

Historical data adapters can provide normalized daily bars through `futures_bot.ports.market_data.HistoricalDataPort`. `futures_bot.application.market_data.MarketDataHistoryService` requests inclusive date ranges, sorts returned bars, rejects instrument mismatches, out-of-range bars, and duplicate bar days, and records success, provider failure, or rejected-history audit events before bars feed continuous-history, trend, carry, or volatility calculations.

Historical bars can be cached with `futures_bot.storage.historical_bars.JsonHistoricalBarStore`. It stores one JSON array of OHLCV daily bars with Decimal prices encoded as strings, reloads bars in stable instrument/date order, supports inclusive instrument/date range reads, and rejects malformed records or duplicate instrument-day bars before cached data can feed strategy calculations.

Readiness-gated order entry should flow through `futures_bot.application.order_gateway.OrderGatewayService`. It can be configured with the broker environment and live-trading activation token so `BROKER_ENV=live` blocks new broker handoff before kill-switch loading, readiness evaluation, risk evaluation, or submission unless the exact activation token is present. It can also be configured with the persistent kill-switch store so an active operator halt blocks new broker handoff before risk evaluation or submission. If the configured kill-switch state cannot be loaded, the gateway fails closed with `kill_switch_state_unavailable`. It also refuses new orders when the latest readiness result is negative, writes an `order_submission_blocked` audit event with the block reason, and only then delegates ready orders into the audited submission service.

Internal positions can be loaded and saved with `futures_bot.storage.positions.JsonPositionStore` and compared against live broker positions through `futures_bot.application.reconciliation.ReconcilePositionsUseCase`. Reconciliation checks for broker positions missing internally, quantity differences, and nonzero internal positions missing at the broker before readiness is allowed to pass.

Internal position accounting can be updated from broker fills through `futures_bot.application.position_ledger.PositionLedgerService`. It applies signed fill quantities using the original order side, requires a fill price for ledger updates, recalculates weighted average price when adding to the same side, preserves average price when reducing without crossing through zero, resets average price to the fill price when a fill flips side, persists the updated position snapshot, and records `position_ledger_fill_applied` audit events. For restart-safe streaming operation, configure it with `futures_bot.storage.processed_fills.JsonlProcessedFillStore`; then each fill update must include a broker execution ID, and replayed execution IDs are audited as `position_ledger_fill_duplicate_ignored` without changing the position a second time.

Order activity can be tracked through `futures_bot.application.order_activity.OrderActivityTracker`. It records accepted broker submissions with the original side, quantity, order type, and limit price, rejects duplicate client order IDs, audits the recorded activity, and builds the `used_client_order_ids` and `recent_order_timestamps` inputs needed by pre-trade duplicate-ID and order-rate risk controls. For restart-safe live operation, back it with `futures_bot.storage.order_activity.JsonlOrderActivityStore` so accepted client order IDs and fill-signing metadata are rehydrated before new order checks and asynchronous fill processing run.

Strategy position targets can be converted to order intents through `futures_bot.application.order_planning.plan_order_to_target`, `plan_orders_to_targets`, or `plan_rebalance_order_phases`. Batch planning skips targets already at the current quantity, rejects duplicate targets and missing current positions, emits risk-reducing orders before new exposure while preserving target order inside each group, and splits long-to-short or short-to-long reversals into separate flatten and open intents with distinct client order IDs. Phase planning keeps reducing and opening exposure in separate phases so later execution code can wait for flatten fills before submitting new exposure. The resulting intents still flow through readiness, risk, submission, broker, lifecycle, and audit services.

Strategy signals can be converted into portfolio targets through `futures_bot.application.strategy_targets.build_strategy_position_targets`. It accepts trend, carry, or composite signals with instrument catalog entries, per-contract dollar volatility estimates, account equity, per-instrument sizing limits, and a portfolio gross-risk cap. Contracts past their last safe trade date produce flat targets before order planning, missing catalog or volatility inputs fail closed, and nonzero targets are scaled through the same portfolio risk cap used by lower-level sizing code.

Back-adjusted continuous futures histories can be built with `futures_bot.market.continuous.build_back_adjusted_continuous_series`. Each roll requires overlapping prices on the new contract's first included day, applies cumulative backward price adjustments to earlier contracts, and rejects missing overlap data instead of letting artificial roll gaps enter trend or volatility signals.

Sequenced rebalance execution can be coordinated through `futures_bot.application.rebalance_execution.RebalanceExecutionCoordinator`. It reads persisted order lifecycle state for each phase, returns unsubmitted intents for the earliest eligible phase, waits while submitted phase orders are not filled, blocks later phases after a cancellation or rejection, and reports completion once every phase is filled. It does not submit orders directly; eligible intents still go through the readiness-gated order gateway.

Eligible rebalance phase intents can be submitted through `futures_bot.application.rebalance_phase_submission.RebalancePhaseSubmissionService`. It asks the coordinator for the next eligible phase, requires a caller-provided `RiskContext` for every eligible client order ID before submitting anything, sends each intent through `OrderGatewayService`, and stops the phase after the first gateway rejection.

Risk contexts for rebalance intents can be built with `futures_bot.application.rebalance_risk_context.build_rebalance_risk_contexts`. It maps each eligible client order ID to a `RiskContext` from caller-provided account, instrument, market, current position, margin estimate, order-activity, PnL, kill-switch, and reconciliation inputs, and rejects duplicate client order IDs or missing/mismatched instrument-scoped inputs before any gateway submission is attempted.

Order margin inputs can be requested through `futures_bot.application.margin_estimates.MarginEstimateService`. It converts intents to broker orders, asks the configured provider for broker/API-derived initial and maintenance margin estimates, audits each estimate, audits provider failures, and raises `MarginEstimateUnavailable` instead of inventing fallback margin.

When a broker route does not expose an order preview, `futures_bot.application.margin_schedules.MarginScheduleProvider` can serve as the approved margin provider from operator-supplied FCM or exchange margin schedules. Each schedule entry must include an instrument ID, positive per-contract initial and maintenance margins, a source label, and a timezone-aware expiry; missing, mismatched, or stale entries raise `MarginEstimateUnavailable`.

Operator-supplied margin schedules can be loaded and saved with `futures_bot.storage.margin_schedules.JsonMarginScheduleStore`. It stores one JSON array of instrument schedules with Decimal values encoded as strings and ISO timezone-aware expiry timestamps, rejects missing files, malformed records, and duplicate instruments, and can feed `MarginScheduleProvider` after loading.

Operator-supplied instrument catalogs can be loaded and saved with `futures_bot.storage.instruments.JsonInstrumentStore`. It stores one JSON array of futures contracts with Decimal multiplier and tick-size values encoded as strings, settlement type, exchange, contract month, first-notice date, last-trade date, and last-safe trade date, then reconstructs validated `FuturesInstrument` values before risk contexts use them.

The IBKR adapter implements the margin estimate provider boundary through a what-if order preview. It builds the same futures contract and order payload used for submission, sets `whatIf` and `transmit`, parses IBKR initial and maintenance margin changes, and maps preview failures to `MarginEstimateUnavailable`.

The TradeStation adapter implements the same margin estimate provider boundary through the v3 order confirmation endpoint. It reuses the live order payload, parses explicit initial and maintenance margin fields when the confirmation response provides them, and raises `MarginEstimateUnavailable` if TradeStation returns only non-margin estimate fields or rejects the confirmation request.

The NinjaTrader adapter exposes the margin estimate provider method but fails closed with `MarginEstimateUnavailable` because the current REST boundary does not provide a verified broker-derived order margin preview. Rebalance execution using NinjaTrader must supply margin estimates from another approved provider before gateway submission.

The Optimus adapter also exposes the margin estimate provider method but fails closed with `MarginEstimateUnavailable` because the configured route bridge does not provide a verified broker-derived order margin preview. Rebalance execution using Optimus must supply route-approved margin estimates before gateway submission.

Approved order intents can be submitted through `futures_bot.application.order_submission.OrderSubmissionService`. It always runs the audited risk check first, blocks rejected orders before the broker port is called, converts approved intents into `BrokerOrder` values, submits them through the configured broker adapter, and audits blocked, submitted, and broker-rejected handoffs. Configure it with a lifecycle store to persist working and rejected lifecycle states as soon as the submission decision is known.

Broker adapters should raise `futures_bot.ports.broker.BrokerSubmissionError` when the broker, exchange, or route rejects a submitted order synchronously. The submission service records a rejected lifecycle with the broker reason and optional broker error code instead of leaving the order in an ambiguous pending state.

Open order cancels can be requested through `futures_bot.application.order_cancellation.OrderCancellationService`. It validates the order lifecycle can move to pending cancel, calls the configured broker adapter, records `order_cancel_requested` audit events for accepted cancel requests, and records `order_cancel_failed` events when adapters raise `futures_bot.ports.broker.BrokerCancellationError`. Configure it with the order lifecycle store so accepted cancel requests persist `pending_cancel` immediately; after a restart, the service can reload the latest lifecycle by client order ID before submitting a cancel, and later broker canceled updates can transition from the recovered pending-cancel state.

Emergency position flattening can be run through `futures_bot.application.position_flattening.PositionFlatteningService`. It connects to the broker, reads the broker account and current positions, converts long positions into sell market orders and short positions into buy market orders, skips zero-quantity positions, records each submitted or failed flatten request, and records a completion summary. This path is intentionally separate from strategy order entry because it is an operator-confirmed risk-reduction command.

Broker adapters can publish order acknowledgements, fills, cancellations, and asynchronous rejects as `futures_bot.ports.broker.BrokerOrderUpdate` values. `futures_bot.application.order_updates.OrderUpdateService` applies those updates to `OrderLifecycle` and appends `order_update_applied` audit events with account ID, client order ID, broker order ID, instrument ID, update type, resulting status, incremental fill quantity, cumulative filled quantity, reject reason, and broker error code. When configured with a position ledger, fill updates also update the internal position snapshot; that path requires the original order side so buy and sell fills are signed correctly. For restart-safe streaming handlers, configure the service with `OrderActivityTracker`, a lifecycle store, and the same processed-fill store used by the position ledger; then missing order quantity and side are recovered from persisted accepted-order activity by client order ID, missing lifecycle state is loaded by client order ID, each applied update persists the new lifecycle, duplicate fill execution IDs are audited as `order_update_fill_duplicate_ignored` before lifecycle or ledger mutation, broker updates with a mismatched instrument are rejected before lifecycle or ledger mutation, and broker order IDs are validated against accepted-order activity whenever the broker stream provides one.

Audit events can be persisted with `futures_bot.storage.audit.JsonlAuditLog`. It appends one JSON object per line, creates parent directories when needed, stores a copy of each event, and replays immutable event snapshots for diagnostics.

Accepted broker order activity can be persisted with `futures_bot.storage.order_activity.JsonlOrderActivityStore`. It appends one JSON object per accepted broker handoff, including client order ID, broker order ID, instrument, timestamp, side, quantity, order type, and limit price. It creates parent directories when needed, reloads timezone-aware activity records on startup, and rejects duplicate or malformed persisted records before they enter risk inputs or fill-ledger recovery paths.

Order lifecycle state can be persisted with `futures_bot.storage.order_lifecycles.JsonlOrderLifecycleStore`. It appends each latest lifecycle state as JSONL, reloads the newest state for a client order ID on startup or broker-stream recovery, and rejects malformed persisted lifecycle records before they can drive fill, cancel, or reject transitions.

## Next Adapter Targets

All named broker adapter boundaries are now represented in the shared broker port. Next broker work should deepen provider-specific transports, streaming order updates, and contract normalization without leaking broker SDK types into the domain or application layers.

## Strategy Roadmap

No strategy can bypass broker ports, reconciliation, risk checks, or audit logging. The first strategy target is diversified futures trend following with volatility targeting after live broker lifecycle handling is in place. `futures_bot.strategies.trend_following.calculate_volatility_adjusted_trend_signal` can convert multi-lookback returns into volatility-normalized scores before they enter portfolio sizing, so weak and strong trends are not treated identically. `futures_bot.strategies.composite.combine_weighted_signals` can blend trend and carry scores per market, and `futures_bot.application.strategy_targets.build_strategy_position_targets` can turn those signals into delivery-date-aware, gross-risk-capped target positions before order planning creates broker intents.
