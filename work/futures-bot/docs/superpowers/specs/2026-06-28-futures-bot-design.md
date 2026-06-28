# Futures Bot Design

Date: 2026-06-28

## Purpose

Build a production-oriented futures trading bot that can eventually trade multiple futures asset classes through real broker APIs. The first implementation slice must be live-capable from the start. Broker paper environments are treated as broker environment choices, not as a separate demo subsystem.

The initial goal is not to maximize strategy complexity. The initial goal is to create a reliable trading system core that prevents unsafe orders, models futures contracts correctly, and can be extended across brokers and futures products without rewriting the domain.

## Scope

### In Scope For The First Build Slice

- Python project under `work/futures-bot`.
- Domain models for futures instruments, orders, fills, positions, accounts, and risk decisions.
- Broker adapter port shared by all broker integrations.
- IBKR adapter skeleton aligned with TWS or IB Gateway live and paper connection modes.
- Configuration that selects real broker environment, such as `paper` or `live`.
- Risk engine with pre-trade checks for:
  - global kill switch
  - stale market data
  - max order quantity
  - max position per instrument
  - max margin usage
  - delivery and expiration cutoff
  - duplicate client order IDs
  - price collars
- Audit log interfaces for orders, decisions, fills, rejects, and operator actions.
- Reconciliation use case that compares internal positions with broker positions.
- CLI entry points for safe operational commands, such as `reconcile`, `flatten`, and `run-live`.
- Unit tests for domain and risk behavior before production code.

### Out Of Scope For The First Build Slice

- Fully automated strategy order placement before risk and reconciliation pass.
- Backtesting engine.
- Direct CME Globex access.
- Co-location, HFT, market making, or queue-position optimization.
- Selling signals, managing third-party accounts, or CTA/CPO compliance automation.
- A fake demo broker that would later be removed.

## Broker Strategy

The system supports a broker adapter architecture. The first concrete adapter is IBKR because it has broad futures coverage and mature API support through TWS or IB Gateway. TradeStation, NinjaTrader, and Optimus Futures routes are added after the core is stable.

Broker order:

1. IBKR: primary first adapter, using TWS or IB Gateway.
2. TradeStation: REST and streaming APIs for futures where account entitlements allow.
3. NinjaTrader: REST/WebSocket trader API or desktop SDK path, depending on account and platform constraints.
4. Optimus Futures: implemented through the selected Optimus execution route, such as Rithmic, CQG, Trading Technologies, CTS, or Firetip.

All adapters implement the same broker port. The application layer must not import broker SDKs directly.

## Architecture

Use clean architecture with dependencies pointing inward.

### Domain Layer

Pure Python models and rules:

- `Instrument`: root metadata for one listed futures contract.
- `ContractSpec`: multiplier, tick size, tick value, settlement type, currency, exchange.
- `TradingCalendar`: sessions, holidays, first notice date, last trade date, last safe trade date.
- `OrderIntent`: desired action before broker-specific translation.
- `Order`: broker-ready request after risk approval.
- `Fill`: execution event.
- `Position`: current signed quantity and average price.
- `AccountSnapshot`: equity, buying power, margin, realized and unrealized P&L.
- `RiskDecision`: approval or rejection with machine-readable reasons.

The domain layer has no dependency on IBKR, TradeStation, NinjaTrader, databases, web frameworks, or CLIs.

### Application Layer

Use cases orchestrate domain objects and ports:

- `PlanOrderUseCase`: converts an order intent into a risk-checked order.
- `SubmitOrderUseCase`: sends approved orders through a broker adapter.
- `ReconcilePositionsUseCase`: compares internal and broker positions.
- `FlattenPositionsUseCase`: creates offsetting orders for allowed open positions.
- `SyncInstrumentsUseCase`: updates instrument metadata through configured sources.

### Ports

Interfaces owned by the application core:

- `BrokerPort`: connect, get account, get positions, submit order, cancel order, stream fills.
- `MarketDataPort`: latest quotes, bars, settlements, and data freshness.
- `InstrumentRepository`: read and write instrument metadata.
- `AuditLogPort`: append immutable operational events.
- `KillSwitchPort`: read and update kill-switch state.

