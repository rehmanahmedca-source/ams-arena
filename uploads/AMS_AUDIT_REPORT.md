# AMS APPLICATION — COMPLETE AUDIT REPORT
**Date:** 2026-08-05  
**Type:** Read-Only Discovery & Business Logic Audit  
**Scope:** Full codebase — main.py (21,421 lines), models.py (48 KB), blueprints/, templates/, utils/, tools/

---

## EXECUTIVE SUMMARY

The AMS application is a Flask-based, single-database ERP system covering bookings, direct sales, GRN/purchasing, inventory (FIFO), client/supplier ledgers, accounts, deliveries, FBM rentals, notifications, cash-flow reconciliation, and multi-tenant management. The application is architecturally sound and contains solid self-healing reconciliation infrastructure. However, there are **two active runtime crashes**, one **critical missing model field**, several **native-select dropdowns that will degrade badly at scale**, and a number of **business logic synchronization gaps** that can cause data inconsistency.

---

## 1. COMPLETE MODULE INVENTORY

| Module | Blueprint / Path | URL Prefix | Purpose |
|---|---|---|---|
| Core ERP | `main.py` | `/` | Bookings, sales, payments, GRN, inventory, ledger, reports, clients, suppliers, dispatching, materials, notifications, cash flow, reconciliation, admin |
| Accounts | `blueprints/accounts.py` | `/accounts` | Account management, ledger, transfers, expenditures, receipts, KPIs, audit trail |
| Admin | `blueprints/admin.py` | `/admin` | Module management, system-level admin actions |
| FBM Rentals | `blueprints/fbm_rentals.py` | `/fbm_rentals` | Equipment rental clients, rental records, returns, transfers, payments, reports |
| Inventory | `blueprints/inventory.py` | `/inventory` | Stock summary, material-level ledger, stock movement |
| Data Lab | `blueprints/data_lab.py` | `/data_lab` | Analytical/data exploration interface |
| Import/Export | `blueprints/import_export.py` | `/import_export` | Bulk import (CSV/Excel) and export of records |

---

## 2. COMPLETE FUNCTION INVENTORY

### 2.1 Bookings Module (`/bookings`)
| Item | Detail |
|---|---|
| **Purpose** | Manage client material bookings (advance reservations) |
| **Route GET** | `/bookings` |
| **Route POST** | `/add_booking`, `/edit_bill/Booking/<id>`, `/client_booking_cancel/<id>`, `/client_booking_cancel_revert/<id>/<entry_id>` |
| **Main Functions** | Create booking with items, edit booking, cancel booking, FIFO queue display per material per client |
| **Buttons** | Add Booking, Edit, Cancel Booking, Revert Cancel, Void, View Bill |
| **Filters** | Client code/name (combobox), date from/to, status |
| **DB Tables** | `booking`, `booking_item`, `booking_allocation`, `entry`, `pending_bill`, `invoice`, `material` |

### 2.2 Direct Sales Module (`/direct_sales`)
| Item | Detail |
|---|---|
| **Purpose** | Record sales of materials to clients with FIFO costing |
| **Route GET** | `/direct_sales` |
| **Route POST** | `/add_direct_sale`, `/add_sale`, `/edit_bill/DirectSale/<id>`, `/void_transaction/DirectSale/<id>`, `/unvoid_transaction/DirectSale/<id>`, `/direct_sales/hold`, `/direct_sales/hold/<id>/resume`, `/direct_sales/hold/<id>/delete` |
| **Main Functions** | Create sale with line items, FIFO GRN batch assignment, booking allocation deduction, pending bill creation, account credit, Hold/Resume drafts |
| **Buttons** | Add Sale, Edit, Void, Restore, Delete, Hold, Resume, View Bill, Export PDF/Excel |
| **Filters** | Client, date range, status |
| **DB Tables** | `direct_sale`, `direct_sale_item`, `direct_sale_draft`, `grn_item`, `booking_allocation`, `entry`, `pending_bill`, `invoice`, `account`, `account_transaction` |

### 2.3 Payments Module (`/payments`)
| Item | Detail |
|---|---|
| **Purpose** | Record and manage client payments (cash/bank) |
| **Route GET** | `/payments` |
| **Route POST** | `/add_payment`, `/edit_bill/Payment/<id>`, `/delete_payment/<id>`, `/void_transaction/Payment/<id>`, `/unvoid_transaction/Payment/<id>` |
| **Main Functions** | Create payment, apply to pending bills (settlement logic), discount/waive-off recording, account credit |
| **Buttons** | Add Payment, Edit, Void, Restore, Delete, View Bill |
| **Filters** | Client, date range, method, status |
| **DB Tables** | `payment`, `waive_off`, `pending_bill`, `account`, `account_transaction` |

