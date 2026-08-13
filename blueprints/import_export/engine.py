"""engine — split from import_export.py."""
from ._common import *  # noqa

def _upsert_pending_bill_from_booking(client_name, manual_bill_no, amount, paid_amount, note=''):
    bill_no = str(manual_bill_no or '').strip()
    if not bill_no:
        return

    booking_client_name = str(client_name or '').strip()
    resolved_client = None
    if booking_client_name:
        resolved_client = Client.query.filter_by(name=booking_client_name).first()

    final_client_code = resolved_client.code if resolved_client else ''
    final_client_name = resolved_client.name if resolved_client else booking_client_name

    bill_amount = float(amount or 0)
    paid = float(paid_amount or 0)
    is_paid = paid >= bill_amount and bill_amount > 0

    pb = PendingBill.query.filter_by(bill_no=bill_no).first()
    if pb:
        if final_client_code:
            pb.client_code = final_client_code
        if final_client_name:
            pb.client_name = final_client_name
        pb.amount = bill_amount
        pb.is_paid = is_paid
        pb.is_manual = True
        if note:
            pb.note = note
        if not pb.reason:
            pb.reason = 'Imported Booking'
        return

    new_pb = PendingBill(
        client_code=final_client_code,
        client_name=final_client_name,
        bill_no=bill_no,
        amount=bill_amount,
        reason='Imported Booking',
        is_paid=is_paid,
        created_at=pk_now().strftime('%Y-%m-%d %H:%M'),
        created_by=_actor_username(),
        is_manual=True,
        note=str(note or '').strip()
    )
    db.session.add(new_pb)


_USER_BOOL_COLS = {
    'can_view_stock', 'can_view_daily', 'can_view_history', 'can_import_export',
    'can_manage_directory', 'can_view_dashboard', 'can_manage_grn', 'can_manage_bookings',
    'can_manage_payments', 'can_manage_sales', 'can_view_delivery_rent',
    'can_manage_pending_bills', 'can_view_reports', 'can_manage_notifications',
    'can_view_client_ledger', 'can_view_supplier_ledger', 'can_view_decision_ledger',
    'can_manage_clients', 'can_manage_suppliers', 'can_manage_materials',
    'can_manage_delivery_persons', 'can_access_settings', 'restrict_backdated_edit',
}
_USER_COL_NAMES = {c.name for c in User.__table__.columns}


def _as_bool_cell(val):
    if isinstance(val, bool):
        return val
    s = str(val or '').strip().lower()
    if s in ('1', 'true', 'yes', 'on', 'y'):
        return True
    if s in ('0', 'false', 'no', 'off', 'n', '', 'none', 'nan'):
        return False
    return bool(val)


def _user_payload_from_row(src):
    payload = {}
    for col in _USER_COL_NAMES:
        if col == 'id':
            continue
        if col not in getattr(src, 'index', []) and col not in (src if isinstance(src, dict) else {}):
            # pandas Series
            try:
                if col not in src:
                    continue
            except Exception:
                continue
        try:
            raw = src.get(col) if hasattr(src, 'get') else src[col]
        except Exception:
            continue
        if raw is None or (isinstance(raw, float) and pd is not None and pd.isna(raw)):
            continue
        if str(raw).strip() == '' or str(raw).strip().lower() == 'nan':
            continue
        if col in _USER_BOOL_COLS:
            payload[col] = _as_bool_cell(raw)
        elif col == 'role':
            role = str(raw).strip().lower()
            payload[col] = 'admin' if role in ('admin', 'administrator') else ('user' if role else 'user')
        elif col == 'status':
            st = str(raw).strip().lower()
            payload[col] = 'inactive' if st in ('inactive', 'disabled', '0', 'false') else 'active'
        else:
            payload[col] = raw
    return payload


def _find_user_sheet(xls):
    names = list(xls.sheet_names or [])
    for want in ('user', 'users', 'User', 'Users'):
        if want in names:
            return want
    for n in names:
        if str(n).strip().lower() in ('user', 'users'):
            return n
    return None


