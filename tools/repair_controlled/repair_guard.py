"""
Repair Guard — Preflight Safety Check
=======================================
Every controlled-repair script must call `preflight()` at the top before
making any database changes.

What it checks:
  1. Explicit --confirm flag is present (prevents accidental runs).
  2. Production DB file exists and is readable.
  3. A fresh backup of the DB is taken to instance/reconcile_backups/.
  4. The action is logged to instance/repair_audit.log.

Usage in a repair script:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from tools.repair_controlled.repair_guard import preflight

    preflight(script_name=__file__, description="Void duplicate DirectSale rows")
    # ... repair logic below ...

To run any script in this folder:
    python tools/repair_controlled/repair_erp_consistency.py --confirm
"""

from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path


_DB_PATH = Path("instance") / "ahmed_cement.db"
_BACKUP_DIR = Path("instance") / "reconcile_backups"
_AUDIT_LOG = Path("instance") / "repair_audit.log"


def preflight(
    script_name: str,
    description: str = "",
    *,
    require_confirm: bool = True,
) -> str:
    """Run all preflight checks. Returns the path to the backup file taken."""
    script_label = Path(script_name).name

    if require_confirm and "--confirm" not in sys.argv:
        print(
            f"\n[AMS RepairGuard] STOPPED — {script_label}\n"
            f"  This script modifies the production database.\n"
            f"  Re-run with --confirm to proceed:\n\n"
            f"    python {script_name} --confirm\n"
        )
        sys.exit(1)

    _check_db()
    backup_path = _take_backup(script_label)
    _log_action(script_label, description, backup_path)

    print(f"[AMS RepairGuard] Preflight OK — {script_label}")
    print(f"  DB backup : {backup_path}")
    print(f"  Audit log : {_AUDIT_LOG}")
    print()
    return backup_path


def _check_db() -> None:
    if not _DB_PATH.exists():
        print(f"[AMS RepairGuard] ERROR — DB not found: {_DB_PATH}")
        sys.exit(1)
    if not os.access(_DB_PATH, os.R_OK | os.W_OK):
        print(f"[AMS RepairGuard] ERROR — DB not readable/writable: {_DB_PATH}")
        sys.exit(1)


def _take_backup(script_label: str) -> str:
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = script_label.replace(".py", "").replace(" ", "_")
    backup_name = f"pre_repair_{safe_label}_{stamp}.db"
    dest = _BACKUP_DIR / backup_name
    shutil.copy2(_DB_PATH, dest)
    _cleanup_old_backups(keep=20)
    return str(dest)


def _cleanup_old_backups(keep: int = 20) -> None:
    try:
        files = sorted(
            [f for f in _BACKUP_DIR.iterdir() if f.suffix == ".db"],
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        for old in files[keep:]:
            old.unlink(missing_ok=True)
    except Exception:
        pass


def _log_action(script_label: str, description: str, backup_path: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user = os.environ.get("USER", os.environ.get("USERNAME", "unknown"))
    argv = " ".join(sys.argv[1:]) or "(no args)"
    line = (
        f"[{ts}] script={script_label!r} user={user!r} args={argv!r} "
        f"description={description!r} backup={backup_path!r}\n"
    )
    try:
        _AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_AUDIT_LOG, "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception as exc:
        print(f"[AMS RepairGuard] WARNING — could not write audit log: {exc}")


if __name__ == "__main__":
    print("Repair Guard — Preflight Checker")
    print(f"  DB path   : {_DB_PATH}  exists={_DB_PATH.exists()}")
    print(f"  Backup dir: {_BACKUP_DIR}  exists={_BACKUP_DIR.exists()}")
    print(f"  Audit log : {_AUDIT_LOG}  exists={_AUDIT_LOG.exists()}")
    if _AUDIT_LOG.exists():
        lines = _AUDIT_LOG.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        print(f"\n  Last {min(10, len(lines))} repair actions:")
        for ln in lines[-10:]:
            print(f"    {ln}")