### 2.4 GRN Module (`/grn`)
| Item | Detail |
|---|---|
| **Purpose** | Goods Received Notes — record stock purchases from suppliers |
| **Route GET/POST** | `/grn`, `/edit_grn/<id>`, `/export_grn`, `/grn/payments/add`, `/grn/payments/<id>/edit`, `/grn/payments/<id>/void`, `/grn/payments/<id>/restore` |
| **Main Functions** | Create GRN with line items, partial payment, tax support, supplier balance tracking, FIFO batch registration |
| **Buttons** | Add GRN, Edit, Void Payment, Restore Payment, Export GRN |
| **Filters** | Supplier, date range |
| **DB Tables** | `grn`, `grn_item`, `supplier`, `supplier_payment`, `entry`, `material`, `account` |

### 2.5 Material Returns (`/material_returns`)
| Item | Detail |
|---|---|
| **Purpose** | Record materials returned by clients |
| **Route GET** | `/material_returns` |
| **Route POST** | `/add_material_return`, `/edit_material_return/<id>` |
| **Main Functions** | Create return, reverse inventory entries, update pending bills or create credit |
| **Buttons** | Add Return, Edit, Void |
| **Filters** | Client, date range |
| **DB Tables** | `material_return`, `material_return_item`, `entry`, `pending_bill`, `payment` |

### 2.6 Supplier Payments (`/pay_supplier`, `/supplier_ledger`)
| Item | Detail |
|---|---|
| **Purpose** | Pay suppliers, view supplier ledger |
| **Routes** | `/pay_supplier`, `/add_supplier_payment`, `/edit_supplier_payment/<id>`, `/delete_supplier_payment/<id>`, `/restore_supplier_payment/<id>`, `/supplier_ledger/<id>`, `/download_supplier_ledger/<id>`, `/download_supplier_payment/<payment_id>` |
| **Buttons** | Pay Supplier, Edit, Delete, Restore, Download Ledger, Download Receipt |
| **Filters** | Supplier, date range, method |
| **DB Tables** | `supplier_payment`, `supplier`, `account`, `account_transaction` |

### 2.7 Dispatching Module (`/dispatching`)
| Item | Detail |
|---|---|
| **Purpose** | Log raw dispatch entries (material movements) |
| **Routes** | `/dispatching`, `/add_record`, `/edit_entry/<id>`, `/delete_entry/<id>`, `/import_dispatch_data` |
| **Buttons** | Add Record, Edit, Delete, Import |
| **Filters** | Client, material, date |
| **DB Tables** | `entry` |

### 2.8 Ledger Module (`/ledger`, `/client_ledger`, `/financial_ledger`)
| Item | Detail |
|---|---|
| **Purpose** | View per-client ledger, full financial history, material ledger |
| **Routes** | `/ledger`, `/ledger/<client_id>`, `/client_ledger/<id>`, `/financial_ledger/<id>`, `/material_ledger/<mat_id>`, `/decision_ledger`, `/download_client_ledger/<id>`, `/download_full_client_history/<id>` |
| **Main Functions** | Compute running balance, display all transactions, download PDF ledger |
| **DB Tables** | `entry`, `invoice`, `payment`, `booking`, `direct_sale`, `material_return`, `pending_bill`, `client` |

### 2.9 Pending Bills (`/pending_bills`)
| Item | Detail |
|---|---|
| **Purpose** | Track outstanding receivables with risk scoring and follow-up workflows |
| **Routes** | `/pending_bills`, `/add_pending_bill`, `/edit_pending_bill/<id>`, `/delete_pending_bill/<id>`, `/toggle_bill_paid/<id>`, `/export_pending_bills`, `/export_unpaid_transactions`, `/import_pending_bills` |
| **Buttons** | Add, Edit, Delete, Mark Paid, Export PDF, Export Excel, Import |
| **Filters** | Client, date range, status, risk level |
| **DB Tables** | `pending_bill`, `follow_up_reminder`, `follow_up_contact` |

### 2.10 Notifications Module (`/notifications`)
| Item | Detail |
|---|---|
| **Purpose** | Reminder system for overdue pending bills, email alerts |
| **Routes** | `/notifications`, `/notifications/upcoming`, `/notifications/add_email`, `/notifications/toggle_email/<id>`, `/notifications/delete_email/<id>`, `/notifications/set_reminder/<bill_id>`, `/notifications/log_contact/<bill_id>`, `/notifications/close_reminder/<id>`, `/notifications/set_severity/<bill_id>`, `/notifications/bill/<bill_id>`, `/notifications/ack_reminder/<id>`, `/notifications/send_daily_now`, `/api/notifications/due`, `/api/notifications/contact_history/<bill_id>` |
| **Background** | `_notification_worker_loop()` — daily email digest |
| **DB Tables** | `pending_bill`, `follow_up_reminder`, `follow_up_contact`, `staff_email` |

### 2.11 Accounts Module (`/accounts`)
| Item | Detail |
|---|---|
| **Purpose** | Double-entry account management, transfers, expenditures, KPIs |
| **Routes** | `/accounts/dashboard`, `/accounts/manage`, `/accounts/add`, `/accounts/<id>/edit`, `/accounts/<id>/ledger`, `/accounts/add_transaction`, `/accounts/add_transfer`, `/accounts/expenditures`, `/accounts/supplier_payments`, `/accounts/client_payments`, `/accounts/receipts`, `/accounts/transfers`, `/accounts/audit`, KPI sub-pages |
| **DB Tables** | `account`, `account_category`, `account_transaction` |

