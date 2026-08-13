"""HTTP routes: api."""
from __future__ import annotations

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, Response, make_response, send_from_directory, abort, session
from flask_login import login_required, login_user, logout_user, current_user
from datetime import datetime, date, timedelta
from sqlalchemy import func, case, text, or_, and_, exists, not_
from types import SimpleNamespace
from decimal import Decimal, ROUND_HALF_UP
import os, io, json, re, logging, calendar

from models import *
from app.services.api import *  # noqa
from utils.audit import audit_log

bp = Blueprint('api', __name__)

@bp.route('/api/ui/theme', methods=['GET', 'POST'])
def ui_theme_preference_api():
    if request.method == 'GET':
        stored = (session.get('ui_theme') or '').strip().lower()
        theme = stored if stored in ('light', 'dark') else None
        return jsonify({'theme': theme})

    payload = request.get_json(silent=True) or {}
    theme = str(payload.get('theme', '')).strip().lower()
    if theme not in ('light', 'dark'):
        return jsonify({'ok': False, 'error': 'Invalid theme'}), 400
    session['ui_theme'] = theme
    return jsonify({'ok': True, 'theme': theme})


@bp.route('/api/client_booking_status/<client_code>')
@login_required
def api_client_booking_status(client_code):
    client = get_client_by_input(client_code)
    if not client:
        return jsonify([])

    # Get bookings by client name (Booking model uses name)
    bookings = Booking.query.filter(
        func.lower(func.trim(Booking.client_name)) == func.lower(func.trim(client.name)),
        Booking.is_void == False
    ).all()
    booking_ids = [b.id for b in bookings]

    def _material_key(v):
        txt = (v or '').strip().lower()
        return re.sub(r'[^a-z0-9]+', '', txt)

    booked_totals = {}
    material_labels = {}
    latest_price = {}
    latest_price_dt = {}
    if booking_ids:
        items = BookingItem.query.filter(BookingItem.booking_id.in_(booking_ids)).all() # BookingItem doesn't have is_void, parent Booking does
        for item in items:
            raw_mat = (item.material_name or '').strip()
            key = _material_key(raw_mat)
            if not key:
                continue
            booked_totals[key] = booked_totals.get(key, 0) + (item.qty or 0)
            if key not in material_labels:
                material_labels[key] = raw_mat
            bk = item.booking
            bk_dt = bk.date_posted if bk and getattr(bk, 'date_posted', None) else None
            if key not in latest_price_dt or (bk_dt and latest_price_dt[key] and bk_dt > latest_price_dt[key]) or (bk_dt and not latest_price_dt[key]):
                latest_price_dt[key] = bk_dt
                latest_price[key] = float(item.price_at_time or 0)
            elif key not in latest_price:
                latest_price[key] = float(item.price_at_time or 0)

    # Get delivered totals from Entry (OUT)
    client_name_norm = (client.name or '').strip().lower()
    entries = Entry.query.filter(
        (Entry.client_code == client.code) | (func.lower(func.trim(Entry.client)) == client_name_norm),
        Entry.type == 'OUT'
    ).filter(
        Entry.is_void == False,
        # Direct Sale credit/cash rows must not consume booking balance.
        not_(and_(Entry.nimbus_no == 'Direct Sale', Entry.client_category != 'Booking Delivery'))
    ).all()

    delivered_totals = {}
    for e in entries:
        key = _material_key(e.booked_material or e.material)
        if not key:
            continue
        delivered_totals[key] = delivered_totals.get(key, 0) + e.qty

    returned_totals = {}
    returns = Entry.query.filter(
        (Entry.client_code == client_code) | (func.lower(func.trim(Entry.client)) == client_name_norm),
        Entry.type == 'IN',
        Entry.is_void == False,
        Entry.nimbus_no == 'Material Return',
        Entry.transaction_category == 'Booked Return'
    ).all()
    for e in returns:
        key = _material_key(e.material)
        if not key:
            continue
        returned_totals[key] = returned_totals.get(key, 0) + e.qty

    status_data = []
    for key, booked_qty in booked_totals.items():
        delivered_qty = delivered_totals.get(key, 0)
        returned_qty = returned_totals.get(key, 0)
        status_data.append({
            'material': material_labels.get(key, key),
            'booked': booked_qty,
            'delivered': delivered_qty,
            'returned': returned_qty,
            'balance': booked_qty - delivered_qty + returned_qty,
            'unit_price': latest_price.get(key, 0)
        })

    return jsonify(status_data)


