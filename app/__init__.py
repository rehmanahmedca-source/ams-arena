"""Application factory — modular AMS ERP."""
from __future__ import annotations

import os
import secrets
import logging
from datetime import timedelta
from pathlib import Path

from flask import Flask
from flask_login import LoginManager

from models import db
from utils.module_loader import load_modules


def create_app(test_config: dict | None = None) -> Flask:
    root = Path(__file__).resolve().parent.parent
    app = Flask(
        __name__,
        template_folder=str(root / "templates"),
        static_folder=str(root / "static"),
        instance_path=str(root / "instance"),
        instance_relative_config=True,
    )

    instance_dir = root / "instance"
    instance_dir.mkdir(parents=True, exist_ok=True)
    (instance_dir / "import_uploads").mkdir(parents=True, exist_ok=True)

    db_path = os.environ.get("APP_DB_PATH") or str(instance_dir / "ahmed_cement.db")
    max_upload_mb = int(os.environ.get("MAX_UPLOAD_MB", "256") or "256")

    secret_file = instance_dir / "secret_key"
    secret = os.environ.get("SECRET_KEY")
    if not secret:
        if secret_file.exists():
            secret = secret_file.read_text(encoding="utf-8").strip()
        if not secret:
            secret = secrets.token_hex(32)
            secret_file.write_text(secret, encoding="utf-8")

    # Yard PCs use plain HTTP (http://192.168.x.x:5000). Secure + SameSite=None
    # cookies are dropped on HTTP, so POST /login 302 then GET / bounces to login.
    # For HTTPS/iframe set AMS_HTTPS=1 (or SESSION_COOKIE_SECURE=1 + SAMESITE=None).
    env_secure = os.environ.get("SESSION_COOKIE_SECURE")
    env_samesite = os.environ.get("SESSION_COOKIE_SAMESITE")
    use_https = (os.environ.get("AMS_HTTPS") or "").strip() == "1"
    if env_secure is None:
        cookie_secure = bool(use_https)
    else:
        cookie_secure = env_secure.strip() not in ("0", "false", "False", "")
    cookie_samesite = (env_samesite or ("None" if cookie_secure else "Lax")).strip() or "Lax"
    if str(cookie_samesite).lower() == "none" and not cookie_secure:
        cookie_samesite = "Lax"

    app.config.update(
        SECRET_KEY=secret,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=max_upload_mb * 1024 * 1024,
        PERMANENT_SESSION_LIFETIME=timedelta(days=14),
        REMEMBER_COOKIE_DURATION=timedelta(days=30),
        SESSION_COOKIE_NAME="ams_session",
        SESSION_COOKIE_PATH="/",
        SESSION_COOKIE_DOMAIN=None,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE=cookie_samesite,
        SESSION_COOKIE_SECURE=cookie_secure,
        SESSION_REFRESH_EACH_REQUEST=True,
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SAMESITE=cookie_samesite,
        REMEMBER_COOKIE_SECURE=cookie_secure,
        PREFERRED_URL_SCHEME="https" if cookie_secure else "http",
        FULL_RAW_IMPORT_ENABLED="1",
        IMPORT_UPLOADS_DIR=str(instance_dir / "import_uploads"),
        IMPORT_REPORTS_DIR=str(instance_dir / "import_reports"),
        TESTING=False,
    )
    if test_config:
        app.config.update(test_config)

    _configure_logging()
    db.init_app(app)

    @app.before_request
    def _sqlite_wal_once():
        if app.config.get('_sqlite_wal_ready'):
            return
        try:
            from sqlalchemy import text as sql_text
            db.session.execute(sql_text('PRAGMA journal_mode=WAL'))
            db.session.execute(sql_text('PRAGMA busy_timeout=8000'))
            app.config['_sqlite_wal_ready'] = True
        except Exception:
            pass

    login_manager = LoginManager()
    login_manager.login_view = "login"
    # None: same user (or several managers) may stay logged in from many IPs/PCs.
    # "basic"/"strong" can drop a session when IP or User-Agent differs.
    login_manager.session_protection = None
    login_manager.init_app(app)

    from app.services.permissions import load_user

    login_manager.user_loader(load_user)

    # Core domain routes first so short names (clients, login, …) are not
    # stolen by later feature packs such as fbm_rentals.clients.
    from app.blueprints.core import bp as core_bp
    from app.blueprints.auth import bp as auth_bp
    from app.blueprints.sales import bp as sales_bp
    from app.blueprints.masters import bp as masters_bp
    from app.blueprints.ledgers import bp as ledgers_bp
    from app.blueprints.ops import bp as ops_bp
    from app.blueprints.reports import bp as reports_bp
    from app.blueprints.api import bp as api_bp
    from app.blueprints.system import bp as system_bp
    from app.blueprints.misc import bp as misc_bp

    for bp in (
        core_bp,
        auth_bp,
        sales_bp,
        masters_bp,
        ledgers_bp,
        ops_bp,
        reports_bp,
        api_bp,
        system_bp,
        misc_bp,
    ):
        if bp.name not in app.blueprints:
            app.register_blueprint(bp)

    _alias_unprefixed_endpoints(app)

    load_modules(app, blueprint_dir=str(root / "blueprints"))

    from app.hooks import register_hooks

    register_hooks(app)

    from app.services.import_jobs import register_import_job_routes

    register_import_job_routes(app)

    with app.app_context():
        from models import ensure_import_tables

        try:
            ensure_import_tables()
        except Exception:
            logging.getLogger(__name__).exception("import tables init failed")
        try:
            from app.services.health import (
                _guard_db_file_before_bootstrap,
                _db_health_check_after_bootstrap,
            )
            from app.services.schema import _bootstrap_database

            if app.config.get("TESTING"):
                from app.services.schema import _ensure_default_admin, _ensure_model_columns
                db.create_all()
                _ensure_model_columns()
                # Keep a fresh test database usable in the same way as a fresh
                # production database.  The smoke tests and local developers
                # rely on the documented Admin login even when no rows exist.
                _ensure_default_admin()
            else:
                _guard_db_file_before_bootstrap()
                _bootstrap_database()
                _db_health_check_after_bootstrap()
        except Exception:
            logging.getLogger(__name__).exception("bootstrap skipped/failed")

    return app


def _alias_unprefixed_endpoints(app: Flask) -> None:
    """Keep legacy url_for('login') / templates working after blueprint split."""
    existing = set(app.view_functions)
    extras = []
    for rule in list(app.url_map.iter_rules()):
        if "." not in rule.endpoint:
            continue
        short = rule.endpoint.split(".", 1)[1]
        if short in existing:
            continue
        view = app.view_functions.get(rule.endpoint)
        if view is None:
            continue
        app.view_functions[short] = view
        extras.append((rule.rule, short, view, sorted((rule.methods or set()) - {"HEAD", "OPTIONS"})))
        existing.add(short)
    for rule, short, view, methods in extras:
        try:
            app.add_url_rule(rule, endpoint=short, view_func=view, methods=methods or None)
        except Exception:
            pass


def _configure_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s]: %(message)s")
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    root.setLevel(logging.INFO)
    root.addHandler(console)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