### 2.12 FBM Rentals Module (`/fbm_rentals`)
| Item | Detail |
|---|---|
| **Purpose** | Equipment rental management — clients, rentals, returns, transfers, payments |
| **Routes** | `/fbm_rentals/dashboard`, `/fbm_rentals/clients`, `/fbm_rentals/rentals`, `/fbm_rentals/rentals/return`, `/fbm_rentals/rentals/transfer`, `/fbm_rentals/client_payment`, `/fbm_rentals/client_ledger`, `/fbm_rentals/inventory`, `/fbm_rentals/reports` |
| **DB Tables** | `fbm_client`, `fbm_rental`, `fbm_rental_item`, `account` |

### 2.13 Cash Drawer (`/fbm_cash_drawer`)
| Item | Detail |
|---|---|
| **Purpose** | Manual cash-in / cash-out log for the FBM till |
| **Routes** | `/fbm_cash_drawer`, `/fbm_cash_drawer/add`, `/fbm_cash_drawer/edit/<id>`, `/fbm_cash_drawer/category/add`, `/fbm_cash_drawer/category/edit/<id>`, `/fbm_cash_drawer/category/toggle/<id>`, `/fbm_cash_drawer/void/<id>` |
| **DB Tables** | `fbm_cash_drawer_entry`, `fbm_cash_drawer_category` |

### 2.14 Cash Flow & Reconciliation (`/cash_flow`)
| Item | Detail |
|---|---|
| **Purpose** | Physical cash vs system cash reconciliation, daily cash flow tracking |
| **Routes** | `/cash_flow`, `/cash_flow_differences`, `/cash_flow_differences/<rec_id>`, `/reconcile_data` |
| **DB Tables** | `cash_flow_difference_adjustment`, `cash_flow_reconciliation_audit` |

### 2.15 Profit Reports (`/profit_reports`)
| Item | Detail |
|---|---|
| **Purpose** | Revenue, cost, gross profit per sale/period |
| **DB Tables** | `direct_sale`, `direct_sale_item`, `grn_item`, `delivery_rent` |

### 2.16 Delivery & Delivery Persons (`/deliveries`, `/delivery_persons`, `/delivery_rents`)
| Item | Detail |
|---|---|
| **Routes** | `/deliveries`, `/delivery_persons`, `/delivery_rents` |
| **DB Tables** | `delivery`, `delivery_item`, `delivery_person`, `sale_delivery_persons`, `delivery_person_payment`, `delivery_rent` |

### 2.17 Tracking (`/tracking`)
| Item | Detail |
|---|---|
| **Purpose** | Per-client material tracking dashboard |
| **DB Tables** | `entry`, `booking`, `client` |

### 2.18 Settings & Admin (`/settings`, `/admin`)
| Item | Detail |
|---|---|
| **Routes** | `/settings`, `/add_user`, `/edit_user_permissions/<id>`, `/delete_user/<id>`, `/change_password`, `/void_audit`, `/void_audit/restore/<entity>/<id>`, `/admin/rebuild_erp_consistency`, `/generate_dummy_data`, `/delete_all_data`, `/delete_selected_data`, `/admin/accounts_domain_wipe`, `/data_wipe_preview` |
| **DB Tables** | `user`, `audit_log`, `system_lock` |

### 2.19 Tenants / Multi-tenant (`/tenants`)
| Item | Detail |
|---|---|
| **Routes** | `/tenants`, `/tenants/create`, `/tenants/<id>/reset_admin`, `/tenants/<id>/status`, `/tenants/<id>/update`, `/tenants/<id>/delete`, `/tenants/<id>/backup_history`, `/tenants/backup_history/download/<id>`, `/tenants/backup_history/restore/<id>` |
| **DB Tables** | Tenant management tables |

### 2.20 Root Backup (`/root`)
| Item | Detail |
|---|---|
| **Routes** | `/root/backup-settings`, `/root/backup-settings/save`, `/root/backup-settings/send-now`, `/root/backup-settings/history/download/<id>`, `/root/backup-settings/history/clear` |
| **Background** | `_hourly_backup_worker_loop()` — automated DB backup & email dispatch |
| **DB Tables** | `root_backup_settings`, `root_backup_email_history` |

