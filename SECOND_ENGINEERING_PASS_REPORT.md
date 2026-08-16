# Second Engineering Remediation Pass

Date: 2026-08-16 (Asia/Karachi)

## Final acceptance status

**Repository acceptance: PASS. Production-host acceptance: BLOCKED pending host access/deployment identification.**

The database repair, password cleanup, route optimization, backup implementation, isolated restore tests, and application regressions are complete in this branch. The repository and GitHub metadata contain no Docker, systemd, Procfile, platform manifest, deployment URL, or other evidence that identifies the real production host. Therefore this report does **not** claim that an external hourly scheduler has been installed on production.

Before production release, the operator must identify the actual host and install its native scheduler to invoke:

```bash
cd <REAL_PRODUCTION_CHECKOUT>
.venv/bin/python tools/maintenance.py backup-if-due
```

Run it hourly. Cross-process locking makes overlap with the embedded fallback recoverable and prevents duplicate concurrent publication. Then verify on that host with:

```bash
cd <REAL_PRODUCTION_CHECKOUT>
.venv/bin/python tools/maintenance.py status
.venv/bin/python tools/maintenance.py backup-if-due
.venv/bin/python tools/maintenance.py status
```

The status must be `HEALTHY`, retention must be `3`, and the scheduler's native history/log must show a successful hourly invocation. Keep the embedded cross-process-locked scheduler enabled until that external scheduler is demonstrated; only then set `BACKUP_EMBEDDED_SCHEDULER=0` in the real application service environment and restart that service with the host's actual process manager.

## 1. Foreign-key diagnosis and remediation

### Diagnosis

`PRAGMA foreign_key_list('booking_allocation')` maps:

- FK ID 0: `booking_item_id -> booking_item.id`
- FK ID 1: `sale_item_id -> direct_sale_item.id`
- FK ID 2: `sale_id -> direct_sale.id`

The supplied database had 208 FK violations across 190 allocation rows:

| Classification | Rows | State | Criticality |
|---|---:|---|---|
| Active allocation to deleted booking line | 106 | active | high business / no direct financial mutation |
| Void allocation to deleted booking line | 5 | void | low financial / low business |
| Void allocation to replaced sale line | 61 | void | low financial / medium audit |
| Void allocation with both child parents deleted | 18 | void | low financial / medium audit |

Field totals were 129 missing booking items and 79 missing sale items. Every allocation retained a valid direct sale. No active allocation was missing its sale item, no sale-item ownership mismatch existed, and all 190 rows met the deliberately narrow repair policy.

The complete row-level diagnosis—including row PK, each FK/reference/value/existence result, business meaning, criticality, safe repair, block status, and available context—is in `artifacts/fk-allocation-diagnosis.json`.

### Root causes and prevention

Two concrete mutation paths were fixed:

1. Direct Sale edit previously voided allocations and bulk-deleted old `direct_sale_item` rows. It now archives and removes exact old booking allocations and removes GRN allocations before replacing source sale lines.
2. Full Booking Item cancellation previously deleted the booking item without considering allocations. It now preflights all hard deletes before any mutation, blocks when an active allocation exists, and archives/removes only remaining void links before deleting an unconsumed line.

Every SQLite application connection now runs and verifies `PRAGMA foreign_keys=ON`, so future parent-deletion regressions fail transactionally.

### Controlled repair

`tools/repair_controlled/repair_booking_allocation_fks.py` provides read-only diagnosis and a guarded write mode. Write mode requires explicit confirmation and exact expected row/FK counts, takes a pre-repair backup, blocks unsafe classifications, rechecks every source identity/state, archives parent snapshots, and commits archive/delete together.

Actual repaired state:

- repair run: `fk-repair-1b6ac047ea244f928389b3ca6db79020`
- allocations before/after: 1,309 / 1,119
- archived exact rows: 190
- `PRAGMA integrity_check`: `ok`
- `PRAGMA foreign_key_check`: 208 -> **0**
- unchanged surviving allocation rows: 1,119
- changed non-target business tables: **0**

The exact write-scope validator compared every row of 59 non-target tables and proved they were unchanged. A second validator compared row hashes, counts, and relevant sums for 21 authoritative financial, payment, inventory, ledger, invoice, supplier, and material tables; all were unchanged. See `artifacts/fk-repair-business-validation.json`.