def _restore_users_from_excel(xls):
    """Always restore managers/roles from backup. Never delete existing users."""
    sheet = _find_user_sheet(xls)
    result = {'name': 'user', 'status': 'skipped', 'inserted': 0, 'updated': 0, 'failed': 0, 'error': '', 'people': []}
    if not sheet:
        result['error'] = 'No user/Users sheet in this file (older backup). Users on this PC were kept.'
        return result
    try:
        df = pd.read_excel(xls, sheet).fillna('')
        df.columns = [str(c).strip() for c in df.columns]
    except Exception as exc:
        result['status'] = 'failed'
        result['error'] = str(exc)
        return result
    me = (getattr(current_user, 'username', None) or '').strip().lower()
    for _, src in df.iterrows():
        payload = _user_payload_from_row(src)
        username = str(payload.get('username') or '').strip()
        if not username:
            continue
        if username.lower() == 'root':
            continue
        try:
            existing = User.query.filter(func.lower(func.trim(User.username)) == username.lower()).first()
            if existing and existing.username.lower() == me:
                # Keep the person running restore logged in; still apply role/permissions.
                for key in list(payload.keys()):
                    if key in ('password_hash', 'password_plain', 'status'):
                        payload.pop(key, None)
            if existing:
                for key, val in payload.items():
                    if key in _USER_COL_NAMES and key != 'id':
                        setattr(existing, key, val)
                result['updated'] += 1
                result['people'].append({'username': username, 'role': payload.get('role') or existing.role, 'action': 'updated'})
            else:
                clean = {k: v for k, v in payload.items() if k in _USER_COL_NAMES and k != 'id'}
                if 'username' not in clean:
                    continue
                db.session.add(User(**clean))
                result['inserted'] += 1
                result['people'].append({'username': username, 'role': clean.get('role') or 'user', 'action': 'created'})
        except Exception as exc:
            result['failed'] += 1
            result['people'].append({'username': username, 'role': payload.get('role') or '', 'action': 'failed', 'error': str(exc)[:200]})
    if result['failed'] and not (result['inserted'] or result['updated']):
        result['status'] = 'failed'
    elif result['failed']:
        result['status'] = 'partial'
    else:
        result['status'] = 'ok'
    return result