### 2.21 Other Modules
| Module | Routes |
|---|---|
| Clients | `/clients`, `/add_client`, `/edit_client/<id>`, `/client_opening_balance/<id>`, `/delete_client/<id>`, `/clients/activate_all`, `/export_clients` |
| Suppliers | `/suppliers`, add/edit/delete supplier routes |
| Materials | `/materials`, `/add_material`, `/stock_summary` |
| Mixed Transactions | `/mixed_transactions` |
| Unpaid Transactions | `/unpaid_transactions` |
| Financial Details | `/financial_details` |
| System Report | `/system_report`, `/fix_system_issues` |
| Daily Transactions | `/daily_transactions` |
| Void Audit | `/void_audit` |
| Decision Ledger | `/decision_ledger` |
| AMS Assistant | `/ams_assistant`, `/api/ams_assistant/chat`, `/api/ams_assistant/export/<token>` |
| Data Lab | `/data_lab` |
| Import/Export | `/import_export`, `/import_export_new`, `/full_raw_import_history` |
| View/Download Bill | `/view_bill/<bill_no>`, `/download_invoice/<bill_no>`, `/view_bill_detail/<type>/<id>` |

---

## 3. MISSING BUTTONS — BY PAGE

| Page | Missing Button | Severity | Notes |
|---|---|---|---|
| **GRN (`/grn`)** | Delete GRN | Medium | No hard-delete or soft-delete for entire GRN records; only payment void is available |
| **GRN (`/grn`)** | Print/Download GRN Receipt | Medium | `/export_grn` exports all GRNs as a list but no per-GRN PDF download |
| **Material Returns** | Void Return | High | No void action on material returns; only edit exists. A voided return should reverse inventory and ledger |
| **Dispatching** | Bulk Delete / Bulk Void | Low | Only per-row delete, no bulk operation |
| **Delivery Persons** | View Delivery History per Person | Medium | No drill-down page for a delivery person's complete history |
| **Delivery Rents** | Edit Delivery Rent | Medium | Only view/list; no edit route found |
| **Tracking** | Export / Print Tracking Report | Low | No export for per-client tracking data |
| **FBM Rentals / Rentals** | Hard Delete Rental | Low | Only active/return/transfer; no delete for test/erroneous records |
| **FBM Rentals / Client Ledger** | Export PDF/Excel Ledger | Medium | Supplier ledger has download; FBM client ledger has no download button |
| **Cash Flow** | Export Cash Flow Report | Medium | No PDF/Excel export for cash flow reconciliation data |
| **Profit Reports** | Export Excel | Medium | No Excel export; PDF only |
| **Daily Transactions** | Export Daily Transactions | Low | No export button |
| **Mixed Transactions** | Export | Low | No export found |
| **Decision Ledger** | Export | Low | No export found |
| **Void Audit** | Bulk Restore | Low | Only per-record restore |
| **Clients** | Deactivate All / Export PDF | Low | Activate-all exists; deactivate-all missing; export is CSV only |
| **AMS Assistant** | Clear History | Low | No conversation reset button visible |

---

## 4. MISSING SEARCHABLE DROPDOWNS — BY PAGE AND FIELD

| Page | Field | Current Control | Recommended Control | Reason |
|---|---|---|---|---|
| **GRN Add Form** (`/grn`) | Material Name (`mat_name[]`) | Native HTML `<select>` | Combobox / TomSelect | When materials grow to 50+, scrolling a plain select is slow and error-prone |
| **Pay Supplier** (`/pay_supplier`) | Supplier (`supplier_id`) | Native HTML `<select>` | Combobox / TomSelect | Suppliers list can grow; native select has no search; misselection risk high since this posts money |
| **Pay Supplier** (`/pay_supplier`) | Account (`payment_account_id`) | Native HTML `<select>` | TomSelect (smaller risk) | Account count is usually small but inconsistent with rest of app |
| **Delivery Rents** (`/delivery_rents`) | Driver (`driver`) | Native HTML `<select>` | Combobox / TomSelect | Drivers list grows; inconsistent with other fields in the app |
| **FBM Rentals — Add Rental** | Client (`client_id`) | Native HTML `<select>` | Combobox | FBM clients can grow; rest of the app uses combobox for clients |
| **FBM Rentals — Add Rental** | Item (`item_id`) | Native HTML `<select>` | Combobox | Inventory items may grow |
| **FBM Rentals — Rental Return** | Account (`payment_account_id`) | Native HTML `<select>` | TomSelect | Accounts may be numerous |
| **FBM Rentals — Transfer** | New Client (`new_client_id`) | Native HTML `<select>` | Combobox | High mis-selection risk when transferring rental to wrong client |
| **FBM Rentals — Reports** | Client (`client_id`) filter | Native HTML `<select>` | TomSelect | Filter UX degrades with large client count |
| **FBM Rentals — Reports** | Item (`item_id`) filter | Native HTML `<select>` | TomSelect | Filter UX degrades |
| **FBM Rentals — Client Payment** | Account (`payment_account_id`) | Native HTML `<select>` | TomSelect | Inconsistency with main payment module |
| **Accounts — New Transaction Modal** | Account dropdowns (multiple) | Native HTML `<select>` | TomSelect | Account list grows with multi-account setups |

**Well-implemented searchable dropdowns (already correct):**  
Client selection in: Bookings, Payments, Material Returns, Dispatching, Client Ledger search, Receiving.  
Material selection in: Bookings, Dispatching, Receiving, GRN Wizard (supplier + material use combobox).

