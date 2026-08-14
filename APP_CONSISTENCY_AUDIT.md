# AMS ERP — Application Consistency Audit

**Audit date:** 2026-08-13  
**Repository:** `rehmanahmedca-source/ams-arena`  
**Database reviewed:** `instance/ahmed_cement.db` (read-only checks; no production rows were changed)

## Executive summary

The application is a substantial Flask/SQLAlchemy ERP with working inventory, sales, booking, payments, accounts, cash-flow, import/export, and reporting flows. The main consistency risk is not a single broken module; it is the coexistence of several representations of the same event:

- source documents (`Booking`, `DirectSale`, `Payment`, `GRN`, `SupplierPayment`),
- derived stock/pending-bill/invoice rows,
- account transactions,
- cash-flow display rows, and
- legacy aliases and legacy models.

That architecture can work, but every display and delete path must apply the same source-marker rules. The audit found and corrected several concrete inconsistencies, including a fresh-database login failure, permission bypass through blueprint aliases, duplicate supplier-payment and cash-receipt reporting, orphan invoices after hard deletion, a malformed Settings template, and a WSGI database-path mismatch.

There are still important production risks listed in **Open findings** below. The most urgent unresolved issues are disabled CSRF protection, legacy plaintext-password support, incomplete client transfer/reclaim behavior, and inconsistent root/admin authorization rules.

## Verification performed

| Check | Result |
|---|---:|
| Existing unit/integration suite | **34 passed** |
| Fresh-database full-app smoke | **96 passed, 0 failed** |
| Jinja template compilation | **93/93 templates compiled** |
| Python compilation | **All tracked Python files compiled** |
| Route inventory | **426 rules / 256 unique paths / 170 duplicate alias paths** |
| Read-only consistency tool | **9 checks; 1 FAIL group, 1 WARN group, 1 WARN baseline** |

The existing database was not repaired automatically. The current DB report is included so data cleanup can be planned safely rather than silently deleting records.

## Concrete fixes applied

### 1. Fresh database now creates the documented Admin login

`_ensure_default_admin()` existed but was never called during normal bootstrap, and the testing bootstrap skipped it as well. A new empty database therefore showed a login page with no usable `Admin` account even though the README and smoke tests relied on `Admin / Admin@fbm12345`.

**Fix:** call the default-admin initializer after schema creation in both production and testing bootstrap paths. Existing non-empty user tables are left unchanged. The password remains configurable with `DEFAULT_ADMIN_USER` and `DEFAULT_ADMIN_PASSWORD`.

### 2. Blueprint-qualified endpoints now honor the permission map

Flask routes resolve to names such as `sales.direct_sales_page`, while the legacy permission table contains `direct_sales_page`. The hook looked up only the full endpoint, so a regular user with `can_manage_sales=False` could still open core sales routes through the qualified endpoint.

**Fix:** permission enforcement falls back to the final endpoint component when a dotted endpoint is not found. A regression test confirms `/direct_sales` is denied for a user without sales permission.

This does not replace the manual guards used by Accounts, Admin, import/export, and destructive system routes; those still need consolidation (see Open findings).

### 3. Root access is consistent for the Accounts module

The global permission hook treats `admin` and `root` as superusers, and several Accounts handlers do the same. The Accounts package-level guard allowed `admin` but rejected `root` when `can_manage_payments` was false.

**Fix:** Accounts now treats both `admin` and `root` as privileged for its package guard. Other `role == 'admin'` checks remain and are called out below.

### 4. Supplier payments are no longer counted twice

New GRNs create a marked `SupplierPayment` row (`[AUTO_GRN_PAY:<id>]`) so the supplier ledger and account posting have one canonical payment record. Several Accounts dashboard/KPI paths also added `GRN.paid_amount`, causing a new GRN payment to appear twice and causing supplier payable calculations to subtract it twice.

**Fix:** new GRN auto-payment rows are canonical; `GRN.paid_amount` is used only as a legacy fallback when no active marked payment row exists. The dashboard, supplier KPI, and supplier payable summary now use the same rule.

### 5. Cash-flow source-document mirrors are excluded

