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
