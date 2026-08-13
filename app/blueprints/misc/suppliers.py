"""suppliers — split from misc.py."""
from ._common import *  # noqa

@bp.route('/pay_supplier', methods=['GET'])
@login_required
def pay_supplier_page():
    return redirect(url_for('accounts.supplier_payments'))


@bp.route('/supplier_ledger/<int:id>')
@login_required
def supplier_ledger(id):
    supplier = Supplier.query.get_or_404(id)
    ledger, balance, total_bill, total_paid = _build_supplier_ledger_rows(supplier)
    page = request.args.get('page', 1, type=int) or 1
    per_page = 10
    total_entries = len(ledger)
    total_pages = max(1, (total_entries + per_page - 1) // per_page)
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages
    start = (page - 1) * per_page
    end = start + per_page
    page_rows = ledger[start:end]
    accounts = Account.query.filter(
        func.coalesce(Account.is_active, True) == True
    ).order_by(Account.category.asc(), Account.name.asc()).all()
    return render_template(
        'supplier_ledger.html',
        supplier=supplier,
        ledger=page_rows,
        accounts=accounts,
        payments_readonly=True,
        ledger_total=total_entries,
        final_balance=balance,
        total_bill=total_bill,
        total_paid=total_paid,
        page=page,
        total_pages=total_pages,
        per_page=per_page,
        today_date=pk_today().strftime('%Y-%m-%d'),
        current_pk_datetime=pk_now().strftime('%Y-%m-%dT%H:%M')
    )


@bp.route('/download_supplier_ledger/<int:id>')
@login_required
def download_supplier_ledger(id):
    supplier = Supplier.query.get_or_404(id)
    ledger, final_balance, total_bill, total_paid = _build_supplier_ledger_rows(supplier)
    action = (request.args.get('action') or 'download').lower()
    disposition = 'inline' if action == 'print' else 'attachment'
    rendered = render_template(
        'supplier_ledger_print.html',
        supplier=supplier,
        ledger=ledger,
        final_balance=final_balance,
        total_bill=total_bill,
        total_paid=total_paid,
        generated_at=pk_now(),
        auto_print=(action == 'print')
    )
    # Prefer WeasyPrint for download output when available.
    if action != 'print':
        pdf_response = _try_render_weasy_pdf(
            rendered,
            _download_filename('SUPPLIERLEDGER', 'pdf'),
            disposition=disposition
        )
        if pdf_response:
            return pdf_response

    response = make_response(rendered)
    response.headers['Content-Disposition'] = f'{disposition}; filename={_download_filename("SUPPLIERLEDGER", "html")}'
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    _disable_response_cache(response)
    return response


@bp.route('/download_supplier_payment/<int:payment_id>')
@login_required
def download_supplier_payment(payment_id):
    payment = SupplierPayment.query.get_or_404(payment_id)
    supplier = db.session.get(Supplier, payment.supplier_id)
    supplier_name = supplier.name if supplier else 'Supplier'

    bill_view = SimpleNamespace(
        manual_bill_no=f"PAY-{payment.id}",
        auto_bill_no='',
        invoice_no='',
        date_posted=payment.date_posted,
        client_name=supplier_name,
        supplier=supplier_name,
        amount=payment.amount or 0,
        paid_amount=0,
        method=payment.method or '',
        bank_name=payment.bank_name or '',
        account_name=payment.account_name or '',
        account_no=payment.account_no or '',
        note=payment.note or ''
    )

    action = (request.args.get('action') or 'download').lower()
    disposition = 'inline' if action == 'print' else 'attachment'

    rendered = render_template(
        'view_bill.html',
        bill=bill_view,
        type='Payment',
        items=[],
        client=None,
        client_balance=0,
        previous_balance=0,
        recent_deliveries=[],
        material_ledger_recent=[],
        material_stock_summary=[],
        auto_print=(action == 'print')
    )
    if action == 'download':
        pdf_response = _try_render_weasy_pdf(
            rendered,
            _download_filename('SUPPLIERPAYMENT', 'pdf'),
            disposition=disposition
        )
        if pdf_response:
            return pdf_response

    response = make_response(rendered)
    response.headers['Content-Disposition'] = f'{disposition}; filename={_download_filename("SUPPLIERPAYMENT", "html")}'
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    return response


@bp.route('/add_supplier_payment', methods=['POST'])
@login_required
def add_supplier_payment():
    flash('Supplier payment posting is disabled. Use Accounts → New Transaction (Pay → Supplier).', 'danger')
    return redirect(url_for('accounts.dashboard'))
    supplier_id = request.form.get('supplier_id')
    if not supplier_id:
        flash('Supplier is required', 'danger')
        return_to = (request.form.get('return_to') or '').strip().lower()
        if return_to == 'payments':
            return redirect(url_for('payments_page', party='supplier'))
        return redirect(url_for('suppliers'))
    amount = float(request.form.get('amount', 0) or 0)
    method = request.form.get('method', 'Cash')
    payment_account_id = request.form.get('payment_account_id')
    note = request.form.get('note', '').strip()
    date_str = request.form.get('date')
    bank_name = request.form.get('bank_name', '').strip()
    account_name = request.form.get('account_name', '').strip()
    account_no = request.form.get('account_no', '').strip()
    manual_bill_raw = request.form.get('manual_bill_no', '').strip()
    manual_bill_no = normalize_manual_bill(manual_bill_raw) if manual_bill_raw else ''
    date_posted = resolve_posted_datetime(date_str)
    auto_bill_no = get_next_bill_no(AUTO_BILL_NAMESPACES['SUPPLIER_PAYMENT'])

    expected_category = _payment_expected_account_category(method)
    pay_account = None
    if payment_account_id:
        try:
            payment_account_id = int(payment_account_id)
        except Exception:
            payment_account_id = None

    if amount > 0 and expected_category in ['cash', 'bank'] and not payment_account_id:
        flash('Select a cash/bank account to post this supplier payment into Accounts.', 'danger')
        return_to = (request.form.get('return_to') or '').strip().lower()
        if return_to == 'payments':
            return redirect(url_for('payments_page', party='supplier'))
        return redirect(url_for('suppliers'))

    if payment_account_id:
        pay_account = Account.query.get(payment_account_id)
        if not pay_account or bool(getattr(pay_account, 'is_active', True)) is False:
            flash('Please select a valid payment account.', 'danger')
            return_to = (request.form.get('return_to') or '').strip().lower()
            if return_to == 'payments':
                return redirect(url_for('payments_page', party='supplier'))
            return redirect(url_for('suppliers'))
        if expected_category and (pay_account.category or '').strip().lower() != expected_category:
            flash(f"Selected payment account must be a {expected_category} account for method '{method}'.", 'danger')
            return_to = (request.form.get('return_to') or '').strip().lower()
            if return_to == 'payments':
                return redirect(url_for('payments_page', party='supplier'))
            return redirect(url_for('suppliers'))
        if float(pay_account.balance or 0) + 0.00001 < float(amount or 0):
            flash('Insufficient balance in selected payment account.', 'danger')
            return_to = (request.form.get('return_to') or '').strip().lower()
            if return_to == 'payments':
                return redirect(url_for('payments_page', party='supplier'))
            return redirect(url_for('suppliers'))

        if expected_category == 'bank':
            bank_name = pay_account.bank_name or ''
            account_name = pay_account.account_holder_name or pay_account.name or ''
            account_no = pay_account.account_number or ''
        else:
            bank_name = ''
            account_name = pay_account.name if pay_account else (account_name or '')
            account_no = ''

    if manual_bill_no:
        conflict = find_bill_conflict(manual_bill_no)
        if conflict:
            flash(f"Manual bill '{manual_bill_no}' already exists in {conflict[0]} #{conflict[1]}.", 'danger')
            return_to = (request.form.get('return_to') or '').strip().lower()
            if return_to == 'payments':
                return redirect(url_for('payments_page', party='supplier'))
            return redirect(url_for('suppliers'))
        
    payment = SupplierPayment(
        supplier_id=int(supplier_id), 
        amount=amount, 
        method=method, 
        note=note, 
        date_posted=date_posted,
        bank_name=bank_name,
        account_name=account_name,
        account_no=account_no,
        payment_account_id=(payment_account_id if (amount > 0 and expected_category in ['cash', 'bank']) else None),
        manual_bill_no=manual_bill_no,
        auto_bill_no=auto_bill_no
    )
    db.session.add(payment)
    db.session.flush()
    _sync_supplier_payment_accounting(payment)
    db.session.commit()
    flash('Supplier payment recorded', 'success')
    return_to = (request.form.get('return_to') or '').strip().lower()
    if return_to == 'payments':
        return redirect(url_for('payments_page', party='supplier'))
    return redirect(url_for('supplier_ledger', id=supplier_id))


@bp.route('/edit_supplier_payment/<int:id>', methods=['POST'])
@login_required
def edit_supplier_payment(id):
    flash('Supplier payment editing is disabled. Use Accounts → Audit / Ledger actions instead.', 'danger')
    return redirect(url_for('accounts.dashboard'))
    payment = SupplierPayment.query.get_or_404(id)
    old_account_id = getattr(payment, 'payment_account_id', None)
    old_amount = float(getattr(payment, 'amount', 0) or 0)
    payment.amount = float(request.form.get('amount', 0) or 0)
    payment.method = request.form.get('method', 'Cash')
    payment_account_id = request.form.get('payment_account_id')
    payment.note = request.form.get('note', '').strip()
    date_str = request.form.get('date')
    if date_str:
        payment.date_posted = resolve_posted_datetime(date_str, fallback_dt=payment.date_posted or pk_now())
        
    payment.bank_name = request.form.get('bank_name', '').strip()
    payment.account_name = request.form.get('account_name', '').strip()
    payment.account_no = request.form.get('account_no', '').strip()

    expected_category = _payment_expected_account_category(payment.method)

    if payment_account_id:
        try:
            payment_account_id = int(payment_account_id)
        except Exception:
            payment_account_id = None

    if float(payment.amount or 0) > 0 and expected_category in ['cash', 'bank'] and not payment_account_id:
        flash('Select a cash/bank account to post this supplier payment into Accounts.', 'danger')
        return_to = (request.form.get('return_to') or '').strip().lower()
        if return_to == 'payments':
            return redirect(url_for('payments_page', party='supplier', show='all'))
        return redirect(url_for('supplier_ledger', id=payment.supplier_id))

    pay_account = None
    if payment_account_id:
        pay_account = Account.query.get(payment_account_id)
        if not pay_account or bool(getattr(pay_account, 'is_active', True)) is False:
            flash('Please select a valid payment account.', 'danger')
            return_to = (request.form.get('return_to') or '').strip().lower()
            if return_to == 'payments':
                return redirect(url_for('payments_page', party='supplier', show='all'))
            return redirect(url_for('supplier_ledger', id=payment.supplier_id))
        if expected_category and (pay_account.category or '').strip().lower() != expected_category:
            flash(f"Selected payment account must be a {expected_category} account for method '{payment.method}'.", 'danger')
            return_to = (request.form.get('return_to') or '').strip().lower()
            if return_to == 'payments':
                return redirect(url_for('payments_page', party='supplier', show='all'))
            return redirect(url_for('supplier_ledger', id=payment.supplier_id))

        new_amount = float(payment.amount or 0)
        if payment_account_id == old_account_id:
            delta = new_amount - float(old_amount or 0)
            if delta > 0 and float(pay_account.balance or 0) + 0.00001 < delta:
                flash('Insufficient balance in selected payment account for the increased amount.', 'danger')
                return_to = (request.form.get('return_to') or '').strip().lower()
                if return_to == 'payments':
                    return redirect(url_for('payments_page', party='supplier', show='all'))
                return redirect(url_for('supplier_ledger', id=payment.supplier_id))
        else:
            if new_amount > 0 and float(pay_account.balance or 0) + 0.00001 < new_amount:
                flash('Insufficient balance in selected payment account.', 'danger')
                return_to = (request.form.get('return_to') or '').strip().lower()
                if return_to == 'payments':
                    return redirect(url_for('payments_page', party='supplier', show='all'))
                return redirect(url_for('supplier_ledger', id=payment.supplier_id))

        if expected_category == 'bank':
            payment.bank_name = pay_account.bank_name or ''
            payment.account_name = pay_account.account_holder_name or pay_account.name or ''
            payment.account_no = pay_account.account_number or ''
        else:
            payment.bank_name = ''
            payment.account_name = pay_account.name if pay_account else (payment.account_name or '')
            payment.account_no = ''

    payment.payment_account_id = (payment_account_id if (float(payment.amount or 0) > 0 and expected_category in ['cash', 'bank']) else None)
    _sync_supplier_payment_accounting(payment)
    
    db.session.commit()
    flash('Payment updated', 'success')
    return_to = (request.form.get('return_to') or '').strip().lower()
    if return_to == 'payments':
        return redirect(url_for('payments_page', party='supplier', show='all'))
    return redirect(url_for('supplier_ledger', id=payment.supplier_id))


@bp.route('/delete_supplier_payment/<int:id>', methods=['POST'])
@login_required
def delete_supplier_payment(id):
    payment = SupplierPayment.query.get_or_404(id)
    payment.is_void = True
    _sync_supplier_payment_accounting(payment)
    marker = f'[SRC:SupplierPayment:{payment.id}]'
    for tx in AccountTransaction.query.filter(AccountTransaction.note.ilike(f'%{marker}%')).all():
        db.session.delete(tx)
    db.session.delete(payment)
    db.session.commit()
    flash('Supplier payment deleted', 'success')
    return_to = (request.form.get('return_to') or '').strip().lower()
    if return_to == 'payments':
        return redirect(url_for('payments_page', party='supplier', show='all'))
    return redirect(url_for('supplier_ledger', id=payment.supplier_id))


@bp.route('/restore_supplier_payment/<int:id>', methods=['POST'])
@login_required
def restore_supplier_payment(id):
    flash('Supplier payment restore is disabled. Use Accounts → Audit / Ledger actions instead.', 'danger')
    return redirect(url_for('accounts.dashboard'))
    payment = SupplierPayment.query.get_or_404(id)
    payment.is_void = False
    _sync_supplier_payment_accounting(payment)
    db.session.commit()
    flash('Supplier payment restored', 'success')
    return_to = (request.form.get('return_to') or '').strip().lower()
    if return_to == 'payments':
        return redirect(url_for('payments_page', party='supplier', show='all'))
    return redirect(url_for('supplier_ledger', id=payment.supplier_id))


