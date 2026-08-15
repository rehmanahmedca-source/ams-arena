# Unified Ledger / Current Payables Audit

Date: 2026-08-15 (UTC)

## Scope

The payables and party-ledger redesign was traced through the Flask route layer,
service layer, SQLAlchemy models, derived PendingBill rows, account posting
services, source transaction tables, exports and existing smoke/regression
coverage. The implementation is read-side and non-destructive: no bill,
payment, stock row, ledger row or master record is deleted or merged by the
report projection.

## Authoritative read-side projection

`app/services/financial_ledgers.py` is the shared accounting projection used by:

- `/current_payables` and the legacy-compatible `/unpaid_transactions`
- `/ledger/<client_id>` (Client Ledger)
- `/supplier_ledger/<id>` (Supplier Ledger)
- `/delivery_person_ledger/<id>` and `/delivery_ledger/<id>`
- dashboard client/supplier due KPIs
- current-payables, client-detail, supplier-balance and delivery-person APIs
- client, supplier and delivery-person exports

### Client convention

`opening balance + booking/direct-sale debit - embedded paid/discount credits -
active payment receipts - returns/waive-offs + refunds` is represented as
`debit - credit`. A positive closing balance is an amount owed by the client.
Zero and credit balances are excluded from the default Current Payables view.

Bookings, direct sales, payments and legacy manual PendingBill rows are included
once. Derived PendingBill rows are ignored when their source table/source id or
bill reference identifies a Booking, DirectSale or Invoice projection. This
prevents a derived row from double-accounting its source transaction while
keeping unlinked historical/manual PendingBill rows visible in the calculation.
Historical duplicate Client master names are consolidated to one stable
summary identity while detail URLs for either legacy master row resolve to the
same name-based financial projection; this prevents duplicate payables and
prevents name-only legacy bills from disappearing.

Payments are allocated FIFO to bill detail rows for presentation only. The
allocation does not mutate `PendingBill`, `Booking`, `DirectSale` or `Payment`.
Partially paid bills therefore expose only their remaining amount; fully paid
bills remain in historical ledger detail but contribute zero to Current Payables.

### Supplier convention

GRNs (including item value, freight/loading/other cost, tax, discount and
adjustment) are credits to the supplier payable account. Supplier payments are
debits. Legacy `GRN.paid_amount` is included only when no active canonical
`SupplierPayment` auto-row exists, so old data remains accurate without double
counting new GRN payments.

### Delivery-person convention

Active `SaleDeliveryPerson.rent_amount` and unmatched legacy `DeliveryRent`
rows are debits owed to the delivery person. A legacy rent row for a sale that
already has an active delivery allocation is not added a second time. Active
`DeliveryPersonPayment` paid and waive-off amounts are credits. Payments linked
to void allocations are not allowed to affect the live balance.

## Current Payables behavior

- Groups all source obligations by Client master identity.
- Shows only positive current balances by default.
- Supports client/name/code search, amount exact/greater/less/between/range,
  start/end date, status, independent and combined filters, clear filters,
  grouped pagination and filtered totals.
- Date semantics are explicit: date filters select a client's **last
  contributing transaction date**, while the displayed amount remains the full
  current balance. Detail ledgers filter individual movements and show a
  carry-forward row when a start date is used.
- Pagination happens after client aggregation.
- `/export_current_payables` and `/export_unpaid_transactions` export the full
  filtered grouped set, not only the visible page.
- `/api/current_payables/<client_id>` returns the complete underlying financial
  movement history for drill-down.

## Audit and integrity controls

`GET /api/audit/financial-integrity` performs a read-only check for:

- duplicate active account transactions with the same structured source,
- payments pointing at missing clients,
- delivery allocations pointing at missing sales/delivery people,
- delivery settlements pointing at missing delivery people/allocations, and
- supplier payments pointing at missing suppliers, and
- active client source rows whose historical name/code cannot resolve to a
  current Client master.

The audit does not auto-delete questionable rows. Existing soft-delete/reversal
workflows remain the mutation path, and source identity/audit metadata remain
preserved. On the supplied historical database, the read-only check identifies
legacy name-only source rows that cannot resolve to a current Client master;
they are reported as `orphan_client_source` for controlled master-data review
and are not silently invented, merged or deleted.

Delivery Person received optional `opening_balance` and
`opening_balance_date` columns. Schema bootstrap adds them with the existing
non-destructive model-column upgrade mechanism; existing rows default to zero.

## Routes / API surface audited

- Current payables: `/current_payables`, `/unpaid_transactions`,
  `/api/current_payables`, `/export_current_payables`.
- Client ledger: `/ledger/<id>`, `/financial_ledger/<id>`,
  `/download_client_ledger/<id>`.
- Supplier ledger: `/supplier_ledger/<id>`, `/api/supplier_balance/<id>`,
  `/download_supplier_ledger/<id>`, supplier search API.
- Delivery person ledger: `/delivery_person_ledger/<id>`, `/delivery_ledger/<id>`,
  `/api/delivery_person_ledger/<id>`, `/download_delivery_person_ledger/<id>`,
  `/delivery_person_ledger/<id>/pay`, and opening-balance update.
- Search selectors: `/api/clients/search`, `/api/suppliers/search`,
  `/api/delivery_persons/search`.

The existing create/edit/void/restore payment services continue to use
`app.services.payments_crud` and the existing accounting synchronization. The
new pages consume those source rows; they do not introduce a second write path.

## Regression evidence

- Full test suite (existing coverage plus unified-ledger regression tests):
  **69 passed**.
- New ledger regression module: **4 passed**. It verifies grouped clients,
  partial and full payment behavior, amount filter totals, supplier running
  balance and delivery-rent de-duplication.
- Full application smoke run on a fresh isolated database: **95 passed / 0
  failed**, including all existing page GETs and CRUD smoke workflows.
- Python compilation: `python -m compileall -q app blueprints models utils`.
- A source-by-source comparison on the supplied database reconciled the new
  client projection against the existing client ledger for all **305 Client
  master rows** (no balance differences above Rs. 0.01); Supplier Ledger
  balances also reconciled for every supplied Supplier row.

## Non-destructive data guarantee

No migration rewrites or removes historical financial rows. The only schema
change is additive (`DeliveryPerson.opening_balance` and
`opening_balance_date`) through the same existing additive bootstrap routine.
Summaries are projections; individual source bills and payments remain
inspectable through the ledger and source transaction pages.