@bp.route('/api/client_financial_summary/<client_code>')
@login_required
def api_client_financial_summary(client_code):
    client = get_client_by_input(client_code)
    if not client:
        resp = jsonify({'found': False, 'generated_at': pk_now().strftime('%Y-%m-%d %H:%M:%S')})
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
        return resp
    summary = _compute_client_financial_summary(client)
    resp = jsonify({
        'found': True,
        'client_name': client.name,
        'client_code': client.code,
        'generated_at': pk_now().strftime('%Y-%m-%d %H:%M:%S'),
        **summary
    })
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp


@bp.route('/api/last_sold_price')
@login_required
def api_last_sold_price():
    client = request.args.get('client', '').strip()
    material = request.args.get('material', '').strip()
    if not client or not material:
        return jsonify({'found': False, 'price': None})
    item = db.session.query(DirectSaleItem).join(
        DirectSale, DirectSaleItem.sale_id == DirectSale.id
    ).filter(
        DirectSale.is_void == False,
        DirectSale.client_name == client,
        DirectSaleItem.product_name == material,
    ).order_by(DirectSale.date_posted.desc()).first()
    if item:
        sale_date = item.direct_sale.date_posted.strftime('%Y-%m-%d') if item.direct_sale and item.direct_sale.date_posted else ''
        return jsonify({'found': True, 'price': item.price_at_time, 'date': sale_date})
    return jsonify({'found': False, 'price': None})


@bp.route('/api/material_next_code')
@login_required
def api_material_next_code():
    category_id = (request.args.get('category_id') or '').strip()
    material_name = (request.args.get('material_name') or '').strip()
    category = None
    if category_id:
        try:
            category = db.session.get(MaterialCategory, int(category_id))
        except Exception:
            category = None
    if not category:
        category = get_or_create_material_category('General')
    code = _next_material_code_for_category(category, material_name=material_name)
    return jsonify({
        'success': True,
        'code': code,
        'category_id': category.id if category else None,
        'category_name': category.name if category else 'General',
        'is_ft_product': bool((material_name or '').strip().upper().startswith('FT-'))
    })


@bp.route('/api/client_next_code')
@login_required
def api_client_next_code():
    return jsonify({
        'success': True,
        'code': generate_client_code()
    })


@bp.route('/api/notifications/contact_history/<int:bill_id>')
@login_required
def api_notifications_contact_history(bill_id):
    pb = db.session.get(PendingBill, bill_id)
    if not pb:
        return jsonify({'error': 'Pending bill not found'}), 404

    logs = FollowUpContact.query.filter_by(pending_bill_id=pb.id).order_by(
        FollowUpContact.contacted_at.desc(),
        FollowUpContact.id.desc()
    ).all()
    return jsonify([{
        'id': x.id,
        'contacted_at': x.contacted_at.strftime('%Y-%m-%d %H:%M') if x.contacted_at else '',
        'channel': x.channel or '',
        'response': x.response or '',
        'note': x.note or '',
        'created_by': x.created_by or ''
    } for x in logs])


