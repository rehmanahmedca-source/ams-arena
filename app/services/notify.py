"""Domain service module — extracted from legacy ERP core."""
from __future__ import annotations

import os
import io
import secrets
import json
import calendar
import threading
import time
import smtplib
import shutil
import sqlite3
import zipfile
import urllib.request
import urllib.error
import re
import logging
import importlib
from itertools import zip_longest
from urllib.parse import unquote
from contextlib import redirect_stderr
from email.message import EmailMessage
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge
from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo
from sqlalchemy import func, case, text, or_, and_, exists, not_
from sqlalchemy.orm import selectinload
from types import SimpleNamespace
from flask import (
    current_app as app,
    render_template, request, redirect, url_for, flash, jsonify,
    send_file, Response, make_response, send_from_directory,
    got_request_exception, abort, session, g,
)
from flask_login import login_user, login_required, logout_user, current_user

from models import *
from utils.audit import audit_log
from utils.reconciliation import run_auto_reconcile
from cash_flow_reconciliation_helpers import (
    create_reconciliation, update_reconciliation, delete_reconciliation,
    get_reconciliation_history, migrate_legacy_record,
)
from app.services import constants as C
from app.services import state

# === explicit service imports ===
from app.services.risk import (
    _normalize_risk_label,
    _pending_bill_age_days,
    _pending_bill_category,
    _pending_bill_risk,
)
from app.services.time_money import (
    pk_now,
    pk_today,
)


# Rebind constants used as bare names
OPEN_KHATA_CODE = C.OPEN_KHATA_CODE
OPEN_KHATA_NAME = C.OPEN_KHATA_NAME
PK_TZ = C.PK_TZ
SALE_CATEGORY_CHOICES = C.SALE_CATEGORY_CHOICES
_SALE_CATEGORY_ALIASES = C._SALE_CATEGORY_ALIASES
DOMAIN_WIPE_REGISTRY = C.DOMAIN_WIPE_REGISTRY
USER_PERMISSION_DEFAULTS = C.USER_PERMISSION_DEFAULTS
PERMISSION_LEGACY_FALLBACKS = C.PERMISSION_LEGACY_FALLBACKS
ENDPOINT_PERMISSION_MAP = C.ENDPOINT_PERMISSION_MAP
AUTO_BILL_NS_DEFAULT = C.AUTO_BILL_NS_DEFAULT
AUTO_BILL_NAMESPACES = C.AUTO_BILL_NAMESPACES
EDITABLE_USER_PERMISSION_FIELDS = C.EDITABLE_USER_PERMISSION_FIELDS
basedir = C.basedir
legacy_instance_dir = C.legacy_instance_dir
legacy_db_path = C.legacy_db_path
db_path = C.db_path
_DB_HEALTH_SNAPSHOT_PATH = C._DB_HEALTH_SNAPSHOT_PATH
_max_upload_mb = C._max_upload_mb
_AUTO_BACKUP_ENABLED = C._AUTO_BACKUP_ENABLED
_WIPE_BACKUP_ENABLED = C._WIPE_BACKUP_ENABLED
_AUTO_RECONCILE_ENABLED = C._AUTO_RECONCILE_ENABLED
_AUTO_RECONCILE_FIX = C._AUTO_RECONCILE_FIX
_AUTO_RECONCILE_INTERVAL_SEC = C._AUTO_RECONCILE_INTERVAL_SEC
_AUTO_RECONCILE_TOL = C._AUTO_RECONCILE_TOL
_ALLOW_EMPTY_DB = C._ALLOW_EMPTY_DB
_ALLOW_DB_DROP = C._ALLOW_DB_DROP
_DB_HEALTH_DROP_RATIO = C._DB_HEALTH_DROP_RATIO
_DB_HEALTH_DROP_MIN = C._DB_HEALTH_DROP_MIN
_DB_HEALTH_MIN_BYTES = C._DB_HEALTH_MIN_BYTES

