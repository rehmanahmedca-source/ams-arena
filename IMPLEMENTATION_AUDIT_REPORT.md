# AMS Reliability, Backup, Storage, Security, and Performance Audit

**Audit date:** 2026-08-16 UTC  
**Baseline commit:** `4bdb96afee55804df370f0d9cb5b1d37defc3eb3`  
**Scope:** actual repository and an isolated copy of the supplied SQLite data

## Executive result

The application now has one authoritative, private, validated backup lifecycle with hourly catch-up scheduling, cross-process exclusion, post-success retention of three backups, controlled restore, storage diagnostics, bounded technical logs, and tests for retention/failure/concurrency/corruption/restore edge cases. Normal exports remain in memory and do not accumulate. Password changes and user creation no longer persist plaintext passwords or display them in administration pages.

No business, financial, inventory, uploaded, tracked, or database records were deleted. The tracked production database was restored byte-for-byte after isolated measurements. The existing 208 foreign-key violations were documented rather than changed automatically.

The implementation is **not represented as perfect**. Several existing pages still produce multi-megabyte responses and two dashboard/report pages take over 700 ms on the supplied data. Broad non-Accounts CSRF coverage, legacy plaintext credentials already present in the database, and the pre-existing foreign-key violations remain follow-up risks.

---

## A. Original architecture

- Python 3.11.2, Flask factory in `app/__init__.py`, entrypoints in `main.py` and `wsgi.py`.
- Flask 3.1.3, Flask-SQLAlchemy 3.1.1, SQLAlchemy 2.0.52 in the isolated audit environment.
- SQLite database at `instance/ahmed_cement.db`, WAL journal mode when the application runs.
- 16 registered blueprints and 461 effective URL rules (legacy aliases included); 272 route decorators in source.
- 61 SQLAlchemy model classes in the modular `models/` package.
- 60 baseline physical tables, 139 explicit non-auto indexes, 99 templates, 4 static files (2 JavaScript and 2 CSS).
- Domain packages cover authentication, master data, sales, bookings, payments, returns, ledgers, inventory, GRN/dispatch, accounts, reports, import/export, administration, notifications, and recovery/wipe workflows.
- 286 baseline Python files. Requirements were not changed.
- Reports and Excel/CSV exports are generally generated into memory (`BytesIO`/response), not permanently stored.
- Uploaded business photos are authoritative files under `static/uploads/`; the root `uploads/` directory contains repository/audit artifacts, not runtime photos.

### Baseline data

| Item | Baseline |
|---|---:|
| Database size | 8,519,680 bytes |
| Tables | 60 |
| Explicit indexes | 139 |
| Integrity check | `ok` |
| Foreign-key check | 208 existing violations |
| Project including `.git` | approximately 50 MiB |
| Files/directories | 475 / 50 at initial checkout |
| Root `uploads/` | 10,745,518 bytes |
| `Realdata/` | 2,979,678 bytes |
| Backups | 0 |
| Technical logs | 0 |

Representative row counts were captured before editing. Important counts remained unchanged: clients 305, suppliers 6, materials 66, bookings 398, direct sales 2,452, direct-sale items 4,503, entries 9,919, payments 724, pending bills 6,812, invoices 2,197, GRNs 58, account transactions 838, and audit rows 705.

---

## B. Storage problems found

1. The former automatic backup switch was hard-disabled.
2. Its request hook attempted to start a process-local thread lazily; it only backed up at minute zero and could miss every backup after restarts.
3. The legacy backup code read a live WAL database as a normal file, without SQLite's backup API or an integrity check.
4. Legacy history defaulted to 200 and used a separate `instance/root_hourly_backups/` location.
5. Locking was process-local only, unsafe under multiple WSGI workers.
6. “Single-store” backup/snapshot helpers were stubs, including pre-upgrade safety snapshots.
7. No authoritative backup health/storage report existed.
8. No rotating application error file existed (console logging did not itself grow on disk, but file logging would have been unbounded if added naively).
9. A 15,069,461-byte tracked workspace ZIP, a 10,682,576-byte tracked combined-source text, a 2,979,549-byte source workbook, and thirty 13-byte tracked import-upload remnants are deployment bloat candidates. They were preserved because they are tracked and their business/deployment purpose is not proven disposable.
10. Test execution generated ignored `__pycache__` files; these were removed after testing and remain excluded by `.gitignore`.
11. Existing export/import archive calls are intentionally no-ops in single-store mode, avoiding normal generated-file accumulation.

