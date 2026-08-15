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
    """Compatibility endpoint delegating to the canonical Accounts service."""
    if not _user_can('can_manage_suppliers'):
        flash('Permission denied', 'danger')
        return redirect(url_for('accounts.supplier_payments'))
    supplier_id = request.form.get('supplier_id')
    try:
        from app.services.payments_crud import save_supplier_payment
        payment, _ = save_supplier_payment(
            supplier_id=supplier_id,
            amount=request.form.get('amount', 0),
            method=request.form.get('method', 'Cash'),
            payment_account_id=request.form.get('payment_account_id'),
            manual_bill_no=request.form.get('manual_bill_no', ''),
            date_posted=request.form.get('date', ''),
            note=request.form.get('note', ''),
            idempotency_key=request.form.get('idempotency_key'),
            actor=current_user,
        )
        db.session.commit()
        flash('Supplier payment recorded.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    except Exception as exc:
        db.session.rollback()
        logging.exception('Supplier payment create failed')
        flash(f'Unable to record supplier payment: {exc}', 'danger')
    return_to = (request.form.get('return_to') or '').strip().lower()
    if return_to == 'payments':
        return redirect(url_for('accounts.supplier_payments'))
    if str(supplier_id or '').isdigit():
        return redirect(url_for('supplier_ledger', id=int(supplier_id)))
    return redirect(url_for('suppliers'))


@bp.route('/edit_supplier_payment/<int:id>', methods=['POST'])
@login_required
def edit_supplier_payment(id):
    """Compatibility endpoint using exactly the same service as Create/Edit."""
    if not _user_can('can_manage_suppliers'):
        flash('Permission denied', 'danger')
        return redirect(url_for('accounts.supplier_payments'))
    payment = SupplierPayment.query.get_or_404(id)
    try:
        from app.services.payments_crud import save_supplier_payment
        save_supplier_payment(
            payment_id=id,
            supplier_id=request.form.get('supplier_id') or payment.supplier_id,
            amount=request.form.get('amount', payment.amount),
            method=request.form.get('method', payment.method or 'Cash'),
            payment_account_id=request.form.get('payment_account_id') or payment.payment_account_id,
            manual_bill_no=request.form.get('manual_bill_no', payment.manual_bill_no or ''),
            date_posted=request.form.get('date', ''),
            note=request.form.get('note', payment.note or ''),
            expected_revision=request.form.get('revision'),
            actor=current_user,
        )
        db.session.commit()
        flash('Supplier payment updated. All balances were recalculated.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    except Exception as exc:
        db.session.rollback()
        logging.exception('Supplier payment edit failed')
        flash(f'Unable to update supplier payment: {exc}', 'danger')
    return redirect(url_for('accounts.supplier_payments', show='all'))


@bp.route('/delete_supplier_payment/<int:id>', methods=['POST'])
@login_required
def delete_supplier_payment(id):
    """Compatibility soft-delete; never hard-deletes accounting history."""
    if not _user_can('can_manage_suppliers'):
        flash('Permission denied', 'danger')
        return redirect(url_for('accounts.supplier_payments'))
    payment = SupplierPayment.query.get_or_404(id)
    try:
        from app.services.payments_crud import delete_supplier_payment as do_delete
        if do_delete(payment, actor=current_user):
            db.session.commit()
            flash('Supplier payment deleted and accounting effects reversed.', 'success')
        else:
            flash('Supplier payment is already deleted.', 'warning')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    except Exception as exc:
        db.session.rollback()
        logging.exception('Supplier payment delete failed')
        flash(f'Unable to delete supplier payment: {exc}', 'danger')
    return redirect(url_for('accounts.supplier_payments', show='all'))


@bp.route('/restore_supplier_payment/<int:id>', methods=['POST'])
@login_required
def restore_supplier_payment(id):
    if not _user_can('can_manage_suppliers'):
        flash('Permission denied', 'danger')
        return redirect(url_for('accounts.supplier_payments'))
    payment = SupplierPayment.query.get_or_404(id)
    try:
        from app.services.payments_crud import restore_supplier_payment as do_restore
        if do_restore(payment, actor=current_user):
            db.session.commit()
            flash('Supplier payment restored and balances re-applied.', 'success')
        else:
            flash('Supplier payment is already active.', 'warning')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    except Exception as exc:
        db.session.rollback()
        logging.exception('Supplier payment restore failed')
        flash(f'Unable to restore supplier payment: {exc}', 'danger')
    return redirect(url_for('accounts.supplier_payments', show='all'))