Booking and direct-sale paid amounts are shown from their source tables, while their account postings carry `[SRC:Booking:<id>]` and `[SRC:DirectSale:<id>]`. Cash Flow excluded Payment/SupplierPayment markers but not Booking/DirectSale markers, so the same cash receipt could be shown once as a source row and again as an account transaction.

**Fix:** Cash Flow page and cash-flow service calculations now exclude all known source-document markers before adding standalone account receipts. Dashboard/KPI receipt calculations were aligned to the same source-marker rule. A regression test covers a direct-sale account mirror.

### 6. Hard-deleting a DirectSale no longer leaves an active orphan Invoice

`hard_delete_transaction('DirectSale', id)` removed the sale and its derived effects but did not remove its linked Invoice. The read-only audit found an active invoice with no active sale.

**Fix:** when no other sale references the invoice, the hard-delete path removes the linked invoice too. Shared legacy invoice rows are preserved rather than deleted blindly.

### 7. Client code follows client name edits for DirectSale rows

The client edit path propagated a renamed client name but left `DirectSale.client_code` unchanged. This creates conflicting identity fields for APIs, exports, and source-scoped rebuilds.

**Fix:** client edits update both `DirectSale.client_name` and `DirectSale.client_code`. A regression test covers the code change.

### 8. Settings page and audit tooling were repaired

- `templates/settings.html` contained an unmatched duplicate Jinja tail and a malformed Notifications checkbox; `/settings` raised `TemplateSyntaxError`.
- `tools/read_only/cash_flow_audit_detail.py` contained literal escaped source text and could not compile.
- `tools/consistency_report.py` ignored `APP_DB_PATH` and always inspected the repository default DB.
- `wsgi.py` set unused `HDC_DB_PATH` instead of the factory's `APP_DB_PATH`.
- `pytest.ini` lacked a repository `pythonpath`, so the documented plain `pytest` command failed during collection in some environments.
- The full smoke harness had a report type-conversion bug and a Python exception-closure bug; both were corrected.

## Current database findings

The read-only consistency checker currently reports:

1. **Account balance mismatches — FAIL group.** Six accounts differ from the sum of their active `AccountTransaction` rows. Some of these rows are clearly audit/test transfer data, and Accounts currently stores initial balances directly without a journalized opening transaction. Therefore the tool cannot distinguish a legitimate opening balance from drift. These balances require an operator-led reconciliation before production use; do not run a blind repair.
2. **One active orphan invoice — WARN.** `Invoice id=1`, `MB NO.CR-AUDIT-1`, has no active `DirectSale`. The new delete fix prevents new orphans but does not delete this existing record automatically.
3. **No material-total mismatch detected.** `Material.total` matched active IN/OUT entries for the reviewed DB.
4. **No orphan active payment/account-transaction references detected.**
5. **No active sale missing an OUT entry detected.**
6. **No active credit sale missing a pending bill detected.**
7. **No booking missing a pending bill detected.**
8. **No health snapshot file existed at audit time.** A fresh normal bootstrap now writes one; an existing deployment should be allowed to create/update its baseline intentionally.

## Open findings, ordered by risk

### High — CSRF protection is disabled

`app/hooks.py::_protect_against_csrf()` is a no-op. The application has many state-changing POST routes, including account transfers/deletes, hard deletes, data wipes, settings changes, imports, and password changes. A logged-in browser can be induced to submit one from another origin.

**Recommendation:** add a real CSRF token/session check for every mutating browser route, including multipart forms and fetch requests. Exempt only explicitly authenticated machine-to-machine endpoints with a separate token. Do not rely on `WTF_CSRF_ENABLED=False` as a security control.

### High — Plaintext password compatibility remains in the data model

`User.password_plain` remains mapped, login accepts legacy plaintext values, and tenant-reset code writes plaintext compatibility values. Settings/integration secrets are also stored in the SQLite database. This increases the impact of a database-file copy.

**Recommendation:** migrate any remaining plaintext values to hashes, stop writing/accepting plaintext, remove the column in a controlled schema migration, and move SMTP/OpenAI/Google secrets to environment or an encrypted secret store.

### High — Client transfer/reclaim is not actually “all transaction data”

