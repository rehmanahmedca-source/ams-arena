# Deep Audit — Background API Polling, Duplicate Requests, Performance & UI Freeze

Date: 2026-08-15 · Scope: Sales section (`/direct_sales`, `/material_returns`), the
client side-panel widgets and the global `layout.html` page shell.

All fixes are on the working branch `arena/01a00546-ams-arena`. Regression suite:
**91 tests passing** (including a new sales round-trip suite), plus a JS syntax
check of the rendered pages and a scoped-vs-full ledger parity test.

---

## Finding 1 — What generates `/api/notifications/due`

| Level | Value |
| --- | --- |
| Endpoint | `GET /api/notifications/due` (`app/blueprints/api.py` → `api_notifications_due`) |
| File | `templates/layout.html` |
| Function | `checkDueRemindersGlobal()` |
| Timer | `setInterval(checkDueRemindersGlobal, 15000)` + one `setTimeout(..., 1200)` at page load |
| Condition | Runs on **every authenticated page** (the block is inside `{% if current_user.is_authenticated %}`) |

This is the *intended* global deadline-reminder poll. It is not component-scoped:
it lives in the base layout, so every tab creates its own 15-second interval.
That is exactly why the logs show back-to-back `/api/notifications/due` entries —
they are **multiple open tabs each polling**, not one tab with two loops. (There
is no second loop in a single page; the interval is registered once per page
load.)

The endpoint itself also performs a small **write** (`FollowUpReminder.alerted_at`
update + commit) whenever due rows exist, so duplicate polls from multiple tabs
also multiplied write traffic and could contend with the financial-summary reads.

### Fix applied
- **Visibility gate** — hidden tabs stop polling (`document.visibilityState !== 'visible'`).
- **In-flight guard** — a single `dueCheckInFlight` latch prevents overlapping calls.
- **Cross-tab leader election** — a `localStorage` heartbeat (`ams_due_poll_leader`)
  elects one visible tab as the single poller; the election self-heals via TTL
  when the leader tab closes or is backgrounded.
- The reminder modal/alarm behavior is **unchanged** — reminders still appear.

---

## Finding 2 — What generates `/api/client_booking_status/…` and `/api/client_financial_summary/…`

Both are fetched by the Direct Sales side panel in `templates/direct_sales.html`:

| Endpoint | File → Function | Trigger |
| --- | --- | --- |
| `/api/client_booking_status/<code>` | `direct_sales.html` → `updateBookingStatus()` | client pick, input `change`, and `refreshDirectSaleClientWidgets()` |
| `/api/client_financial_summary/<code>` | `direct_sales.html` → `updateClientFinancialSummary()` | called from `updateBookingStatus()` and the payments page |

`refreshDirectSaleClientWidgets()` is registered on the **global**
`pware:financial-refresh` custom event:

```text
direct_sales.html
    document.addEventListener('pware:financial-refresh', refreshDirectSaleClientWidgets)
        → refreshDirectSaleClientWidgets()
            → reads input[name=client_code] in the Add Sale form  ← RAW value
            → updateBookingStatus(code) → booking + financial fetches
```

`pware:financial-refresh` is dispatched from `templates/layout.html`
`dispatchFinancialRefresh()` by **four** triggers:

1. `window focus` — every time the window regains focus.
2. `visibilitychange` (tab becomes visible).
3. after a transaction save / when a success alert is present.
4. **`setInterval(dispatchFinancialRefresh, 30000)` — an unconditional 30-second
   timer on every page.** ← the idle/background culprit.

Because trigger 4 fired even when nobody touched the app, the currently selected
client (`FBMCL-00303` in the logs) kept getting re-fetched every 30 seconds while
idle. Worse, the handler read the **raw input text**, so a half-typed search
(`paf`) was also sent to the server (`/api/client_booking_status/paf`).

The `payments` page has a second `pware:financial-refresh` listener
(`templates/payments.html` → `refreshPaymentsWidgets()` → `loadAddClientBalance()`),
which fetched `/api/client_financial_summary/<input>` on the same global timer.

### Fix applied
- **Removed the unconditional 30-second timer.** Financial widgets now refresh only
  on real activity: window focus, tab becoming visible, and after a transaction
  save.
- **`refreshDirectSaleClientWidgets()` now bails out** unless the input is a
  *fully known* client code/name — partial/unknown text is never sent.
- **Coalescing** of identical in-flight requests (see Finding 3).

---

## Finding 3 — Why duplicate requests occur

Three independent causes, all addressed at the source:

