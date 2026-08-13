#!/usr/bin/env python
"""Reset User account passwords and roles.

Usage:
    python tools/repair_controlled/fix_accounts_and_test.py --confirm
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from tools.repair_controlled.repair_guard import preflight
preflight(
    script_name=__file__,
    description="Reset User account passwords and roles in the production database",
)

from werkzeug.security import generate_password_hash  # noqa: E402

from main import app  # noqa: E402
from models import db, User  # noqa: E402


ALLOWED = {
    # desired_username: role
    "Rehman Ahmed": "admin",
    "Rizwan Ahmed": "user",
    "Adnan Ahmed": "user",
    "Shujaat Muzaffar": "user",
    "Admin": "admin",
}

SAME_PASSWORD_FOR_ALL = "Admin@fbm12345"


def _login_ok(client, username: str, password: str) -> bool:
    resp = client.post(
        "/login",
        data={"username": username, "password": password, "remember_me": "0"},
        follow_redirects=False,
    )
    if resp.status_code not in (301, 302, 303, 307, 308):
        return False
    loc = resp.headers.get("Location") or ""
    return ("/login" not in loc) and ("/root/recovery" not in loc)


def main() -> int:
    with app.app_context():
        users = User.query.order_by(User.id.asc()).all()

        # Delete root if present.
        for u in list(users):
            if (u.username or "").strip().lower() == "root" or (u.role or "").strip().lower() == "root":
                db.session.delete(u)

        # Delete users not in allowed list (by current username).
        for u in users:
            if u in db.session.deleted:
                continue
            if u.username not in ALLOWED:
                db.session.delete(u)

        db.session.flush()

        # Ensure/normalize the allowed accounts (create missing ones).
        for desired_username, role in ALLOWED.items():
            u = User.query.filter_by(username=desired_username).order_by(User.id.asc()).first()
            if not u:
                u = User(username=desired_username, role=role, status="active")
                db.session.add(u)

            u.username = desired_username
            u.role = role
            u.status = "active"

            u.password_hash = generate_password_hash(SAME_PASSWORD_FOR_ALL)
            u.password_plain = SAME_PASSWORD_FOR_ALL

        db.session.commit()

        # Test logins
        client = app.test_client()
        results = {}
        for username in ALLOWED.keys():
            results[username] = _login_ok(client, username, SAME_PASSWORD_FOR_ALL)
            client.get("/logout")

        print("Login test results:")
        for username, ok in results.items():
            print(f"- {username}: {'OK' if ok else 'FAIL'}")

        bad = [u for u, ok in results.items() if not ok]
        if bad:
            print("")
            print("One or more logins failed:", ", ".join(bad))
            return 2

        print("")
        print("Final accounts (username / password):")
        for username in ALLOWED.keys():
            print(f"- {username} / {SAME_PASSWORD_FOR_ALL}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