def _start_notification_worker():
    if state.NOTIFY_WORKER_STARTED:
        return
    t = threading.Thread(target=_notification_worker_loop, daemon=True, name='notify-daily-mailer')
    t.start()
    state.NOTIFY_WORKER_STARTED = True


def _smtp_send_attachments_to(recipients, subject, body, attachments):
    recipients = [x.strip() for x in (recipients or []) if str(x or '').strip()]
    if not recipients:
        return False, 'No recipients configured'

    settings_obj = Settings.query.first()
    smtp_host = (settings_obj.smtp_host if settings_obj and settings_obj.smtp_host else os.environ.get('SMTP_HOST', '')).strip()
    smtp_user = (settings_obj.smtp_user if settings_obj and settings_obj.smtp_user else os.environ.get('SMTP_USER', '')).strip()
    smtp_pass = (settings_obj.smtp_pass if settings_obj and settings_obj.smtp_pass else os.environ.get('SMTP_PASS', '')).strip().replace(' ', '')
    smtp_port = int((settings_obj.smtp_port if settings_obj and settings_obj.smtp_port else os.environ.get('SMTP_PORT', '587')) or 587)
    if settings_obj and settings_obj.smtp_use_tls is not None:
        use_tls = bool(settings_obj.smtp_use_tls)
    else:
        use_tls = os.environ.get('SMTP_USE_TLS', '1').strip() != '0'
    from_email = (
        (settings_obj.smtp_from if settings_obj and settings_obj.smtp_from else '') or
        os.environ.get('SMTP_FROM', '') or
        smtp_user
    ).strip()
    if not smtp_host or not from_email:
        return False, 'SMTP settings missing'
    if smtp_user and not smtp_pass:
        return False, 'SMTP password missing'

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = from_email
    msg['To'] = ', '.join(recipients)
    msg.set_content(body)
    for fname, mime, content in attachments:
        maintype, subtype = mime.split('/', 1)
        msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=fname)

    try:
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=60) as server:
                if smtp_user:
                    server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=60) as server:
                if use_tls:
                    server.starttls()
                if smtp_user:
                    server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        return True, f'Sent to {len(recipients)} email(s)'
    except Exception as e:
        return False, f'SMTP send failed: {e}'


def _build_notifications_pdf_bytes(rows):
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    page_width = 14.8 * cm
    page_height = 21 * cm
    margin = 1 * cm
    c = canvas.Canvas(buf, pagesize=(page_width, page_height))
    width, height = page_width, page_height

    y = height - margin
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, y, f"Pending Credit Notifications - {pk_now().strftime('%Y-%m-%d')}")
    y -= 24
    c.setFont("Helvetica", 9)
    c.drawString(margin, y, "Client")
    c.drawString(210, y, "Bill")
    c.drawString(300, y, "Category")
    c.drawString(390, y, "Days")
    c.drawString(440, y, "Amount")
    c.drawString(510, y, "Risk")
    y -= 14

    for r in rows[:120]:
        if y < margin:
            c.showPage()
            y = height - margin
        c.setFont("Helvetica", 8)
        c.drawString(margin, y, str(r['client'])[:30])
        c.drawString(210, y, str(r['bill_no'])[:14])
        c.drawString(300, y, str(r['category'])[:12])
        c.drawRightString(420, y, str(r['age_days']))
        c.drawRightString(500, y, f"{r['amount']:.0f}")
        c.drawString(510, y, str(r['risk_level']))
        y -= 12

    c.save()
    buf.seek(0)
    return buf.read()


def _build_notifications_xlsx_bytes(rows):
    import pandas as pd
    data = [{
        'Client': r['client'],
        'Bill No': r['bill_no'],
        'Category': r['category'],
        'Age Days': r['age_days'],
        'Amount': r['amount'],
        'Risk': r['risk_level'],
        'Risk Score': r['risk_score'],
    } for r in rows]
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as writer:
        pd.DataFrame(data).to_excel(writer, index=False, sheet_name='PendingCredit')
    out.seek(0)
    return out.read()