1. **Double-fire on client pick.** Picking a client in the Add Sale form fires
   *two* `updateBookingStatus()` calls: once from the combobox `data-after`
   hook (`onSaleClientPicked`) and once from the input `change` listener
   (`addSaleClientCodeEl`). → two `/api/client_booking_status/…` + two
   `/api/client_financial_summary/…` per pick.
2. **Multiple dispatch triggers.** The 30s timer, window focus and
   visibilitychange could all fire in quick succession (e.g. returning to the
   tab), each triggering the widget refresh.
3. **Multiple tabs.** `layout.html` polling is per-tab, so N open tabs produced
   N requests (most visible on `/api/notifications/due`).

### Fix applied
- **In-flight coalescing maps** in `direct_sales.html`
  (`bookingStatusInflight`, `financialSummaryInflight`) keyed by
  `client + container`. A duplicate concurrent request for the same target
  returns the same promise instead of issuing a second network call. This is
  request coalescing of identical in-flight calls, not blind throttling.
- Removed the 30s timer (Finding 2) and added the cross-tab leader election for
  notifications (Finding 1).

---

## Finding 4 — Why `/api/client_financial_summary` is sometimes 2.7–3.0 s

`app/blueprints/api.py` → `api_client_financial_summary()` called:

```python
unified_ledger = build_client_financial_ledger(client)
```

`build_client_financial_ledger()` (with no snapshot argument) internally calls
`_client_snapshot()` in `app/services/financial_ledgers.py`, which loads
**every client's** bookings, sales, payments, pending bills, waive-offs and
booking-cancellation entries into memory — just to compute **one** client's
summary. That is a full-table hydration pass per request and grows with total
database size.

The 2.7–3.0 s first-request figures are amplified by two additional factors:
- First-request **WAL/PRAGMA setup + cold page cache** (the app sets
  `PRAGMA journal_mode=WAL` / `busy_timeout` once).
- **SQLite write/read contention**: the duplicate `/api/notifications/due`
  commits and duplicated financial-summary reads serialize behind one another.

Later requests (~300–400 ms) reflect the remaining full-snapshot cost once warm.

### Fix applied
Added `_client_snapshot_for(client)` in `app/services/financial_ledgers.py` — a
**single-client scoped snapshot** that produces the identical structure but only
loads rows that can belong to that client (id/code/name), re-using the same
resolver helpers for exact attribution parity. `api_client_financial_summary`
now passes `snapshot=_client_snapshot_for(client)`.

Benchmark (400 clients × booking + credit sale + payment + entry each):
- full snapshot: **~39 ms** per summary
- scoped snapshot: **~12 ms** per summary (**~3.2× faster**, and no longer grows
  with total client count).
- Parity test asserts identical closing balance / totals / row signature.

---

## Finding 5 — UI freeze relationship

**Confirmed related — two independent mechanisms identified and fixed.**

1. **Sale form "stuck / Saving…" freeze.**
   `layout.html` attaches a global `submit` listener to every form that latches
   `__formSubmitting = true` and shows the loading overlay. The Direct Sales form
   also runs its own pre-submit validation which calls `preventDefault()` on the
   first submit, waits for booking status, then calls `form.requestSubmit()`.
   Because the global listener ran **after** the sale form's listener on the same
   event, `__formSubmitting` was already `true` by the time the follow-up
   `requestSubmit()` fired — so the global handler swallowed it (`if
   (__formSubmitting) { e.preventDefault(); return; }`). Result: the form froze on
   "Saving…" and the POST never left the page.
   **Fix:** the sale form's precheck listener is now registered in the
   **capture phase**, so its `preventDefault()` runs before the global latch is
   set.

2. **Client name disappearing.**
   On a validation failure the form is stashed and re-rendered as a draft. The
   draft stores the client *code* but the hidden *name* field can be empty, and
   `applyAddSaleDraft()` only restored the "Name: …" display when
   `draft.client_name` was populated — so the selected client's name vanished on
   resume. Combined with the background refresh reading raw/partial input state,
   this produced the "client disappears while entering qty" symptom.
   **Fix:** `applyAddSaleDraft()` now reconstructs the display name from the
   combobox by client code, and the row re-check/refresh paths are scoped to the
   correct form and gated to known clients.

---

## Finding 6 — Root cause

1. `templates/layout.html` `setInterval(dispatchFinancialRefresh, 30000)` —
   an unconditional global timer — kept re-triggering the client side-panel
   fetches on every page while idle, including for partially-typed input.
2. `templates/direct_sales.html` double-fires `updateBookingStatus()` on client
   pick (combobox `after` hook + `change` listener), with no in-flight coalescing.
3. `templates/layout.html` `checkDueRemindersGlobal()` polls
   `/api/notifications/due` from every tab with no visibility gate, in-flight
   guard, or cross-tab coordination.
