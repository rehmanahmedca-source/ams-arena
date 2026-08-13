"""payments — split from sales.py."""
from ._common import *  # noqa

@bp.route('/payments')
@login_required
def payments_page():
    payments_readonly = True
    party = (request.args.get('party', 'customer') or 'customer').strip().lower()
    if party not in ['customer', 'supplier', 'all']:
        party = 'customer'
    show_mode = (request.args.get('show', 'active') or 'active').strip().lower()
    date_from = (request.args.get('date_from') or '').strip()
    date_to = (request.args.get('date_to') or '').strip()
    client_filter = (request.args.get('client') or '').strip()
    method_filter = (request.args.get('method') or '').strip()
    amount_min_raw = (request.args.get('amount_min') or '').strip()
    amount_max_raw = (request.args.get('amount_max') or '').strip()

    def _parse_amount(val):
        if val in (None, ''):
            return None
        try:
            return float(val)
        except Exception:
            return None

    amount_min = _parse_amount(amount_min_raw)
    amount_max = _parse_amount(amount_max_raw)
    page_customer = request.args.get('page_customer', 1, type=int)
    page_supplier = request.args.get('page_supplier', 1, type=int)
    per_page_customer = request.args.get('per_page_customer', 10, type=int)
    per_page_supplier = request.args.get('per_page_supplier', 10, type=int)
    per_page_customer = min(max(per_page_customer, 10), 50)
    per_page_supplier = min(max(per_page_supplier, 10), 50)
    payments = []
    supplier_payments = []
    customer_pagination = None
    supplier_pagination = None

    if party in ['customer', 'all']:
        payments_q = Payment.query
        if show_mode == 'voided':
            payments_q = payments_q.filter(Payment.is_void == True)
        elif show_mode == 'all':
            payments_q = payments_q
        else:
            show_mode = 'active'
            payments_q = payments_q.filter(Payment.is_void == False)
        if client_filter:
            resolved_client = get_client_by_input(client_filter)
            if resolved_client:
                payments_q = payments_q.filter(
                    func.lower(func.trim(Payment.client_name)) == resolved_client.name.strip().lower()
                )
            else:
                payments_q = payments_q.filter(Payment.client_name.ilike(f"%{client_filter}%"))
        if method_filter:
            payments_q = payments_q.filter(Payment.method == method_filter)
        if date_from:
            payments_q = payments_q.filter(func.date(Payment.date_posted) >= date_from)
        if date_to:
            payments_q = payments_q.filter(func.date(Payment.date_posted) <= date_to)
        if amount_min is not None:
            payments_q = payments_q.filter(Payment.amount >= amount_min)
        if amount_max is not None:
            payments_q = payments_q.filter(Payment.amount <= amount_max)
        customer_pagination = payments_q.order_by(Payment.date_posted.desc()).paginate(
            page=page_customer, per_page=per_page_customer, error_out=False
        )
        payments = customer_pagination.items

    if party in ['supplier', 'all']:
        supplier_q = SupplierPayment.query
        if show_mode == 'voided':
            supplier_q = supplier_q.filter(SupplierPayment.is_void == True)
        elif show_mode == 'all':
            supplier_q = supplier_q
        else:
            show_mode = 'active'
            supplier_q = supplier_q.filter(SupplierPayment.is_void == False)
        supplier_pagination = supplier_q.order_by(SupplierPayment.date_posted.desc()).paginate(
            page=page_supplier, per_page=per_page_supplier, error_out=False
        )
        supplier_payments = supplier_pagination.items

    clients = Client.query.filter_by(is_active=True).order_by(Client.name.asc()).all()
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name.asc()).all()
    accounts = Account.query.filter(func.coalesce(Account.is_active, True) == True).order_by(Account.name.asc()).all()
    next_auto = peek_next_bill_no(AUTO_BILL_NAMESPACES['PAYMENT'])
    return render_template('payments.html',
                           payments=payments,
                           supplier_payments=supplier_payments,
                           clients=clients,
                           suppliers=suppliers,
                           accounts=accounts,
                           next_auto=next_auto,
                           payments_readonly=payments_readonly,
                           show_mode=show_mode,
                           party=party,
                           today_date=pk_today().strftime('%Y-%m-%d'),
                           date_from=date_from,
                           date_to=date_to,
                           client_filter=client_filter,
                           method_filter=method_filter,
                           amount_min=amount_min_raw,
                           amount_max=amount_max_raw,
                           customer_pagination=customer_pagination,
                           supplier_pagination=supplier_pagination,
                           page_customer=page_customer,
                           page_supplier=page_supplier,
                           per_page_customer=per_page_customer,
                           per_page_supplier=per_page_supplier)