---

## 5. BUSINESS LOGIC RISKS

### BL-01 — `DirectSale` Model Missing `client_code` Field ⛔ ACTIVE CRASH
- **Evidence:** `errorlog.txt` shows 4 occurrences of `'DirectSale' object has no attribute 'client_code'` on 2026-08-04.
- **Root cause:** `DirectSale` model (line 426, `models.py`) has `client_name` but **no `client_code` column**. Code in `main.py` references `sale.client_code` in several places (pending bill sync, ledger rebuild, FIFO entry generation).
- **Impact:** Direct sale creation and/or editing silently fails or crashes. Pending bills and ledger entries for affected sales may be missing or corrupt.
- **Risk level:** **CRITICAL** — financial records are incomplete for every sale that triggered this error.

### BL-02 — Bookings Page Hard Crash ⛔ ACTIVE CRASH
- **Evidence:** `errorlog.txt` — `jinja2.exceptions.TemplateAssertionError: No filter named 'enumerate'` at `templates/bookings.html` line 705.
- **Root cause:** Template uses `mq.rows | enumerate` which is not a registered Jinja2 filter. Jinja2 does not expose Python's built-in `enumerate` as a filter.
- **Impact:** The entire `/bookings` page returns a 500 error. No user can view or manage bookings.
- **Risk level:** **CRITICAL** — core module inaccessible.

### BL-03 — Payment Settlement Logic Race Condition
- `_apply_settlement_to_pending_bills_for_client()` matches pending bills by `client_name` string comparison, not by a client foreign key. If a client name is spelled differently across records, payments will not settle the correct pending bills.
- **Impact:** Pending bill balances remain incorrect; client ledger balance is wrong.

### BL-04 — Void Does Not Always Reverse Account Transactions
- `_set_payment_void_state()` flips `is_void` on the payment but the corresponding `AccountTransaction` reversal must be explicitly triggered. If the account transaction reversal step is not reached (e.g., due to the `client_code` crash in BL-01), the account balance remains credited even though the sale was voided.
- **Impact:** Account balance inflated; ledger inconsistency.

### BL-05 — FIFO Batch Not Locked During Multi-Item Sales
- `_fifo_grn_item_for_material()` selects the oldest unconsumed GRN batch. For a sale with multiple line items of the same material, each item calls FIFO independently. Without a row-level lock, two concurrent sales could select the same GRN batch.
- **Impact:** Over-consumption of a GRN batch; stock count becomes negative or incorrect; COGS miscalculated.

### BL-06 — Booking `paid_amount` Not Updated on Payment Void
- When a payment is voided, `_sync_booking_pending_bill()` re-evaluates pending bills but the `Booking.paid_amount` field may not be decremented. This means the booking shows more paid than was actually received.
- **Impact:** Client appears to have paid for their booking when the payment was voided.

### BL-07 — Material Return Type Determines Inventory and Ledger Path
- `add_material_return` handles "return to stock" vs "exchange" vs "credit note" via a `return_type` field. If this field is not validated server-side, a crafted POST can create a return with an invalid type, potentially applying a stock increase without a corresponding credit.
- **Impact:** Inventory inflated without supplier/client ledger credit.

### BL-08 — `DirectSaleDraft` (Hold) Payload Not Validated on Resume
- When resuming a held draft, the JSON `payload` stored in `direct_sale_draft.payload` is deserialized and used directly. If prices or stock changed between hold and resume, the sale is posted at stale prices with potentially unavailable GRN batches.
- **Impact:** Sales posted at wrong price; FIFO may reference an exhausted or voided GRN batch.

### BL-09 — Supplier Opening Balance Not Represented in Ledger
- `Supplier` model has `opening_balance` and `opening_balance_date` fields but there is no corresponding `Entry` or `AccountTransaction` record generated for this balance. The supplier ledger calculates balance from GRNs and payments only, meaning the opening balance is either shown as a UI annotation or ignored.
- **Impact:** Supplier ledger starting balance may be incorrect for imported/migrated data.

### BL-10 — `WaiveOff` Records Are Not Reversed on Payment Void
- `WaiveOff` rows are linked to a `Payment` via FK. When a payment is voided, the waive-off amounts should also be reversed in the client ledger. It is not confirmed that this reversal is implemented.
- **Impact:** A voided payment's waive-off discount remains in effect; client balance understated.

---

## 6. DATA INTEGRITY RISKS

### DI-01 — `Entry` Table Used as Universal Ledger Without FK to Source
- `Entry` has `source_module`, `source_table`, `source_id`, `source_bill_no` as loose string/int references rather than real foreign keys. If a source record is deleted or hard-deleted, its `Entry` rows become orphans with no way to trace them.
- **Impact:** Material stock calculations (which sum Entry rows) may include orphaned entries and report incorrect stock.

