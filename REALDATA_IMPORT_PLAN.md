# Real‑Data Import Plan — `Realdata/ALLEXPORT-14-08-2026_05-51PM.xlsx`

## Goal
Replace the sample/demo data currently in `instance/ahmed_cement.db` with the
real data in the supplied XLSX, with **zero data loss**, then prove the
import/export round‑trip is faithful.

## 1. What the file is
- It is the app's own **"Export Full XLSX"** (`export_kind = literal_all`,
  `format_version = 2026-04`) — 50 physical‑table sheets + `__AMS_META__`.
- Every sheet name maps 1:1 to a database table name; every column in every
  sheet already exists in the current DB schema. **No table or column in the
  file is missing from the app.**

## 2. Schema drift found (app has evolved *past* the export)
These exist in the current app schema but are **absent from the file**, so they
will be empty/NULL after import — this is *expected* and is not data loss:

| Kind | Item | Why it's safe |
|------|------|---------------|
| New tables | `cash_flow_category`, `cash_flow_entry`, `cash_flow_party`, `cash_flow_subcategory`, `grn_allocation` | Added after the export was taken; seed categories are re‑created lazily on first Cash‑Flow page load. |
| App infra tables | `import_job`, `import_upload`, `import_history_entry`, `tenant_wipe_backup_history` | Runtime bookkeeping, empty in a fresh DB. |
| New columns | `audit_log.username`, `booking.receive_in_account_id`, `direct_sale.client_code`, `direct_sale_item.cost_rate_at_sale`, `grn_item.is_locked` | NULL after import; `client_code` is back‑filled by the existing bootstrap consistency pass from `client_name`. |

The reverse direction (a column in the file but not in the DB) is **empty** —
so importing can never drop a value from the file.

## 3. Steps
1. **Back up** the current `ahmed_cement.db` (and side‑car files) so nothing is
   irreversible.
2. **Complete clean** — delete the DB file; the app factory re‑creates the full
   current schema (all 59 tables, including the newer tables/columns) and a
   default admin.
3. **Import** the file with the app's real engine
   (`_run_full_raw_import_bytes`, `mode=replace_tenant_data`), the same code
   path the Import/Export page uses.
4. **Consistency pass** — run the same non‑destructive bootstrap back‑fills the
   app runs on startup (client_code back‑fill, material category, user
   permission defaults) so derived columns match what the app would produce.
5. **Verify counts** — every sheet's row count must equal the table's row count.
6. **Round‑trip smoke test**:
   - Export the imported DB (`_build_full_raw_export_bytes`).
   - Diff the export against the original file sheet‑by‑sheet / row‑by‑row,
     ignoring the documented drift (new empty columns/tables + `exported_at`).
   - Re‑import the export and confirm the DB is unchanged (idempotent).
7. **Live smoke test** — boot the server, log in, hit every page/route, confirm
   no 500s.

## 4. Acceptance criteria
- `import file ⇄ export file`: every non‑empty cell in the original file
  reappears identically in the re‑exported file; re‑importing the export is a
  no‑op.
- The app runs and all pages load with the real data.
