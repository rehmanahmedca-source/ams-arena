# Material Return — Deep Stability Audit & Smoke Test Report

**Date:** 2026-08-15  
**Tester:** Automated deep-audit suite  
**Scope:** Material Return (Normal, Booked, Credit Sale), Booked Sale lifecycle,  
frontend state analysis, loading overlay audit, race-condition audit.

---

## A. Reproduction Attempt

### Was the bug reproduced?

**No — the exact intermittent "client disappears + page unselectable" could not be
reproduced consistently in automated testing.** The backend logic is deterministic
and correct (all 84 tests pass). The issue is intermittent and frontend-specific,
requiring a real browser session with specific timing/sequence to trigger.

### Reproduction steps attempted (via automated backend simulation)

1. Normal Return (single) — ✅ PASS
2. Booked Return (single) — ✅ PASS
3. 6 Repeated Returns, same client, same material — ✅ PASS
4. 5 Returns across 3 different clients — ✅ PASS
5. 5 Returns, same client, 3 different materials — ✅ PASS
6. Alternating Normal/Booked Returns — ✅ PASS
7. Over-return protection — ✅ PASS
8. Booked Sale → Booked Return → Booked Sale lifecycle — ✅ PASS
9. Credit Sale → Return → verify financial ledger — ✅ PASS
10. 10 consecutive returns (stress test) — ✅ PASS
11. No duplicate ledger entries — ✅ PASS
12. Edit return flow — ✅ PASS

### Environment

- Python 3.11 / Flask / SQLAlchemy
- SQLite (isolated test databases)
- Jinja2 templates with vanilla JavaScript (Bootstrap 5)

---

## B. Root Cause Analysis

### Backend — NO root cause found

The entire Material Return backend was audited:

| Component | Status | Notes |
|---|---|---|
| `add_material_return` | ✅ CLEAN | Always redirects (success or error). No inline rendering. |
| `edit_material_return` | ✅ CLEAN | Always redirects. Admin-only. |
| `delete_bill` (MaterialReturn) | ✅ CLEAN | Always redirects. |
| `_client_material_returnable_qty_map` | ✅ CORRECT | Computes `delivered - returned`. |
| `_client_booked_material_returnable_qty_map` | ✅ CORRECT | Computes `booked_delivered - booked_returned`. |
| `_sync_payment_waive_off` | ✅ CLEAN | No side effects on form state. |
| `_apply_settlement_to_pending_bills` | ✅ CLEAN | Correctly reduces pending bills. |
| `rebuild_pending_bills` | ✅ CLEAN | Called only in edit flow. |
| `add_material_return` exception handling | ✅ CLEAN | `try/except` with `db.session.rollback()` + redirect. |

**Key finding:** The backend is **stateless** with respect to the form UI.
Every POST results in a redirect to a fresh page. There is no persistent
"loading", "processing", or "locked" state on the server.

### Frontend — SUSPECTED root cause areas

| Component | Status | Notes |
|---|---|---|
| Global loading overlay (`#loadingOverlay`) | 🟡 SAFETY NET | Shown on every form submit; hidden on `pageshow`/`load`/`DOMContentLoaded`. Has 120-second auto-dismiss timer. |
| `showLoading()` / `hideLoading()` | 🟡 SAFETY NET | If form submit fails due to JS exception, overlay stays visible. 120-second timeout eventually dismisses. |
| Generic combobox system (client selection) | ✅ CLEAN | Uses `data-combo-code` attribute, event delegation. Properly isolated from material combobox. |
| Material combobox system | ✅ CLEAN | Uses separate `activeReturnMaterialInput` variable. Items lack `data-combo-code` so they can't trigger generic handler. |
| Bootstrap modal backdrop | ✅ CLEAN | Standard Bootstrap 5 modal lifecycle. Backdrop properly cleaned up on modal close. |
| Form submission handler | 🟡 POTENTIAL | Does NOT call `e.preventDefault()` before `showLoading()`. In rare cases (JS exception), overlay could show without form submitting. |

### Most likely trigger

The most plausible trigger for the reported bug is:

1. User fills in the Material Return form (modal)
2. User clicks "Save Return"
3. `showLoading()` is called → loading overlay appears (covers entire page)
4. The **form submission fails** silently (network error, server crash, or JS exception)
5. The loading overlay REMAINS visible, blocking ALL page interactions
6. User cannot see the form fields, cannot click anything
7. If a partial state update occurred (e.g., JS exception modified the DOM before failing), the client field could appear blank
8. User refreshes → page reloads → `pageshow` fires → `hideLoading()` → page works again

This explains:
- ✅ "Page becomes unselectable" — loading overlay at z-index 9999 covers everything
- ✅ "Client disappears from field" — could be a partial DOM update before the exception
- ✅ "Refreshing recovers" — new page load triggers `hideLoading()`
- ✅ "Intermittent" — depends on network conditions, server load, or JS timing
- ✅ "After 2-3 returns" — could be cumulative DOM state changes (e.g., cloned rows accumulating event listeners)

### Additional possibility: Multiple clone event listeners

Each time a return row is added via `+ Add Row`, the `bindRow` function adds
`input` event listeners to ALL inputs in the cloned row. After 2-3 rows have
been added and removed, there could be stale closures or event listeners
affecting performance or causing subtle bugs.

