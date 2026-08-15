# Accounts Section — Integrity Audit Report

Scope: payments, reconciliation, consistency and audit upgrade of the Accounts section
(`blueprints/accounts/*`), the shared accounting services it relies on, and its templates.
Date: 2026-08-15. Branch: `arena/01a003f5-ams-arena`.

---

## 1. Issues found

| # | Issue | Severity |
|---|-------|----------|
| 1 | **Client Payments (Accounts) had no Create form and an inconsistent Edit modal.** Edit posted to `sales.edit_payment` via a *different, simplified* form than the create form, and the modal referenced a `clients` variable that the route never passed (empty client dropdown). | High |
| 2 | **Supplier Payments (Accounts) had no actions at all** — no Create/Edit/Delete/View. The legacy `add_supplier_payment` / `edit_supplier_payment` / `restore_supplier_payment` routes were hard-disabled with a "disabled" flash, while the `payments.html` (Sales) supplier form still posted to the disabled endpoint. | High |
| 3 | **Edit-amount guard broke legitimate edits.** Supplier-payment editing checked "insufficient balance" against the *current* balance, which already contains the old payment, so raising the amount of an existing payment was wrongly rejected. | High |
| 4 | **Suspended clients could still be selected.** `_resolve_client` matched suspended clients; new receive/refund transactions accepted them. | Medium |
| 5 | **No per-account reconciliation.** Only aggregate cash-flow reconciliation existed; cash/bank/company accounts could not be reconciled individually with Loss/Excess classification. | Medium |
| 6 | **Account "Delete" was ambiguous.** Only a deactivate toggle existed; there was no guarded delete/archive path and no protection statement for accounts with history. | Medium |
| 7 | **Selectors were plain `<select>`s** on payment forms (non-searchable) and inconsistent across pages. | Low |
| 8 | **Float arithmetic** throughout payments (e.g. `float(...)` accumulation) — drift risk on values like `11905692.80`. | Low (new code uses rounding) |

## 2. Root cause of each issue

1. The Accounts section was re-factored away from the old Sales "Payments" page (`payments.html`), but the
   Accounts `client_payments` page kept a legacy hand-written edit modal and never wired a create path or
   passed the client list.
2. Supplier-payment management was intentionally "disabled" during the modularisation but never replaced with
   a working path, leaving a dead form + dead routes.
3. The balance guard was written for create-only and reused verbatim for edit without accounting for the
   already-posted old payment.
4. `_resolve_client` did a plain code/name lookup with no `is_active` filter.
5. Only `cash_flow` (aggregate drawer) reconciliation existed; there was no account-level equivalent.
6. Account deletion was left as a toggle with no audit-grade archive/delete decision.
7. Several forms used native selects; no shared searchable-selector component existed.
8. Legacy code uses SQLite `REAL` + `float()` for money; no central rounding at the boundaries.

## 3. Files / modules / routes changed

### New
- `app/services/payments_crud.py` — shared create/edit/delete/reconcile business logic (single code path for
  Create + Edit; money rounding; active-only validation; audit logging with before/after values).
- `templates/accounts/_entity_combobox.html` — reusable searchable selector macro (client/supplier/account).
- `templates/accounts/_client_payment_form.html` — shared client payment form (Create **and** Edit).
- `templates/accounts/_supplier_payment_form.html` — shared supplier payment form (Create **and** Edit).
- `templates/accounts/reconcile_account.html` — per-account reconciliation screen.
- `templates/accounts/reconciliations.html` — immutable reconciliation history list.
- `tests/test_accounts_crud_smoke.py` — 12 smoke tests (service + HTTP).

### Modified
- `blueprints/accounts/payments.py` — passes `clients`/`account_options`/`supplier_options`; adds
  `client_payment_save`, `client_payment_data`, `supplier_payment_save`, `supplier_payment_data`,
  `supplier_payment_delete`, `supplier_payment_restore`; refactored void/restore onto the shared service;
  supplier list now supports Active/Deleted/All.
- `blueprints/accounts/accounts_crud.py` — adds `reconciliations`, `reconcile_account`, guarded `delete_account`.
- `blueprints/accounts/helpers.py` — `_resolve_client(active_only=)`, `_active_clients`, `_active_suppliers`,
  `_account_option_label`, `_money_round`.