@bp.route('/api/notifications/due')
@login_required
def api_notifications_due():
    now = pk_now()
    due = FollowUpReminder.query.filter(
        FollowUpReminder.is_done == False,
        FollowUpReminder.remind_at <= now,
        FollowUpReminder.alerted_at == None
    ).order_by(FollowUpReminder.remind_at.asc()).all()
    payload = []
    for r in due:
        pb = r.pending_bill
        payload.append({
            'id': r.id,
            'client': pb.client_name if pb else '',
            'bill_no': pb.bill_no if pb else '',
            'amount': float(pb.amount or 0) if pb else 0,
            'note': r.note or '',
            'remind_at': r.remind_at.strftime('%Y-%m-%d %H:%M')
        })
        r.alerted_at = now
    if due:
        db.session.commit()
    return jsonify(payload)


@bp.route('/api/clients/search')
@login_required
def api_clients_search():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    clients = Client.query.filter(
        db.or_(Client.name.ilike(f'%{q}%'), Client.code.ilike(f'%{q}%'))).limit(10).all()
    return jsonify([{'name': c.name, 'code': c.code, 'category': c.category} for c in clients])


@bp.route('/api/check_bill/<path:bill_no>')
@login_required
def check_bill_api(bill_no):
    entry = Entry.query.filter_by(bill_no=bill_no).first()
    if entry:
        return jsonify({
            'exists': True,
            'url': url_for('tracking', search=bill_no),
            'material': entry.material,
            'qty': int(entry.qty)
        })
    return jsonify({'exists': False})


@bp.route('/api/ams_assistant/chat', methods=['POST'])
@login_required
def ams_assistant_chat_api():
    try:
        payload = request.get_json(silent=True) or {}
        user_query = str(payload.get('message') or '').strip()
        if not user_query:
            return jsonify({'ok': False, 'error': 'Query is required.'}), 400

        # Safety guard: AMS Assistant is report/read-only and must never modify app data.
        q_low = user_query.lower()
        write_patterns = [
            r'\b(edit|update|change|modify|delete|remove|void|restore|create|add|insert|post|adjust|merge|rename|wipe)\b',
            r'\b(mark\s+paid|set\s+paid|clear\s+bill|close\s+bill)\b'
        ]
        if any(re.search(p, q_low) for p in write_patterns):
            return jsonify({
                'ok': True,
                'intent': 'read_only_guard',
                'title': 'Read-Only Assistant',
                'answer': 'AMS Assistant is read-only. It can only view/analyze data and export reports, not change records.',
                'summary': '',
                'rows': [],
                'row_count': 0,
                'excel_url': ''
            })

        start_date, end_date = _ams_parse_date_range(user_query)
        material_name = _ams_best_material_match(user_query)
        material_keyword = _ams_material_keyword(user_query)
        client_obj = _ams_best_client_match(user_query)
        intent = _ams_detect_intent(user_query)
        intent, client_obj, material_name, start_date, end_date = _ams_resolve_followup(
            user_query, intent, client_obj, material_name, start_date, end_date
        )
        wants_excel = any(x in user_query.lower() for x in ['excel', 'xlsx', 'sheet', 'download'])

        if intent == 'losses':
            result = _ams_query_losses(start_date, end_date, material_name=material_name)
        elif intent == 'material_received':
            result = _ams_query_material_flow(start_date, end_date, material_name=material_name, flow_type='IN')
        elif intent == 'material_delivered':
            result = _ams_query_material_flow(start_date, end_date, material_name=material_name, flow_type='OUT')
        elif intent == 'grn':
            result = _ams_query_grn(start_date, end_date, material_name=material_name)
        elif intent == 'client_ledger':
            if not client_obj:
                return jsonify({'ok': True, 'answer': 'Please include the client name or code for client ledger queries.'})
            result = _ams_query_client_ledger(client_obj, start_date, end_date, material_name=material_name)
        elif intent == 'client_overview':
            if not client_obj:
                return jsonify({'ok': True, 'answer': 'Please include the client name or code for client overview query.'})
            result = _ams_query_client_overview(client_obj)
        elif intent == 'material_ledger':
            result = _ams_query_material_ledger(start_date, end_date, material_name=material_name)
        elif intent == 'client_remaining':
            if not client_obj:
                return jsonify({'ok': True, 'answer': 'Please include the client name or code for remaining balance query.'})
            result = _ams_query_client_remaining(client_obj, material_name=material_name, material_keyword=material_keyword)
        else:
            # Smart fallback: if a client is recognized, return a full client overview.
            if client_obj:
                result = _ams_query_client_overview(client_obj)
                intent = 'client_overview'
            else:
                return jsonify({
                    'ok': True,
                    'answer': 'I can help with: losses, delivered/received quantity, GRN summary, client ledger, material ledger, client remaining material, and client overview. Include date range and optional material/client.'
                })

        rows = result.get('rows') or []
        summary_text = result.get('summary') or ''
        answer = summary_text
        api_key = _ams_get_configured_api_key()
        ai_answer = _ams_call_openai(api_key, user_query, summary_text, rows)
        if ai_answer:
            answer = ai_answer
        elif rows:
            answer = f"{summary_text}\nRows found: {len(rows)}"

        export_url = ''
        if wants_excel and rows:
            import pandas as pd
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine='openpyxl') as writer:
                pd.DataFrame(rows).to_excel(writer, index=False, sheet_name='Result')
            out.seek(0)
            _ams_cleanup_export_cache()
            token = secrets.token_urlsafe(24)
            AMS_ASSISTANT_EXPORT_CACHE[token] = {
                'user_id': current_user.id,
                'tenant_id': getattr(current_user, 'tenant_id', None),
                'filename': f"ams_assistant_{pk_now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                'content': out.getvalue(),
                'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'expires_at': time.time() + 1800,
            }
            export_url = url_for('ams_assistant_export_api', token=token)

        _ams_set_context_for_user({
            'intent': intent,
            'client_code': (client_obj.code if client_obj else ''),
            'client_name': (client_obj.name if client_obj else ''),
            'material_name': material_name or '',
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
        })

        return jsonify({
            'ok': True,
            'intent': intent,
            'title': result.get('title') or 'Result',
            'date_range': {'start': start_date.isoformat(), 'end': end_date.isoformat()},
            'answer': answer,
            'summary': summary_text,
            'rows': rows[:200],
            'row_count': len(rows),
            'excel_url': export_url,
        })
        
    except Exception as e:
        app.logger.exception("AMS assistant chat failed")
        return jsonify({'ok': False, 'error': f'Assistant failed: {str(e)}'}), 500


