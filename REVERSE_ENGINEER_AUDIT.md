# AMS ERP — Full reverse-engineering audit

**Date:** 2026-08-13  
**System:** AMS SYSTEM FOR EASE (cement / building-materials trading ERP)  
**Company defaults in Settings:** FAZAL BUILDING MATERIALS, Jalal Pur Sobtian, PKR  
**Runtime:** Flask + SQLAlchemy + SQLite (`instance/ahmed_cement.db`) + Jinja/Bootstrap 5  
**Identity of this review:** independent reverse-engineer of the live workspace (not vendor marketing).

**Evidence also used:** 106/106 live-page smoke (`SMOKE_TEST_REPORT.md`), 28/28 unit tests, route map (~210 unique URLs after aliasing), models, hooks, void/rebuild, accounts, cash flow.

---

## 1. What this software actually is

A **single-tenant trading ERP** for a Pakistani building-materials yard:

| Job | How the app does it |
|---|---|
| Buy stock | GRN (goods received) from suppliers, FIFO lots |
| Reserve stock | Bookings (advance / reserved qty + money) |
| Sell stock | Direct Sales: Cash, Credit, Booked delivery, Mixed, Open Khata |
| Collect / pay money | Accounts (company cash/bank) + Payments / Supplier payments |
| Day cash diary | Cash Flow (derived + recorded spend/receive) |
| Track who owes what | Client ledger, pending bills, supplier ledger |
| Control users | Role + per-module flags; Admin / root |
| Move data | Import/Export, wipe, rebuild, backups |

It is **not** a general accounting package (no full GL, no VAT return, no multi-company books). It is a **source-document ERP**: each booking/sale/GRN/payment is the source; ledgers and pending bills are **derived and rebuilt**.

---

## 2. Architecture (as implemented)

```
Browser (templates/*.html + layout combobox JS)
        │
        ▼
app/create_app()     main.py is ~8 lines
        │
        ├─ app/blueprints/*     HTTP (core, auth, sales, masters, ledgers, ops, reports, api, system, misc)
        ├─ blueprints/*         extra packs loaded by utils/module_loader.py
        │                       accounts (/accounts), import_export, inventory, admin, data_lab
        │
        ├─ app/services/*       domain logic (sales_core, void_rebuild, accounting, cash_flow_svc, …)
        ├─ models/*             SQLAlchemy tables
        └─ instance/ahmed_cement.db
```

**Two HTTP trees exist on purpose**

1. **Unprefixed “core”** (`app/blueprints`) — `/direct_sales`, `/grn`, `/cash_flow`, `/login`  
2. **Prefixed packs** (`blueprints/`) — `/accounts`, `/import_export`, `/inventory`, `/admin`  

`create_app()` then **aliases** every `blueprint.view` to a short name (`cash_flow` as well as `reports.cash_flow`) so old `url_for('cash_flow')` still works. That is why the route dump shows **duplicates** (same path twice).

**What “modular” means here (honest)**

- **True:** factory, models split by domain, services imported by name, blueprints not one 20k-line file.
- **Still fake-ish:** many services start with a huge unused import block copied from the old monolith (`constants.py`, `void_rebuild.py`, `cash_flow_svc.py` all import Flask, smtplib, zipfile…).  
- **Split files are thin wrappers** (`_direct_sales_add_direct_sale.py`) that `from ._common import *`.  
- **Cycle break:** `billing ↔ void_rebuild` uses a local import in one function.

Verdict: **modular enough to maintain**, not a clean hexagonal architecture.

---

## 3. Domain map — how money and bags move

```
                    ┌──────────── GRN (IN stock, FIFO lots) ────────────┐
                    │  Supplier bill  →  AccountTransaction (if paid)   │
                    └──────────────────────┬────────────────────────────┘
                                           │ stock +
                                           ▼
 Client ──► Booking (reserve qty + advance) ──► BookingItem / PendingBill
                │ paid_amount → Account (receive_in_account_id)
                ▼
         Direct Sale categories
         ├─ Booking Delivery  → consume reserved qty, amount MUST be 0, no invoice
         ├─ Mixed Transaction → reserved part + extra credit
         ├─ Credit Customer   → due on client ledger + invoice
         ├─ Cash              → paid now into account, unbilled optional
         └─ Open Khata        → informal name, special client code OPEN-KHATA

         Each sale writes:
           Entry (OUT stock) + optional GRNAllocation (FIFO cost)
           + BookingAllocation if booked
           + PendingBill if still due
           + AccountTransaction if cash received [SRC:DirectSale:id]
           + Invoice if billed credit

 Payment (client)  → settle pending bills FIFO-ish + Account Receipt [SRC:Payment:id]
 SupplierPayment   → reduce supplier payable + Account Payment [SRC:SupplierPayment:id]
 MaterialReturn    → IN stock + credit client (payment row) ; booked vs normal
 Cash Flow entry   → Account Receipt/Expense [SRC:CashFlow] + CashFlowEntry (category/party)
```

