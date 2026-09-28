# Sentinel Iron Futures Operations Console — backend wiring

This patch adds a local, dependency-free web server for the Sentinel Iron futures bot UI.

It is designed for the existing Sentinel Iron safety model:

- read-only dashboard panels poll local Sentinel Iron JSON/JSONL state files;
- broker connect and reconciliation call the existing Sentinel Iron CLI commands;
- kill-switch activation and clearing call the existing kill-switch command;
- emergency flatten calls the existing explicit `flatten` command and still requires `FLATTEN-LIVE-POSITIONS`;
- when `BROKER_ENV=live`, the backend still requires the live activation token before broker route construction.

The UI does not add normal strategy buy/sell buttons or a casual order ticket.

## Files added

```text
src/sentinel_iron/ui_server.py
src/sentinel_iron/ui_assets/index.html
scripts/run-sentinel-iron-ui.ps1
docs/SENTINEL_IRON_UI_BACKEND.md
```

## Install into the bot repo

From PowerShell:

```powershell
cd C:\Users\automation\GitBots\Sentinel-Iron
Expand-Archive -Path C:\path\to\sentinel_iron_ui_backend_patch.zip -DestinationPath . -Force
python -m pip install -e ".[dev]"
```

## Start the UI

```powershell
cd C:\Users\automation\GitBots\Sentinel-Iron
python -m sentinel_iron.ui_server --host 127.0.0.1 --port 8765 --repo-root .
```

Then open:

```text
http://127.0.0.1:8765
```

Or run:

```powershell
.\scripts\run-sentinel-iron-ui.ps1
```

## Backend files the UI reads

The server resolves these from the repo root unless the corresponding environment variable is set:

| UI field | Environment variable | Default |
|---|---|---|
| Audit stream | `AUDIT_LOG_PATH` | `data/audit.jsonl` |
| Kill switch | `KILL_SWITCH_STATE_PATH` | `data/kill_switch.json` |
| Internal positions | `INTERNAL_POSITIONS_PATH` | `data/internal_positions.json` |
| Instrument catalog | `INSTRUMENT_CATALOG_PATH` | `data/instruments.json` |
| Margin schedules | `MARGIN_SCHEDULE_PATH` | `data/margin_schedules.json` |
| Historical bars | `HISTORICAL_BARS_PATH` | `data/historical_bars.json` |
| Order activity | `ORDER_ACTIVITY_PATH` | `data/order_activity.jsonl` |
| Order lifecycle | `ORDER_LIFECYCLE_PATH` | `data/order_lifecycles.jsonl` |
| Processed fills | `PROCESSED_FILLS_PATH` | `data/processed_fills.jsonl` |

## API routes

Read-only:

```text
GET /api/health
GET /api/snapshot
```

Guarded actions:

```text
POST /api/actions/broker-connect
POST /api/actions/reconcile
POST /api/actions/validate-catalog
POST /api/actions/validate-margin-schedules
POST /api/actions/kill-switch/activate
POST /api/actions/kill-switch/clear
POST /api/actions/flatten
```

The served page receives an in-memory action token and sends it as `X-Sentinel-Iron-Action-Token` for state-changing routes. The server binds to `127.0.0.1` by default and refuses non-loopback hosts unless `--allow-remote` is passed.

## Live-mode note

The UI does not weaken Sentinel Iron's live gate. In `BROKER_ENV=live`, emergency flatten still requires:

```text
FLATTEN-LIVE-POSITIONS
ENABLE-LIVE-TRADING
```

The second token is entered in the live activation field in the flatten modal.
