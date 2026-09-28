# Fully Operational Sentinel Iron UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every visible Sentinel Iron UI control deterministic and operational while preserving the existing emergency-flatten-only live order safety boundary.

**Architecture:** Keep the Python UI server as the guarded local API boundary and keep the HTML asset dependency-free. Add focused server tests for action safety, then update the frontend adapter and local UI script so controls update real UI state, submit guarded backend actions, and report status clearly.

**Tech Stack:** Python 3.11, `http.server`, Sentinel Iron CLI entrypoint, pytest, vanilla HTML/CSS/JavaScript, Playwright browser checks.

---

## File Structure

- Modify `src/sentinel_iron/ui_server.py`: small backend route improvements only if tests expose missing behavior.
- Modify `src/sentinel_iron/ui_assets/index.html`: frontend control behavior, copy, and browser-test hooks.
- Create `tests/test_ui_server.py`: focused unit/integration tests for guarded API behavior without running a long-lived server.
- Create `work/verify_sentinel_iron_ui.py`: local Playwright sweep script for manual verification. Keep under `work/` so it is not product code.
- Modify `docs/SENTINEL_IRON_UI_BACKEND.md`: update docs if behavior or wording changes.

## Task 1: Backend Action Safety Tests

**Files:**
- Create: `tests/test_ui_server.py`
- Modify if needed: `src/sentinel_iron/ui_server.py`

- [ ] **Step 1: Write failing tests for token and confirmation enforcement**

Create `tests/test_ui_server.py` with:

```python
from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from sentinel_iron.ui_server import (
    ACTION_HEADER,
    CLEAR_KILL_SWITCH_CONFIRMATION,
    FLATTEN_CONFIRMATION,
    SentinelIronUiHandler,
    SentinelIronUiServer,
    ServerConfig,
)


@contextmanager
def running_ui_server(tmp_path: Path, token: str = "test-token") -> Iterator[str]:
    asset_dir = tmp_path / "assets"
    asset_dir.mkdir()
    (asset_dir / "index.html").write_text(
        "<!doctype html><script>window.SENTINEL_IRON_UI_CONFIG={actionToken:'__SENTINEL_IRON_UI_ACTION_TOKEN__',pollMs:Number('__SENTINEL_IRON_UI_POLL_MS__')};</script>",
        encoding="utf-8",
    )
    config = ServerConfig(
        repo_root=tmp_path,
        host="127.0.0.1",
        port=0,
        action_token=token,
        asset_dir=asset_dir,
        poll_hint_ms=1000,
        allow_remote=False,
    )
    server = SentinelIronUiServer(("127.0.0.1", 0), SentinelIronUiHandler)
    server.config = config
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def post_json(base_url: str, path: str, body: dict[str, object], token: str | None = "test-token") -> dict[str, object]:
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers[ACTION_HEADER] = token
    request = Request(
        f"{base_url}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(base_url: str, path: str) -> dict[str, object]:
    with urlopen(f"{base_url}{path}", timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def test_action_routes_reject_missing_action_token(tmp_path: Path) -> None:
    with running_ui_server(tmp_path) as base_url:
        with pytest.raises(HTTPError) as exc:
            post_json(base_url, "/api/actions/kill-switch/activate", {"reason": "operator halt"}, token=None)

    assert exc.value.code == 403
    body = json.loads(exc.value.read().decode("utf-8"))
    assert body["ok"] is False
    assert ACTION_HEADER in body["error"]


def test_kill_switch_clear_requires_exact_confirmation(tmp_path: Path) -> None:
    with running_ui_server(tmp_path) as base_url:
        with pytest.raises(HTTPError) as exc:
            post_json(base_url, "/api/actions/kill-switch/clear", {"broker": "tradestation", "confirm": "clear"})

    assert exc.value.code == 400
    body = json.loads(exc.value.read().decode("utf-8"))
    assert body["ok"] is False
    assert CLEAR_KILL_SWITCH_CONFIRMATION in body["error"]


def test_flatten_requires_exact_confirmation(tmp_path: Path) -> None:
    with running_ui_server(tmp_path) as base_url:
        with pytest.raises(HTTPError) as exc:
            post_json(base_url, "/api/actions/flatten", {"broker": "tradestation", "confirm": "flatten"})

    assert exc.value.code == 400
    body = json.loads(exc.value.read().decode("utf-8"))
    assert body["ok"] is False
    assert FLATTEN_CONFIRMATION in body["error"]


def test_snapshot_and_served_html_are_ui_ready(tmp_path: Path) -> None:
    with running_ui_server(tmp_path) as base_url:
        health = get_json(base_url, "/api/health")
        snapshot = get_json(base_url, "/api/snapshot?config=0")
        with urlopen(f"{base_url}/", timeout=5) as response:
            html = response.read().decode("utf-8")

    assert health["ok"] is True
    assert snapshot["ok"] is True
    assert snapshot["paths"]["audit_log"].endswith("data/audit.jsonl")
    assert "__SENTINEL_IRON_UI_ACTION_TOKEN__" not in html
    assert "test-token" in html
```

