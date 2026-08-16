# BOOKED-SALE EDIT BUG — FIX + AUDIT REPORT

## ROOT CAUSE

`edit_direct_sale` in `app/blueprints/sales/_direct_sales_edit_direct_sale.py`
rebuilt each posted sale line as a **single** `parsed_items` entry carrying the
raw submitted unit rate, and never set `is_booking`. It also never computed
the client's per-material booking balance and therefore never split a line
into a reserved slice (rate 0, `is_booking=True`) and a chargeable slice —
unlike `add_direct_sale`, which does exactly that.

Consequences:

1. `_apply_booking_allocations_for_sale` only creates allocations for items
   with `is_booking=True`, so every existing `BookingAllocation` row was
   archived/deleted by the edit handler and **never recreated**.
2. The edit modal pre-fills `unit_rate` from `DirectSaleItem.price_at_time`,
   which is 0 for booked items, but the live booking-status JavaScript can
   overwrite the rate with the client's reserved unit price when balance is
   positive. On save that line then had `price>0`, tripping
   *"Booked Sale can only contain reserved items (rate 0)."* even though
   the underlying line was a valid booked dispatch.
3. The modal did not pre-fill the alternate-material field, so alternate
   dispatches (e.g. KOHAT delivered against RENT-CEMENT) lost their
   `booked_material` mapping on edit.

The validation itself was correct; the reconstruction path was wrong.

## FILES CHANGED

| File | Why |
| --- | --- |
| `app/blueprints/sales/_direct_sales_edit_direct_sale.py` | Compute per-material booking balances for the resolved client, split each posted line into reserved (`is_booking=True`, rate 0) and chargeable slices mirroring `add_direct_sale`, parse `grn_item_id[]` and `ignore_booking_item[]`, run FIFO expansion, and classify the sale from the resulting `is_booking` flags. Excludes the sale being edited from its own delivered/returned totals so a no-op save does not see its own booking as consumed. |
| `app/blueprints/sales/_direct_sales_direct_sales_edit_modal.py` | Look up the active Entry rows for the sale and pass `sale_alt_material_by_product` to the template so alternate-material dispatches pre-fill their Alternate field. |
| `templates/_direct_sale_edit_modal.html` | Bind the alternate-material input's `value` to the existing booked material when present. |
| `tests/test_booked_sale_edit.py` | New regression + smoke tests covering open / no-op save / quantity edit / add reserved / remove booked / alternate / invalid chargeable / mixed / atomic failure. |

No models, migrations, validation rules, UI styling, reports, accounts or
unrelated blueprints were touched.

## FIX

The edit handler now mirrors the add-sale flow for item reconstruction:

* Looks up active `Booking`/`BookingItem` rows for the resolved client.
* Sums existing `OUT` `Entry` rows (excluding the sale being edited) to
  derive per-material delivered totals, and `IN` Booked-Return rows for
  returned totals — same formula as the booking-status API.
* For each posted line, consumes the available balance into a reserved
  slice (`is_booking=True`, `price_at_time=0`, alt mapped to booked material)
  and any remainder into a chargeable slice with the submitted rate /
  material unit price and GRN allocation.
* Honours `ignore_booking_item[]` for Cash / Credit / Open Khata and the
  user's explicit "ignore" toggle.
* Runs `_expand_chargeable_items_fifo` (excluding this sale) and derives
  `any_booking_item` / `any_chargeable_item` from the `is_booking` flag
  instead of merely inspecting the posted rate, so the existing
  *"Booked Sale can only contain reserved items (rate 0)."* protection
  remains intact and only fires for genuinely chargeable lines.
* The edit modal pre-fills the Alternate field from existing entries, so
  alternate dispatches retain their booked-material mapping visibly and on
  save.

## BEFORE

* Existing booked sale opened with lines classified NON-BOOKED by the live
  JS because the modal did not pre-mark them as reserved and did not
  pre-fill the alternate-material field.
* Saving without changes deleted all `BookingAllocation` rows for the sale
  and never recreated them.
* Saving with a new item (or when the reserved rate had been pushed into
  the rate field) returned *"Booked Sale can only contain reserved items
  (rate 0)."* even though every line was a valid booked dispatch.
* Alternate-material bookings lost their `booked_material` after edit.

## AFTER

* Existing booked lines keep `is_booking=True`, rate 0, and their booking
  allocation across the edit → validate → save flow.
* Saving an unchanged Booked Sale is a no-op for allocations, entries,
  stock and ledger.
* Editing quantities, adding a reserved item, removing a booked item and
  editing an alternate-material dispatch all rebuild allocations correctly.
* Genuinely chargeable items in a Booked Sale are still rejected with the
  same validation message, and the rejection is atomic (no partial update).
* Mixed (Booked + Due) sales retain both the reserved and chargeable
  slices, allocations, and amount through edit.

## SMOKE TEST RESULTS

The following tests in `tests/test_booked_sale_edit.py` all PASS:

| # | Test | Result |
| - | --- | ------ |
| 1 | Open existing booked sale — modal shows Booking Delivery, material, rate=0 (not the reserved rate) | PASS |
| 2 | Save without changes — items / allocations / entries identical before & after | PASS |
| 3 | Edit booked quantity within remaining reservation — allocation & entry updated, no duplicate | PASS |
| 4 | Add another reserved item — new allocation created, both reserved | PASS |
| 5 | Remove booked item — its allocation is released, no orphans | PASS |
| 6 | Alternate-material booked sale — alt field pre-fills, re-save preserves `booked_material` and allocation | PASS |
| 7 | Genuinely non-booked chargeable item in Booked Sale is rejected with the existing "reserved items (rate 0)" message and no state mutation | PASS |
| 8 | Booked + Due (Mixed Transaction) edit — both slices, allocations, amount preserved | PASS |
| 11 | Failed edit (duplicate bill_no) leaves sale, items, allocations and entries unchanged (atomicity) | PASS |

In addition the existing suite stays green:

```
$ pytest tests/
119 passed
```

(including `test_sales_roundtrip.py`, `test_booking_allocation_integrity.py`,
`test_refund_flow.py`, `test_material_return_*`, `test_grn_fifo_costing.py`,
etc.).

## DATABASE INTEGRITY

The production database file was not used by any test (each test creates a
temp SQLite DB) and was byte-identical before and after the work
(`0812b18cb3f2f937e82f640ac92b0423`). A direct check on
`instance/ahmed_cement.db` reports:

- SQLite integrity: **ok**
- `PRAGMA foreign_key_check`: **0 rows**
- Void/orphan `booking_allocation` rows: 112 pre-existing soft-voided rows
  (unchanged by this fix — they belong to historical voided sales and are
  excluded by `is_void=False` filters; no new orphan allocations are
  introduced).

## REGRESSION STATUS

PASS. Audited code paths: Booked Sale creation (unchanged), Booked Sale
editing (fixed), Booked + Due editing (fixed), Due/Cash/Open-Khata editing
(now explicitly force `ignore_booking=True`, same as add flow), alternate
materials (fixed in modal + handler), booking allocation (re-uses existing
`_apply_booking_allocations_for_sale`), inventory deduction (unchanged,
still goes through `rebuild_direct_sale_effects` →
`_rebuild_material_totals`), returns (unchanged), ledger synchronisation
(unchanged) and financial totals (unchanged).

## UNRELATED CODE

Confirmed: no unrelated code was changed. The diff is limited to the two
direct-sales-edit Python files, the one alternate-material input in the
edit-modal template, and the new test file. No models, migrations, CSS,
reports, dashboards, auth, accounts, inventory logic or unrelated
blueprints were modified.
