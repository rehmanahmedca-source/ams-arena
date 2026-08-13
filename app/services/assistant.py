"""Domain service."""
from __future__ import annotations

import os, io, json, re, logging, calendar, threading, time, smtplib, shutil, sqlite3, zipfile
import urllib.request, urllib.error, secrets, importlib
from itertools import zip_longest
from urllib.parse import unquote
from contextlib import redirect_stderr
from email.message import EmailMessage
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo
from sqlalchemy import func, case, text, or_, and_, exists, not_
from sqlalchemy.orm import selectinload
from types import SimpleNamespace
from flask import current_app, render_template, request, redirect, url_for, flash, jsonify
from flask import send_file, Response, make_response, send_from_directory, abort, session, g
from flask_login import login_user, login_required, logout_user, current_user

from models import *
from utils.audit import audit_log
from utils.reconciliation import run_auto_reconcile
from cash_flow_reconciliation_helpers import (
    create_reconciliation, update_reconciliation, delete_reconciliation,
    get_reconciliation_history, migrate_legacy_record,
)
from app.services import constants as C

AUTO_BILL_NS_DEFAULT = C.AUTO_BILL_NS_DEFAULT
AUTO_BILL_NAMESPACES = C.AUTO_BILL_NAMESPACES
OPEN_KHATA_CODE = C.OPEN_KHATA_CODE
OPEN_KHATA_NAME = C.OPEN_KHATA_NAME
PK_TZ = C.PK_TZ
SALE_CATEGORY_CHOICES = C.SALE_CATEGORY_CHOICES
_SALE_CATEGORY_ALIASES = C._SALE_CATEGORY_ALIASES
DOMAIN_WIPE_REGISTRY = C.DOMAIN_WIPE_REGISTRY
USER_PERMISSION_DEFAULTS = C.USER_PERMISSION_DEFAULTS
PERMISSION_LEGACY_FALLBACKS = C.PERMISSION_LEGACY_FALLBACKS
ENDPOINT_PERMISSION_MAP = C.ENDPOINT_PERMISSION_MAP
EDITABLE_USER_PERMISSION_FIELDS = C.EDITABLE_USER_PERMISSION_FIELDS
basedir = C.basedir
legacy_instance_dir = C.legacy_instance_dir
legacy_db_path = C.legacy_db_path
db_path = C.db_path
_DB_HEALTH_SNAPSHOT_PATH = C._DB_HEALTH_SNAPSHOT_PATH
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

from app.services import state

# === explicit service imports ===
from app.services.finance_clients import (
    _compute_client_financial_summary,
)
from app.services.ledgers import (
    _build_client_ledger_rows,
)
from app.services.permissions import (
    _user_can,
)
from app.services.sales_core import (
    _cost_rate_for_material,
    normalize_sale_category,
)
from app.services.time_money import (
    _parse_dt_safe,
    pk_today,
)



# --- from assistant_cache.py ---
def _ams_cleanup_export_cache():
    now_ts = time.time()
    expired = [k for k, v in state.AMS_ASSISTANT_EXPORT_CACHE.items() if float(v.get('expires_at', 0) or 0) <= now_ts]
    for k in expired:
        state.AMS_ASSISTANT_EXPORT_CACHE.pop(k, None)


def _ams_cleanup_context_cache():
    now_ts = time.time()
    expired = [k for k, v in state.AMS_ASSISTANT_CONTEXT_CACHE.items() if float(v.get('expires_at', 0) or 0) <= now_ts]
    for k in expired:
        state.AMS_ASSISTANT_CONTEXT_CACHE.pop(k, None)


def _ams_get_context_for_user():
    _ams_cleanup_context_cache()
    return state.AMS_ASSISTANT_CONTEXT_CACHE.get(current_user.id) or {}


def _ams_set_context_for_user(ctx):
    base = dict(ctx or {})
    base['expires_at'] = time.time() + (2 * 60 * 60)  # 2 hours rolling context
    state.AMS_ASSISTANT_CONTEXT_CACHE[current_user.id] = base



# --- from assistant_query.py ---
def _can_manage_categories():
    return current_user.is_authenticated and _user_can('can_manage_materials')