**Golden rule the code tries to enforce**

- **Source of truth:** Booking, DirectSale, Payment, GRN, SupplierPayment, CashFlowEntry, Account.  
- **Derived:** `Entry` (material movement), `PendingBill`, `Invoice` effects, account rows tagged `[SRC:…]`.  
- **Rebuild:** `rebuild_direct_sale_effects`, `rebuild_pending_bills`, `_rebuild_material_totals`, `rebuild_all_erp_consistency`.  
- **Delete:** `hard_delete_transaction` — reverse effects, then **delete the row** (UI says Delete, not Void). Void flags still exist internally as a reverse step.

---

## 4. Sale types (business law in code)

From `SALE_CATEGORY_CHOICES` + `direct_sales.html` + `void_rebuild.py`:

| UI label | Stored category | Stock | Client money | Invoice |
|---|---|---|---|---|
| Booked Sale | `Booking Delivery` | OUT reserved; rate hidden | **Amount forced 0** | No |
| Booked + Due | `Mixed Transaction` | reserved + extra | Extra qty charged | Yes if billed |
| Due Sale | `Credit Customer` | OUT + FIFO cost | Full amount due | Yes |
| Cash Sale | `Cash` | OUT + FIFO | Paid now | Usually no |
| Open Khata | `Open Khata` | OUT | Informal / follow-up | Special |

Smoke audit already proved: booked sale with rates in the form still posts **amount=0** and **no invoice**. That is intentional.

FIFO: `GRNAllocation` + `cost_rate_at_sale`. Deleting a GRN **fails** if lots are locked by cash/credit sales.

---

## 5. Accounts vs Cash Flow (as of this build)

**Accounts (`/accounts`)** — company cash/bank books.

- Create/edit accounts, transfers, receive from client / other source, pay supplier / expense / refund.  
- Client/supplier **payments belong here** (Payments page is **read-only** — confirmed by smoke flash).  
- Each money row is `AccountTransaction` and usually a `Payment` or `SupplierPayment` with a `[SRC:…]` note so delete can reverse both.

**Cash Flow (`/cash_flow`)** — day diary, **not a second set of books**.

- **Derived:** cash client payments, cash sales, supplier payments (do not re-enter).  
- **Recorded:** fuel, repair, food, loan in/out, outsider — must pick an **existing** company account.  
- Categories/subcategories are labels only; **accounts are never created here**.  
- Opening override + physical count are display/recon, not GL.

**Removed from UI (code leftovers remain)**

- FBM Rentals (blueprint + templates deleted; `models/rentals.py` still in DB).  
- FBM Cash Drawer (routes deleted; `FbmCashDrawerEntry` still used in Accounts expenditure KPIs).

---

## 6. Data model (tables that matter)

**Identity / system:** `User` (many `can_*` flags), `Settings`, `AuditLog` (+ username), `SchemaVersion`, `SystemLock`, `RootRecoveryCode`.

**Parties:** `Client`, `Supplier`, `DeliveryPerson`.

**Catalog / stock:** `Material`, `MaterialCategory`, `Entry` (IN/OUT/CANCEL), `GRN` / `GRNItem`.

**Trading:** `Booking` / `BookingItem` / `BookingAllocation`, `DirectSale` / `DirectSaleItem` / `DirectSaleDraft`, `GRNAllocation`, `Payment`, `WaiveOff`, `Invoice`, `BillCounter`, `PendingBill`, `MaterialReturn` / `MaterialReturnItem`.

**Money:** `Account`, `AccountCategory`, `AccountTransaction`, `SupplierPayment`, `CashFlowEntry` / `CashFlowCategory` / `CashFlowSubcategory` / `CashFlowParty`, recon tables.

