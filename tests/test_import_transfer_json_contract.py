"""Regression tests: /import_export/transfer/import must answer JSON for
fetch-driven clients (the hub page "Import Full XLSX" flow) instead of
redirecting to an HTML page, which swallowed the real result and made the UI
show the generic "Server did not send a table list" dialog.

Also guards that plain (non-fetch) clients keep the classic flash+redirect
behavior.
"""
import io
import os

import pytest

os.environ["ALLOW_EMPTY_DB"] = "1"
os.environ["ALLOW_DB_DROP"] = "1"


@pytest.fixture()
def app(tmp_path):
    db_file = tmp_path / "test.db"
    os.environ["APP_DB_PATH"] = str(db_file)
    os.environ["ALLOW_EMPTY_DB"] = "1"
    from app import create_app
    from models import db, User
    from werkzeug.security import generate_password_hash

    application = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_file}",
            "WTF_CSRF_ENABLED": False,
            "SECRET_KEY": "test",
            "LOGIN_DISABLED": True,
            "FULL_RAW_IMPORT_ENABLED": "1",
            # Keep any upload artifacts out of the repo's instance dir.
            "IMPORT_UPLOADS_DIR": str(tmp_path / "uploads"),
        }
    )
    with application.app_context():
        db.create_all()
        if not User.query.filter_by(username="tester").first():
            u = User(
                username="tester",
                role="admin",
                status="active",
                password_hash=generate_password_hash("secret"),
                can_import_export=True,
            )
            db.session.add(u)
            db.session.commit()
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()


def _xlsx_bytes(sheets):
    """Build an in-memory xlsx where sheets maps sheet name -> list of dict rows."""
    import pandas as pd

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, rows in sheets.items():
            pd.DataFrame(rows).to_excel(writer, sheet_name=name, index=False)
    return buf.getvalue()


FETCH_HEADERS = {"X-Requested-With": "fetch", "Accept": "application/json"}


def test_bogus_xlsx_fetch_gets_json_error_not_redirect(client):
    """The exact reported failure: arbitrary xlsx + literal_all + fetch headers
    must come back as JSON with a real error, never an HTML redirect."""
    blob = _xlsx_bytes({"Data": [{"foo": "bar"}]})
    rv = client.post(
        "/import_export/transfer/import",
        data={
            "file": (io.BytesIO(blob), "random.xlsx"),
            "sections": "literal_all",
            "mode": "append",
        },
        headers=FETCH_HEADERS,
        content_type="multipart/form-data",
    )
    assert rv.status_code == 400
    assert rv.is_json, "fetch client must receive JSON, got: %s" % rv.content_type
    body = rv.get_json()
    assert body.get("ok") is False
    assert "No importable sheets found" in (body.get("headline") or "")
    assert body.get("table_results") == []


def test_bogus_xlsx_plain_post_still_redirects(client):
    """Non-fetch clients keep the classic flash + redirect behavior."""
    blob = _xlsx_bytes({"Data": [{"foo": "bar"}]})
    rv = client.post(
        "/import_export/transfer/import",
        data={
            "file": (io.BytesIO(blob), "random.xlsx"),
            "sections": "literal_all",
            "mode": "append",
        },
        content_type="multipart/form-data",
    )
    assert rv.status_code == 302


def test_missing_file_fetch_gets_json_error(client):
    rv = client.post(
        "/import_export/transfer/import",
        data={"sections": "literal_all", "mode": "append"},
        headers=FETCH_HEADERS,
        content_type="multipart/form-data",
    )
    assert rv.status_code == 400
    assert rv.is_json
    assert "upload" in (rv.get_json().get("headline") or "").lower()


def test_valid_xlsx_fetch_gets_json_report_and_inserts(client, app):
    """A workbook with real table sheets must return the per-table JSON report
    and actually persist the rows."""
    from models import Client, MaterialCategory, db

    blob = _xlsx_bytes(
        {
            "client": [
                {"code": "FBMCL-T01", "name": "Test Import Client"},
            ],
            "material_category": [
                {"name": "Import Test Category"},
            ],
        }
    )
    rv = client.post(
        "/import_export/transfer/import",
        data={
            "file": (io.BytesIO(blob), "backup.xlsx"),
            "sections": "literal_all",
            "mode": "append",
        },
        headers=FETCH_HEADERS,
        content_type="multipart/form-data",
    )
    assert rv.status_code == 200
    assert rv.is_json
    body = rv.get_json()
    assert body.get("ok") is True
    assert body.get("table_results"), "expected per-table breakdown in JSON"
    names = [r.get("name") for r in body["table_results"]]
    assert "client" in names and "material_category" in names

    with app.app_context():
        assert Client.query.filter_by(code="FBMCL-T01").first() is not None
        assert MaterialCategory.query.filter_by(name="Import Test Category").first() is not None


def test_detect_master_backup_switches_and_returns_json(client, app):
    """A master-style workbook uploaded to the literal_all card is auto-switched
    to all_business and still answers JSON for fetch clients."""
    from models import MaterialCategory, db

    blob = _xlsx_bytes(
        {
            "Clients": [{"code": "FBMCL-T02", "name": "Master Import Client"}],
            "Materials": [{"code": "MAT-T02", "name": "Master Import Material"}],
            "MaterialCategories": [{"name": "Master Import Category"}],
            "PendingBills": [{"client_code": "FBMCL-T02", "bill_no": "PB-1", "amount": 100}],
        }
    )
    rv = client.post(
        "/import_export/transfer/import",
        data={
            "file": (io.BytesIO(blob), "master.xlsx"),
            "sections": "literal_all",
            "mode": "append",
        },
        headers=FETCH_HEADERS,
        content_type="multipart/form-data",
    )
    assert rv.status_code == 200
    assert rv.is_json
    body = rv.get_json()
    assert body.get("ok") is True
    assert "Master Backup" in (body.get("headline") or "")

    with app.app_context():
        assert MaterialCategory.query.filter_by(name="Master Import Category").first() is not None
        assert db.session.execute(
            db.select(db.text("count(*)")).select_from(db.text("client"))
        ).scalar() >= 1