def _build_pending_rows_for_report():
    pending = PendingBill.query.filter(
        PendingBill.is_void == False,
        PendingBill.is_paid == False,
        PendingBill.amount > 0
    ).all()
    rows = []
    for pb in pending:
        score, level = _pending_bill_risk(pb)
        rows.append({
            'client': pb.client_name or pb.client_code or '',
            'bill_no': pb.bill_no or '',
            'category': _pending_bill_category(pb),
            'age_days': _pending_bill_age_days(pb),
            'amount': float(pb.amount or 0),
            'risk_score': score,
            'risk_level': level,
        })
    rows.sort(key=lambda x: (x['risk_score'], x['age_days'], x['amount']), reverse=True)
    return rows


def _send_daily_notifications_email():
    emails = [x.email for x in StaffEmail.query.filter_by(is_active=True).all() if x.email]
    if not emails:
        return False, 'No active staff emails configured'

    settings_obj = Settings.query.first()
    rows = _build_pending_rows_for_report()
    pdf_bytes = _build_notifications_pdf_bytes(rows)
    xlsx_bytes = _build_notifications_xlsx_bytes(rows)
    attachments = [
        (f"pending_credit_{pk_today().isoformat()}.pdf", 'application/pdf', pdf_bytes),
        (f"pending_credit_{pk_today().isoformat()}.xlsx", 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', xlsx_bytes),
    ]
    subject = f"Daily Pending Credit Report - {pk_today().isoformat()}"
    body = f"Attached: daily pending credit report (PDF + Excel).\nTotal pending records: {len(rows)}"

    smtp_host = (settings_obj.smtp_host if settings_obj and settings_obj.smtp_host else os.environ.get('SMTP_HOST', '')).strip()
    smtp_user = (settings_obj.smtp_user if settings_obj and settings_obj.smtp_user else os.environ.get('SMTP_USER', '')).strip()
    smtp_pass = (settings_obj.smtp_pass if settings_obj and settings_obj.smtp_pass else os.environ.get('SMTP_PASS', '')).strip()
    # Gmail app passwords are often pasted with spaces; normalize to avoid auth failures.
    smtp_pass = smtp_pass.replace(' ', '')
    smtp_port = int((settings_obj.smtp_port if settings_obj and settings_obj.smtp_port else os.environ.get('SMTP_PORT', '587')) or 587)
    if settings_obj and settings_obj.smtp_use_tls is not None:
        use_tls = bool(settings_obj.smtp_use_tls)
    else:
        use_tls = os.environ.get('SMTP_USE_TLS', '1').strip() != '0'
    from_email = (
        (settings_obj.smtp_from if settings_obj and settings_obj.smtp_from else '') or
        os.environ.get('SMTP_FROM', '') or
        smtp_user
    ).strip()
    if not smtp_host or not from_email:
        return False, 'SMTP settings missing. Configure in Settings -> General Settings (SMTP) or env.'
    if smtp_user and not smtp_pass:
        return False, 'SMTP password missing. Enter SMTP App Password in Settings.'

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = from_email
    msg['To'] = ', '.join(emails)
    msg.set_content(body)
    for fname, mime, content in attachments:
        maintype, subtype = mime.split('/', 1)
        msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=fname)

    try:
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as server:
                if smtp_user:
                    server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                if use_tls:
                    server.starttls()
                if smtp_user:
                    server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        return True, f'Sent via SMTP to {len(emails)} email(s)'
    except smtplib.SMTPAuthenticationError as e:
        detail = ''
        try:
            detail = (e.smtp_error or b'').decode(errors='ignore').strip()
        except Exception:
            detail = str(e)
        msg = 'SMTP login failed. For Gmail, use a 16-character App Password.'
        if detail:
            msg = f'{msg} Server says: {detail}'
        return False, msg
    except Exception as e:
        return False, f'SMTP send failed: {e}'


