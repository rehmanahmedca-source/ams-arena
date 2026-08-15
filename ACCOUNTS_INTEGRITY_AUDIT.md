# Accounts Integrity Audit — Final Implementation Report

**Scope:** Accounts payments, account ledgers, reconciliation, audit, selectors, master-entity lifecycle, reports, and all payment-producing compatibility routes
**Date:** 2026-08-15
**Branch:** `arena/01a0041c-ams-arena`

## Executive result

The Accounts payment stack now uses one canonical backend mutation service and one shared frontend form per payment type. Client and supplier payment create/edit/delete/restore operations preserve source identity, synchronise linked account transactions and exact minor-unit balances, rebuild dependent client bill state, and write a structured audit event in the same database transaction. Reconciliation now stores the complete carry chain and posts an immutable, referenced Loss or Profit/Excess adjustment.

Final automated result: **65 passed, 0 failed**.

---

## 1. Issues found and root causes

| # | Issue found | Root cause | Resolution |
|---|---|---|---|
| 1 | Legacy Sales, Suppliers, and Accounts dashboard endpoints could create/edit/delete payments through different logic. | Business rules had been copied across route modules. Some supplier endpoints were disabled; another supplier delete endpoint hard-deleted both source and ledger rows. | All reachable client/supplier payment endpoints delegate to `app/services/payments_crud.py`. Deletes are reversals/soft-voids and preserve stable IDs/history. |
| 2 | Refund Payment rows could be listed but not edited by the shared form; the service rejected negative rows. | Refunds were represented as negative `Payment` rows with a separately hand-built cash-out transaction and no explicit type. | Added explicit Receipt/Refund/Waive-Off form mode. Refund input remains positive in the UI and is stored as a negative client-ledger credit with a linked `Refund` account outflow. |
| 3 | Material-return and GRN-generated payments could be edited/deleted independently, corrupting their source modules. | Generated rows had only note markers and Accounts treated all rows as independent payments. | Added `source_type/source_id`, backfilled note markers, visibly labels linked rows, and forces edits/deletes through Material Return or GRN. |
| 4 | Reconciliation expected balance ignored opening balances. A bank with Rs. 5,000 opening and no transactions calculated as zero. | Expected balance was only the net of `AccountTransaction` rows. | Added explicit/inferred opening baselines and a reproducible `opening + incoming - outgoing` ledger calculation. |
| 5 | Reconciliation rows did not contain a complete daily carry chain and adjustment notes did not reference a reconciliation ID. | The adjustment was created before the reconciliation identity and only expected/actual/difference were stored. | Reconciliation now stores previous reconciliation, previous/opening balance, period start/end, in/out/net, expected, actual, signed adjustment, final balance, actor/session/IP, and adjustment transaction ID. Adjustment notes contain `[RECON:<id>]`. |
| 6 | Reconciled history could be invalidated by backdated payment edits/deletes. | No closed-period mutation guard existed. | Accounting-changing mutations in a closed period are rejected with a clear instruction to post an open-period reversal/adjustment. Later same-day activity remains possible after the prior closing timestamp. |
| 7 | Reconciliation shortage/excess did not flow into P/L reporting. | Adjustments were generic `Adjustment` rows and profit reports did not query them. | Uses `Reconciliation Loss` / `Reconciliation Excess`, displays them in ledgers/audit, and includes them as explicit P/L events. |
| 8 | Money was stored and mutated through binary floating-point only. | Legacy SQLite schema uses `REAL`; routes directly added/subtracted Python floats. | Added authoritative integer minor-unit columns for Accounts payment, supplier payment, account transaction, account balance/opening, and reconciliation values. `utils/money.py` applies finite Decimal half-up validation and mirrors legacy REAL fields for compatibility. |
| 9 | Duplicate submits and stale concurrent edits were not protected. | No idempotency key or record revision existed. | Added unique idempotency keys, revision fields, SQLAlchemy optimistic version predicates, and revision checks in shared forms/services. |
| 10 | Audit detail was free text and could be lost independently of the financial mutation. | Legacy `audit_log()` uses an independent session and intentionally swallows failures. | Added append-only `AccountingAuditLog` with structured before/after JSON, amount/account/party transitions, actor, timestamp, IP, session, and reason. It is added to the same transaction and cannot silently fail. |
| 11 | Account deletion checked only three reference types and archived accounts disappeared from management. | Deletion used a hand-maintained subset of foreign keys; Account list queried active rows only. | Deletion inspects every model FK to `account.id`, archives any referenced account, hard-deletes only an unreferenced account, and provides Active/Archived/All management views with restore toggle. |
| 12 | Client stable identity was name-only, so master renames could orphan payments from ledgers/totals. | `Payment` had no `client_id`; every report joined by mutable text. | Added/backfilled `client_id`, retained `client_name` as historical snapshot, and updated core client balances, ledgers, pending-bill replay, Accounts totals, and payment reports to use ID with legacy-name fallback. |
| 13 | Supplier master deletion could hard-delete a supplier with payments when no GRN existed. | The guard checked GRNs only. | Supplier/client delete now consistently suspends and retains every historical relationship, with structured Suspend/Activate audit events. |
| 14 | Payment filters omitted explicit party/account filters, bill references in search, deterministic tie ordering, and robust last-page behavior. | Listing queries were minimal and ordered only by date. | Added intersecting date/method/party/account/status/search filters, bill/reference/account search, 10/25/50/100 page size, deterministic `date,id` ordering, first/previous/page/next/last controls, filter persistence, and page clamping after deletes. |
| 15 | Searchable selectors did not support keyboard navigation and transaction account selectors were inconsistent. | Multiple custom/plain select implementations had drifted. | Extended the shared Accounts combobox with ARIA listbox semantics, arrow/Enter/Escape navigation, active-state styling, hidden-value safety, and reusable native-select enhancement for dynamic dashboard account lists. |
| 16 | Suspended materials were offered by several create workflows. | Material queries did not filter `is_active`. | Active-only lists are now used by Material Return, Direct Sale, Booking, GRN, and Dispatch create workflows. Material Return edit retains an inactive historical material only when it already belongs to that return. |
| 17 | Accounts POST routes had no CSRF enforcement. | The CSRF hook was a no-op. | Added session-bound CSRF validation for Accounts mutations and central token injection into all mutating forms. Tests can explicitly disable it. |
| 18 | Account audit “Delete” permanently removed source/ledger records, including linked payments. | Audit action called a hard-delete utility. | Audit actions now delegate to canonical payment reversal or soft-void an independent ledger row; reconciliation adjustments are immutable. |