def _ams_resolve_followup(user_query, intent, client_obj, material_name, start_date, end_date):
    q = (user_query or '').lower()
    ctx = _ams_get_context_for_user()
    followup_markers = ['only', 'just', 'same', 'entries', 'that', 'those', 'this']
    is_followup = any(m in q for m in followup_markers)

    # If follow-up omitted client/date/intent, inherit from previous context.
    if is_followup:
        if not client_obj and ctx.get('client_code'):
            client_obj = Client.query.filter(func.lower(Client.code) == str(ctx.get('client_code')).lower()).first()
        if not material_name and ctx.get('material_name'):
            material_name = ctx.get('material_name')
        if intent == 'unknown' and ctx.get('intent'):
            intent = ctx.get('intent')

        if (re.search(r'\b(only|entries|just)\b', q) and
            (ctx.get('intent') in ['client_ledger', 'client_overview', 'client_remaining']) and
            intent in ['unknown', 'client_overview']):
            intent = 'client_ledger'

        # Natural conversational follow-up support:
        # "his materials", "her materials", "materials", etc.
        if client_obj and (
            re.search(r'\b(his|her|their)\b', q) or
            'materials' in q or
            'material' in q
        ):
            if intent in ['unknown', 'client_overview', 'client_ledger']:
                intent = 'client_remaining'

        # If user added a material in follow-up, prefer material remaining view.
        if client_obj and material_name and intent in ['unknown', 'client_overview']:
            intent = 'client_remaining'

        if ctx.get('start_date') and ctx.get('end_date'):
            try:
                if not re.search(r'\d{4}-\d{2}-\d{2}|yesterday|today|this month|last month', q):
                    start_date = datetime.strptime(str(ctx.get('start_date')), '%Y-%m-%d').date()
                    end_date = datetime.strptime(str(ctx.get('end_date')), '%Y-%m-%d').date()
            except Exception:
                pass

    return intent, client_obj, material_name, start_date, end_date


def _ams_parse_date_range(text):
    q = (text or '').lower()
    today = pk_today()
    matches = re.findall(r'\b(\d{4}-\d{2}-\d{2})\b', q)

    def _to_date(val):
        try:
            return datetime.strptime(val, '%Y-%m-%d').date()
        except Exception:
            return None

    if len(matches) >= 2:
        d1 = _to_date(matches[0])
        d2 = _to_date(matches[1])
        if d1 and d2:
            return (min(d1, d2), max(d1, d2))
    if len(matches) == 1:
        d = _to_date(matches[0])
        if d:
            return (d, d)
    if 'yesterday' in q:
        d = today - timedelta(days=1)
        return (d, d)
    if 'today' in q:
        return (today, today)
    if 'last month' in q:
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        return (first_prev, last_prev)
    if 'this month' in q:
        return (today.replace(day=1), today)
    return (today - timedelta(days=30), today)


def _ams_best_material_match(text):
    q = (text or '').strip().lower()
    if not q:
        return None
    names = [x[0] for x in Material.query.with_entities(Material.name).all() if x[0]]
    direct = [n for n in names if n.lower() in q]
    if direct:
        return sorted(direct, key=lambda x: len(x), reverse=True)[0]
    m = re.search(r'(?:material|for|of|about)\s+([a-z0-9\- ]{3,80})', q)
    if m:
        guess = m.group(1).strip()
        row = Material.query.filter(Material.name.ilike(f'%{guess}%')).order_by(func.length(Material.name).asc()).first()
        if row:
            return row.name
    # Token fuzzy fallback (handles typos like "stee" and short aliases like "dg")
    tokens = [t for t in re.findall(r'[a-z0-9\-]+', q) if len(t) >= 2]
    best_name = None
    best_score = 0
    for n in names:
        nl = n.lower()
        score = 0
        for t in tokens:
            if t in nl:
                score += len(t)
            elif nl.startswith(t):
                score += max(1, len(t) - 1)
            elif t.startswith(nl[:max(2, min(4, len(nl)))]):
                score += 1
        if score > best_score:
            best_name = n
            best_score = score
    if best_name and best_score >= 3:
        return best_name
    return None