@bp.route('/api/ams_assistant/export/<string:token>')
@login_required
def ams_assistant_export_api(token):
    _ams_cleanup_export_cache()
    rec = AMS_ASSISTANT_EXPORT_CACHE.get(token)
    if not rec:
        flash('Export link expired. Please run the assistant query again.', 'warning')
        return redirect(url_for('ams_assistant_page'))
    if rec.get('user_id') != current_user.id:
        flash('Unauthorized export link.', 'danger')
        return redirect(url_for('ams_assistant_page'))
    return send_file(
        io.BytesIO(rec.get('content') or b''),
        as_attachment=True,
        download_name=_download_filename('AMSASSISTANT', _ext_from_name(rec.get('filename'), 'xlsx')),
        mimetype=rec.get('mimetype') or 'application/octet-stream'
    )


@bp.route('/api/supplier_balance/<int:id>')
@login_required
def api_supplier_balance(id):
    supplier = db.session.get(Supplier, id)
    if not supplier:
        return jsonify({'balance': 0})

    ledger_rows, balance, total_bill, total_paid = _build_supplier_ledger_rows(supplier)
    return jsonify({
        'balance': float(balance or 0),
        'opening_balance': float(_to_float_or_zero(getattr(supplier, 'opening_balance', 0))),
        'total_bill': float(total_bill or 0),
        'total_paid': float(total_paid or 0),
        'rows': len(ledger_rows or [])
    })


