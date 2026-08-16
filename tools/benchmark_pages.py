#!/usr/bin/env python3
"""Read-only representative page timing against an isolated database copy."""
from __future__ import annotations
import json
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    from app import create_app

    source = ROOT / "instance" / "ahmed_cement.db"
    with tempfile.TemporaryDirectory(prefix="ams-benchmark-") as folder:
        target = Path(folder) / "benchmark.db"
        src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        dst = sqlite3.connect(target)
        src.backup(dst)
        dst.close()
        src.close()
        started = time.perf_counter()
        app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{target}",
            "BACKUP_EMBEDDED_SCHEDULER": False,
            "WTF_CSRF_ENABLED": False,
            "SECRET_KEY": "benchmark-only",
        })
        startup_ms = (time.perf_counter() - started) * 1000
        client = app.test_client()
        login_started = time.perf_counter()
        login = client.post("/login", data={
            "username": "Admin", "password": "Admin@fbm12345", "remember_me": "0"
        }, follow_redirects=False)
        login_ms = (time.perf_counter() - login_started) * 1000
        pages = [
            "/", "/clients", "/materials", "/bookings", "/direct_sales",
            "/pending_bills", "/inventory/stock_summary", "/accounts/",
            "/profit_reports", "/api/clients/search?q=ahm",
        ]
        results = {}
        for path in pages:
            samples = []
            status = None
            size = None
            for _ in range(4):
                tick = time.perf_counter()
                response = client.get(path, follow_redirects=False)
                samples.append((time.perf_counter() - tick) * 1000)
                status = response.status_code
                size = len(response.data)
            warm = sorted(samples[1:])
            results[path] = {
                "status": status,
                "median_ms": round(warm[len(warm) // 2], 2),
                "response_bytes": size,
            }
        print(json.dumps({
            "startup_ms": round(startup_ms, 2),
            "login_status": login.status_code,
            "login_ms": round(login_ms, 2),
            "route_rules": len(list(app.url_map.iter_rules())),
            "pages": results,
        }, indent=2))


if __name__ == "__main__":
    main()