def _run_full_raw_import_bytes(file_bytes, scope_ctx, mode, source_file_name):
    try:
        xls = pd.ExcelFile(io.BytesIO(file_bytes))
    except Exception as e:
        raise ValueError(f'Invalid Excel file: {e}')

    scoped_tables = _full_raw_tables_for_scope(scope_ctx)
    selected_tables = []
    for t in scoped_tables:
        if t.name[:31] in xls.sheet_names:
            selected_tables.append(t)

    if not selected_tables:
        raise ValueError('No importable sheets found for current scope.')

    report = {'inserted': 0, 'skipped': 0, 'tables': len(selected_tables), 'table_results': [], 'users': []}
    report_name = None
    skipped_rows = []
    target_tenant_id = scope_ctx.get('target_tenant_id')
    user_restore = _restore_users_from_excel(xls)
    report['users'] = user_restore.get('people') or []
    report['table_results'].append({
        'name': 'user (roles/managers)',
        'status': user_restore.get('status'),
        'inserted': user_restore.get('inserted') or 0,
        'updated': user_restore.get('updated') or 0,
        'skipped': 0,
        'failed': user_restore.get('failed') or 0,
        'error': user_restore.get('error') or '',
    })
    report['inserted'] += (user_restore.get('inserted') or 0) + (user_restore.get('updated') or 0)

    if mode == 'replace_tenant_data':
        # Replace mode must fully reset tenant-scoped dataset for the target tenant,
        # even if some tables are missing in the incoming workbook.
        replace_targets = list(reversed(_full_raw_tables_for_scope(scope_ctx)))
        for t in replace_targets:
            if scope_ctx.get('scope') != 'tenant' or 'tenant_id' not in t.c:
                continue
            if t.name in WIPE_PROTECTED_TABLES:
                continue
            if scope_ctx.get('scope') != 'tenant' or 'tenant_id' not in t.c:
                continue
            db.session.execute(t.delete().where(t.c.tenant_id == target_tenant_id))

    for t in selected_tables:
        if t.name == 'user':
            continue
        table_stat = {'name': t.name, 'status': 'ok', 'inserted': 0, 'updated': 0, 'skipped': 0, 'failed': 0, 'error': ''}
        try:
            df = pd.read_excel(xls, t.name[:31]).fillna('')
        except Exception as exc:
            table_stat['status'] = 'failed'
            table_stat['error'] = str(exc)[:300]
            report['table_results'].append(table_stat)
            continue
        pk_cols = [c for c in t.primary_key.columns]
        pk_names = {c.name for c in pk_cols}
        for _, src in df.iterrows():
            payload = {}
            for col in t.columns:
                name = col.name
                if name not in df.columns:
                    continue
                val = _normalize_excel_cell(src.get(name), col)
                if val == '':
                    val = None
                if name == 'tenant_id' and scope_ctx.get('scope') == 'tenant':
                    val = target_tenant_id
                if col.primary_key and val in [None, '']:
                    continue
                payload[name] = val
            if not payload:
                report['skipped'] += 1
                table_stat['skipped'] += 1
                skipped_rows.append({
                    'table': t.name,
                    'reason': 'empty_payload',
                    'pk': '',
                    'label': '',
                    'row_json': '',
                })
                continue
            if t.name == 'user':
                username_value = str(payload.get('username') or '').strip()
                if not username_value:
                    report['skipped'] += 1
                    skipped_rows.append({
                        'table': t.name,
                        'reason': 'missing_username',
                        'pk': '',
                        'label': '',
                        'row_json': json.dumps(_serialize_payload(payload), ensure_ascii=True),
                    })
                    continue
                if username_value.lower() == 'root':
                    report['skipped'] += 1
                    skipped_rows.append({
                        'table': t.name,
                        'reason': 'blocked_root_username',
                        'pk': '',
                        'label': username_value,
                        'row_json': json.dumps(_serialize_payload(payload), ensure_ascii=True),
                    })
                    continue
                me = (getattr(current_user, 'username', None) or '').strip()
                if me and username_value.lower() == me.lower():
                    payload.pop('password_hash', None)
                    payload.pop('status', None)
                payload.pop('id', None)
                existing_user = User.query.filter(
                    func.lower(func.trim(User.username)) == username_value.lower()
                ).first()
                if existing_user:
                    for key, val in payload.items():
                        if hasattr(existing_user, key) and key not in ('id',):
                            setattr(existing_user, key, val)
                    report['inserted'] += 1
                    continue
                db.session.add(User(**{k: v for k, v in payload.items() if hasattr(User, k)}))
                report['inserted'] += 1
                continue
            if pk_cols:
                pk_values = []
                missing_pk = False
                for c in pk_cols:
                    if c.name not in payload or payload[c.name] in [None, '']:
                        missing_pk = True
                        break
                    pk_values.append(payload[c.name])
                if not missing_pk:
                    pk_cond = and_(*[c == v for c, v in zip(pk_cols, pk_values)])
                    existing = db.session.execute(select(t).where(pk_cond).limit(1)).first()
                    if existing:
                        report['skipped'] += 1
                        table_stat['skipped'] += 1
                        label = _build_report_label(payload, pk_names)
                        row_json = json.dumps(_serialize_payload(payload), ensure_ascii=True)
                        skipped_rows.append({
                            'table': t.name,
                            'reason': 'duplicate_pk',
                            'pk': ','.join([str(v) for v in pk_values]),
                            'label': label,
                            'row_json': row_json,
                        })
                        continue
            db.session.execute(t.insert().values(**payload))
            report['inserted'] += 1
            table_stat['inserted'] += 1
        if table_stat['failed']:
            table_stat['status'] = 'partial' if table_stat['inserted'] else 'failed'
        report['table_results'].append(table_stat)

    db.session.commit()
    report_name = f"full_raw_import_report_{pk_now().strftime('%Y%m%d_%H%M%S')}"
    if True:
        report_name = report_name
        report_meta = {
            'name': report_name,
            'created_at': pk_now().strftime('%Y-%m-%d %H:%M:%S'),
            'mode': mode,
            'scope': scope_ctx.get('scope'),
            'inserted': report['inserted'],
            'skipped': report['skipped'],
            'tables': report['tables'],
            'source_file': source_file_name,
            'skipped_rows_count': len(skipped_rows),
        }
        session['full_raw_import_report'] = report_name
        session['full_raw_import_report_meta'] = report_meta
    return report, report_name