def _ams_best_client_match(text):
    q = (text or '').strip().lower()
    if not q:
        return None
    code_match = re.search(r'\b(fbmcl-\d+|fbm-\d+|tmpc-\d+)\b', q, flags=re.IGNORECASE)
    if code_match:
        client = Client.query.filter(func.lower(Client.code) == code_match.group(1).lower()).first()
        if client:
            return client
    rows = Client.query.with_entities(Client.name, Client.code).all()
    names = [r[0] for r in rows if r[0]]
    direct = [n for n in names if n.lower() in q]
    if direct:
        best = sorted(direct, key=lambda x: len(x), reverse=True)[0]
        return Client.query.filter_by(name=best).first()

    # Token-based loose matching (e.g., "tahir remaining", "rehman cement")
    stop = {
        'remaining', 'total', 'material', 'reserved', 'cement', 'steel', 'loss', 'losses',
        'ledger', 'client', 'from', 'to', 'between', 'yesterday', 'today', 'report', 'show',
        'for', 'of', 'and', 'in', 'by', 'how', 'much', 'give', 'me'
    }
    tokens = [t for t in re.findall(r'[a-z0-9]+', q) if len(t) >= 3 and t not in stop]
    if not tokens:
        return None
    best_name = None
    best_score = 0
    for n in names:
        nl = (n or '').lower()
        score = 0
        for t in tokens:
            if t in nl:
                score += len(t)
        if score > best_score:
            best_score = score
            best_name = n
    if best_name and best_score >= 3:
        return Client.query.filter_by(name=best_name).first()
    return None


def _ams_detect_intent(text):
    q = (text or '').lower()
    if re.search(r'\b(his|her|their)\s+materials?\b', q):
        return 'client_remaining'
    if re.search(r'\bmaterials?\b', q):
        return 'client_remaining'
    if 'remaining' in q or 'balance' in q:
        return 'client_remaining'
    if 'loss' in q:
        return 'losses'
    if 'client ledger' in q or ('ledger' in q and ('client' in q or _ams_best_client_match(q))):
        return 'client_ledger'
    if 'material ledger' in q:
        return 'material_ledger'
    if 'grn' in q or 'goods receipt' in q:
        return 'grn'
    if 'overview' in q or 'summary' in q:
        return 'client_overview'
    if 'received' in q or 'inward' in q:
        return 'material_received'
    if 'deliver' in q or 'dispatched' in q or 'how much' in q:
        return 'material_delivered'
    return 'unknown'


def _ams_material_keyword(text):
    q = (text or '').lower()
    for k in ['cement', 'steel', 'rent', 'sand', 'crush']:
        if k in q:
            return k
    return None


def _ams_query_losses(start_date, end_date, material_name=None):
    bq = Booking.query.filter(
        Booking.is_void == False,
        func.date(Booking.date_posted) >= start_date.isoformat(),
        func.date(Booking.date_posted) <= end_date.isoformat()
    )
    sq = DirectSale.query.filter(
        DirectSale.is_void == False,
        func.date(DirectSale.date_posted) >= start_date.isoformat(),
        func.date(DirectSale.date_posted) <= end_date.isoformat()
    )
    pq = Payment.query.filter(
        Payment.is_void == False,
        func.date(Payment.date_posted) >= start_date.isoformat(),
        func.date(Payment.date_posted) <= end_date.isoformat()
    )
    wq = WaiveOff.query.filter(
        WaiveOff.is_void == False,
        func.date(WaiveOff.date_posted) >= start_date.isoformat(),
        func.date(WaiveOff.date_posted) <= end_date.isoformat()
    )

    rows = []
    booking_discount = float(bq.with_entities(func.sum(Booking.discount)).scalar() or 0)
    sale_discount = float(sq.with_entities(func.sum(DirectSale.discount)).scalar() or 0)
    payment_discount = float(pq.with_entities(func.sum(Payment.discount)).scalar() or 0)
    waive_loss = float(wq.with_entities(func.sum(WaiveOff.amount)).scalar() or 0)
    rent_variance_loss = float(sq.with_entities(func.sum(DirectSale.rent_variance_loss)).scalar() or 0)

    rows.append({'component': 'Booking Discount', 'amount': round(booking_discount, 2)})
    rows.append({'component': 'Direct Sale Discount', 'amount': round(sale_discount, 2)})
    rows.append({'component': 'Payment Discount', 'amount': round(payment_discount, 2)})
    rows.append({'component': 'Waive-Off', 'amount': round(waive_loss, 2)})
    rows.append({'component': 'Delivery Rent Variance Loss', 'amount': round(rent_variance_loss, 2)})

    if material_name:
        est_loss = 0.0
        b_items = db.session.query(BookingItem, Booking).join(
            Booking, BookingItem.booking_id == Booking.id
        ).filter(
            Booking.is_void == False,
            func.date(Booking.date_posted) >= start_date.isoformat(),
            func.date(Booking.date_posted) <= end_date.isoformat(),
            BookingItem.material_name.ilike(f'%{material_name}%')
        ).all()
        for item, booking in b_items:
            qty = float(item.qty or 0)
            sale_rate = float(item.price_at_time or 0)
            c_rate, known = _cost_rate_for_material(item.material_name, booking.date_posted.date() if booking.date_posted else None)
            if not known:
                continue
            p = (qty * sale_rate) - (qty * c_rate)
            if p < 0:
                est_loss += abs(p)
        ds_items = db.session.query(DirectSaleItem, DirectSale).join(
            DirectSale, DirectSaleItem.sale_id == DirectSale.id
        ).filter(
            DirectSale.is_void == False,
            func.date(DirectSale.date_posted) >= start_date.isoformat(),
            func.date(DirectSale.date_posted) <= end_date.isoformat(),
            DirectSaleItem.product_name.ilike(f'%{material_name}%')
        ).all()
        for item, sale in ds_items:
            if normalize_sale_category(getattr(sale, 'category', None)) == 'Booking Delivery':
                continue
            qty = float(item.qty or 0)
            sale_rate = float(item.price_at_time or 0)
            c_rate, known = _cost_rate_for_material(item.product_name, sale.date_posted.date() if sale.date_posted else None)
            if not known:
                continue
            p = (qty * sale_rate) - (qty * c_rate)
            if p < 0:
                est_loss += abs(p)
        rows.append({'component': f'Estimated Material Loss ({material_name})', 'amount': round(est_loss, 2)})

    total = round(sum(float(r.get('amount') or 0) for r in rows), 2)
    return {
        'title': 'Loss Summary',
        'summary': f"Total loss from {start_date} to {end_date}: Rs. {total:,.2f}",
        'rows': rows
    }


