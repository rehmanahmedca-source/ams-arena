# AMS ERP — true modular structure

The old dump (`ams_app/main.py`, ~850 KB) is **deleted**.  
There is **no wire-all-globals hack**. Services import each other by name.

```
HTTP          app/blueprints/*     +  blueprints/accounts|import_export|…
     ↓ imports named functions
Services      app/services/billing.py, void_rebuild.py, accounting.py, …
     ↓
Models        models/core.py, sales.py, cash.py, …
     ↑
Factory       app/create_app()     main.py is 8 lines
```

## What “modular” means here

| Wrong (previous) | Now |
|------------------|-----|
| Keep `ams_app/main.py` and re-export routes | Dump removed |
| `wire_services()` copies every function into every module | Explicit `from app.services.X import y` |
| `from main import cash_flow, rebuild_…` | Import the domain module |
| One 20k-line file | Domain packages + factory |

Cycle `billing ↔ void_rebuild` is broken with a **local import** inside `find_bill_conflict` only. Everything else is a top-level named import.

## Run / test

```bash
pip install -r requirements.txt
ALLOW_EMPTY_DB=1 python main.py
ALLOW_EMPTY_DB=1 python -m pytest tests/ -q
```

## Backup and storage maintenance

Authoritative backups are private directories under `instance/storage/backups/`.
Each contains a transactionally consistent SQLite snapshot, permanent uploaded
business documents from `static/uploads/`, and a checksummed JSON manifest.
The newest backup is fully validated before retention is applied; the default
steady state is the latest **3 successful backups**.

The app starts a cross-process-locked fallback scheduler at process startup.
For production, also configure the host's hourly scheduler (cron,
PythonAnywhere scheduled task, Windows Task Scheduler, or equivalent) from the
repository root. The command is idempotent and does not create missed
historical backups:

```bash
.venv/bin/python tools/maintenance.py backup-if-due
```

Useful controlled operations:

```bash
.venv/bin/python tools/maintenance.py status
.venv/bin/python tools/maintenance.py backup-now
.venv/bin/python tools/maintenance.py verify instance/storage/backups/backup_YYYYMMDD_HHMMSS
# Stop normal writers and use a maintenance window before restore:
.venv/bin/python tools/maintenance.py restore instance/storage/backups/backup_YYYYMMDD_HHMMSS --confirm
```

Configuration environment variables include `BACKUP_INTERVAL_SECONDS`
(default `3600`), `BACKUP_RETENTION` (default `3`), `BACKUP_DIR`,
`MAINTENANCE_TEMP_DIR`, `MIN_FREE_DISK_BYTES`, and
`BACKUP_EMBEDDED_SCHEDULER`. Set the final variable to `0` only when the
external scheduler is guaranteed. Backup paths are not exposed as static URLs.
Technical warnings/errors rotate at 2 MiB with three retained files by default
(`ERROR_LOG_MAX_BYTES`, `ERROR_LOG_BACKUP_COUNT`).