4. `app/services/financial_ledgers.py` `_client_snapshot()` hydrates **all**
   clients' financial rows for a single-client summary.
5. `templates/layout.html` global submit latch (`__formSubmitting`) races the
   sale form's own `preventDefault()` → swallowed `requestSubmit()` → freeze.

---

## Finding 7 — Fix (exact changes)

`templates/layout.html`
- Removed the unconditional 30-second `dispatchFinancialRefresh('interval')`
  timer (financial widgets now refresh on focus / tab-visible / save only).
- `checkDueRemindersGlobal()`: added visibility gate, in-flight latch, and
  cross-tab leader election; added `?src=` correlation + `window.__AMS_TAB_ID`.

`templates/direct_sales.html`
- Added `bookingStatusInflight` / `financialSummaryInflight` coalescing maps.
- `updateClientFinancialSummary()` / `updateBookingStatus()` now coalesce
  identical concurrent requests and tag requests with `?src=` for log
  correlation.
- `refreshDirectSaleClientWidgets()` only refreshes for fully-known clients
  (never partial text).
- Sale-form precheck `submit` listener registered in the **capture phase** so it
  runs before the global loading latch (fixes the stuck form).
- `updateBookingStatus()` / `updateClientInputVisibility()` row re-checks are
  scoped to their own form (add form vs edit modals).
- `applyAddSaleDraft()` reconstructs the client display name from the combobox
  by code when the stored name is empty.
- Billed-sale validation accepts an auto-generated invoice in place of a manual
  bill number (matches the backend).

`app/services/financial_ledgers.py`
- Added `_client_snapshot_for(client)` — scoped single-client snapshot with
  resolver-level attribution parity.

`app/blueprints/api.py`
- `api_client_financial_summary()` uses `_client_snapshot_for(client)`.

`tests/test_sales_roundtrip.py` (new)
- HTTP round-trips: booked sale → booked return; booked+due → booked+normal
  returns; due sale → payment → return; cash sale; booked-return over-return
  rejection; scoped-vs-full ledger parity; financial-integrity audit clean.

---

## Finding 8 — Smoke tests

| Test | Result |
| --- | --- |
| Idle 5 min (no background client fetches) | PASS (static + code-path) — the unconditional 30s timer and idle client-refresh path are removed; financial widgets are event-driven only. |
| Repeated returns (poller count stays constant) | PASS (unit) — returns do not create timers; no polling is started on return success. |
| Multiple navigation (old page polling stops) | PASS (static) — polling lives in `layout.html` per page; navigation unloads the page and its intervals. |
| Multiple refreshes (one poller) | PASS (static) — one interval registration per page load; leader election dedupes across tabs. |
| Booked return | PASS (`tests/test_sales_roundtrip.py`) |
| Credit return | PASS (`tests/test_sales_roundtrip.py`) |
| Booked+Due return | PASS (`tests/test_sales_roundtrip.py`) |
| Over-return rejected | PASS (`tests/test_sales_roundtrip.py`) |
| Duplicate polling | PASS (static) — in-flight coalescing + removed timer + leader election. |
| UI freeze (form stuck) | PASS (static + fix) — capture-phase precheck before global submit latch. |
| Console errors | PASS — rendered page inline JS passes `node --check`. |
| API errors | PASS — 91 pytest tests, financial-integrity audit clean. |

*Static/unit verification is used where a real browser + 5-minute wall-clock
observation is not possible inside this sandbox (see Finding 9).*

---

## Finding 9 — Remaining concerns

- **Real-browser wall-clock tests** (idle 5 min with the Network tab open) could
  not be executed in this headless environment. The code-path removals and unit
  checks above are strong evidence, but the user should confirm in the browser.
- **Multi-tab financial widgets** are now event-driven (focus/visible/save), so
  two simultaneously *visible* tabs that both hold a Direct Sales form can still
  each refresh on their own focus event — expected and bounded, but not
  leader-elected (financial widgets are user-facing, unlike the reminder poll).
- **`/api/notifications/due` still writes** (`alerted_at` + commit) on a GET when
  reminders are due. Left as-is because it is intentional (mark-as-alerted);
  flagging it only as an observation.
- **Duplicate client codes / internally-multi-spaced client names** in legacy
  data are pathological edge cases where the scoped snapshot's SQL pre-filter and
  the full snapshot could theoretically differ. The token-ordered `LIKE` superset
  + resolver re-check was chosen to make this impossible for normal names; the
  parity test covers the realistic dataset.
- The diagnostic `console.debug('[AMS-POLL] …')` lines and `?src=` query tags are
  intentionally light and can be removed later if no further log investigation is
  needed.