def _ams_query_material_flow(start_date, end_date, material_name=None, flow_type='OUT'):
    q = Entry.query.filter(
        Entry.is_void == False,
        Entry.type == flow_type,
        Entry.date >= start_date.isoformat(),
        Entry.date <= end_date.isoformat()
    )
    if material_name:
        q = q.filter(Entry.material.ilike(f'%{material_name}%'))
    rows = db.session.query(
        Entry.material,
        func.sum(Entry.qty).label('qty')
    ).filter(
        Entry.id.in_(q.with_entities(Entry.id))
    ).group_by(Entry.material).order_by(func.sum(Entry.qty).desc()).all()
    out = [{'material': r.material, 'qty': round(float(r.qty or 0), 2)} for r in rows if r.material]
    total = round(sum(x['qty'] for x in out), 2)
    action = 'Delivered' if flow_type == 'OUT' else 'Received'
    return {
        'title': f'{action} Material Summary',
        'summary': f"{action} qty from {start_date} to {end_date}: {total:,.2f}",
        'rows': out
    }


def _ams_query_grn(start_date, end_date, material_name=None):
    q = db.session.query(
        GRN.date_posted,
        GRN.supplier,
        GRN.manual_bill_no,
        GRN.auto_bill_no,
        GRNItem.mat_name,
        GRNItem.qty,
        GRNItem.price_at_time
    ).join(GRNItem, GRNItem.grn_id == GRN.id).filter(
        GRN.is_void == False,
        func.date(GRN.date_posted) >= start_date.isoformat(),
        func.date(GRN.date_posted) <= end_date.isoformat()
    )
    if material_name:
        q = q.filter(GRNItem.mat_name.ilike(f'%{material_name}%'))
    rows = []
    total_value = 0.0
    for r in q.order_by(GRN.date_posted.desc()).all():
        line_total = float(r.qty or 0) * float(r.price_at_time or 0)
        total_value += line_total
        rows.append({
            'date': r.date_posted.strftime('%Y-%m-%d') if r.date_posted else '',
            'supplier': r.supplier or '',
            'bill_no': r.manual_bill_no or r.auto_bill_no or '',
            'material': r.mat_name or '',
            'qty': round(float(r.qty or 0), 2),
            'rate': round(float(r.price_at_time or 0), 2),
            'line_total': round(line_total, 2),
        })
    return {
        'title': 'GRN Summary',
        'summary': f"GRN value from {start_date} to {end_date}: Rs. {total_value:,.2f}",
        'rows': rows
    }