- `blueprints/accounts/transactions.py` — receive/refund flows resolve clients active-only.
- `blueprints/accounts/_common.py` — added `SUPPLIER_PAYMENT` bill namespace.
- `models/cash.py` — new `AccountReconciliation` model.
- Templates: `client_payments.html`, `supplier_payments.html`, `manage_accounts.html`,
  `account_ledger.html` (Reconcile link + delete/reconcile actions).
- `.gitignore` — ignore SQLite WAL/SHM runtime files.

### New routes
- `GET/POST /accounts/payments/clients/save` (create + edit, one form)
- `GET /accounts/payments/clients/<id>/data`
- `GET/POST /accounts/payments/suppliers/save` (create + edit, one form)
- `GET /accounts/payments/suppliers/<id>/data`
- `POST /accounts/payments/suppliers/<id>/delete` and `/<id>/restore`
- `GET /accounts/reconciliations`
- `GET/POST /accounts/<account_id>/reconcile`
- `POST /accounts/<account_id>/delete`

## 4. Database changes / migrations

- New table **`account_reconciliation`** (id, account_id FK, reconciliation_date, expected_balance,
  actual_balance, difference, difference_type, status, note, created_by, created_at, updated_at).
  Created automatically by the existing `db.create_all()` bootstrap on next start — non-destructive.
- No existing table or column was altered; no existing financial rows were migrated or deleted.
- Reconciliation balancing entries are posted as `AccountTransaction(type='Adjustment')` with a
  `[RECON:ACTUAL:<id>]` note marker (transparent, auditable, visible in the account ledger).

## 5. Tests performed

- Full existing suite: **57 passed** (45 pre-existing + 12 new).
- New `tests/test_accounts_crud_smoke.py`:
  - Client payment create → edit (same identity) → delete, with `Account.balance` recalc each step.
  - Client payment rejects suspended client / suspended account / method-account mismatch.
  - Supplier payment create → edit amount → edit account → delete, with balance recalc on both accounts.
  - Supplier payment rejects suspended supplier and insufficient balance.
  - Reconciliation: Matched / Loss (shortage) / Excess (profit) classification + transparent adjustment +
    ledger agreement + carry-forward as next opening balance.
  - HTTP flows: pages render with "New Payment", create/edit/delete via the shared routes, no duplicate rows.
- Manual template render check for `/accounts/payments/clients`, `/accounts/payments/suppliers`,
  `/accounts/accounts`, `/accounts/reconciliations`, `/accounts/<id>/reconcile`, `/accounts/audit` — all 200.

## 6. Tests passed / failed

- Passed: 57/57 (`ALLOW_EMPTY_DB=1 python -m pytest tests/ -q`).
- Failed: 0.

## 7. Remaining risks / follow-ups

- **Float storage (schema-level).** Money columns remain SQLite `REAL` across the legacy schema. New payment /
  reconciliation code rounds at every boundary (`_money`), but a full `Float → Numeric` migration is a
  cross-cutting schema change that was deliberately not forced on existing data. Recommend a future,
  non-destructive migration if precision issues are observed in reports.
- **Dashboard selectors.** The dashboard receive/pay account selects remain native `<select>`s (client/supplier
  pickers there already use searchable comboboxes and active-only lists). The new payment forms use the shared
  searchable macro; rolling the macro into the 1000-line dashboard template is a follow-up to reduce regression risk.
- **Materials/categories suspended filtering** is already applied in the Sales/GRN modules (outside Accounts);
  no Accounts selector uses materials/categories, so no Accounts change was required there.
- **Voided-account deletion** — `delete_account` archives any account referenced by transactions/payments
  (including voided ones) rather than hard-deleting, which is the safe default; a future "purge unreferenced
  voided history" tool could reclaim such rows if ever needed.

## 8. What was deliberately NOT changed (and why)

- The existing **Cash Flow** aggregate reconciliation (physical drawer, carry-forward, audit) was kept intact —
  it is correct and complementary; the new per-account reconciliation layers on top of it.
- The Sales `payments.html` page was left as-is (read-only list); the Accounts section is the canonical
  payments workspace and now owns full CRUD.
- No global schema float→decimal migration (risk to existing data), and no destructive cleanup of historical
  rows.