- [ ] **Step 2: Run the new tests to verify failures or current coverage**

Run: `python -m pytest tests/test_ui_server.py -v`

Expected before implementation: at least one failure if route behavior or response shaping is incomplete. If all pass, keep the tests as regression coverage and continue.

- [ ] **Step 3: Make minimal server adjustments only if tests fail**

If the tests expose a backend issue, adjust `src/sentinel_iron/ui_server.py` only around the failing route. Example for preserving JSON error shape:

```python
except ValueError as exc:
    self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
```

- [ ] **Step 4: Run backend UI tests**

Run: `python -m pytest tests/test_ui_server.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit backend safety test work**

```bash
git add tests/test_ui_server.py src/sentinel_iron/ui_server.py
git commit -m "test: cover Sentinel Iron UI action safety"
```

## Task 2: Rail, Chart, Heatmap, and Utility Controls

**Files:**
- Modify: `src/sentinel_iron/ui_assets/index.html`

- [ ] **Step 1: Write a browser check that currently fails on inert controls**

Create `work/verify_sentinel_iron_ui.py` with this initial check:

```python
from __future__ import annotations

from playwright.sync_api import sync_playwright


URL = "http://127.0.0.1:8765"


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors: list[str] = []
        page.on("console", lambda msg: errors.append(f"{msg.type}: {msg.text}") if msg.type in {"error", "warning"} else None)
        page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
        page.goto(URL)
        page.wait_for_load_state("load")

        page.get_by_text("Market", exact=True).click()
        active_rail = page.evaluate("document.querySelector('.rail-item.active')?.innerText")
        hidden_after_market = page.evaluate("[...document.querySelectorAll('.card.hidden')].length")
        assert active_rail == "MARKET"
        assert hidden_after_market > 0

        page.locator("[data-id='marketMap'] .seg button", has_text="15m").click()
        active_chart = page.evaluate("[...document.querySelectorAll('[data-id=\"marketMap\"] .seg button')].find(b => b.classList.contains('active'))?.innerText")
        assert active_chart == "15m"

        page.locator("[data-id='heatmap'] .seg button", has_text="Margin").click()
        active_heat = page.evaluate("[...document.querySelectorAll('[data-id=\"heatmap\"] .seg button')].find(b => b.classList.contains('active'))?.innerText")
        assert active_heat == "Margin"

        assert errors == []
        browser.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the browser check and verify it fails for current inert controls**

Run: `python work/verify_sentinel_iron_ui.py`

Expected: failure on rail active state or chart/heatmap active state.

- [ ] **Step 3: Add control state and rail filtering to `index.html`**

Inside the first script block, add a shared UI state object and rail map near existing constants:

```javascript
const uiState = {
  chartFrame: '5m',
  heatMode: 'Volume',
  selectedInstrument: 'ESU26 CME',
  activeView: 'ops'
};
const railViews = {
  ops: ['marketMap','readiness','ladder','risk','routes','heatmap','rebalance','positions','margin','audit'],
  market: ['marketMap','ladder','heatmap','positions'],
  risk: ['readiness','risk','margin','rebalance','audit'],
  catalog: ['positions','margin','routes','heatmap'],
  routes: ['routes','readiness','audit'],
  audit: ['audit','rebalance','risk']
};
```

Add functions before `initInteractions()`:

```javascript
function setActiveButton(container, button){
  $$('button', container).forEach(b=>b.classList.remove('active'));
  button.classList.add('active');
}
function setRailView(view, button){
  uiState.activeView = view;
  $$('.rail-item').forEach(b=>b.classList.remove('active'));
  button.classList.add('active');
  const visible = new Set(railViews[view] || railViews.ops);
  $$('.card[data-id]').forEach(card=>card.classList.toggle('hidden', !visible.has(card.dataset.id)));
  $$('[data-widget]').forEach(cb=>{
    const card = $(`[data-id="${cb.dataset.widget}"]`);
    if(card) cb.checked = !card.classList.contains('hidden');
  });
  setTimeout(redrawAll, 80);
}
function setChartFrame(button){
  setActiveButton(button.closest('.seg'), button);
  uiState.chartFrame = button.textContent.trim();
  const sub = $('[data-id="marketMap"] .sub');
  if(sub) sub.textContent = `${uiState.selectedInstrument} · ${uiState.chartFrame} · collar + roll markers`;
  redrawAll();
}
function setHeatMode(button){
  setActiveButton(button.closest('.seg'), button);
  uiState.heatMode = button.textContent.trim();
  const sub = $('[data-id="heatmap"] .sub');
  if(sub) sub.textContent = `${uiState.heatMode.toLowerCase()} mode`;
  drawHeat();
}
function setChartInstrument(select){
  uiState.selectedInstrument = select.value;
  const sub = $('[data-id="marketMap"] .sub');
  if(sub) sub.textContent = `${uiState.selectedInstrument} · ${uiState.chartFrame} · collar + roll markers`;
  redrawAll();
}
```