---

## 2. Architecture after the upgrade

### Canonical client payment flow

`Shared client form (Receipt / Refund / Waive-Off)`
→ `accounts.client_payment_save` or compatibility endpoint
→ `save_client_payment()`
→ validate active/stable client + method/account + revision/idempotency + period lock
→ update the same `Payment.id`
→ synchronise Receipt/Refund/Loss `AccountTransaction` source row
→ exact account minor-unit balance
→ waive-off and pending-bill rebuild
→ atomic structured audit
→ one commit/rollback.

### Canonical supplier payment flow

`Shared supplier form`
→ `accounts.supplier_payment_save` or compatibility endpoint
→ `save_supplier_payment()`
→ validate active/stable supplier + method/account + funds + revision/idempotency + period lock
→ update the same `SupplierPayment.id`
→ synchronise one Supplier Payment ledger row
→ exact account balance
→ atomic structured audit
→ one commit/rollback.

### Reconciliation carry chain

`Previous final reconciled balance`
→ `opening balance`
→ `period incoming - period outgoing`
→ `expected closing`
→ `actual closing`
→ `difference = actual - expected`
→ `Matched / Loss / Profit-Excess`
→ transparent linked adjustment
→ `final reconciled balance`
→ next reconciliation opening.

Historical source transactions are never rewritten to force a match.

---

## 3. Files/modules/routes changed

### Canonical services and integrity utilities

- `app/services/payments_crud.py` — canonical payment CRUD, refund flow, source locks, idempotency, revisions, closed-period guard, reproducible ledger, complete reconciliation.
- `app/services/accounting.py` — exact minor-unit account effects and source-linked receipt/refund/supplier/loss rows.
- `utils/money.py` — Decimal validation and integer minor-unit conversion.
- `utils/accounting_audit.py` — atomic structured financial audit events.
- `app/services/schema.py` — backward-compatible additive migration/backfill and partial unique idempotency indexes.
- `app/services/void_rebuild.py`, `app/services/waive.py`, `app/services/grn_svc.py` — retained void history, stable party/source identity, generated-payment metadata.

### Models

- `models/sales.py` — client payment stable identity, payment/source type, exact amounts, idempotency, revision, actor/timestamps.
- `models/parties.py` — supplier payment exact/source/idempotency/revision/audit metadata.
- `models/cash.py` — exact/opening Account values, richer AccountTransaction source/audit fields, complete AccountReconciliation chain.
- `models/core.py` — `AccountingAuditLog`.
- `models/events.py` — central exact-money mirror synchronisation.

### Accounts routes/UI

- `blueprints/accounts/payments.py` and shared payment partials — shared create/edit forms, complete actions, combined filters, robust pagination, linked-source protection.
- `blueprints/accounts/accounts_crud.py` — safe account archive/delete, account-master permissions, reproducible ledger balances, reconciliation filters/flows.
- `blueprints/accounts/transactions.py` — canonical payment delegation, exact transfers, source-aware soft reversals, structured ledger audits.
- `blueprints/accounts/extra.py`, `templates/accounts/audit.html` — transaction audit plus structured before/after operation history.
- `templates/accounts/reconcile_account.html`, `reconciliations.html` — full carry-chain display.
- `templates/accounts/_entity_combobox.html`, `templates/layout.html` — shared accessible searchable selector, CSRF token injection, dynamic searchable select enhancement.

### Related modules