---

## C. Changes made

- Added `app/services/maintenance.py` as the authoritative maintenance service.
- Added configurable backup paths, interval, retention, lock timeout, temp retention, disk threshold, and embedded fallback controls.
- Moved fallback scheduling to application startup rather than user requests.
- Added `tools/maintenance.py` for cron/PythonAnywhere/Task Scheduler invocation.
- Added `tools/benchmark_pages.py` for repeatable read-only timing against an isolated database copy.
- Adapted the old root backup UI to the authoritative service. Legacy ZIP downloads are built in memory and are not retained as duplicate files.
- Added rotating `instance/logs/errorlog.txt`: 2 MiB per file and three rotations by default.
- Added storage/backup health reporting through the CLI.
- Added `.gitignore` rules for private backups, maintenance temp, logs, and business uploads.
- Added ten focused maintenance tests.
- Removed per-client N+1 counter queries in the clients page, replacing up to 40 queries per page with two grouped queries.
- Removed per-sale delivery-person lookup queries by using the already loaded delivery-person list.
- Stopped all normal app user-create/password-change/reset paths from writing plaintext password values and removed plaintext password display from settings/tenant pages.

---

## D. Backup architecture

1. Resolve the configured file-backed SQLite source.
2. Check minimum free disk space.
3. Acquire an atomic cross-process directory lock with PID/age metadata.
4. Recover a lock only when it is older than the configured stale limit **and** its PID is not alive.
5. Create a uniquely owned staging directory under `instance/storage/temp/`.
6. Use `sqlite3.Connection.backup()` to make a transactionally consistent online snapshot.
7. Run `PRAGMA integrity_check`, require application tables, and require a non-empty database.
8. Copy only permanent business uploads from `static/uploads/`, excluding source, Git, dependencies, logs, caches, exports, and root audit artifacts.
9. Write a versioned JSON manifest with database/table metadata, sizes, and SHA-256 hashes for the database and uploads.
10. Fully validate the staged backup.
11. Atomically rename it into `instance/storage/backups/backup_YYYYMMDD_HHMMSS[_NN]`.
12. Validate the official path again.
13. Only then prune older **valid** backups beyond retention.
14. Invalid/unknown directories are logged and never automatically deleted.

Backup failures are logged with traceback and free-space/target context. Staging is cleaned in `finally`; existing valid backups are untouched.

## E. Retention and scheduling

- `BACKUP_INTERVAL_SECONDS=3600` by default.
- `BACKUP_RETENTION=3` by default.
- Zero, one, and two backups grow naturally without premature deletion.
- The fourth successful backup removes only the oldest validated backup.
- A failed/corrupt fourth backup leaves all three existing backups.
- Duplicate-second names receive `_01`, `_02`, etc.
- After downtime, `backup-if-due` makes one current backup, not many historical copies.
- Preferred production scheduler: `.venv/bin/python tools/maintenance.py backup-if-due` once per hour.
- A startup daemon is the fallback. Multi-worker duplicates are prevented by the same cross-process lock.
- No backup runs on every request and no request waits for a backup.

One real validated backup was created during verification. Health correctly reported `WARNING`, not `HEALTHY`, because this new installation has one of the configured steady-state three. It becomes healthy after three successful hourly points exist.

## F. Restore architecture

`restore_backup()`:

1. Fully validates source manifest, database integrity, table set, paths, sizes, and hashes.
2. Pins the source into an owned temporary directory so retention cannot rotate it mid-restore.
3. Creates a validated pre-restore safety backup of live DB and uploads.
4. Uses SQLite's online backup API to restore into the live database.
5. Re-runs integrity/table validation.
6. Publishes uploads using directory renames/copies only after DB validation.
7. On failure, restores the safety database and prior uploads.
8. Cleans controlled restore temp paths in `finally`.

The CLI requires both an explicit path and `--confirm`; documentation requires a maintenance window. There is no public restore-upload route in the active single-store application, so no unbounded restore upload repository was added.

## G. Storage comparison

| Category | Before | After |
|---|---:|---:|
| Tracked database | 8,519,680 bytes | 8,519,680 bytes (unchanged) |
| Authoritative backups | 0 | 1 validated point, ~8.69 MB runtime-only |
| Maintenance temp | 0 | 0 after operations |
| Runtime business uploads | 0 in supplied checkout | 0 |
| Technical logs | 0 | ~4.7 KB during audit; bounded rotation |
| Root tracked audit artifacts | 10.75 MB | unchanged/preserved |
| Realdata | 2.98 MB | unchanged/preserved |