### Infrastructure Adapters

Concrete implementations live at the edge:

- `brokers/ibkr`: IBKR TWS or IB Gateway adapter.
- `brokers/tradestation`: future adapter.
- `brokers/ninjatrader`: future adapter.
- `brokers/optimus`: future route-specific adapters.
- `storage`: file, SQLite, or Postgres repositories.
- `ops`: logging, metrics, alerts, and secrets loading.

## Data Flow

1. Operator starts the service with a broker configuration.
2. System loads instrument metadata and risk limits.
3. Broker adapter connects to the configured real broker environment.
4. Reconciliation runs before order submission is enabled.
5. Strategy or operator creates an `OrderIntent`.
6. Risk engine evaluates the intent against account, position, market data, and instrument state.
7. Approved intents become broker orders.
8. Broker adapter submits orders and streams acknowledgements and fills.
9. Audit log records every decision, request, response, reject, fill, and operator action.
10. Reconciliation periodically compares internal state with broker state and blocks trading on mismatch.

## Risk Rules

Trading is blocked when any of these conditions are true:

- kill switch is active
- account snapshot is missing or stale
- market data is missing or stale
- instrument metadata is incomplete
- order quantity exceeds configured max
- resulting position exceeds configured max
- estimated margin usage exceeds configured limit
- limit price violates configured collar
- contract is past its last safe trade date
- order client ID was already used
- broker positions and internal positions are unreconciled

Every reject includes a stable reason code and human-readable detail.

## Configuration

Configuration is explicit and environment based:

- `BROKER=ibkr`
- `BROKER_ENV=paper` or `live`
- `IBKR_HOST`
- `IBKR_PORT`
- `IBKR_CLIENT_ID`
- `TRADING_ENABLED=false` by default
- `MAX_MARGIN_USAGE`
- `MAX_DAILY_LOSS`
- `ORDER_STALE_AFTER_SECONDS`
- `MARKET_DATA_STALE_AFTER_SECONDS`

Secrets are never committed. The project uses local `.env` files only through ignored paths.

## Testing

Development follows test-driven development for new behavior.

Initial tests cover:

- tick value and tick rounding
- contract expiration and delivery cutoff blocking
- stale market data rejection
- kill switch rejection
- max quantity and max position rejection
- margin usage rejection
- duplicate client order ID rejection
- price collar rejection
- reconciliation mismatch blocks trading
- broker adapter contract using fake in-memory broker objects only where needed to exercise the port

The first build is complete only when these tests pass locally.

## Operational Safety

The bot starts with trading disabled. Operators must explicitly enable trading after:

- broker connection succeeds
- account snapshot is fresh
- market data is fresh
- instrument metadata is loaded
- positions reconcile
- kill switch is inactive

The system must provide a `flatten` command, but it also runs through risk controls that prevent sending malformed or duplicate orders. If normal order submission is unavailable, the operator must use the broker's native interface.

## Strategy Roadmap

The first tradable strategy should be diversified trend following with volatility targeting. It is intentionally not part of the first build slice because the execution and risk foundation must exist first.

Later strategy modules can include:

- time-series momentum across liquid futures
- carry and curve signals
- calendar-spread strategies
- execution timing models
- regime and volatility filters

No strategy may bypass the same broker, risk, audit, and reconciliation path.

## Acceptance Criteria

The first build slice is accepted when:

- the project has a runnable Python package
- domain and risk tests pass
- broker port is implemented
- IBKR adapter skeleton loads configuration and validates connection settings
- no strategy can submit orders before reconciliation and risk checks pass
- CLI exposes operational commands without requiring code edits
- audit events are written for every risk decision and order lifecycle event
- README explains setup, environment variables, and current limitations

## Self-Review

- No placeholder requirements remain.
- The first implementation scope is intentionally limited to core, risk, operations, and the IBKR skeleton.
- Paper and live behavior are modeled as real broker environments, not fake demo infrastructure.
- The design does not imply profitability or regulatory compliance.
- Broker-specific SDKs are isolated at the infrastructure edge.