### DI-02 — `PendingBill` Not Automatically Cleared on Direct Sale Cash Payment
- When a direct sale is cash (`is_cash=True`), a `PendingBill` should either not be created or be immediately marked paid. If `_sync_direct_sale_pending_bill()` creates a pending bill regardless of payment method, cash sales will appear as outstanding receivables.

### DI-03 — `Account.balance` Is a Cached Denormalized Field
- `Account.balance` is updated on each transaction but is also periodically corrected by `reconcile_account_balances()`. If a transaction errors mid-flight (e.g., due to BL-01 crash), the `account_transaction` row may not be committed while the `account.balance` was already modified in the session, leaving the balance off by the transaction amount until the next reconciliation cycle.

### DI-04 — `Material.total` (Stock) Is a Cached Denormalized Field
- Same risk as DI-03. `Material.total` is the cached stock count, corrected by `reconcile_material_totals()`. Crashes between the entry write and the material total update leave stock temporarily wrong.

### DI-05 — `BillCounter` Sequence Not Protected Against Concurrent Requests
- `get_next_bill_no()` reads the counter, increments it, and writes it back. Without database-level row locking (e.g., `SELECT FOR UPDATE`), two simultaneous bill submissions could receive the same auto bill number.
- **Impact:** Duplicate bill numbers; bill lookup by number returns wrong record.

### DI-06 — Hard Delete Routes for Bills Without Audit Trail
- `/delete_bill/<type>/<id>` performs a hard delete. The `AuditLog` records the action but the deleted record's data is not preserved. For financial records (payments, GRNs, sales), this is a permanent data loss with no recovery path from within the application.

### DI-07 — `BookingAllocation` Not Voided When Parent Sale Is Voided
- `BookingAllocation` links a direct sale to a booking item. If a direct sale is voided, the booking item's allocated quantity should be released back to the booking. If this release is not performed atomically, the booking shows stock allocated to a voided sale.

### DI-08 — `DeliveryRent` Costs Not Reversed on Sale Void
- `DeliveryRent` records are tied to a `DirectSale`. The profit calculation subtracts `delivery_rent_cost` from `DirectSale`. If a sale is voided and the delivery rent is not also voided, the cost still appears in profit calculations for the period.

---

## 7. CALCULATION RISKS

### CR-01 — FIFO COGS May Use Wrong GRN Batch After GRN Edit
- `/edit_grn/<id>` allows editing GRN item quantities and unit rates. `DirectSaleItem.grn_item_id` stores which GRN batch was used at sale time. After a GRN edit, the rate stored on `grn_item` changes, but the historical sale's COGS (computed live from `grn_item.unit_rate`) changes retroactively — historical profit reports are re-calculated with the new rate rather than the rate at the time of sale.
- **Impact:** Profit reports are not historically stable; past periods change when GRN data is edited.

### CR-02 — `DirectSale.amount` vs Sum of `DirectSaleItem` Prices
- `DirectSale.amount` is stored as a scalar. If items are edited post-creation without recalculating `DirectSale.amount`, the header total diverges from the line-item sum. Ledger entries and pending bills use the header `amount` while profit calculations may use the line-item sum.

### CR-03 — Discount Applied at Payment Level Not Reflected in Per-Bill Settlement
- `Payment.discount` is a global discount on the payment. `_apply_settlement_to_pending_bills_for_client()` must distribute this discount proportionally across settled bills. If the distribution logic rounds incorrectly or does not handle partial payments across multiple bills, individual bill balances will be off by rounding differences.

### CR-04 — Supplier Balance Calculation
- Supplier balance = sum of GRN totals − sum of payments. If a GRN is voided but its payment is not, or a payment is voided but the GRN is not, the balance computation will be wrong. No cross-check enforces that GRN void status and payment void status are synchronized.

### CR-05 — Cash Flow `physical_cash_available` vs `calculated_closing`
- The cash flow reconciliation compares physical cash entered by the user against the system-calculated closing balance. The `difference` field stores the gap. There is no enforcement that the difference is zero before the next period opens; periods can be opened with an unresolved discrepancy, which compounds into subsequent periods.

### CR-06 — FBM Rental Billing (Per Day vs Per Unit)
- `FBMRental` supports `rent_per_day` and `rent_per_unit` pricing modes. If the rental type changes between creation and return (e.g., via an edit), the billed amount at return may use a different rate than the one agreed at creation. No snapshot of the rate at rental time is stored in the model.

### CR-07 — `DeliveryPersonPayment` vs `SaleDeliveryPerson` Allocation
- Delivery person payments are allocated per sale via `delivery_person_payment.allocation_id`. If the allocation is edited (sale items changed), the payment amounts allocated may no longer match the actual delivery costs, silently creating a gap in delivery cost accounting.

---

## 8. UI / WORKFLOW GAPS

### UX-01 — No Confirmation Modal for Hard Delete
- Routes like `/delete_payment/<id>`, `/delete_bill/<type>/<id>`, `/delete_supplier_payment/<id>`, `/delete_client/<id>` accept a POST and immediately delete. While some templates may have a JS `confirm()` dialog, there is no server-side double-confirmation token (CSRF aside). A user who accidentally submits loses data permanently.