def _ams_query_client_ledger(client_obj, start_date, end_date, material_name=None):
    summary = _compute_client_financial_summary(client_obj)
    financial_history, _, _, _, _, _ = _build_client_ledger_rows(client_obj)
    rows = []
    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())
    for row in financial_history:
        dt = row.get('date')
        dt_val = dt if isinstance(dt, datetime) else _parse_dt_safe(dt)
        if dt_val and (dt_val < start_dt or dt_val > end_dt):
            continue
        if material_name:
            desc = str(row.get('description') or '').lower()
            bill_no = str(row.get('bill_no') or '').lower()
            if material_name.lower() not in desc and material_name.lower() not in bill_no:
                continue
        rows.append({
            'date': row.get('date_display') or '',
            'description': row.get('description') or '',
            'bill_no': row.get('bill_no') or '',
            'debit': round(float(row.get('debit') or 0), 2),
            'credit': round(float(row.get('credit') or 0), 2),
            'balance': round(float(row.get('balance') or 0), 2),
        })
    return {
        'title': f'Client Ledger: {client_obj.name}',
        'summary': f"Balance: Rs. {float(summary.get('balance', 0) or 0):,.2f} | Debit: Rs. {float(summary.get('total_debit', 0) or 0):,.2f} | Credit: Rs. {float(summary.get('total_credit', 0) or 0):,.2f}",
        'rows': rows
    }


def _ams_query_material_ledger(start_date, end_date, material_name=None):
    q = Entry.query.filter(
        Entry.is_void == False,
        Entry.date >= start_date.isoformat(),
        Entry.date <= end_date.isoformat()
    )
    if material_name:
        q = q.filter(Entry.material.ilike(f'%{material_name}%'))
    rows = []
    total_in = 0.0
    total_out = 0.0
    for e in q.order_by(Entry.date.desc(), Entry.time.desc()).limit(500).all():
        qty = float(e.qty or 0)
        if (e.type or '').upper() == 'IN':
            total_in += qty
        elif (e.type or '').upper() == 'OUT':
            total_out += qty
        rows.append({
            'date': e.date or '',
            'time': e.time or '',
            'type': e.type or '',
            'material': e.material or '',
            'client': e.client or '',
            'qty': round(qty, 2),
            'bill_no': e.bill_no or e.auto_bill_no or '',
        })
    return {
        'title': 'Material Ledger',
        'summary': f"IN: {total_in:,.2f} | OUT: {total_out:,.2f} | NET: {(total_in-total_out):,.2f}",
        'rows': rows
    }


def _ams_query_client_remaining(client_obj, material_name=None, material_keyword=None):
    def _key(v):
        txt = (v or '').strip().lower()
        return re.sub(r'[^a-z0-9]+', '', txt)

    bookings = Booking.query.filter_by(client_name=client_obj.name, is_void=False).all()
    booking_ids = [b.id for b in bookings]
    booked_totals = {}
    labels = {}
    if booking_ids:
        for item in BookingItem.query.filter(BookingItem.booking_id.in_(booking_ids)).all():
            k = _key(item.material_name)
            if not k:
                continue
            booked_totals[k] = booked_totals.get(k, 0.0) + float(item.qty or 0)
            labels.setdefault(k, (item.material_name or '').strip())

    entries = Entry.query.filter(
        (Entry.client_code == client_obj.code) | (Entry.client == client_obj.name),
        Entry.type == 'OUT',
        Entry.is_void == False,
        not_(and_(Entry.nimbus_no == 'Direct Sale', Entry.client_category != 'Booking Delivery'))
    ).all()
    delivered_totals = {}
    for e in entries:
        k = _key(e.booked_material or e.material)
        if not k:
            continue
        delivered_totals[k] = delivered_totals.get(k, 0.0) + float(e.qty or 0)

    rows = []
    for k, booked in booked_totals.items():
        delivered = float(delivered_totals.get(k, 0.0))
        balance = float(booked - delivered)
        mat_label = labels.get(k, k)
        if material_name and material_name.lower() not in mat_label.lower():
            continue
        if material_keyword and material_keyword.lower() not in mat_label.lower():
            continue
        rows.append({
            'material': mat_label,
            'booked': round(booked, 2),
            'delivered': round(delivered, 2),
            'remaining': round(balance, 2),
        })
    rows.sort(key=lambda x: x.get('remaining', 0), reverse=True)
    total_remaining = round(sum(float(r.get('remaining') or 0) for r in rows), 2)
    filter_label = material_name or material_keyword or 'all materials'
    return {
        'title': f'Remaining Material: {client_obj.name}',
        'summary': f"Total remaining ({filter_label}): {total_remaining:,.2f}",
        'rows': rows
    }