def _notification_worker_loop():
    while True:
        try:
            with app.app_context():
                now = pk_now()
                settings_obj = Settings.query.first()
                target_time = (settings_obj.notify_daily_time if settings_obj and settings_obj.notify_daily_time else os.environ.get('NOTIFY_DAILY_TIME', '08:00'))
                hh, mm = 8, 0
                try:
                    hh, mm = [int(x) for x in target_time.split(':', 1)]
                except Exception:
                    pass
                if now.hour == hh and now.minute == mm and state.NOTIFY_LAST_SENT_DATE != now.date():
                        _send_daily_notifications_email()
                        state.NOTIFY_LAST_SENT_DATE = now.date()
            time.sleep(30)
        except Exception:
            time.sleep(60)


def _build_notification_rows(category_filter='all', status_filter='all', risk_filter='all', q=''):
    q = (q or '').strip().lower()
    bills = PendingBill.query.filter(PendingBill.is_void == False).all()
    contact_count_rows = db.session.query(
        FollowUpContact.pending_bill_id,
        func.count(FollowUpContact.id)
    ).group_by(FollowUpContact.pending_bill_id).all()
    contact_count_by_bill = {bill_id: int(cnt or 0) for bill_id, cnt in contact_count_rows}
    rows = []
    for pb in bills:
        # Credit follow-up queue: only open credit balances.
        # Exclude paid, zero/negative, and cash-tagged rows.
        if pb.is_paid:
            continue
        if float(pb.amount or 0) <= 0:
            continue
        if pb.is_cash:
            continue

        category = _pending_bill_category(pb)
        age_days = _pending_bill_age_days(pb)
        contact_count = contact_count_by_bill.get(pb.id, 0)
        score, risk_level = _pending_bill_risk(pb, contact_count=contact_count)
        status = 'Paid' if pb.is_paid else 'Pending'
        row = {
            'bill': pb,
            'category': category,
            'status': status,
            'age_days': age_days,
            'risk_score': score,
            'risk_level': risk_level,
            'risk_level_key': _normalize_risk_label(risk_level),
            'amount': float(pb.amount or 0),
            'client_text': f"{pb.client_name or ''} {pb.client_code or ''}".strip(),
            'contact_count': contact_count
        }
        if category_filter != 'all':
            if category_filter == 'billed' and category != 'Billed':
                continue
            if category_filter == 'unbilled' and category != 'Unbilled':
                continue
            if category_filter == 'open_khata' and category != 'Open Khata':
                continue
            if category_filter == 'cash_unbilled' and category != 'Unbilled Cash':
                continue
            if category_filter == 'cash_paid' and category != 'Cash Paid':
                continue
        if status_filter != 'all' and status.lower() != status_filter.lower():
            continue
        if risk_filter != 'all' and _normalize_risk_label(risk_level) != _normalize_risk_label(risk_filter):
            continue
        if q:
            combined = f"{pb.client_name or ''} {pb.client_code or ''} {pb.bill_no or ''} {pb.reason or ''}".lower()
            if q not in combined:
                continue
        rows.append(row)

    rows.sort(key=lambda r: (r['risk_score'], r['age_days'], r['amount']), reverse=True)
    return rows


def _resolve_reminder_with_contact(rem, response_text, channel='Call', note='', contacted_at=None, created_by=''):
    if not rem:
        return False, 'Reminder not found'
    if not response_text:
        return False, 'Customer response is required'

    if channel not in ['Call', 'WhatsApp', 'SMS', 'Email', 'Visit', 'Other']:
        channel = 'Other'
    contact_time = contacted_at or pk_now()

    db.session.add(FollowUpContact(
        pending_bill_id=rem.pending_bill_id,
        reminder_id=rem.id,
        contacted_at=contact_time,
        channel=channel,
        response=response_text[:200],
        note=(note or 'Reminder marked done')[:500],
        created_by=created_by or ''
    ))
    rem.is_done = True
    rem.acknowledged_at = pk_now()
    db.session.commit()
    return True, 'Reminder closed and history saved'