The UI promises to move all transaction data, but `transfer_client` and `reclaim_client` currently update only `Entry`, `PendingBill`, and `WaiveOff` rows. Bookings, direct sales, payments, invoices, material returns, and drafts retain the old identity. Reclaim then updates all matching target rows, which can move the target client's original transactions as well as the transferred rows.

**Recommendation:** introduce a transfer batch/source table or immutable client foreign keys. Record exactly which rows were moved, update every source table consistently, and make reclaim reverse only that batch. Add an integration test with source and target clients that both already have transactions.

### High — Authorization policy is split across three systems

The central permission map, blueprint `before_request` guards, and inline `role == 'admin'` checks do not use one policy. The route inventory found 193 view endpoints not directly represented by the central map (many are intentionally manually guarded or aliases, but the fall-through behavior is difficult to prove safe). Examples of remaining role drift include the Admin blueprint and Settings/system handlers that accept `admin` but not `root`, while other code treats root as a superuser.

**Recommendation:** define `is_superuser()` and `require_permission()` once; apply them to every blueprint and route. Make the central map fail closed for mutating endpoints. Add a role/permission matrix test for every mutating route.

### Medium — Account opening balances are not journalized

Creating an Account can set `Account.balance` directly, while later transactions change the same field. The consistency tool compares the final balance only to transaction net movement and therefore reports opening balances as mismatches. This makes genuine drift and legitimate opening balances look identical.

**Recommendation:** add an explicit opening-balance/adjustment transaction or an immutable `opening_balance` field with a documented cutover date. Update the consistency checker to include that baseline and add concurrency/reversal tests.

### Medium — Several “receipt” screens use different definitions

The main Accounts dashboard, KPI pages, Cash Flow, Accounts Receipts, and Payments pages do not all show the same event set. The source-marker fixes align the highest-impact dashboard/Cash Flow paths, but the Accounts Receipts screen still labels GRN supplier payments under “Receipts,” and client-payment totals include ledger payment rows that are not necessarily cash movements (for example, material-return credits).

**Recommendation:** define explicit measures such as `cash_received`, `client_ledger_credits`, `supplier_cash_paid`, and `stock_purchase_total`; reuse the same service query in every screen and label each measure accordingly.

### Medium — Hard-delete and void workflows coexist

The UI says Delete, while legacy `/void_transaction` and `/unvoid_transaction` routes and `is_void` flags remain. This creates different expectations about auditability and restoration. A failed multi-step reversal can also leave intermediate derived rows until reconciliation runs.

**Recommendation:** choose either audited voids or true deletes per entity, expose one workflow, and wrap source plus all derived effects in one transaction with post-commit consistency checks.

### Medium — Preview/security headers are production-unsafe

The response hook always emits `X-Frame-Options: ALLOWALL` and `Content-Security-Policy: frame-ancestors *` to support the Arena preview. This permits clickjacking in a normal deployment.

**Recommendation:** enable the permissive headers only behind an explicit preview/development setting. Use a restricted frame ancestor and a normal CSP in production.

### Low/Medium — Legacy modules and aliases increase maintenance risk

The app registers duplicate short aliases for many blueprint routes, a demo `/module_name` blueprint, and legacy models/routes for rentals, cash drawer, and old Delivery tables. The aliases are useful for compatibility but make endpoint/permission/debugging behavior harder to reason about.

**Recommendation:** keep aliases temporarily, emit deprecation telemetry, remove the demo blueprint, and retire unused tables only after an export/migration plan.

## Recommended next sequence

1. Implement CSRF and remove plaintext password writes/fallbacks.
2. Design an immutable client identity/transfer model and repair transfer/reclaim.
3. Consolidate authorization and add a route permission matrix.
4. Journalize account opening balances and reconcile the existing DB interactively, including the orphan invoice.
5. Standardize cash/account/ledger measures and retire legacy aliases/modules.

## Conclusion

The core ERP flows are testable and the principal source-of-truth model is recoverable. The audit does **not** support declaring the current database fully clean: the account ledger baseline and one orphan invoice need explicit review, and the unresolved security/data-transfer findings are material. The code changes in this branch reduce several repeatable inconsistencies and add regression coverage, but the remaining findings should be addressed before treating the system as production-safe.