def _ams_query_client_overview(client_obj):
    # Financial outstanding
    pending_total = float(db.session.query(func.sum(PendingBill.amount)).filter(
        PendingBill.client_code == client_obj.code,
        PendingBill.is_void == False,
        PendingBill.is_paid == False
    ).scalar() or 0)

    # Bookings and sales totals
    booking_total = float(db.session.query(func.sum(Booking.amount)).filter(
        func.lower(func.trim(Booking.client_name)) == (client_obj.name or '').strip().lower(),
        Booking.is_void == False
    ).scalar() or 0)
    booking_paid = float(db.session.query(func.sum(Booking.paid_amount)).filter(
        func.lower(func.trim(Booking.client_name)) == (client_obj.name or '').strip().lower(),
        Booking.is_void == False
    ).scalar() or 0)

    sale_total = float(db.session.query(func.sum(DirectSale.amount)).filter(
        func.lower(func.trim(DirectSale.client_name)) == (client_obj.name or '').strip().lower(),
        DirectSale.is_void == False
    ).scalar() or 0)
    sale_paid = float(db.session.query(func.sum(DirectSale.paid_amount)).filter(
        func.lower(func.trim(DirectSale.client_name)) == (client_obj.name or '').strip().lower(),
        DirectSale.is_void == False
    ).scalar() or 0)

    payments_total = float(db.session.query(func.sum(Payment.amount)).filter(
        func.lower(func.trim(Payment.client_name)) == (client_obj.name or '').strip().lower(),
        Payment.is_void == False
    ).scalar() or 0)

    # Reserved material remaining
    rem = _ams_query_client_remaining(client_obj)
    rem_rows = rem.get('rows') or []
    reserved_remaining_total = float(sum(float(r.get('remaining') or 0) for r in rem_rows))

    rows = [
        {'metric': 'Pending Outstanding Amount', 'value': round(pending_total, 2), 'unit': 'PKR'},
        {'metric': 'Booking Total', 'value': round(booking_total, 2), 'unit': 'PKR'},
        {'metric': 'Booking Paid', 'value': round(booking_paid, 2), 'unit': 'PKR'},
        {'metric': 'Booking Remaining', 'value': round(max(0.0, booking_total - booking_paid), 2), 'unit': 'PKR'},
        {'metric': 'Sales Total', 'value': round(sale_total, 2), 'unit': 'PKR'},
        {'metric': 'Sales Paid', 'value': round(sale_paid, 2), 'unit': 'PKR'},
        {'metric': 'Sales Remaining', 'value': round(max(0.0, sale_total - sale_paid), 2), 'unit': 'PKR'},
        {'metric': 'Payments Received', 'value': round(payments_total, 2), 'unit': 'PKR'},
        {'metric': 'Reserved Material Remaining', 'value': round(reserved_remaining_total, 2), 'unit': 'Qty'},
    ]
    # Add top material balances for quick answers.
    for r in rem_rows[:10]:
        rows.append({
            'metric': f"Remaining: {r.get('material')}",
            'value': round(float(r.get('remaining') or 0), 2),
            'unit': 'Qty'
        })

    return {
        'title': f'Client Overview: {client_obj.name}',
        'summary': (
            f"Outstanding: Rs. {pending_total:,.2f} | "
            f"Reserved Remaining Qty: {reserved_remaining_total:,.2f}"
        ),
        'rows': rows
    }


def _ams_get_configured_api_key():
    settings_obj = Settings.query.first()
    if settings_obj and (settings_obj.ams_openai_api_key or '').strip():
        return (settings_obj.ams_openai_api_key or '').strip()
    return (os.environ.get('OPENAI_API_KEY', '') or '').strip()


def _ams_call_openai(api_key, user_query, summary_text, sample_rows):
    if not api_key:
        return ''
    model = (os.environ.get('AMS_ASSISTANT_MODEL') or 'gpt-4o-mini').strip()
    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an accounting assistant for ERP users. "
                    "Treat person-like names in user query as client names when context is accounts/ledger/materials. "
                    "This assistant is strictly read-only: never suggest edits/deletes/voids/updates. "
                    "Respond in concise plain text. Do not fabricate numbers. Use provided data only."
                )
            },
            {
                "role": "user",
                "content": f"Question: {user_query}\nSummary: {summary_text}\nSample rows: {json.dumps(sample_rows[:10], ensure_ascii=True)}"
            }
        ]
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode('utf-8'),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            obj = json.loads(resp.read().decode('utf-8'))
        return (((obj.get('choices') or [{}])[0].get('message') or {}).get('content') or '').strip()
    except Exception:
        return ''


