# AMS full smoke test

Ran: **2026-08-13 08:08** as **Admin**.
Checks: **106 passed**, **0 failed**, **106 total**.

Isolated records used the `SMOKE …` prefix and were deleted where the app allowed.

## auth

| Result | Check | Detail |
|---|---|---|
| PASS | GET /login | HTTP 200 |
| PASS | POST /login Admin | HTTP 302 |

## GET pages

| Result | Check | Detail |
|---|---|---|
| PASS | GET / | HTTP 200 · System Dashboard · flashes=- |
| PASS | GET /login | HTTP 200 · System Dashboard · flashes=- |
| PASS | GET /clients | HTTP 200 · Client Ledger · flashes=['Warning: This will move ALL transaction data from "Audit Client" to another client. The source client will become inactive and cannot be used again.', 'Warning: This will move ALL tra |
| PASS | GET /materials | HTTP 200 · Material Brands · flashes=['This action cannot be undone.', 'Tip: This matches ignoring case and spaces.'] |
| PASS | GET /suppliers | HTTP 200 · Supplier Ledger · flashes=- |
| PASS | GET /delivery_persons | HTTP 200 · Delivery Persons · flashes=- |
| PASS | GET /bookings | HTTP 200 · Bookings · flashes=- |
| PASS | GET /payments | HTTP 200 · Payments Hub · flashes=['Payments are read-only . Use Accounts → New Transaction for Receive/Pay.'] |
| PASS | GET /direct_sales | HTTP 200 · Sales · flashes=- |
| PASS | GET /material_returns | HTTP 200 · AMS SYSTEM FOR EASE · flashes=- |
| PASS | GET /pending_bills | HTTP 200 · Pending Bills Filtered: 6 · flashes=['Row must have: BillNo AND ( ClientCode OR ClientName ). Blanks are accepted. Missing clients auto-created.'] |
| PASS | GET /grn | HTTP 200 · AMS SYSTEM FOR EASE · flashes=- |
| PASS | GET /dispatching | HTTP 200 · Booking Delivery (Dispatch) · flashes=- |
| PASS | GET /tracking | HTTP 200 · History & Search · flashes=- |
| PASS | GET /ledger | HTTP 200 · Ledger - Select Client · flashes=- |
| PASS | GET /decision_ledger | HTTP 200 · Decision Ledger · flashes=- |
| PASS | GET /financial_details | HTTP 200 · Cash Received Details · flashes=- |
| PASS | GET /cash_flow | HTTP 200 · Cash Flow · flashes=['Today’s list starts from 2026-08-13 13:08 on this page only. Account balances are not changed.'] |
| PASS | GET /cash_flow_differences | HTTP 200 · Cash Flow Reconciliations · flashes=- |
| PASS | GET /profit_reports | HTTP 200 · Profit Reports · flashes=- |
| PASS | GET /unpaid_transactions | HTTP 200 · Paid & Unpaid Transactions Filtered: 0 · flashes=- |
| PASS | GET /mixed_transactions | HTTP 200 · History & Search Filtered: 0 · flashes=- |
| PASS | GET /daily_transactions | HTTP 200 · Daily Breakdown · flashes=- |
| PASS | GET /delivery_rents | HTTP 200 · Delivery Person Rent · flashes=- |
| PASS | GET /notifications | HTTP 200 · Notifications · flashes=- |
| PASS | GET /notifications/upcoming | HTTP 200 · Upcoming Reminders · flashes=- |
| PASS | GET /settings | HTTP 200 · Settings · flashes=- |
| PASS | GET /settings/activity | HTTP 200 · Activity Log · flashes=- |
| PASS | GET /import_export/ | HTTP 200 · Import / Export Center · flashes=- |
| PASS | GET /import_export/history | HTTP 200 · (no title) · flashes=- |
| PASS | GET /import_export/uploads | HTTP 200 · (no title) · flashes=- |
| PASS | GET /inventory/stock_summary | HTTP 200 · Stock Summary · flashes=- |
| PASS | GET /inventory/daily_transactions | HTTP 200 · Daily Breakdown · flashes=- |
| PASS | GET /inventory/inventory_log | HTTP 200 · Stock Summary · flashes=- |
| PASS | GET /stock_summary | HTTP 200 · Stock Summary · flashes=- |
| PASS | GET /accounts/ | HTTP 200 · Accounts Dashboard · flashes=- |
| PASS | GET /accounts/accounts | HTTP 200 · Manage Accounts · flashes=- |
| PASS | GET /accounts/accounts/add | HTTP 200 · Add New Account · flashes=['Tip: A clear group makes receive/pay flows much faster later on.', 'The page will refresh after the group is created so it appears in the dropdown.'] |
| PASS | GET /accounts/receipts | HTTP 200 · Receipts · flashes=- |
| PASS | GET /accounts/transfers | HTTP 200 · Account Transfers · flashes=- |
| PASS | GET /accounts/transfers/add | HTTP 200 · New Transfer · flashes=['Insufficient balance in source account.'] |
| PASS | GET /accounts/expenditures | HTTP 200 · Expenditures · flashes=- |
| PASS | GET /accounts/payments/clients | HTTP 200 · Client Payments · flashes=- |
| PASS | GET /accounts/payments/suppliers | HTTP 200 · Supplier Payments · flashes=- |
| PASS | GET /accounts/audit | HTTP 200 · Audit Trail · flashes=- |
| PASS | GET /accounts/kpi/cash_money | HTTP 200 · Total Cash (KPI Drill-Down) · flashes=- |
| PASS | GET /accounts/kpi/bank_accounts | HTTP 200 · Bank Accounts · flashes=- |
| PASS | GET /accounts/kpi/cash_accounts | HTTP 200 · Cash Accounts · flashes=- |
| PASS | GET /accounts/kpi/client_payments | HTTP 200 · Client Payments (KPI Drill-Down) · flashes=- |
| PASS | GET /accounts/kpi/supplier_payments | HTTP 200 · Supplier Payments (KPI Drill-Down) · flashes=- |
| PASS | GET /accounts/kpi/expenditures | HTTP 200 · Expenditures (KPI Drill-Down) · flashes=- |
| PASS | GET /accounts/kpi/receipts | HTTP 200 · Receipts (KPI Drill-Down) · flashes=- |
| PASS | GET /accounts/kpi/company_money | HTTP 200 · Company Money (KPI Drill-Down) · flashes=- |
| PASS | GET /pay_supplier | HTTP 200 · Supplier Payments · flashes=- |
| PASS | GET /ams_assistant | HTTP 200 · AMS Assistant · flashes=- |
| PASS | GET /admin/ | HTTP 200 · Admin Dashboard · flashes=- |
| PASS | GET /admin/modules | HTTP 200 · Loaded Modules · flashes=- |
| PASS | GET /admin/api/health | HTTP 200 · (no title) · flashes=- |
| PASS | GET /admin/api/modules | HTTP 200 · (no title) · flashes=- |
| PASS | GET /system_report | HTTP 200 · System Report · flashes=['No stock discrepancies found. All material balances match.'] |
| PASS | GET /void_audit | HTTP 200 · Deleted / Suspended Audit · flashes=- |
| PASS | GET /debug/db | HTTP 200 · (no title) · flashes=- |
| PASS | GET /api/notifications/due | HTTP 200 · (no title) · flashes=- |
| PASS | GET /api/client_next_code | HTTP 200 · (no title) · flashes=- |
| PASS | GET /api/material_next_code | HTTP 200 · (no title) · flashes=- |
| PASS | GET /api/clients/search | HTTP 200 · (no title) · flashes=- |
| PASS | GET /api/ui/theme | HTTP 200 · (no title) · flashes=- |

## GET with IDs

| Result | Check | Detail |
|---|---|---|
| PASS | GET /ledger/1 | HTTP 200 · flashes=- |
| PASS | GET /client_ledger/1 | HTTP 200 · flashes=- |
| PASS | GET /financial_ledger/1 | HTTP 200 · flashes=- |
| PASS | GET /api/client_booking_status/AUD-001 | HTTP 200 · flashes=- |
| PASS | GET /api/client_financial_summary/AUD-001 | HTTP 200 · flashes=- |
| PASS | GET /material_ledger/1 | HTTP 200 · flashes=- |
| PASS | GET /accounts/ledger/1 | HTTP 200 · flashes=- |
| PASS | GET /accounts/1/data | HTTP 200 · flashes=- |
| PASS | GET /supplier_ledger/1 | HTTP 200 · flashes=['Supplier payments are read-only . Use Accounts → New Transaction for supplier payments.'] |
| PASS | GET /api/supplier_balance/1 | HTTP 200 · flashes=- |

## CRUD create

| Result | Check | Detail |
|---|---|---|
| PASS | Create client | ['Client Registered — by Admin', 'Warning: This will move ALL transaction data from "Audit Client" to another client. The source client will become inactive and cannot be used again.', 'Warning: This will move ALL transa |
| PASS | Create material | ['Brand Added — by Admin', 'This action cannot be undone.', 'Tip: This matches ignoring case and spaces.'] |
| PASS | Create supplier | ['Supplier Added — by Admin'] |
| PASS | Create cash account (Accounts) | ['Account added successfully! — by Admin'] |
| PASS | Client persisted | id=3 |
| PASS | Material persisted | SMOKE MAT 080855 |
| PASS | Account persisted | id=6 |
| PASS | Supplier persisted | id=3 |
| PASS | Create GRN | ['GRN added successfully! — by Admin'] |
| PASS | Create booking (unpaid) | ['Booking added successfully â€” Pending amount: 10000.0 — by Admin'] |
| PASS | Create credit sale | ['Direct sale added successfully â€” Invoice: MB NO.SMK-BILL-080855 — by Admin'] |
| PASS | Create client payment | ['Payment received successfully - applied to: SB-BK-1003: partial Rs.500.00 — by Admin', 'Payments are read-only . Use Accounts → New Transaction for Receive/Pay.'] |
| PASS | Create material return | ['Material return saved successfully. — by Admin'] |
| PASS | Create pending bill | ['Pending bill added — by Admin', 'Row must have: BillNo AND ( ClientCode OR ClientName ). Blanks are accepted. Missing clients auto-created.'] |
| PASS | Create cash-flow spend | ['Spent Rs. 100 recorded. — by Admin', 'Today’s list starts from 2026-08-13 13:08 on this page only. Account balances are not changed.'] |
| PASS | Accounts receive (other source) | ['Receive transaction recorded successfully. — by Admin'] |

## CRUD edit

| Result | Check | Detail |
|---|---|---|
| PASS | Edit client name | ['Client updated — by Admin', 'Warning: This will move ALL transaction data from "Audit Client" to another client. The source client will become inactive and cannot be used again.', 'Warning: This will move ALL transacti |
| PASS | Edit material | ['Brand Updated — by Admin', 'This action cannot be undone.', 'Tip: This matches ignoring case and spaces.'] |
| PASS | Edit payment | ['Payment updated — by Admin'] |

## CRUD delete

| Result | Check | Detail |
|---|---|---|
| PASS | Delete payment | ['Payment deleted — by Admin'] |
| PASS | Delete booking | ['Booking deleted — by Admin'] |
| PASS | Delete material return | ['MaterialReturn deleted — by Admin'] |
| PASS | Delete smoke client | ['Client suspended — by Admin', 'Warning: This will move ALL transaction data from "Audit Client" to another client. The source client will become inactive and cannot be used again.', 'Warning: This will move ALL transac |
| PASS | Delete smoke material | ['Material status updated — by Admin', 'This action cannot be undone.', 'Tip: This matches ignoring case and spaces.'] |
| PASS | Delete smoke supplier | ['Cannot delete supplier with existing GRNs. Deactivate instead. — by Admin'] |

## CRUD update

| Result | Check | Detail |
|---|---|---|
| PASS | Deactivate smoke account | ['Account deactivated. — by Admin'] |

## audit

| Result | Check | Detail |
|---|---|---|
| PASS | Audit log has Admin rows | count=59 |

## Raw create / edit / delete flashes

- **CREATE client** — HTTP 200 — ['Client Registered — by Admin', 'Warning: This will move ALL transaction data from "Audit Client" to another client. The source client will become inactive and cannot be used again.', 'Warning: This will move ALL transaction data from "SMOKE Client 080847 Edited" to another client. The source client will become inactive and cannot be used again.', 'Warning: This will move ALL transaction data from "SMOKE Client 080855" to another client. The source client will become inactive and cannot be used again.']
- **CREATE material** — HTTP 200 — ['Brand Added — by Admin', 'This action cannot be undone.', 'Tip: This matches ignoring case and spaces.']
- **CREATE supplier** — HTTP 200 — ['Supplier Added — by Admin']
- **CREATE account** — HTTP 200 — ['Account added successfully! — by Admin']
- **CREATE GRN** — HTTP 200 — ['GRN added successfully! — by Admin']
- **CREATE booking** — HTTP 200 — ['Booking added successfully â€” Pending amount: 10000.0 — by Admin']
- **CREATE credit sale** — HTTP 200 — ['Direct sale added successfully â€” Invoice: MB NO.SMK-BILL-080855 — by Admin']
- **CREATE payment** — HTTP 200 — ['Payment received successfully - applied to: SB-BK-1003: partial Rs.500.00 — by Admin', 'Payments are read-only . Use Accounts → New Transaction for Receive/Pay.']
- **CREATE return** — HTTP 200 — ['Material return saved successfully. — by Admin']
- **CREATE pending bill** — HTTP 200 — ['Pending bill added — by Admin', 'Row must have: BillNo AND ( ClientCode OR ClientName ). Blanks are accepted. Missing clients auto-created.']
- **CREATE cash flow spend** — HTTP 200 — ['Spent Rs. 100 recorded. — by Admin', 'Today’s list starts from 2026-08-13 13:08 on this page only. Account balances are not changed.']
- **CREATE accounts receive** — HTTP 200 — ['Receive transaction recorded successfully. — by Admin']
- **EDIT client** — HTTP 200 — ['Client updated — by Admin', 'Warning: This will move ALL transaction data from "Audit Client" to another client. The source client will become inactive and cannot be used again.', 'Warning: This will move ALL transaction data from "SMOKE Client 080847 Edited" to another client. The source client will become inactive and cannot be used again.', 'Warning: This will move ALL transaction data from "SMOKE Client 080855 Edited" to another client. The source client will become inactive and cannot be used again.']
- **EDIT material** — HTTP 200 — ['Brand Updated — by Admin', 'This action cannot be undone.', 'Tip: This matches ignoring case and spaces.']
- **EDIT payment** — HTTP 200 — ['Payment updated — by Admin']
- **DELETE payment** — HTTP 200 — ['Payment deleted — by Admin']
- **DELETE booking** — HTTP 200 — ['Booking deleted — by Admin']
- **DELETE return** — HTTP 200 — ['MaterialReturn deleted — by Admin']
- **TOGGLE account** — HTTP 200 — ['Account deactivated. — by Admin']
- **DELETE client** — HTTP 200 — ['Client suspended — by Admin', 'Warning: This will move ALL transaction data from "Audit Client" to another client. The source client will become inactive and cannot be used again.', 'Warning: This will move ALL transaction data from "SMOKE Client 080847 Edited" to another client. The source client will become inactive and cannot be used again.']
- **DELETE material** — HTTP 200 — ['Material status updated — by Admin', 'This action cannot be undone.', 'Tip: This matches ignoring case and spaces.']
- **DELETE supplier** — HTTP 200 — ['Cannot delete supplier with existing GRNs. Deactivate instead. — by Admin']