### UX-02 — Edit GRN Has No Void-and-Recreate Flow
- The GRN edit route (`/edit_grn/<id>`) allows changing quantities and rates on a received GRN. This is financially dangerous: a received GRN is a committed stock event. The correct workflow is to void the GRN and create a new one. No such guided flow exists.

### UX-03 — Bookings Page Is Completely Broken (see BL-02)
- Users cannot access `/bookings` at all due to the Jinja2 `enumerate` filter crash.

### UX-04 — Direct Sale Form: No Real-Time Stock Availability Warning
- When adding a sale, the form shows materials and prices but does not check live available stock before submission. A user can enter a quantity greater than available stock, which will either fail silently or create a negative-stock entry depending on the FIFO logic's guard.

### UX-05 — No Bulk Void / Bulk Cancel
- For situations like end-of-period corrections, there is no bulk void operation. Each transaction must be voided one by one.

### UX-06 — `client_booking_cancel` and `client_booking_cancel_revert` Are Per-Client Not Per-Booking
- The cancel route `/client_booking_cancel/<client_id>` cancels all remaining bookings for a client, not a single booking. This is a major usability risk — a single misclick cancels all of a client's outstanding bookings.

### UX-07 — Password Stored in Plain Text
- `User` model has both `password_hash` and `password_plain` columns. Storing a plain-text password alongside the hash is a security risk and should not exist in a production-grade ERP.

### UX-08 — No Audit Trail for GRN Edits
- The `AuditLog` records user actions but GRN edits (which retroactively change COGS) may not produce a detailed audit entry showing what was changed (old value vs new value). Without a before/after diff in the audit log, it is impossible to know what a GRN looked like before editing.

### UX-09 — System Report (`/system_report`) Does Not Surface the `client_code` Crash
- The system report checks for orphan records and balance mismatches but does not validate that `DirectSale` records affected by the `client_code` attribute error have correct pending bills and ledger entries. The error exists in the logs but is invisible in the health dashboard.

### UX-10 — `data_wipe_preview` and `delete_all_data` Routes Accessible to Non-Root
- If any non-root admin user has access to these routes, they can wipe all data. The permission check must be verified to be root-only (`require_root()` decorator must be applied).

---

## 9. RECOMMENDATIONS

### IMMEDIATE — Production-Blocking

1. **Fix the `DirectSale.client_code` crash (BL-01).** Add `client_code = db.Column(db.String(50))` to the `DirectSale` model and migrate. Then audit all affected sales created since 2026-08-04 to rebuild their missing pending bills and ledger entries using `rebuild_all_erp_consistency()`.

2. **Fix the bookings template crash (BL-02).** Replace `mq.rows | enumerate` in `templates/bookings.html` line 705 with a Jinja2-compatible equivalent such as `mq.rows | list` with a `loop.index` variable, or register `enumerate` as a custom Jinja2 filter in the Flask app.

3. **Remove plain-text password storage (UX-07).** Drop `password_plain` from the `User` model. This is a regulatory and security violation.

### HIGH PRIORITY — Data Integrity

4. **Add `SELECT FOR UPDATE` (or equivalent) to `_fifo_grn_item_for_material()` and `get_next_bill_no()` (BL-05, DI-05)** to prevent race conditions under concurrent requests.

5. **Verify that `BookingAllocation` is released on sale void (DI-07).** Add an explicit check and add a test case covering void→booking-allocation-release→re-availability flow.

6. **Verify that `WaiveOff` is reversed on payment void (BL-10).** If not implemented, add reversal logic in the void handler.

7. **Freeze GRN unit_rate at sale time (CR-01).** Store `unit_rate_at_sale` in `DirectSaleItem` so COGS is immutable after the sale is posted, making profit reports historically stable.

8. **Restrict GRN editing to pending/draft GRNs only (UX-02).** Once a GRN is received and used in sales, it must be read-only. Provide a "void and recreate" guided flow instead.

### MEDIUM PRIORITY — Searchable Dropdowns

9. **Replace native `<select>` on GRN material field** with a combobox consistent with the rest of the app. The current selector will become unusable past ~50 materials.

10. **Replace native `<select>` on Pay Supplier — Supplier field** with a combobox. This is a money-posting action; misselection risk is high.

11. **Replace all FBM Rentals native `<select>` fields** (client, item, transfer target) with combobox controls consistent with the main app.

### MEDIUM PRIORITY — Business Logic

12. **Validate `return_type` server-side in `add_material_return` (BL-07).** Reject any value not in the expected set before applying inventory/ledger changes.

13. **Re-price drafts on resume (BL-08).** When resuming a held draft, re-fetch current material prices and GRN availability. Warn the user if anything has changed.

14. **Align client payment settlement on name vs code (BL-03).** Use `client_code` as the settlement key, not `client_name`. Add a DB index on `pending_bill.client_code`.