Authenticated isolated-copy rendering before and after repair was byte-identical after normalizing only the per-session CSRF token for Dashboard, Accounts, Profit Report, Stock Summary, Pending Bills, Direct Sales, and Bookings. See `artifacts/fk-repair-route-parity.json`.

## 2. Password remediation

Seven users had both a recognized Werkzeug scrypt hash and a populated legacy plaintext field. `tools/repair_controlled/clear_verified_plaintext_passwords.py`:

- verifies each plaintext value against that row's existing hash before any write;
- blocks the entire operation if any row fails verification;
- requires explicit confirmation and an exact expected count;
- takes a guarded backup;
- performs compare-and-update inside `BEGIN IMMEDIATE`;
- preserves every hash and every non-user table exactly;
- never prints or records password values.

Result:

- verified against own hash: 7 / 7
- plaintext rows: 7 -> **0**
- password hashes changed: **0**
- changed non-user tables: **0**
- isolated post-cleanup login checks: 7 / 7 successful

Normal hash-based login now also clears a redundant plaintext fallback. Plaintext-only legacy login still upgrades to a Werkzeug hash and clears plaintext on successful authentication. See `artifacts/plaintext-password-remediation.json`.

## 3. Route payload and query remediation

Per-row dialogs were moved to authenticated lazy fragments while preserving edit/view/transfer behavior, CSRF fields, draft resume, Bootstrap lifecycle, and row actions.

| Route | Before | After | Reduction |
|---|---:|---:|---:|
| Direct Sales | 6,519,403 B | 866,942 B | 86.7% |
| Bookings | 1,973,148 B | 421,142 B | 78.7% |
| Pending Bills | 2,654,071 B | 429,947 B | 83.8% |
| Clients | 824,820 B | 264,367 B | 67.9% |

The isolated benchmark records response bytes, client total time, Flask server time, cumulative DB time, template time, and query count. Reproducible baseline/final profiler output and final warm-sample metrics are committed as `artifacts/route-profile-baseline.json`, `artifacts/route-profile-final.json`, and `artifacts/route-benchmark-final.json`. Final warm medians:

| Route | Total / server / DB / template | Queries | Bytes |
|---|---|---:|---:|
| Dashboard | 341.20 / 340.37 / 5.71 / 1.75 ms | 22 | 117,063 |
| Accounts | 361.62 / 360.78 / 1.67 / 9.00 ms | 28 | 535,907 |
| Profit Report | 79.96 / 79.21 / 6.64 / 2.07 ms | 39 | 261,802 |

Comparable baseline to optimized query profiles:

- Dashboard: 1,194.39 ms / 2,551 queries -> 346.33 ms / 22 queries
- Accounts: 1,255.30 ms / 2,655 queries -> 403.55 ms / 28 queries
- Profit Report: 766.92 ms / 1,993 queries -> 86.55 ms / 39 queries

Client summary parity covered all 305 clients with zero differences. Supplier summary parity covered all six active suppliers with zero differences. Profit Report response comparison differed only by its generated CSRF token.

## 4. Backups, restore, retention, and storage

The dedicated `tools/maintenance.py` CLI uses SQLite's online backup API, checksum and integrity validation, atomic publication, cross-process duplicate protection, exact latest-three-successful retention, and restore rollback protection. Backup paths are private and not served as static files.

Acceptance coverage proves:

- the fourth successful backup removes only the oldest successful backup;
- exactly three successful backups remain;
- failed, corrupt, or low-disk attempts preserve existing valid backups;
- manifest/SQLite corruption is rejected;
- concurrent owners cannot steal/delete a live lock;
- duplicate timestamps are collision-safe;
- due state is read from durable on-disk backups, not in-process memory;
- missed historical runs do not create a backup storm after restart;
- restore validation uses an isolated environment, restores DB and uploads, takes rollback protection, and cleans owned temporary data;
- cleanup removes only stale maintenance-owned paths.

The only remaining backup gate is real-host scheduler activation and observation, described at the top of this report.

## 5. Regression evidence

- `git diff --check`: passed
- Python compileall for application, models, tools, and tests: passed
- full pytest suite: **110 passed in 53.18 seconds**
- lazy fragment JavaScript: every extracted nonempty inline script passed Node `--check`
- database integrity: `ok`
- database FK violations: 0
- plaintext password rows: 0