Wire them in `initInteractions()`:

```javascript
$$('.rail-item[data-view]').forEach(btn=>btn.addEventListener('click',()=>setRailView(btn.dataset.view, btn)));
$$('[data-chart-frame]').forEach(btn=>btn.addEventListener('click',()=>setChartFrame(btn)));
$$('[data-heat-mode]').forEach(btn=>btn.addEventListener('click',()=>setHeatMode(btn)));
$('#chartInstrumentSelect')?.addEventListener('change',e=>setChartInstrument(e.target));
```

Add stable attributes to the markup:

```html
<button class="rail-item active" type="button" data-view="ops">...</button>
<button class="rail-item" type="button" data-view="market">...</button>
<button class="rail-item" type="button" data-view="risk">...</button>
<button class="rail-item" type="button" data-view="catalog">...</button>
<button class="rail-item" type="button" data-view="routes">...</button>
<button class="rail-item" type="button" data-view="audit">...</button>
<button class="active" data-chart-frame="5m">5m</button>
<button data-chart-frame="15m">15m</button>
<button data-chart-frame="1h">1h</button>
<button data-chart-frame="1D">1D</button>
<select class="select-chip" id="chartInstrumentSelect">...</select>
<button class="active" data-heat-mode="Volume">Volume</button>
<button data-heat-mode="Margin">Margin</button>
<button data-heat-mode="Exposure">Exposure</button>
```

- [ ] **Step 4: Run the browser check**

Run: `python work/verify_sentinel_iron_ui.py`

Expected: the rail, chart, and heatmap assertions pass with no console errors.

- [ ] **Step 5: Commit frontend control behavior**

```bash
git add src/sentinel_iron/ui_assets/index.html work/verify_sentinel_iron_ui.py
git commit -m "feat: make Sentinel Iron UI controls operational"
```

## Task 3: Backend Action States and Copy Cleanup

**Files:**
- Modify: `src/sentinel_iron/ui_assets/index.html`
- Modify: `docs/SENTINEL_IRON_UI_BACKEND.md`

- [ ] **Step 1: Extend browser check for backend action state and copy**

Append these checks to `work/verify_sentinel_iron_ui.py` before `assert errors == []`:

```python
        body_text = page.locator("body").inner_text()
        assert "Prototype preview" not in body_text
        assert "prototype mirrors" not in body_text.lower()

        page.locator("#liveConnectBtn").click()
        page.wait_for_selector("#liveToast.open")
        toast_text = page.locator("#liveToast").inner_text()
        assert "broker-connect" in toast_text or "config" in toast_text.lower() or "missing" in toast_text.lower()
        disabled_count = page.evaluate("[...document.querySelectorAll('#liveActionBar button')].filter(b => b.disabled).length")
        assert disabled_count == 0
```

- [ ] **Step 2: Run the browser check and verify it fails on copy or action state**

Run: `python work/verify_sentinel_iron_ui.py`

Expected: failure if prototype wording remains or action state is incomplete.

- [ ] **Step 3: Add action busy state helper**

In the backend adapter script in `index.html`, add:

```javascript
function setActionBusy(isBusy){
  $$('#liveActionBar button, #confirmFlatten, #confirmKill, #clearKillSwitchBtn').forEach(btn=>{
    if(!btn) return;
    btn.dataset.wasDisabled = btn.disabled ? '1' : '0';
    btn.disabled = isBusy || btn.dataset.wasDisabled === '1';
    btn.classList.toggle('loading', isBusy);
  });
}
```

Then wrap `sendAction`:

```javascript
async function sendAction(path, payload){
  setActionBusy(true);
  toast('Submitting backend action...', 'warn', 0);
  try{
    const result = await api(path, {method:'POST', body:JSON.stringify(payload || {})});
    const out = result?.cli?.stdout || result?.cli?.stderr || 'Action completed.';
    toast(`<b>${esc(result.action || 'action')}</b><br>${esc(out)}`, result.ok ? 'good' : 'bad', 7200);
    if(result.snapshot) applySnapshot(result.snapshot); else schedulePoll(200);
    return result;
  }finally{
    setActionBusy(false);
  }
}
```

If the `dataset.wasDisabled` logic keeps confirmation buttons disabled after input changes, replace it with explicit selectors:

```javascript
function setActionBusy(isBusy){
  $$('#liveActionBar button, #clearKillSwitchBtn').forEach(btn=>{ btn.disabled = isBusy; btn.classList.toggle('loading', isBusy); });
  const flatten = $('#confirmFlatten');
  if(flatten) flatten.disabled = isBusy || $('#flattenInput').value.trim() !== FLATTEN_CONFIRMATION;
  const kill = $('#confirmKill');
  if(kill) kill.disabled = isBusy || $('#killInput').value.trim().length < 8;
}
```

- [ ] **Step 4: Replace prototype copy**

Change modal text in `index.html`:

```html
<p>This backend-wired operator flow submits Sentinel Iron's explicit emergency flatten command. In live mode, it requires the exact command confirmation plus the runtime live-trading activation token before broker route construction. Normal strategy order entry is not exposed here.</p>
<p>Type <b>FLATTEN-LIVE-POSITIONS</b> to submit an emergency flatten request through the guarded backend route.</p>
```

Change click fallback messages:

```javascript
$('#confirmFlatten').addEventListener('click',()=>{renderAudit([new Date().toTimeString().slice(0,8),'position_flatten_requested','Emergency flatten request submitted through the guarded backend route.','warn']); closeModals();});
$('#confirmKill').addEventListener('click',()=>{renderAudit([new Date().toTimeString().slice(0,8),'kill_switch_requested','Kill switch activation submitted through the guarded backend route.','bad']); closeModals();});
```

Update `docs/SENTINEL_IRON_UI_BACKEND.md` only if wording still calls the backend UI a prototype.

- [ ] **Step 5: Run browser check**

Run: `python work/verify_sentinel_iron_ui.py`

Expected: no copy or action-state assertion failures.

- [ ] **Step 6: Commit action-state and copy cleanup**

```bash
git add src/sentinel_iron/ui_assets/index.html docs/SENTINEL_IRON_UI_BACKEND.md work/verify_sentinel_iron_ui.py
git commit -m "feat: add Sentinel Iron UI action states"
```

## Task 4: Final Verification

**Files:**
- Modify only if verification exposes a defect: `src/sentinel_iron/ui_assets/index.html`, `src/sentinel_iron/ui_server.py`, `tests/test_ui_server.py`, `docs/SENTINEL_IRON_UI_BACKEND.md`

- [ ] **Step 1: Run Python syntax check**

Run: `python -m py_compile src\sentinel_iron\ui_server.py`

Expected: exit code 0.

- [ ] **Step 2: Run JavaScript syntax check**

Run:

```powershell
$html = Get-Content -Raw 'src\sentinel_iron\ui_assets\index.html'
$matches = [regex]::Matches($html, '(?s)<script(?:\s[^>]*)?>(.*?)</script>')
$tmp = 'work\jscheck-final'
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
$i=0
foreach ($m in $matches) {
  $i++
  $path = Join-Path $tmp "script-$i.js"
  Set-Content -LiteralPath $path -Value $m.Groups[1].Value -Encoding UTF8
  node --check $path
}
Write-Host "Checked $i script blocks"
```

Expected: `Checked 3 script blocks`.

- [ ] **Step 3: Run focused UI server tests**

Run: `python -m pytest tests/test_ui_server.py -v`

Expected: all tests pass.

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest tests -v`

Expected: all tests pass.

- [ ] **Step 5: Ensure local UI server is running**

Run:

```powershell
if (-not (Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)) {
  Start-Process -FilePath 'python' -ArgumentList @('-m','sentinel_iron.ui_server','--host','127.0.0.1','--port','8765','--repo-root','.') -WorkingDirectory (Get-Location) -WindowStyle Hidden
}
```

Expected: `http://127.0.0.1:8765/api/health` returns `ok: true`.

- [ ] **Step 6: Run Playwright sweep**

Run: `python work/verify_sentinel_iron_ui.py`

Expected: exit code 0, no console errors, no page errors.

- [ ] **Step 7: Check git status and final diff**

Run: `git status --short`

Expected: only intended UI, server test, docs, and optional work verification script changes are present.

- [ ] **Step 8: Final commit**

```bash
git add src/sentinel_iron/ui_assets/index.html src/sentinel_iron/ui_server.py tests/test_ui_server.py docs/SENTINEL_IRON_UI_BACKEND.md work/verify_sentinel_iron_ui.py
git commit -m "feat: complete Sentinel Iron UI operations"
```

If the user did not request commits for implementation changes, skip the final commit and report the ready working-tree changes instead.

## Self-Review Notes

- Spec coverage: backend actions, rail filters, chart controls, utility controls, copy cleanup, safety boundary, and verification are each covered by a task.
- Placeholder scan: no `TBD`, `TODO`, or unspecified implementation steps are intentionally left.
- Type consistency: tests import existing names from `sentinel_iron.ui_server`; frontend functions use existing `$`, `$$`, `redrawAll`, `drawHeat`, and DOM structure.