@bp.route('/add_payment', methods=['POST'])
@login_required
def add_payment():
    if not _user_can('can_manage_payments'):
        flash('Permission denied', 'danger')
        return redirect(url_for('accounts.dashboard'))

    def _as_bool(val):
        return str(val).strip().lower() in ['1', 'true', 'on', 'yes']

    # Form submits `client_code` (search input), keep legacy fallback for `client_name`.
    client_input = (request.form.get('client_code') or request.form.get('client_name') or '').strip()
    client_name = client_input
    amount = float(request.form.get('amount', 0) or 0)
    if _user_can('can_manage_payments'):
        try:
            discount, discount_reason = _parse_discount_fields(
                request.form.get('discount', 0),
                request.form.get('discount_reason', ''),
                label='Payment discount',
                require_reason=True
            )
        except ValueError as ve:
            flash(str(ve), 'danger')
            return redirect(url_for('payments_page'))
        settle_leftover_with_discount = _as_bool(request.form.get('settle_leftover_with_discount'))
    else:
        discount = 0
        discount_reason = ''
        settle_leftover_with_discount = False
    method = request.form.get('method', 'Cash')
    payment_account_id = request.form.get('payment_account_id')
    expected_category = _payment_expected_account_category(method)
    if payment_account_id:
        try:
            payment_account_id = int(payment_account_id)
            account = Account.query.get(payment_account_id)
            if account:
                if expected_category and (account.category or '').strip().lower() != expected_category:
                    raise ValueError(f"Selected account must be a {expected_category} account for method '{method}'.")
                bank_name = account.bank_name or ''
                account_name = account.account_holder_name or account.name
                account_no = account.account_number or ''
            else:
                payment_account_id = None
        except (ValueError, TypeError) as ve:
            flash(str(ve), 'danger')
            return redirect(url_for('payments_page'))
    else:
        bank_name = request.form.get('bank_name', '').strip()
        account_name = request.form.get('account_name', '').strip()
        account_no = request.form.get('account_no', '').strip()
    
    if expected_category != 'bank':
        bank_name = ''
        if expected_category == 'cash':
            # Keep account_name/account_no for cash account context when provided manually.
            pass
        else:
            account_name = ''
            account_no = ''

    if expected_category in ['cash', 'bank'] and not payment_account_id:
        flash('Select an account (cash/bank) to post this payment into Accounts.', 'danger')
        return redirect(url_for('payments_page'))
    manual_bill_raw = request.form.get('manual_bill_no', '').strip()
    manual_bill_no = normalize_manual_bill(manual_bill_raw) if manual_bill_raw else ''
    note = request.form.get('note', '').strip()
    date_str = (request.form.get('date') or '').strip()
    photo_path = save_photo(request.files.get('photo'))
    photo_url = request.form.get('photo_url', '').strip()
    payment_posted_at = resolve_posted_datetime(date_str)
    auto_bill_no = get_next_bill_no(AUTO_BILL_NAMESPACES['PAYMENT'])

    # Find client by name or code
    client = get_client_by_input(client_input)

    auto_discount_applied = 0.0
    if client:
        client_name = client.name

    if manual_bill_no:
        conflict = find_bill_conflict(manual_bill_no)
        if conflict:
            flash(f"Manual bill '{manual_bill_no}' already exists in {conflict[0]} #{conflict[1]}.", 'danger')
            return redirect(url_for('payments_page'))

    payment = Payment(client_name=client_name,
                      amount=amount,
                      discount=discount,
                      discount_reason=discount_reason,
                      bank_name=bank_name,
                      account_name=account_name,
                      account_no=account_no,
                      method=method,
                      payment_account_id=payment_account_id,
                      manual_bill_no=manual_bill_no,
                      auto_bill_no=auto_bill_no,
                      photo_path=photo_path,
                      photo_url=photo_url,
                      date_posted=payment_posted_at,
                      note=note)
    db.session.add(payment)
    db.session.flush()

    # Apply payment to matching pending bills when possible
    remaining = float(amount) + float(discount)
    applied = []
    bill_candidates = []
    if manual_bill_no:
        bill_candidates = _bill_no_variants(manual_bill_no)

    def _is_open_khata_bill(pb):
        return pb and (pb.client_code == OPEN_KHATA_CODE or (pb.client_name or '').strip().upper() == OPEN_KHATA_NAME)

    if client:
        # Prefer matching by manual_bill_no when provided
        if manual_bill_no:
            filters = []
            for candidate in bill_candidates:
                filters.append(PendingBill.bill_no.ilike(candidate))
                filters.append(PendingBill.nimbus_no.ilike(candidate))

            pending_q = PendingBill.query.filter(
                PendingBill.client_code == client.code,
                PendingBill.is_paid == False,
                or_(*filters)
            ).order_by(PendingBill.id.asc()).all()

            # Fallback for imported data where pending bill has missing/misaligned client code.
            if not pending_q:
                fallback_q = PendingBill.query.filter(
                    PendingBill.is_paid == False,
                    or_(*filters)
                ).order_by(PendingBill.id.asc()).all()
                compatible = [
                    pb for pb in fallback_q
                    if (
                        (not (pb.client_code or '').strip()) or
                        (pb.client_code == client.code) or
                        ((pb.client_name or '').strip().lower() == client.name.strip().lower())
                    )
                ]
                # Only auto-attach on an unambiguous single match.
                if len(compatible) == 1:
                    pb = compatible[0]
                    pb.client_code = client.code
                    if not (pb.client_name or '').strip():
                        pb.client_name = client.name
                    pending_q = [pb]
        else:
            # Otherwise apply to oldest unpaid bills for this client
            pending_q = PendingBill.query.filter_by(client_code=client.code, is_paid=False).order_by(PendingBill.id.asc()).all()

        for pb in pending_q:
            if remaining <= 0:
                break
            if pb.is_paid:
                continue
            if remaining >= (pb.amount or 0):
                remaining -= (pb.amount or 0)
                applied.append((pb.bill_no, f'paid Rs.{pb.amount}'))
                pb.amount = 0
                pb.is_paid = True
                if _is_open_khata_bill(pb):
                    pb.is_cash = True
            else:
                applied.append((pb.bill_no, f'partial Rs.{remaining:.2f}'))
                pb.amount = (pb.amount or 0) - remaining
                remaining = 0

        if settle_leftover_with_discount and manual_bill_no:
            for pb in pending_q:
                if pb.is_paid:
                    continue
                outstanding = float(pb.amount or 0)
                if outstanding <= 0:
                    continue
                pb.amount = 0
                pb.is_paid = True
                auto_discount_applied += outstanding
                applied.append((pb.bill_no, f'waived off (loss) Rs.{outstanding:.2f}'))
                if _is_open_khata_bill(pb):
                    pb.is_cash = True
                break
    elif manual_bill_no:
        # Open Khata / unknown-client fallback: apply by bill number even without client match.
        filters = []
        for candidate in bill_candidates:
            filters.append(PendingBill.bill_no.ilike(candidate))
            filters.append(PendingBill.nimbus_no.ilike(candidate))

        pending_q = PendingBill.query.filter(
            PendingBill.is_paid == False,
            or_(*filters)
        ).order_by(PendingBill.id.asc()).all()

        for pb in pending_q:
            if remaining <= 0:
                break
            if pb.is_paid:
                continue
            if remaining >= (pb.amount or 0):
                remaining -= (pb.amount or 0)
                applied.append((pb.bill_no, f'paid Rs.{pb.amount}'))
                pb.amount = 0
                pb.is_paid = True
                if _is_open_khata_bill(pb):
                    pb.is_cash = True
            else:
                applied.append((pb.bill_no, f'partial Rs.{remaining:.2f}'))
                pb.amount = (pb.amount or 0) - remaining
                remaining = 0

    # If manual_bill_no is provided but didn't match an existing bill,
    # create a Receipt record in PendingBill so it appears in the list.
    created_receipt = False
    if manual_bill_no and client:
        existing_target_filters = [PendingBill.bill_no.ilike(x) for x in bill_candidates]
        existing_target = PendingBill.query.filter(
            PendingBill.client_code == client.code,
            or_(*existing_target_filters)
        ).first()
        if not existing_target:
            # Fallback: attach imported pending bill with same bill no if client code was blank/misaligned.
            global_target = PendingBill.query.filter(or_(*existing_target_filters)).order_by(PendingBill.id.desc()).first()
            if global_target and (
                (not (global_target.client_code or '').strip()) or
                (global_target.client_code == client.code) or
                ((global_target.client_name or '').strip().lower() == client.name.strip().lower())
            ):
                global_target.client_code = client.code
                if not (global_target.client_name or '').strip():
                    global_target.client_name = client.name
                existing_target = global_target
        if not existing_target:
            receipt_pb = PendingBill(
                client_code=client.code,
                client_name=client.name,
                bill_no=manual_bill_no,
                amount=0, # Zero balance for receipts
                reason=f"Payment Received ({method})",
                is_paid=True,
                is_manual=True,
                bill_kind='MB',
                created_at=pk_now().strftime('%Y-%m-%d %H:%M'),
                created_by=current_user.username,
                note=note
            )
            db.session.add(receipt_pb)
            created_receipt = True

    if auto_discount_applied > 0:
        payment.discount = float(payment.discount or 0) + auto_discount_applied
        auto_reason = f'Auto waive-off (loss) settlement for bill {manual_bill_no}'
        if payment.discount_reason:
            if auto_reason not in payment.discount_reason:
                payment.discount_reason = f"{payment.discount_reason}; {auto_reason}"
        else:
            payment.discount_reason = auto_reason

    _sync_payment_waive_off(payment)
    _sync_payment_accounting(payment)
    db.session.commit()

    msg = 'Payment received successfully'
    if applied:
        details = ', '.join([f"{b}: {s}" for b, s in applied])
        msg += f" - applied to: {details}"
    if created_receipt:
        msg += f" - Receipt #{manual_bill_no} recorded"
    if auto_discount_applied > 0:
        msg += f" - leftover waived off as loss Rs.{auto_discount_applied:.2f}"
    elif remaining > 0 and amount > 0:
        msg += f" - Rs.{remaining:.2f} unapplied (advance)"

    if manual_bill_no and not applied and not created_receipt and amount > 0:
        # Diagnostic check
        reason = "check number or client"
        filters_global = []
        for candidate in bill_candidates:
            filters_global.append(PendingBill.bill_no.ilike(candidate))
            filters_global.append(PendingBill.nimbus_no.ilike(candidate))
        global_match = PendingBill.query.filter(or_(*filters_global)).first()
        if global_match:
            if not client:
                 reason = f"Bill belongs to {global_match.client_name} (Client not identified)"
            elif global_match.client_code != client.code:
                reason = f"Bill belongs to {global_match.client_name}"
            elif global_match.is_paid:
                reason = "Bill is already paid"
        else:
            reason = "Bill number not found"
        flash(msg + f" (Warning: Could not link to Bill '{manual_bill_no}' - {reason})", 'warning')
    else:
        flash(msg, 'success')

    bill_ref = manual_bill_no or payment.auto_bill_no or f"PAY-{payment.id}"
    return redirect(url_for(
        'payments_page',
        download_bill=bill_ref,
        download_src='payment',
        download_src_id=payment.id,
        download_client_code=(client.code if client else None),
        download_client_name=payment.client_name
    ))