def _run_master_import_bytes(file_bytes, actor_username=None, progress_cb=None):
    ok, msg = backup_database()
    if not ok:
        raise RuntimeError(f"Backup failed: {msg}")

    xls = pd.ExcelFile(io.BytesIO(file_bytes))
    report = {'imported': 0, 'updated': 0, 'skipped': 0, 'errors': 0, 'table_results': [], 'users': []}
    user_restore = _restore_users_from_excel(xls)
    report['users'] = user_restore.get('people') or []
    report['table_results'].append({
        'name': 'user (roles/managers)',
        'status': user_restore.get('status'),
        'inserted': user_restore.get('inserted') or 0,
        'updated': user_restore.get('updated') or 0,
        'skipped': 0,
        'failed': user_restore.get('failed') or 0,
        'error': user_restore.get('error') or '',
    })
    report['imported'] += user_restore.get('inserted') or 0
    report['updated'] += user_restore.get('updated') or 0
    if user_restore.get('failed'):
        report['errors'] += user_restore.get('failed') or 0
    steps = [
        'Clients', 'MaterialCategories', 'Materials', 'PendingBills',
        'Dispatch', 'Bookings', 'BookingItems', 'Payments', 'FBMCashDrawer',
        'FBMCashDrawerCategories', 'Sales', 'SaleItems', 'GRN', 'GRNItems',
        'DeliveryPersons', 'DeliveryRents'
    ]
    total = len(steps)

    def _read_sheet(name):
        d = pd.read_excel(xls, name)
        d.columns = [c.lower().strip().replace(' ', '_') for c in d.columns]
        return d.fillna('')

    for idx, sheet_name in enumerate(steps, start=1):
        pct = 8 + int(((idx - 1) / total) * 84)
        exists = sheet_name in xls.sheet_names
        if progress_cb:
            msg = f"Processing sheet {idx}/{total}: {sheet_name}" if exists else f"Skipping missing sheet {idx}/{total}: {sheet_name}"
            progress_cb(pct, msg)
        if not exists:
            continue

        if sheet_name == 'Clients':
            _process_clients(_read_sheet('Clients'), 'update', report)
        elif sheet_name == 'MaterialCategories':
            _process_material_categories(_read_sheet('MaterialCategories'), report)
        elif sheet_name == 'Materials':
            _process_materials(_read_sheet('Materials'), report)
        elif sheet_name == 'PendingBills':
            _process_pending_bills(_read_sheet('PendingBills'), 'update', 'create', report)
        elif sheet_name == 'Dispatch':
            df = _read_sheet('Dispatch')
            df.rename(columns={'cement_brand': 'item', 'client_name': 'customer', 'bill_date': 'date', 'nimbus': 'nimbus_no'}, inplace=True)
            _process_dispatch(df, 'skip', 'create', report)
        elif sheet_name == 'Bookings':
            _process_bookings(_read_sheet('Bookings'), 'update', report)
        elif sheet_name == 'BookingItems':
            _process_booking_items(_read_sheet('BookingItems'), 'update', report)
        elif sheet_name == 'Payments':
            _process_payments(_read_sheet('Payments'), 'update', report)
        elif sheet_name == 'FBMCashDrawer':
            df = _read_sheet('FBMCashDrawer')
            for _, row in df.iterrows():
                try:
                    amount = float(row.get('amount', 0) or 0)
                except Exception:
                    amount = 0
                entry_type = str(row.get('entry_type', 'out')).strip().lower()
                if entry_type not in ['in', 'out']:
                    entry_type = 'out'
                method = str(row.get('method', 'Cash')).strip() or 'Cash'
                category = str(row.get('category', '')).strip()
                note = str(row.get('note', '')).strip()
                source = str(row.get('source', 'manual')).strip() or 'manual'
                created_by = str(row.get('created_by', '')).strip() or (actor_username or _actor_username())
                is_void = str(row.get('is_void', '')).strip().lower() in ['true', '1', 'yes', 'on']
                posted_raw = row.get('date_posted')
                posted_at = posted_raw if isinstance(posted_raw, datetime) else None
                if posted_at is None:
                    try:
                        posted_at = datetime.fromisoformat(str(posted_raw).strip())
                    except Exception:
                        posted_at = pk_now()

                existing = None
                raw_id = str(row.get('id', '')).strip()
                if raw_id:
                    try:
                        existing = db.session.get(FbmCashDrawerEntry, int(float(raw_id)))
                    except Exception:
                        existing = None

                if existing:
                    existing.entry_type = entry_type
                    existing.amount = amount
                    existing.category = category
                    existing.method = method
                    existing.note = note
                    existing.source = source
                    existing.date_posted = posted_at
                    existing.created_by = created_by
                    existing.is_void = is_void
                    report['updated'] += 1
                else:
                    db.session.add(FbmCashDrawerEntry(
                        entry_type=entry_type,
                        amount=amount,
                        category=category,
                        method=method,
                        note=note,
                        source=source,
                        date_posted=posted_at,
                        created_by=created_by,
                        is_void=is_void,
                    ))
                    report['imported'] += 1
        elif sheet_name == 'FBMCashDrawerCategories':
            df = _read_sheet('FBMCashDrawerCategories')
            for _, row in df.iterrows():
                name = str(row.get('name', '')).strip()
                if not name:
                    report['skipped'] += 1
                    continue
                is_active_raw = str(row.get('is_active', '')).strip().lower()
                is_active = is_active_raw not in ['false', '0', 'no', 'off']
                existing = FbmCashDrawerCategory.query.filter(
                    func.lower(func.trim(FbmCashDrawerCategory.name)) == name.lower()
                ).first()
                if existing:
                    existing.is_active = is_active
                    report['updated'] += 1
                else:
                    db.session.add(FbmCashDrawerCategory(name=name, is_active=is_active))
                    report['imported'] += 1
        elif sheet_name == 'Sales':
            _process_sales(_read_sheet('Sales'), 'update', report)
        elif sheet_name == 'SaleItems':
            _process_sale_items(_read_sheet('SaleItems'), 'update', report)
        elif sheet_name == 'GRN':
            _process_grn(_read_sheet('GRN'), 'update', report)
        elif sheet_name == 'GRNItems':
            _process_grn_items(_read_sheet('GRNItems'), 'update', report)
        elif sheet_name == 'DeliveryPersons':
            df = _read_sheet('DeliveryPersons')
            for _, row in df.iterrows():
                name = str(row.get('name', '')).strip()
                if not name:
                    continue
                phone = str(row.get('phone', '')).strip()
                existing = DeliveryPerson.query.filter(
                    func.lower(func.trim(DeliveryPerson.name)) == name.lower()
                ).first()
                is_active_raw = str(row.get('is_active', '')).strip().lower()
                is_active = is_active_raw not in ['false', '0', 'no', 'off']
                if existing:
                    existing.is_active = is_active
                    if phone:
                        existing.phone = phone
                    report['updated'] += 1
                else:
                    db.session.add(DeliveryPerson(name=name, phone=phone or None, is_active=is_active))
                    report['imported'] += 1
        elif sheet_name == 'DeliveryRents':
            df = _read_sheet('DeliveryRents')
            for _, row in df.iterrows():
                driver_name = str(row.get('delivery_person_name', '')).strip()
                bill_no = str(row.get('bill_no', '')).strip()
                if not driver_name:
                    report['skipped'] += 1
                    continue
                try:
                    amount = float(row.get('amount', 0) or 0)
                except Exception:
                    amount = 0

                sale_id = None
                raw_sale_id = str(row.get('sale_id', '')).strip()
                if raw_sale_id:
                    try:
                        sale_id = int(float(raw_sale_id))
                    except Exception:
                        sale_id = None

                if not sale_id and bill_no:
                    sale = DirectSale.query.filter(
                        or_(DirectSale.manual_bill_no == bill_no, DirectSale.auto_bill_no == bill_no)
                    ).first()
                    if sale:
                        sale_id = sale.id

                existing = None
                if sale_id:
                    existing = DeliveryRent.query.filter_by(sale_id=sale_id).first()
                if not existing and bill_no:
                    existing = DeliveryRent.query.filter(
                        DeliveryRent.bill_no == bill_no,
                        func.lower(func.trim(DeliveryRent.delivery_person_name)) == driver_name.lower()
                    ).first()

                is_void_raw = str(row.get('is_void', '')).strip().lower()
                is_void = is_void_raw in ['true', '1', 'yes', 'on']
                note = str(row.get('note', '')).strip()
                created_by = str(row.get('created_by', '')).strip() or (actor_username or _actor_username())

                if existing:
                    existing.delivery_person_name = driver_name
                    existing.bill_no = bill_no
                    existing.amount = amount
                    existing.note = note
                    existing.created_by = created_by
                    existing.is_void = is_void
                    report['updated'] += 1
                else:
                    db.session.add(DeliveryRent(
                        sale_id=sale_id,
                        delivery_person_name=driver_name,
                        bill_no=bill_no,
                        amount=amount,
                        note=note,
                        created_by=created_by,
                        is_void=is_void
                    ))
                    report['imported'] += 1

    if progress_cb:
        progress_cb(97, 'Finalizing import...')
    db.session.commit()
    return report


