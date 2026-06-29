# Futures Bot Context

This project builds a live-capable futures trading bot. Paper trading is treated as a real broker environment because broker paper routes still use broker connectivity, account state, permissions, and exchange/product metadata.

## Domain Terms

- **Broker Route**: The configured broker adapter bundle for one broker name. A route exposes explicit capabilities for execution, margin estimation, and historical data instead of relying on callers to probe methods.
- **Execution Adapter**: The broker adapter capability that connects, reads account and positions, submits approved orders, and cancels orders.
- **Margin Estimator**: The broker adapter capability that estimates order margin impact without submitting a live order. If a broker cannot provide a verified estimate, it must fail closed.
- **Historical Data Adapter**: The broker adapter capability that returns verified normalized daily bars. If data is absent, malformed, stale, or unsupported, it must fail closed.
- **Historical Bar**: One normalized OHLCV daily record for one futures instrument. Prices must be positive, OHLC relationships must be valid, and volume must be absent or integral.
- **Historical Signal Input**: A strategy-ready sequence of `PricePoint` values produced from fetched, validated, cached, and optionally back-adjusted futures contract histories.
- **Self-Match Guard**: A pre-trade risk control that blocks an incoming order when it could execute against a known working opposite-side order from the same bot/account context on the same instrument.
- **Instrument Catalog**: Operator-supplied contract metadata, including exchange, contract month, multiplier, tick size, settlement type, and safe trading calendar dates.
- **Margin Schedule**: Operator-supplied fallback margin data used only when broker-provided margin estimates are unavailable and explicitly routed through the margin schedule provider.
- **Rebalance Phase**: A step in the live rebalance workflow that must receive risk context, kill-switch status, broker state, margin data, and audit logging before order submission.
- **Live Trading Activation**: A runtime operator token required before a command may submit orders while `BROKER_ENV=live`. Broker credentials and command-specific confirmations are not sufficient by themselves.

## Operating Invariants

- No adapter may fake a broker response for production paths.
- Paper mode is not demo mode. It must use real broker connectivity and credentials for that broker's paper environment.
- Live mode order submission requires an explicit runtime live-trading activation in addition to credentials and command-specific confirmations.
- Strategy code must not bypass broker routes, risk checks, kill switch checks, audit logging, reconciliation, or order lifecycle persistence.
- Risk checks should prevent avoidable self-trading before a broker or exchange-level self-match prevention setting has to intervene.
- Historical data absence is a data-quality failure unless a caller explicitly introduces a separate, reviewed sparse-history workflow.