**Ops:** delivery rent, import jobs, notifications, tenants, backups.

**Dead but still mapped:** `FBMRental*`, `FbmCashDrawer*`, `Delivery` / `DeliveryItem` (old delivery module).

Naming debt: `Entry.nimbus_no` is a **type tag** (“Direct Sale”, “Material Return”), not a Nimbus product ID. `is_void` remains even after the product language became Delete.

---

## 7. HTTP surface

~210 unique routes (424 lines in the map because of aliases).

| Area | Prefix | Role |
|---|---|---|
| Auth | `/login` `/logout` | Flask-Login |
| Masters | `/clients` `/materials` `/suppliers` `/delivery_persons` | Directory |
| Ops | `/grn` `/dispatching` `/tracking` `/add_record` | Stock in/out/history |
| Sales | `/direct_sales` `/bookings` `/payments` `/material_returns` `/pending_bills` | Trading |
| Ledgers | `/ledger` `/client_ledger` `/financial_ledger` `/decision_ledger` | Views |
| Accounts pack | `/accounts/*` | Company money |
| Cash Flow | `/cash_flow` | Diary + recon |
| Reports | `/profit_reports` `/unpaid_transactions` `/financial_details` | Analysis |
| System | `/settings` `/settings/activity` `/notifications` `/import_export` `/admin` `/tenants` | Control |

Permissions: `ENDPOINT_PERMISSION_MAP` → `User.can_*`. **Admin and root skip the map.** Endpoints **not listed are open to any logged-in user** (including the booking/financial JSON APIs used by Sales left panel).

---

## 8. Security reverse-engineering

| Finding | Severity | Detail |
|---|---|---|
| CSRF disabled | **High** | `_protect_against_csrf` returns `None`. Any logged-in session can be forged from another site. |
| `password_plain` column | **High** | Still on `User`. Login can accept plaintext then hash it. Risk if any row still stores plaintext. |
| Frame / CSP `ALLOWALL` | Medium | Needed for Arena preview; in production this is clickjacking-friendly. |
| No CSRF + wipe/delete POSTs | **High** | `/delete_selected_data`, `/delete_all_data`, `/accounts/.../delete` are session-only. |
| Permission map incomplete | Medium | Unmapped endpoints are allowed for every user. |
| SQLite file + import uploads | Medium | `instance/import_uploads/*.xlsx` persist; secret_key file on disk. |
| Default admin | Info | `Admin` / `Admin@fbm12345` created if DB empty. Fine for this yard; change if exposed. |
| SMTP / OpenAI / Google tokens | Medium | Stored in `Settings` table in clear SQLite. |

Login itself: Flask-Login + hashed passwords (werkzeug). Roles `admin`, `root`, `user`.

---

## 9. Consistency engine (the hard part)

This is the heart of the reverse-engineer: **why edit/delete is complicated**.

1. Posting a sale/booking/payment writes **source + derived** rows.  
2. Edit calls `rebuild_direct_sale_effects` / pending rebuild rather than hand-editing ledgers.  
3. Delete calls `hard_delete_transaction`: void-to-reverse, then `DELETE` the source and tagged account rows.  
4. Stock is **recomputed** from non-void `Entry` (`_rebuild_material_totals`).  
5. Auto-reconcile worker (env `AUTO_RECONCILE_ENABLED`) can repair drift every 10 minutes.  
6. Bill numbers live in namespaces (`BillCounter`: sale, booking, payment, GRN…).  
7. Source stamping (`source_module`, `source_table`, `source_id`, `[SRC:Type:id]`) is how Accounts and Cash Flow know not to double-count.

**Known sharp edges**

- Dual void **and** hard-delete paths still exist (`/void_transaction` vs `/delete_transaction`).  
- `is_void` leftovers if a delete fails mid-way (mitigated by rebuild).  
- Booking has `client_name` but **no `client_code` column** (identity via lookup). Sales have both.  
- Cash Flow “fresh start” **hides** today’s older rows in the report only — balances in Accounts do not reset. Easy to misread.  
- Payments hub is read-only; staff must use Accounts. Easy to miss without the flash.

---

## 10. UI / UX reverse-engineer