### Why it's NOT a backend issue

- All 84 tests pass, including 15 new stress/regression tests
- The backend always redirects (never renders inline)
- No persistent server-side state
- All response shapes are handled via `try/except`

---

## C. Targeted Fixes

### Fix 1: Defensive loading-overlay cleanup on form errors

**File:** `templates/layout.html`  
**Change:** Add `error` event listener on `window` that hides the loading overlay
when the page encounters an unhandled error.

**Why:** If a JS exception interrupts form submission after `showLoading()` is
called, the overlay stays visible. This catches that edge case.

### Fix 2: Prevent double-form-submit race

**File:** `templates/layout.html`  
**Change:** Add a guard flag `__formSubmitting` to prevent double-clicks on the
submit button from triggering multiple form submissions while the loading
overlay is active.

**Why:** Double-clicking "Save Return" could send two POST requests. The first
may complete and redirect, but the second could cause a 500 error or duplicate.

### Fix 3: Add `pointer-events: auto` guard for loading overlay

**File:** `static/theme.css`  
**Change:** Already present — the loading overlay naturally blocks clicks when
visible. No change needed.

### Fix 4: Ensure edit modal doesn't conflict with add modal

**File:** `templates/material_returns.html`  
**Change:** No issue found. The edit modal only appears on dedicated `edit_id`
URLs.

---

## D. Regression Test Matrix

| Test | Result | Notes |
|---|---|---|
| Normal Return (single) | ✅ PASS | 1 return, correct stock/entries |
| Booked Return (single) | ✅ PASS | Correct booked returnable qty |
| 6 Repeated Returns (same client) | ✅ PASS | State remains clean after 6 iterations |
| 5 Returns (different clients) | ✅ PASS | Client isolation verified |
| 5 Returns (3 materials, same client) | ✅ PASS | Multi-material state correct |
| Alternating Normal/Booked Returns | ✅ PASS | Both maps work correctly |
| Over-Return Protection | ✅ PASS | Cannot exceed delivered qty |
| Booked Sale → Return → Sale | ✅ PASS | Booking allocation restored |
| Credit Sale → Return → Ledger | ✅ PASS | Financial balance correct |
| 10-Return Stress Test | ✅ PASS | No cumulative corruption |
| No Duplicate Ledger Entries | ✅ PASS | Exactly 1 Entry per return item |
| Edit Return | ✅ PASS | State consistent after edit |
| Route Registration | ✅ PASS | All endpoints accessible |
| No Processing Flag | ✅ PASS | Backend is stateless |
| Modal Markup Correct | ✅ PASS | Bootstrap 5 patterns followed |
| Existing smoke tests (69) | ✅ ALL PASS | No regressions |

---

## E. Ledger Verification

| Ledger | Verified | Method |
|---|---|---|
| Client Material Ledger (Normal) | ✅ | `_client_material_returnable_qty_map` |
| Client Material Ledger (Booked) | ✅ | `_client_booked_material_returnable_qty_map` |
| Booking Material | ✅ | `_allocate_booking_quantities_for_sale_item` |
| Sale Quantity | ✅ | `DirectSaleItem.qty` |
| Returned Quantity | ✅ | `MaterialReturnItem.qty` |
| Available Booked Quantity | ✅ | Pool = booked - allocated + returned |
| Client Financial Balance | ✅ | `_compute_client_financial_summary` |
| Credit-Sale Balance | ✅ | PendingBill.amount after settlement |
| Stock/Material Ledger | ✅ | `Material.total` after IN/OUT |
| No duplicate records | ✅ | Count assertions in tests |
| No duplicate ledger entries | ✅ | Entry count == return count |
| No duplicate bookings | ✅ | Booking lifecycle test |
| Over-return prevented | ✅ | Beyond delivered qty blocked |

---

## F. Remaining Risks

1. **The exact frontend lock-up could not be reproduced in automated testing.**
   The bug requires a real browser session, specific timing, and possibly
   network latency or CPU load to trigger.

2. **Browser extensions / ad blockers** intercepting form submission or
   modifying the DOM could cause unexpected behavior. This cannot be tested
   in the automated suite.

3. **Slow server responses** (e.g., large datasets, high concurrency) could
   cause the loading overlay to appear for an extended period before the
   redirect. The 120-second safety timer handles this, but 120s is a long
   wait. A shorter grace period (e.g., 30s) could improve UX.

4. **The material combobox shares a single DOM list** (`#returnMaterialCombobox`)
   between both the Add and Edit modals. Under heavy concurrent interaction,
   `activeReturnMaterialInput` could theoretically be overwritten. This is
   low-risk because the modals are mutually exclusive (Bootstrap modals).

5. **No client-side form validation prevents double-submit.** While the
   loading overlay provides visual feedback, a quick double-click could
   theoretically send two POST requests before the first redirect completes.

---

## G. Fix Implementation

The following targeted fixes address the most likely root cause without
making random changes:

1. **Add JS error handler to hide loading overlay** — catches the scenario
   where `showLoading()` runs but form submission fails.

2. **Add form-submission guard** — prevents double-submit race conditions.

3. **Reduce loading overlay auto-dismiss from 120s to 30s** — users won't
   wait 2 minutes for a stuck overlay.

These fixes are minimal, defensive, and do not change any business logic.