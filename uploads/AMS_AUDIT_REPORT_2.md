# AMS APPLICATION — FEATURE PRESENCE & BUSINESS LOGIC AUDIT (REPORT 2)
**Date:** 2026-08-05  
**Type:** Read-Only Feature Presence & Business Logic Audit  
**Scope:** 8 specific audit items per uploaded brief  
**Basis:** main.py (21,421 lines), models.py, blueprints/, templates/

---

## AUDIT ITEM 1 – Booking Payment Receive Account

### Status: 🟡 Partially Implemented

---

### What Exists

**Model field:**  
`Booking.receive_in_account_id` — `db.Column(db.Integer, db.ForeignKey('account.id'), nullable=True)`  
Relationship: `receive_in_account = db.relationship('Account', ...)`  
Location: `models.py` line 314–316

**Routes:**
- `POST /add_booking` (main.py line 5070) — reads `receive_in_account_id` from form, validates it, requires it to be non-null and active
- `POST /edit_bill/Booking/<id>` (main.py line 5203) — also reads and updates `receive_in_account_id`

**Form:**  
`templates/bookings.html` lines 289 and 416 — both the Add Booking modal and Edit Booking modal contain:
```html
<select name="receive_in_account_id" class="form-select bg-dark text-white border-secondary" required>
```
The select lists all `Account` objects (all types: cash, bank, other). The account type is **not filtered** — any active account can be selected, including non-cash/non-bank types.