- Dark theme, sidebar groups: Inventory → Transactions, Accounts + Cash Flow, Directory, System.  
- Searchable **combobox** (`layout.html` `showCombobox` / `selectComboboxItem`) is the standard for client/material/supplier names. Apostrophes are stored in `data-combo-*` (not inline JS).  
- Sales left panel: `GET /api/client_booking_status/<code>` + `GET /api/client_financial_summary/<code>` → booking cards + RUNNING PENDING.  
- Global loading overlay + task-progress modal on save/download.  
- Combobox hidden-id pattern: `data-combo-value-input` + `data-store=name` for FBM-style id+name (supplier, cash-flow account).

---

## 11. Testing reality

| Suite | Result (2026-08-13) |
|---|---|
| `pytest tests/` | **28 passed** (FIFO, refund, returns, cash-flow recon, modular app) |
| `tests/full_app_smoke.py` | **106/106** GET pages + create/edit/delete |
| Heavy audit | Booked vs credit rules, GRN lock, actor audit |

Coverage is **happy-path + money invariants**, not every permission matrix or import file.

---

## 12. Dead code & dual systems (cleanup backlog)

| Leftover | Risk |
|---|---|
| `models/rentals.py` + wipe targets | Confusing; unused UI |
| `FbmCashDrawer*` + `app/services/drawer.py` | Expenditures KPI still mixes drawer OUT with account expenses |
| `blueprints/module_template.py` at `/module_name` | Demo CRUD still registered |
| Duplicate route aliases | Debugging `url_for` is noisy |
| Monolith import headers in services | Slows reading; hides real deps |
| `Delivery` / `DeliveryItem` | Old delivery module vs current SaleDeliveryPerson |

---

## 13. Strengths (what the reverse-engineer would keep)

1. **Source → derived rebuild** is the correct model for a yard ERP (better than editing ledgers by hand).  
2. **Sale category law** is explicit and tested (booked ≠ credit).  
3. **FIFO + GRN lock** prevents deleting stock that was already sold.  
4. **Accounts vs Cash Flow split** now matches how the owner thinks: books vs diary.  
5. **Actor stamp** on flashes and `AuditLog.username`.  
6. **Factory + named services** is maintainable enough for one product team.

---

## 14. Risks & recommendations (priority)

**P0 — before any internet exposure**

1. Turn CSRF on for all POST (Flask-WTF or same-site token).  
2. Stop storing / accepting `password_plain`; migrate leftovers.  
3. Tighten CSP / X-Frame-Options outside the preview host.  
4. Change default Admin password if this DB is shared.

**P1 — product clarity**

5. Remove or hide `/module_name` demo.  
6. Drop or archive rental/drawer models after a one-time data migrate (expenditures KPI should use Cash Flow + AccountTransaction only).  
7. Add `client_code` on Booking for consistent identity.  
8. Document Cash Flow fresh-start in one line on the page (already improved; keep it).  
9. Map remaining APIs in `ENDPOINT_PERMISSION_MAP` or mark them public on purpose.

**P2 — engineering hygiene**

10. Strip unused imports from service modules.  
11. One URL per endpoint (stop aliasing in production, or generate a route catalog).  
12. Expand tests: permission denial, CSRF, concurrent GRN+sale, cash-flow vs account balance equality.

---

## 15. One-page “how to operate” (reverse-engineered SOP)

1. **Stock in:** GRN (supplier + material + qty + rate).  
2. **Reserve:** Booking for a client (optional advance into an account).  
3. **Sell:** Sales → pick type → pick client (left panel shows booking + running due) → materials/GRN → delivery persons → save.  
4. **Collect / pay:** Accounts → New Transaction (not the Payments menu).  
5. **Other cash (fuel, loan, person):** Cash Flow → pick **existing** account → category → save.  
6. **Fix mistakes:** Delete (hard reverse). Do not invent ledger rows.  
7. **If numbers drift:** Settings / Admin rebuild ERP consistency; check Activity log (`— by Admin`).

---

## 16. Conclusion

AMS is a **real, working yard ERP** reverse-engineered from a monolith into a factory + domain packages. The money model is coherent: **documents first, ledgers rebuilt, cash diary second**. The main residual risk is **web security (CSRF, plaintext password column, open framing)** and **leftover FBM rental/drawer schema**, not “the books don’t add up” on the paths we smoked.

It is **fit for on-site Admin use** with the SOP above. It is **not yet fit** as a multi-user internet app without the P0 items.
