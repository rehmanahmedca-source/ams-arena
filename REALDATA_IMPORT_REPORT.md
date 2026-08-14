# Real-Data Import & Smoke-Test — Results

## Outcome
The app database has been **completely cleaned** and re-populated from
`Realdata/ALLEXPORT-14-08-2026_05-51PM.xlsx` with **zero data loss**.
Import ⇄ Export round-trips verified in both directions.

## 1. Import summary
| Metric | Value |
|--------|-------|
| Sheets imported | 50 physical tables + `__AMS_META__` |
| Rows inserted | **35,716** |
| Rows updated | 1 (`Admin` up-sert on the first pass; 0 on clean run) |
| Rows failed | **0** |
| Rows skipped | 0 |

Key table counts after import: `client` 305 · `material` 66 · `supplier` 6 ·
`direct_sale` 2452 · `booking` 398 · `payment` 724 · `entry` 9919 ·
`pending_bill` 6812 · `invoice` 2197 · `grn` 58 · `user` 7 · `account` 12.

## 2. Schema drift (handled — no data loss)
The file is an export from an *earlier* build; the current app has evolved past
it. Every table/column **in the file** exists in the current schema, so nothing
was dropped:

| Drift | Detail | Result |
|-------|--------|--------|
| New tables absent from file | `cash_flow_*`, `grn_allocation`, `import_*`, `tenant_wipe_backup_history` | Empty after import; cash-flow categories are re-seeded lazily by the app on first Cash-Flow page load. |
| New columns absent from file | `audit_log.username`, `booking.receive_in_account_id`, `direct_sale.client_code`, `direct_sale_item.cost_rate_at_sale`, `grn_item.is_locked` | NULL after import; `direct_sale.client_code` was back-filled from `client_name` by the app's own consistency pass. |
| Removed `settings` columns present in file | `smtp_*`, `ams_openai_api_key`, `notify_daily_time` (8 columns) | The app no longer models these; the `settings` sheet has **0 data rows**, so nothing was lost. |

## 3. Round-trip smoke test
Using the app's own engine (`_run_full_raw_import_bytes` /
`_build_full_raw_export_bytes`) — the exact code paths the Import/Export page
uses.

| Check | Result |
|-------|--------|
| **import file == export file** (original vs re-export after import) | ✅ PASS — 616,724 cells, **0 mismatches** |
| **export file == import file** (re-import the re-export, export again) | ✅ PASS — E1 vs E2 identical, **0 mismatches**; re-import report `status=ok`, `failed=0`, `warnings=0` |
| **current DB == original file** (final export from live DB vs original) | ✅ PASS — 616,724 cells, **0 mismatches** |

## 4. Live page smoke test
Booted the app against the migrated DB, logged in as `Admin`, and GET-ed every
page (60+ routes incl. all ledgers, reports, KPIs, inventory, import/export,
admin): **all return 200, no 500s**.

### Pre-existing bugs fixed along the way
Two pages were throwing 500s due to dangling template references left by the
modular refactor (unrelated to the import):

1. **`/settings`** — "Suspend/Activate" button called a non-existent
   `toggle_user_status` route. Added the route in
   `app/blueprints/misc/users_settings.py` (mirrors the existing
   `delete_user`/`edit_user_permissions` guards; refuses root/admin/self).
2. **`/notifications`** — "Send Daily PDF Now" button called a removed
   `notifications_send_daily_now` endpoint (email delivery was removed from
   this build). Removed the dead button from `templates/notifications.html`.

## 5. Login after migration
All 7 users were restored verbatim (ids, hashes, created_at):

| Username | Role | Password |
|----------|------|----------|
| Admin | admin | `Admin@fbm12345` |
| Rehman Ahmed / Rizwan Ahmed / Adnan Ahmed / Shujaat Muzaffar | admin | `Admin@fbm12345` |
| Ahmed Hassan | admin | `Hassan12345` |
| Mohsan Javed | user | `mohsan12345` |

## 6. Reproducible tooling (committed under `tools/`)
- `tools/realdata_migration.py` — clean DB → import → backfill → verify → export.
- `tools/roundtrip_compare.py` — "import file == export file" cell-by-cell diff.
- `tools/roundtrip2_idempotency.py` — "export file == import file" idempotency check.
- `tools/live_smoke.py` — read-only live page smoke test.

Run them with:
```bash
ALLOW_EMPTY_DB=1 ALLOW_DB_DROP=1 FULL_RAW_IMPORT_ENABLED=1 python tools/realdata_migration.py --clean
```
