#!/usr/bin/env python
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from main import app  # noqa: E402
from models import db, User  # noqa: E402


def main() -> int:
    with app.app_context():
        users = User.query.order_by(User.id.asc()).all()
        print(f"Total users: {len(users)}")
        print("")
        print("id\tusername\trole\tstatus\tpassword_plain")
        for u in users:
            pw = u.password_plain
            if pw is None:
                pw = ""
            print(f"{u.id}\t{u.username}\t{u.role}\t{u.status}\t{pw}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