@bp.route('/edit_bill/Payment/<int:id>', methods=['POST'])
@login_required
def edit_payment(id):
    if not _user_can('can_manage_payments'):
        flash('Permission denied', 'danger')
        return redirect(url_for('accounts.client_payments'))

    payment = Payment.query.get_or_404(id)

    client_code = request.form.get('client_code', '').strip()
    client_name_input = request.form.get('client_name', '').strip()

    # Find client by name or code
    client = get_client_by_input(client_code) or get_client_by_input(client_name_input)
    if client:
        payment.client_name = client.name

    payment.amount = float(request.form.get('amount', 0) or 0)
    if _user_can('can_manage_payments'):
        try:
            payment.discount, payment.discount_reason = _parse_discount_fields(
                request.form.get('discount', 0),
                request.form.get('discount_reason', ''),
                label='Payment discount',
                require_reason=True
            )
        except ValueError as ve:
            flash(str(ve), 'danger')
            return redirect(url_for('payments_page'))
    payment.method = request.form.get('method', 'Cash')
    payment_account_id = request.form.get('payment_account_id')
    expected_category = _payment_expected_account_category(payment.method)
    if payment_account_id:
        try:
            payment.payment_account_id = int(payment_account_id)
            account = Account.query.get(payment.payment_account_id)
            if not account:
                payment.payment_account_id = None
                raise ValueError('Selected account not found.')
            if expected_category and (account.category or '').strip().lower() != expected_category:
                raise ValueError(f"Selected account must be a {expected_category} account for method '{payment.method}'.")
            payment.bank_name = account.bank_name or ''
            payment.account_name = account.account_holder_name or account.name
            payment.account_no = account.account_number or ''
        except (ValueError, TypeError) as ve:
            flash(str(ve), 'danger')
            return redirect(url_for('payments_page'))
    else:
        payment.payment_account_id = None
        payment.bank_name = request.form.get('bank_name', '').strip()
        payment.account_name = request.form.get('account_name', '').strip()
        payment.account_no = request.form.get('account_no', '').strip()

    if expected_category != 'bank':
        payment.bank_name = ''

    if expected_category in ['cash', 'bank'] and not payment.payment_account_id:
        flash('Select an account (cash/bank) to post this payment into Accounts.', 'danger')
        return redirect(url_for('payments_page'))
    manual_bill_raw = request.form.get('manual_bill_no', '').strip()
    payment.manual_bill_no = normalize_manual_bill(manual_bill_raw) if manual_bill_raw else ''
    payment.note = request.form.get('note', '').strip()
    date_str = (request.form.get('date') or '').strip()
    if date_str:
        payment.date_posted = resolve_posted_datetime(date_str, fallback_dt=payment.date_posted or pk_now())

    payment.photo_url = request.form.get('photo_url', '').strip()
    new_photo = save_photo(request.files.get('photo'))
    if new_photo:
        payment.photo_path = new_photo

    if payment.manual_bill_no:
        conflict = find_bill_conflict(payment.manual_bill_no)
        if conflict and not (conflict[0] == 'Payment' and conflict[1] == payment.id):
            flash(f"Manual bill '{payment.manual_bill_no}' already exists in {conflict[0]} #{conflict[1]}.", 'danger')
            return redirect(url_for('payments_page'))

    _sync_payment_waive_off(payment)
    _sync_payment_accounting(payment)
    db.session.commit()
    flash('Payment updated', 'success')

    return redirect(url_for('accounts.client_payments', show='active'))