Source size increased only for the maintenance implementation, tests, documentation, and benchmark tool. Long-term automatic growth is bounded to three successful data backups plus rotating technical logs; database and permanent business uploads retain legitimate growth.

## H. Database optimization

- No schema migration or index was added blindly.
- Existing schema has substantial indexing (139 baseline explicit indexes).
- Client-page N+1 aggregate queries were replaced by two grouped SQL aggregates.
- Direct-sale fallback delivery-person N+1 lookups were eliminated.
- Existing server-side pagination was confirmed on clients, bookings, direct sales, pending bills, payments, and returns.
- No `VACUUM`, record deletion, financial cleanup, or unsafe pragma was applied.
- `foreign_keys=ON` was not forced because the supplied database has 208 existing violations; enabling it without remediation could break legitimate existing writes.

## I. Frontend/security optimization

- Existing UI, navigation, terminology, and layouts were preserved.
- No framework or dependency was introduced.
- Existing JS/CSS were not removed without proof.
- Plaintext passwords are no longer stored by normal create/change/reset code and are no longer rendered in admin tables. Temporary generated credentials are still shown once in the success message so an administrator can deliver them.
- Existing legacy plaintext rows were not mass-deleted because some legacy accounts may still rely on login-time hash upgrade. Successful legacy login already hashes and clears that value.
- Backups and logs are private instance paths, not static URLs.

## J. Performance results

The benchmark uses four requests per page against a SQLite backup copied to an isolated temp DB and reports the median of three warm requests.

| Operation | First measured | Final measured | Classification |
|---|---:|---:|---|
| Login | 109.24 ms | 110.79 ms | Unchanged/noise |
| Dashboard `/` | 1,184.54 ms | 1,168.27 ms | Unchanged |
| Clients | 56.34 ms | **29.76 ms** | Improved 47% |
| Materials | 5.63 ms | 5.80 ms | Unchanged |
| Bookings | 39.01 ms | 36.56 ms | Unchanged/slightly improved |
| Direct sales | 226.67 ms | 216.14 ms | Slightly improved/noise |
| Pending bills | 52.28 ms | 46.57 ms | Slightly improved |
| Stock summary | 18.39 ms | 18.04 ms | Unchanged |
| Accounts dashboard | 1,265.93 ms | 1,236.76 ms | Unchanged/slightly improved |
| Profit reports | 728.40 ms | 731.09 ms | Unchanged |
| Client search API | 2.44 ms | 2.26 ms | Unchanged/fast |

Response-size risks remain: clients 824,820 bytes; bookings 1,973,174; direct sales 6,519,459; pending bills 2,654,071. They are already row-paginated, so much of the payload is form option/template data. Reducing it needs UI/API restructuring and was not done speculatively.

The first measurement was taken after the reliability subsystem but before query optimization; no representative page benchmark was captured before any code edit. Therefore page changes unrelated to the two proven query fixes are classified as unchanged, not claimed as gains.

## K. Test results

### Baseline

- 92 tests passed in 45.50 seconds.

### Final automated suite

- 102 tests passed in 37.69 seconds before the final two query-only optimizations.
- Focused post-optimization suite: 26 passed in 6.36 seconds.
- Final full suite after every code and query change: **102 passed in 39.23 seconds**.

### Focused maintenance coverage

- First through fourth backup and exact retention.
- Failed new validation preserves existing backups.
- Corrupt SQLite backup rejected.
- Concurrent lock attempt rejected without deleting owner lock.
- Duplicate timestamp collision-safe naming.
- Low-disk failure preserves existing backup.
- Missed intervals create one current backup only.
- Valid restore restores database and uploads.
- Pre-restore safety backup created.
- Restore temp cleanup.
- Cleanup deletes only known owned/stale categories.
- Health and storage report.
- Real SQLite backup creation and validation.
- Two consecutive isolated application starts: 461 rules each, login page HTTP 200, database integrity `ok`.
- Python compilation and `git diff --check`.

The broader existing suite exercises authentication, modular routes, Accounts CRUD/integrity, cash flow reconciliation, sales round trips, booking allocation, bill lifecycle, GRN FIFO, imports, material returns, voiding, and ledger behavior with database assertions.

## L. Failed tests

One initial focused run had two test-harness failures:

- **Failure:** retention/failure tests raised `StopIteration`.
- **Cause:** the mocked clock supplied one timestamp per backup, while lock metadata also requests the clock.
- **Fix:** changed the deterministic clock fixture to support both calls per operation.
- **Retest:** focused suite passed 8/8, later expanded to 10 tests; full suite passed.
- **Application defect:** none; no production logic was changed to hide the harness issue.

No final known test failure is hidden.

## M. Remaining risks / not fully tested

1. **Pre-existing FK violations:** 208; not repaired. Native integrity is `ok`, but relationship quality requires a separate business-approved remediation project.
2. **CSRF:** explicit protection currently covers Accounts mutations, not every mutating route. Broadening it requires template/API token migration and full browser workflow testing.
3. **Legacy plaintext values:** new writes/display are fixed, but existing values were not mass-cleared. Rotate those users' passwords or let successful login upgrade them.
4. **Large responses:** direct sales, pending bills, bookings, and clients remain large despite DB pagination.
5. **Slow pages:** dashboard, Accounts dashboard, and profit reports remain 0.7–1.25 seconds on this dataset and need query-profile-led work.
6. **True OS process termination mid-restore, physical disk-full, and permission-denied restore:** represented by injected low-space/corruption/failure tests, but not destructively reproduced on the host filesystem.
7. **Live concurrent financial write during restore:** not performed; restore is intentionally documented as maintenance-window-only.
8. **External scheduler installation:** code and command are supplied, but cron/PythonAnywhere/Windows configuration cannot be installed without knowing the real host. The guarded embedded fallback is enabled by default.
9. **PDF/Excel at extreme scale:** existing tests cover behavior but not hundred-thousand-row memory load.
10. **Browser UX/double-click behavior:** not fully browser-automated in this environment.

## N. Files changed/added

- `.gitignore` — ignore private runtime storage/logs/uploads.
- `README.md` — deployment, scheduler, backup, verify, status, and restore instructions.
- `app/__init__.py` — configuration, rotating log, startup scheduler.
- `app/services/maintenance.py` — new authoritative maintenance implementation.
- `app/services/backup.py` — legacy root UI compatibility over authoritative backups.
- `app/blueprints/auth.py` — stream legacy backup ZIP downloads from memory.
- `app/blueprints/masters/clients.py` — remove aggregate N+1 queries.
- `app/blueprints/sales/_direct_sales_direct_sales_page.py` — remove delivery-person N+1 lookup.
- `app/blueprints/misc/extra.py` — stop plaintext password persistence.
- `app/blueprints/misc/users_settings.py` — stop plaintext password persistence.
- `app/blueprints/system/tenants.py` — stop plaintext password persistence and correct missing-hash reset logic.
- `templates/settings.html` — remove plaintext password display.
- `templates/tenants.html` — remove plaintext password display.
- `tests/test_maintenance.py` — backup/restore/storage/failure/concurrency tests.
- `tools/maintenance.py` — production maintenance CLI.
- `tools/benchmark_pages.py` — isolated read-only benchmark.
- `IMPLEMENTATION_AUDIT_REPORT.md` — this report.

## O. Files removed

None. Generated Python caches were removed from the working tree after testing; they are ignored and are not source/business files.

## P. Important files intentionally preserved

- `instance/ahmed_cement.db` — unchanged tracked business database.
- `Realdata/*.xlsx` — uncertain authoritative/import purpose.
- `workspace-*.zip` — tracked deployment/workspace artifact; reported, not deleted.
- `uploads/flask_app_combined.txt` and audit reports — tracked audit artifacts; reported, not deleted.
- `instance/import_uploads/*.xlsx` — tracked remnants; not deleted without ownership evidence.
- All models, routes, templates, static assets, migrations/bootstrap logic, financial rows, inventory rows, uploads, and audit history.

---

## Before/after classification

- **Improved:** backup integrity/retention/locking/scheduling; restore safety; log bounds; temp cleanup; disk monitoring; client query count; plaintext credential handling.
- **Unchanged:** route inventory, models, dependencies, UI design, business terminology, tracked database rows/schema/file, most page timings.
- **Changed intentionally:** old root backup UI now uses the sole authoritative backup store and streams transient ZIPs; admin pages no longer reveal passwords.
- **Potentially risky:** host scheduler still requires deployment configuration; restore requires a maintenance window; legacy plaintext rows and FK violations remain.
- **Not changed:** business/financial/inventory calculations, dependency versions, exports' formats, database records, destructive wipe semantics, static library set.