**Ledger / Accounting Updates:**  
`_sync_booking_payment_accounting(booking)` (main.py line 5933) is called after every booking create/edit when `paid_amount > 0`. It:
1. Finds or creates an `AccountTransaction` of `transaction_type='Receipt'` linked to the booking via a source marker in the note field
2. Posts `paid_amount` to `receive_in_account_id` (credits that account's balance)
3. On re-sync (edit), if the account or amount changed, it voids the old transaction and creates a new one
4. On void, the receipt transaction is also voided

---

### What Is Missing / Risk

| Gap | Detail |
|---|---|
| **Non-searchable select** | The account picker is a native `<select>` with no filtering. If there are many accounts, selection is error-prone |
| **No account-type enforcement in form** | The form does not filter accounts by type (cash/bank). A user could accidentally select an expense or contra account. The backend does not validate account category for bookings (unlike payments, which enforce `expected_category`) |
| **`paid_amount = 0` still requires account** | The validation (`if not receive_in_account_id: flash error`) fires even when `paid_amount = 0`, meaning a receive account must always be selected even when no money is collected at booking time |
| **Booking `paid_amount` does not settle pending bills** | `_sync_booking_pending_bill()` creates a pending bill for `amount - discount - paid_amount`. The booking `paid_amount` is credited to an account but is **not applied via `_apply_settlement_to_pending_bills_for_client()`** — it is stored directly on the `Booking` record. This means the pending bill system reflects the booking's own ledger but does not automatically settle other outstanding bills |

---

## AUDIT ITEM 2 – Payment Edit & Hard Delete

### Status: 🟡 Partially Implemented — varies by payment type

---

### Client Payments (`Payment` model) — ✅ Both Edit and Hard Delete exist

| Operation | Route | Location | Notes |
|---|---|---|---|
| **Edit** | `POST /edit_bill/Payment/<id>` | main.py line 6514 | Full edit: client, amount, method, account, discount, date, photo. Calls `_sync_payment_accounting()` to reconcile accounting after edit |
| **Hard Delete** | `POST /delete_payment/<id>` | main.py line 6603 | Voids payment first (reverses `AccountTransaction`), then calls `db.session.delete(payment)`. True hard delete |

Permission: `can_manage_payments`

---

### Supplier Payments (`SupplierPayment` model) — ✅ Both Edit and Hard Delete exist

| Operation | Route | Location | Notes |
|---|---|---|---|
| **Edit** | `POST /edit_supplier_payment/<id>` | main.py line 21211 | Edits amount, method, account, date, note. Calls `_sync_supplier_payment_accounting()` |
| **Hard Delete** | `POST /delete_supplier_payment/<id>` | main.py line 21298 | Voids then `db.session.delete()`. True hard delete |

Permission: `can_manage_suppliers`

---

### GRN Payments (`GRN` payment fields) — 🟡 Edit exists; Hard Delete is missing

| Operation | Route | Location | Notes |
|---|---|---|---|
| **Edit** | `POST /grn/payments/<id>/edit` | main.py line 20715 (as `grn_edit_payment_receive`) | Edit of GRN payment account, method, amount, date |
| **Void** | `POST /grn/payments/<id>/void` | main.py line 20812 | Voids and reverses accounting |
| **Restore** | `POST /grn/payments/<id>/restore` | main.py line 20840 | Unvoids |
| **Hard Delete** | ❌ Not found | — | No route exists to permanently delete a GRN payment. Only void/restore cycle available |

---

### FBM Rental Payments — ❌ Neither Edit nor Hard Delete exist

| Operation | Route | Status |
|---|---|---|
| **Add** | `POST /fbm_rentals/clients/<id>/payment` | ✅ Exists |
| **Edit** | — | ❌ Not found |
| **Hard Delete** | — | ❌ Not found |
| **Void** | — | ❌ Not found |

FBM rental payments post to `AccountTransaction` via `_sync_payment_accounting()` but once posted, there is no route to correct or reverse an FBM payment.

---

### Booking Payments — ❌ No standalone edit/delete; embedded in booking

Booking payments (`paid_amount`) are part of the `Booking` record itself. To change the amount paid at booking time, you edit the booking via `edit_booking`. There is no separate `Payment` record created for booking advance payments — they are tracked as `AccountTransaction` via `_sync_booking_payment_accounting()`. There is no standalone "delete booking payment" route.

---

### Summary Table

| Payment Type | Edit | Hard Delete | Notes |
|---|---|---|---|
| Client Payment | ✅ | ✅ | Full support |
| Supplier Payment | ✅ | ✅ | Full support |
| GRN Payment | ✅ | ❌ | Void only, no hard delete |
| FBM Rental Payment | ❌ | ❌ | No correction workflow at all |
| Booking Advance | 🟡 (via booking edit) | ❌ | Embedded in booking, no standalone delete |

---

## AUDIT ITEM 3 – Ledger Synchronization

### Status: 🟡 Partially Implemented — shared function, but name-match fragility

---

### Unified Balance Calculator

Both the **Client Ledger** and the **Decision Ledger** call the same function:

```python
_calculate_client_pending_balance(client_code_or_name)
```
Location: main.py line 2625

This is explicitly documented as a **"UNIFIED PENDING BALANCE CALCULATOR"** designed to keep both ledgers consistent. It computes:
- Booking debits (using `_booking_ledger_gross_due()` with legacy-lift logic)
- Booking credits (`paid_amount`)
- DirectSale debits (`amount`)
- DirectSale credits (`paid_amount`, `discount`)
- Payment credits (`amount`)
- WaiveOff credits (via `_client_waive_off_total()`)
- Opening balance
- Booking discounts

**Decision Ledger** (main.py line 11932): `balance = _calculate_client_pending_balance(client.code)`  
**Client Ledger** (view_bill, financial_ledger): also routes through `_calculate_client_pending_balance`

---

### Risks and Inconsistencies

| Risk | Detail |
|---|---|
| **Name-based matching for `DirectSale`** | `DirectSale` model has **no `client_code` column** (confirmed bug from Audit Report 1). The function matches DirectSale records by `func.lower(func.trim(DirectSale.client_name)) == client_name_norm`. If a client's name is later edited, all DirectSale records retain the old name — they become invisible to the balance calculator for the updated client name |
| **Two balance functions exist** | `_calculate_client_pending_balance()` is used for Decision Ledger and pending balance display. `_client_balance_as_of(client_obj, cutoff_dt)` (line 4548) is a **different function** used in `view_bill`, bill snapshots, and download ledger contexts. These two functions use different calculation paths — if `_client_balance_as_of` is not kept in sync with `_calculate_client_pending_balance`, the ledger download and the Decision Ledger will show different balances for the same client |
| **Legacy lift in Decision Ledger is recomputed, not cached** | The Decision Ledger page (line 11896) loops over all clients and calls `_calculate_client_pending_balance()` for each. This is a live computation; for large client bases this will be slow and could time out |
| **Cancel entries affect booking debit** | The legacy lift logic suppresses booking debit when a `CANCEL` Entry exists for that booking's bill ref. If a cancel entry is voided later, the legacy lift is re-enabled and the debit may change. This is correct behavior, but the dependency on `Entry.type == 'CANCEL'` means the balance changes when entries are voided — without any notification to the user |

---

## AUDIT ITEM 4 – Global Synchronization

### Status: 🟡 Partially Implemented — hook exists but does not update all dependent data

---

### The Sync Hook

`_global_sync_after_transaction_change(client_code, client_name)` (main.py line 6159) is called after most create/edit/delete operations on:
- Bookings ✅
- Client Payments ✅
- Direct Sales ✅
- Material Returns ✅

It resolves the client and calls `_calculate_client_pending_balance()`. However, inspecting the function body reveals it does **not actually update any database records** — it computes and returns the balance, but the comment "Dashboard and report calculations will automatically use new balance" relies on subsequent live recalculation on page load, not on a persistent sync.

---

### Operations and Their Sync Coverage

| Operation | Pending Bill Sync | Account Sync | Material Stock Sync | Decision Ledger Sync | Notes |
|---|---|---|---|---|---|
| Add Booking | ✅ `_sync_booking_pending_bill()` | ✅ `_sync_booking_payment_accounting()` | ✅ (via Entry) | ✅ `_global_sync...()` | Complete |
| Edit Booking | ✅ | ✅ | ✅ (via Entry rebuild) | ✅ | Complete |
| Void Booking | ✅ `_set_booking_void_state()` reverses | ✅ reverses AccountTransaction | ✅ reverses Entries | 🟡 No explicit global sync call in void_transaction handler for Booking | `void_transaction` does not call `_global_sync_after_transaction_change` |
| Add Direct Sale | ✅ | ✅ | ✅ | ✅ | Complete |
| Edit Direct Sale | ✅ | ✅ | ✅ via `rebuild_direct_sale_effects()` | ✅ | Complete |
| Void Direct Sale | ✅ `_atomic_void_direct_sale_with_tracking()` | ✅ | ✅ | ❌ `void_transaction` route does not call `_global_sync_after_transaction_change` | Stale pending balance in Decision Ledger until next page load |
| Add Payment | ✅ pending bill settlement | ✅ AccountTransaction | N/A | ✅ | Complete |
| Edit Payment | ✅ | ✅ | N/A | ✅ | Complete |
| Void Payment | 🟡 `rebuild_pending_bills(client_id)` called | ✅ reversed | N/A | ❌ no global sync call | Pending bills rebuilt but Decision Ledger not explicitly refreshed |
| Delete Payment | ✅ (void first) | ✅ (void first) | N/A | ✅ | Complete |
| Add Material Return | ✅ payment created, synced | ✅ | ✅ stock incremented | ✅ | Complete |
| Void Material Return | ✅ `_set_material_return_void_state()` | ✅ | ✅ stock reversed | ❌ no global sync call in `void_transaction` | Same gap as void booking/sale |
| Add GRN | N/A (supplier side) | ✅ | ✅ stock added | N/A | Complete |
| Void GRN payment | N/A | ✅ reversed | N/A | N/A | Supplier balance recalculated live |
| Add Supplier Payment | N/A | ✅ | N/A | N/A | Complete |
| Delete Supplier Payment | N/A | ✅ (void first) | N/A | N/A | Complete |
| FBM payment | N/A | ✅ | N/A | N/A | Complete (but no edit/delete exists — see Item 2) |

---

### Key Gap: `void_transaction` Route Does Not Call Global Sync

The `void_transaction` route (main.py line 8755) handles voids for Entry, DirectSale, MaterialReturn, Booking, and Payment. Examining the route body: it calls the individual void state setters but does **not** call `_global_sync_after_transaction_change()` for most types. Only `Payment` void explicitly calls `rebuild_pending_bills(client_id=client.id)`. Booking, DirectSale, and MaterialReturn voids leave the Decision Ledger balance stale until the next page load recalculates it.

---

## AUDIT ITEM 5 – Material Return Logic

### Status: ✅ Fully Implemented — Normal Return and Booked Return have separate execution paths

---

### Type Resolution

`_resolve_material_return_type(value)` (main.py line 7680) normalizes the return type:
- `'normal'`, `'return'`, `'material return'` → mapped to `'normal'`
- `'booked'`, `'booked return'` → mapped to `'booked'`

Called in `add_material_return` (line 7947):
```python
return_type = _resolve_material_return_type(request.form.get('return_type'))
```

---

### Where the Paths Diverge

| Step | Normal Return | Booked Return |
|---|---|---|
| **Returnable qty check** | `_client_material_returnable_qty_map(client)` — sums normal OUT entries to determine how much was dispatched and can be returned | `_client_booked_material_returnable_qty_map(client)` — looks only at Booking Delivery OUT entries |
| **Rate required** | `unit_rate` required and must be > 0 (price of material) | `unit_rate` is ignored; `rent_rate` is required |
| **Total amount** | `qty × (unit_rate + rent_rate)` | `qty × rent_rate` only |
| **Entry `transaction_category`** | `'Return'` | `'Booked Return'` |
| **Entry `client_category`** | `'Material Return'` | `'Booked Return'` |
| **`MaterialReturnItem.price_at_time`** | `unit_rate` (legacy field) | `rent_rate` (legacy field) |
| **`MaterialReturn.return_type`** | `'normal'` | `'booked'` |

---

### Where the Paths Converge (Shared Logic)

After the type-specific computations, both paths share:
- Same `MaterialReturn` record creation
- Same `Payment` record creation (method = 'Material Return') — both create a credit payment for the client
- Same `Entry` creation (type = 'IN', returning stock)
- Same `mat_obj.total += qty` stock increment
- Same `_sync_payment_waive_off(pay)` call
- Same `_global_sync_after_transaction_change()` call

The `edit_material_return` route (line 8083) also reads `return_type` and applies the same divergence logic when editing.

---

## AUDIT ITEM 6 – Sales Partial Payment

### Status: 🟡 Partially Implemented — inconsistent across sale types

---

### Sale Type Analysis

| Sale Type | Category Field | Partial Payment | Enforcement | Pending Bill | Notes |
|---|---|---|---|---|---|
| **Cash Sale** | `'Cash'` | ❌ **Not allowed** | Backend enforces: `"Cash Sale must be fully paid"` — if `(paid_amount + discount) < (amount - 0.01)`, sale is rejected | No pending bill created | Fully paid at point of sale. No partial. |
| **Due Sale** | `'Credit Customer'` | ✅ Supported | `paid_amount` can be 0 or any value ≤ amount. No minimum enforced | Pending bill created for `amount - paid_amount - discount` | Requires `manual_bill_no`. Partial payment stored in `DirectSale.paid_amount` |
| **Booked Sale** | `'Booking Delivery'` | ❌ Enforced to 0 | Code explicitly sets `paid_amount = 0` (line in sale processor). No payment collected at delivery | No financial pending bill (booking already tracks payment) | The booking's own `paid_amount` handles advance payment. Delivery creates no new charge |
| **Booked + Due Sale** | `'Mixed Transaction'` | ✅ Supported for the due portion | `paid_amount` applies to the non-booked chargeable portion. Can be 0 or partial | Pending bill created for the chargeable portion minus `paid_amount` | Requires `manual_bill_no`. Mixed: booked items at zero price, chargeable items at rate |

---

### Inconsistency: Cash Sale Cannot Carry Partial Payment

The Cash Sale (`category = 'Cash'`) is the only type with a hard payment requirement. If a customer takes goods and pays only part in cash, the form must be submitted as a `Credit Customer` (Due Sale) instead. There is no "partially-paid cash sale" mode — the category must change.

---

### Inconsistency: `paid_amount` on `DirectSale` Not Always Reflected in Account

`DirectSale.paid_amount` stores the upfront cash collected. `_sync_direct_sale_payment_accounting()` (called via `_sync_direct_sale_pending_bill()`) creates an `AccountTransaction` for `paid_amount` only if `paid_amount > 0` and a `payment_account_id` is set. However:

- For Due Sales (`Credit Customer`) with `paid_amount = 0`, no account transaction is created (correct behavior)
- For Due Sales with `paid_amount > 0` but no `payment_account_id`, the validation check prevents this at the backend — but only if `expected_pay_category in ['cash', 'bank']`. If `payment_method` is something else, the check is skipped

---

### Missing: No "Record Additional Payment Against Existing Sale"

Once a Due Sale is created with partial payment, collecting the remaining balance must be done via a standalone Payment (`/add_payment`). There is no "Pay Balance" button on a sale record that links the incoming payment to that specific sale invoice and marks it fully settled. Settlement happens implicitly via pending bill matching, not via a direct FK relationship between Payment and DirectSale.

---

## AUDIT ITEM 7 – Void vs Hard Delete

### Status: 🟡 Partially Implemented — behavior is inconsistent across modules; `/delete_bill/` route does NOT hard delete

---

### Void Behavior (`/void_transaction/<type>/<id>`)

| Action | What Happens |
|---|---|
| Record | Remains in DB with `is_void = True` |
| Inventory | Reversed via `_set_entry_void_state()` / `_set_direct_sale_void_state()` etc. |
| Accounts | `AccountTransaction` is reversed via `_void_account_tx()` |
| Pending Bills | Pending bill for that source is voided/recalculated |
| Booking Allocations | Released via `_void_sale_booking_allocations()` |
| Bill Number | **Retired** — `find_bill_conflict()` still finds the voided record; the number cannot be reassigned to a new transaction |
| Audit Trail | Written to `AuditLog` |

---

### The `/delete_bill/<type>/<id>` Route — Important Discovery

Examining main.py lines 9904–9950: this route is named `delete_bill` but its implementation only **voids** the record (`_set_booking_void_state(bill, True)`, etc.) and calls `db.session.commit()`. It does **not call `db.session.delete()`**. The record is **not removed** from the database. Despite the "delete" name, this route is a **soft delete / void only**.

This means the `/delete_bill/` endpoint is functionally identical to `/void_transaction/` — both soft-delete the record. There is no hard delete path through this route for Booking, DirectSale, or MaterialReturn.

---

### True Hard Delete Routes (Where They Exist)

| Payment Type | Route | Hard Delete? | Notes |
|---|---|---|---|
| Client Payment | `/delete_payment/<id>` | ✅ Yes — `db.session.delete()` after void | Reverses accounting before deletion |
| Supplier Payment | `/delete_supplier_payment/<id>` | ✅ Yes — `db.session.delete()` after void | Reverses accounting before deletion |
| GRN Payment | None | ❌ No hard delete | Void/restore only |
| Booking | `/delete_bill/Booking/<id>` | ❌ Only voids | Record stays in DB |
| DirectSale | `/delete_bill/DirectSale/<id>` | ❌ Only voids | Record stays in DB |
| MaterialReturn | `/delete_bill/MaterialReturn/<id>` | ❌ Only voids | Record stays in DB |

---

### Bill Number Reuse Behavior

**After Void:**  
- The voided record remains in DB with `is_void=True`
- `find_bill_conflict(bill_no)` scans all bill-bearing tables including voided records
- The voided bill number **cannot be reused** — any new transaction using the same manual bill number is rejected with a conflict error
- Auto-generated bill numbers are **never reused** — `get_next_bill_no()` only increments forward; gaps appear when records are voided

**After Hard Delete (Payment / SupplierPayment only):**  
- The deleted record is removed from DB
- `find_bill_conflict()` can no longer find it
- The bill number **can be reused** for a new transaction
- The auto-bill counter is not decremented; only the manual bill number becomes available again
- This creates a data integrity risk: if a deleted payment's bill number is reused, historical references (audit logs, external documents) to that number become ambiguous

---

## AUDIT ITEM 8 – Client Clearance Bill

### Status: ❌ Missing as a dedicated feature — closest equivalent is "Full Client History" download

---

### What Was Searched

| Term | Routes | Templates | Buttons | Result |
|---|---|---|---|---|
| Clearance Bill | None | None | None | ❌ Not found |
| Client Statement | None | None | None | ❌ Not found |
| Outstanding Statement | None | None | None | ❌ Not found |
| Consolidated Statement | None | None | None | ❌ Not found |
| Account Statement | None | None | None | ❌ Not found |

---

### What Does Exist (Closest Equivalents)

**1. Full Client History PDF (`/download_full_client_history/<id>`)**  
- Route: main.py line 11466  
- Template: `templates/client_full_history_pdf.html`  
- Contents: Complete financial history (all bookings, sales, payments, material returns), pending bills list, material history grouped by material, receipt blocks  
- Format: PDF (via WeasyPrint) or HTML fallback  
- This is the closest equivalent to a "Statement" but is not labeled as such and is not designed for client-facing clearance purposes

**2. Client Ledger PDF (`/download_client_ledger/<id>`)**  
- Route: main.py line 11513  
- Template: `templates/client_ledger_print.html`  
- Contents: Transaction-by-transaction ledger with running balance, pending bills  
- Format: PDF/HTML  
- Accessible from the Client Ledger view page

**3. Pending Bills Export (`/export_pending_bills`)**  
- Route: main.py line 16944  
- Exports outstanding receivables across all clients as Excel/PDF  
- Not per-client

---

### What a True Clearance Bill Would Need

A "Clearance Bill" or "Client Statement" would typically:
1. Show total outstanding balance as of a selected date
2. List all unpaid invoices/bills with their amounts and due dates
3. Be addressed to the client (show client name, contact)
4. Include a "please pay by" or clearance stamp
5. Be printable/sendable as a formal document

None of these capabilities are implemented as a dedicated module. The `download_full_client_history` PDF comes closest but is an internal audit document, not a client-facing statement or demand notice.

---

## SUMMARY TABLE

| Audit Item | Status | Key Finding |
|---|---|---|
| **1. Booking Payment Receive Account** | 🟡 Partial | Field, form, and accounting exist. Account type not validated; `paid_amount=0` still requires account selection; native `<select>` control |
| **2. Payment Edit & Hard Delete** | 🟡 Partial | Client and Supplier payments: full edit + hard delete. GRN payments: edit + void only. FBM payments: no edit or delete at all |
| **3. Ledger Synchronization** | 🟡 Partial | Both ledgers share `_calculate_client_pending_balance()` — unified source. Risk: name-based matching for DirectSale (no `client_code`); two balance functions (`_client_balance_as_of` vs `_calculate_client_pending_balance`) that can diverge |
| **4. Global Synchronization** | 🟡 Partial | Hook exists and is called on most operations. Void operations (via `/void_transaction/`) do not call the global sync hook for Booking/DirectSale/MaterialReturn. FBM payments not synced. `_global_sync` function computes but does not write back balance |
| **5. Material Return Logic** | ✅ Full | Normal Return and Booked Return have separate qty-check functions, rate requirements, total calculations, and Entry tags. Shared code only in record persistence layer |
| **6. Sales Partial Payment** | 🟡 Partial | Cash Sale: no partial (enforced). Due Sale: partial supported. Booked Sale: no payment (designed). Booked+Due: partial supported for due portion. No "pay remaining balance" button on existing sale |
| **7. Void vs Hard Delete** | 🟡 Partial | `/delete_bill/` route only voids — does not hard delete despite its name. True hard delete only exists for Client Payment and Supplier Payment. Voided bill numbers cannot be reused; hard-deleted bill numbers can be reused (risk) |
| **8. Client Clearance Bill** | ❌ Missing | No clearance bill, statement, or outstanding statement feature exists. Closest equivalent: `download_full_client_history` PDF (internal audit document, not client-facing) |

---

*End of AMS Audit Report 2 — Read-Only, No Code Modified*
