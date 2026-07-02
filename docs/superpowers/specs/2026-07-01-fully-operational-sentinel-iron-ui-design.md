# Fully Operational Sentinel Iron UI Design

## Goal

Make the backend-wired Sentinel Iron UI fully operational at the level of every visible control while preserving the existing Sentinel Iron safety boundary. The UI must remain an operator console, not a casual live trading terminal.

## Scope

In scope:

- Every visible button, segmented control, selector, modal action, keyboard shortcut, export control, widget control, and navigation rail item has deterministic behavior.
- Backend actions continue to call the guarded local API routes in `sentinel_iron.ui_server`.
- The UI exposes busy, success, failure, and disabled states for backend actions.
- Chart, heatmap, navigation, and settings controls update the rendered UI state instead of acting as static decoration.
- Prototype wording is replaced with accurate backend-wired operator-console wording.
- Tests cover server action behavior and browser-level control operation.

Out of scope:

- Normal buy/sell order tickets.
- Strategy-driven live order loops.
- Any bypass of `FLATTEN-LIVE-POSITIONS`.
- Any bypass of live-mode activation requirements.
- Remote binding by default.

## Safety Boundary

The UI must keep Sentinel Iron's current order-submission model intact. Emergency flatten remains the only live-capable operator order-submission surface exposed by the UI. It must require the exact `FLATTEN-LIVE-POSITIONS` confirmation text, and when `BROKER_ENV=live`, the UI must pass the live activation token through the existing CLI path instead of creating a separate broker path.

All other operational controls either read local state, validate local files, connect to a broker for account-state checks, reconcile positions, or operate the kill switch through existing CLI commands.

## Functional Design

### Backend Actions

The live action bar contains Connect, Validate, and Reconcile controls. Each action sends a guarded API request with `X-Sentinel-Iron-Action-Token`, disables action buttons while running, shows a clear toast for success or failure, and applies any returned snapshot.

The Validate action runs catalog validation and margin-schedule validation as separate backend calls, then reports both outcomes. If either validation fails, the UI reports the failed command and leaves the dashboard usable.

The Kill Switch modal activates the kill switch only with a non-empty reason. Clear requires exact `CLEAR-KILL-SWITCH` confirmation. Both routes refresh snapshot state after completion.

The Emergency Flatten modal submits only through `/api/actions/flatten`, using the selected broker route, required confirmation text, and optional live activation token.

### Navigation Rail

Rail buttons become view filters:

- Ops shows all cards.
- Market emphasizes market map, ladder, heatmap, and positions.
- Risk emphasizes readiness, risk, margin, kill-switch status, and rebalance.
- Catalog emphasizes positions, margin schedules, routes, and validation context.
- Routes emphasizes broker route matrix and backend action state.
- Audit emphasizes audit stream and lifecycle-related cards.

The active rail item is visually selected, non-matching cards are hidden, and returning to Ops restores all cards.

### Chart Controls

The chart timeframe segmented control updates active state and chart labeling. The instrument selector chooses the rendered instrument when historical bars exist for that instrument. If no live historical bars exist, it still updates the selected label and keeps fallback data deterministic.

The heatmap mode segmented control switches between volume, margin, and exposure rendering modes, updates active state, updates legend/labels, and redraws the canvas.

### Utility Controls

Existing visual utility controls remain but must be verified:

- Settings open/close and backdrop close.
- Theme rail and settings theme buttons update `data-theme`.
- Density buttons update active state and body font size.
- Glow slider updates the CSS glow variable and label.
- Widget checkboxes hide/show cards.
- Edit mode enables visible drag/remove affordances.
- Remove hides the card and unchecks the matching setting.
- Collapse, fullscreen, float, popout, and export perform the advertised UI operation.
- Keyboard shortcuts continue to map to edit, settings, flatten, kill-switch, refresh/redraw, and close.

### Copy

Remove text that describes backend-wired flows as prototypes or previews. Keep explicit safety text for emergency flatten, kill switch behavior, and live activation.

## Testing Design

Add focused Python tests for `sentinel_iron.ui_server`:

- Action routes reject missing or invalid action tokens.
- Kill-switch activation and clear enforce required inputs.
- Flatten enforces exact confirmation.
- Snapshot and action results are shaped consistently enough for the UI adapter.

Add a browser-level control sweep using Playwright:

- Load the local UI.
- Assert no page or console errors.
- Click safe controls and verify expected DOM state transitions.
- Exercise segmented controls, rail filters, settings controls, modal open/close, collapse/fullscreen/float/export, and action-button error states with missing local config.

The final verification command set is:

- `python -m py_compile src/sentinel_iron/ui_server.py`
- `node --check` for each inline script block in `src/sentinel_iron/ui_assets/index.html`
- `python -m pytest tests -v`
- A Playwright sweep against `http://127.0.0.1:8765`

## Acceptance Criteria

- No visible safe UI control is inert.
- Backend action controls are guarded, show state, and refresh snapshots.
- Chart, heatmap, and rail controls visibly affect the UI.
- Safety boundary remains unchanged.
- Browser sweep reports no console errors or page errors.
- Full Python test suite passes.