- Legacy Sales/Supplier payment endpoints now delegate to canonical services.
- Client ledgers, finance summaries, pending rebuilds, Accounts due summaries, and reports use stable payment client IDs.
- Profit report includes reconciliation P/L.
- Material Return/GRN generated payments are source-controlled.
- Client/Supplier suspend/activate/delete paths preserve history and emit structured audit.
- Material selectors are active-only in core create workflows while historical edit values remain available where required.

---

## 4. Database changes / migration safety

All changes are **additive and backward-compatible**. Existing payment, bill, account, and ledger IDs are retained.

### New table

- `accounting_audit_log`

### Extended tables

- `account`: exact current/opening minor values, explicit opening baseline/date, revision/update metadata.
- `payment`: `client_id`, exact amount/discount, type/source, idempotency, revision, actor/timestamps.
- `supplier_payment`: exact amount, type/source, idempotency, revision, actor/timestamps.
- `account_transaction`: exact amount, stable source, reconciliation reference, actor/void timestamps.
- `account_reconciliation`: complete period/carry/adjustment/final values in legacy and exact minor units, previous reconciliation, adjustment transaction, user/IP/session.

### Backfill behavior

- Exact minor values are calculated from existing values with Decimal half-up rounding.
- Legacy Account opening is inferred as `stored current balance - active ledger net`, so migration does not alter the live balance.
- Payment `client_id` is populated only on an exact historical name match; unresolved legacy rows retain their original name and continue using fallback logic.
- Material Return and GRN source IDs are recovered from existing markers.
- Revision is initialised with raw SQL before versioned ORM updates.
- Partial unique indexes protect non-null payment idempotency keys.

### Existing-data dry run

A temporary copy of the bundled production-shaped database was upgraded (the repository database itself was not mutated):

- Before/after source counts: Accounts **12/12**, Client Payments **724/724**, Supplier Payments **78/78**, Account Transactions **838/838**, legacy Audit rows **705/705**.
- Null exact-money values after backfill: **0** for Accounts, Payments, Supplier Payments, and Account Transactions.
- `opening + active ledger net == current balance` mismatches: **0**.
- New reconciliation/audit tables created successfully.

---

## 5. Tests performed

### Automated

Command:

```bash
ALLOW_EMPTY_DB=1 python -m pytest -q
```

Result: **65 passed, 0 failed**.

Coverage includes:

- Client receipt create → same-form edit → same ID → delete/reverse.
- Client refund create/edit/delete with exact outgoing account effects.
- Supplier payment create → amount edit → account edit → delete/reverse.
- Idempotent replay produces no duplicate.
- Stale revision is rejected.
- Suspended client/supplier/account rejection and historical inactive-account preservation.
- Material Return/GRN source-controlled payment protection.
- Exact values including `11905692.80`, `12446109.99`, `49.99`, and `0.01` in minor units.
- Stable client identity across master rename.
- Opening-balance reconciliation regression (Rs. 5,000 is expected as Rs. 5,000, not zero).
- Matched/Loss/Excess classification, transparent adjustment reference, carry-forward, and backdated-history lock.
- Structured Create/Edit/Delete audit before/after values.
- CSRF rejection/acceptance and account-master authorization.
- HTTP shared-form create/edit/delete flows and no duplicate identity.
- Existing cash-flow reconciliation, material return/refund, GRN, import, modularity, and consistency regression suites.

### Static/runtime checks

- `python -m compileall -q app blueprints models utils tests` — passed.
- `git diff --check` — passed.
- Authenticated UI render smoke for Dashboard, Accounts (Active/Archived/All), Client Payments, Supplier Payments, New Transfer, Audit, Reconciliations, Reconcile Account, and Account Ledger including voided rows — all HTTP 200.
- Temporary-copy migration/backfill validation — passed with unchanged source counts and zero account-chain mismatches.

---

## 6. Remaining risks

1. **Legacy SQLite REAL columns remain as compatibility mirrors.** The upgraded Accounts payment/reconciliation chain uses authoritative integer minor units, but older Sales/Inventory quantity/rate models outside this scope still use REAL. A future whole-ERP cents/decimal migration should be staged separately because changing all historical sales/stock cost columns at once would carry materially higher migration risk.
2. **Unresolved legacy payment party IDs.** Exact-name matches are backfilled safely. Ambiguous/unmatched legacy names intentionally remain `client_id = NULL` and use historical-name fallback rather than being guessed.
3. **SQLite write concurrency.** WAL, busy timeout, atomic transactions, idempotency indexes, and optimistic record revisions substantially reduce risk, but SQLite still serialises writers. A high-write multi-site deployment should use a server database in a separately planned migration.
4. **Closed-period corrections.** Accounting-changing edits/deletes are intentionally rejected after reconciliation. Operators must post a transparent current-period reversal/adjustment; this is an integrity control, not a missing feature.

No known broken Accounts action, orphaned payment ledger row, destructive payment delete, stale reconciliation adjustment, or failing automated test remains.