15. **Synchronize supplier payment void with GRN void status (CR-04).** Add a validation that prevents voiding a GRN payment if the GRN is still active (or vice versa).

### LOW PRIORITY — Completeness

16. **Add per-GRN PDF download button.** Currently only a bulk GRN export exists.

17. **Add void action to material returns.** Currently only edit is available; a return cannot be reversed without manual data correction.

18. **Add stock availability check in real time on the direct sale form (UX-04).** Use the existing `/api/client_booking_status` pattern to build an API endpoint for live stock levels, called via AJAX before the form submits.

19. **Add export (PDF/Excel) to Cash Flow, FBM Client Ledger, Profit Reports, and Daily Transactions pages** to match the export capability present in the main ledger, pending bills, and GRN modules.

20. **Surface reconciliation errors in System Report.** After each `run_auto_reconcile()` cycle, write a structured log entry that the System Report page can display, so administrators know if auto-healing changed anything — and why.

21. **Investigate `client_booking_cancel` route UX risk (UX-06).** Consider changing the route to cancel a single booking item by ID, not all bookings for a client in one action.

22. **Add audit diff logging for GRN edits, Direct Sale edits, and Payment edits (UX-08).** The current `AuditLog` stores `action` and `details` as a string; extend it to store a JSON before/after diff for financial record changes.

---

## APPENDIX A — Complete Database Model List

| Model | Table | Key Status Fields |
|---|---|---|
| AuditLog | audit_log | — |
| User | user | status, 15+ permission booleans |
| Client | client | is_active, transferred_to_id |
| Supplier | supplier | is_active |
| SupplierPayment | supplier_payment | is_void |
| Material | material | is_active, total (cached stock) |
| MaterialCategory | material_category | is_active |
| Entry | entry | is_void, type, transaction_type, source_* |
| PendingBill | pending_bill | is_paid, is_void, risk_override |
| Booking | booking | is_void, paid_amount |
| BookingItem | booking_item | — |
| BookingAllocation | booking_allocation | is_void |
| Payment | payment | is_void, discount |
| WaiveOff | waive_off | is_void |
| Invoice | invoice | is_void, status, balance |
| BillCounter | bill_counter | namespace, count |
| DirectSale | direct_sale | is_void, payment_method |
| DirectSaleDraft | direct_sale_draft | — |
| DirectSaleItem | direct_sale_item | grn_item_id (FIFO link) |
| DeliveryPerson | delivery_person | is_active |
| SaleDeliveryPerson | sale_delivery_persons | is_void |
| DeliveryPersonPayment | delivery_person_payment | is_void |
| DeliveryRent | delivery_rent | is_void |
| MaterialReturn | material_return | return_type |
| MaterialReturnItem | material_return_item | — |
| GRN | grn | is_void |
| GRNItem | grn_item | is_void, available_qty, qty_returned |
| Delivery | delivery | — |
| DeliveryItem | delivery_item | — |
| FollowUpReminder | follow_up_reminder | — |
| FollowUpContact | follow_up_contact | — |
| Account | account | is_active, balance (cached) |
| AccountCategory | account_category | — |
| AccountTransaction | account_transaction | is_void |
| CashFlowDifferenceAdjustment | cash_flow_difference_adjustment | status |
| CashFlowReconciliationAudit | cash_flow_reconciliation_audit | — |
| FbmCashDrawerEntry | fbm_cash_drawer_entry | is_void |
| FbmCashDrawerCategory | fbm_cash_drawer_category | is_active |
| FBMClient | fbm_client | — |
| FBMRental | fbm_rental | status |
| FBMRentalItem | fbm_rental_item | — |
| StaffEmail | staff_email | is_active |
| SystemLock | system_lock | status |
| ReconBasket | recon_basket | status |
| RootBackupEmailHistory | root_backup_email_history | status |
| RootBackupSettings | root_backup_settings | — |

---

## APPENDIX B — Background Processes

| Process | Function | Trigger | Purpose |
|---|---|---|---|
| Notification Worker | `_notification_worker_loop()` | On app start, daemon thread | Daily email digest of overdue pending bills |
| Hourly Backup Worker | `_hourly_backup_worker_loop()` | On app start, daemon thread | Automated DB backup ZIP to email |
| Auto Reconcile Worker | `run_auto_reconcile()` (utils/reconciliation.py) | On app start, periodic loop | Self-healing: syncs Material.total, Account.balance, DirectSaleItem names |

---

## APPENDIX C — Confirmed Active Errors (from errorlog.txt)

| Date | Error | Affected Route | Status |
|---|---|---|---|
| 2026-07-30 | `TemplateAssertionError: No filter named 'enumerate'` in bookings.html:705 | GET /bookings | **UNRESOLVED — PAGE CRASHES** |
| 2026-08-04 (×4) | `'DirectSale' object has no attribute 'client_code'` | Direct Sale operations | **UNRESOLVED — DATA LOSS RISK** |

---

*End of AMS Audit Report — Read-Only, No Code Modified*
