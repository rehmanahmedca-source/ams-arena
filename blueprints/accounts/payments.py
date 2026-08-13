"""payments — split from accounts.py."""
from ._common import *  # noqa

@accounts_bp.route('/payments/clients')
@login_required
def client_payments():
    """View and manage payments from clients."""
    page = request.args.get('page', 1, type=int)
    per_page = 50
    search = (request.args.get('q') or '').strip()
    method_f = (request.args.get('method') or '').strip()
    show_mode = (request.args.get('show') or 'active').strip().lower()
    if show_mode not in ['active', 'voided', 'all']:
        show_mode = 'active'
    date_from, date_to_excl = _parse_date_range()

    q = Payment.query
    if show_mode == 'active':
        q = q.filter(Payment.is_void == False)
    elif show_mode == 'voided':
        q = q.filter(Payment.is_void == True)

    q = q.filter(
        Payment.date_posted >= date_from,
        Payment.date_posted < date_to_excl
    )
    if search:
        like = f'%{search}%'
        q = q.filter(or_(Payment.client_name.ilike(like), Payment.note.ilike(like), Payment.account_name.ilike(like)))
    if method_f:
        q = q.filter(func.lower(Payment.method) == method_f.lower())

    total_amount = q.with_entities(func.coalesce(func.sum(Payment.amount), 0)).scalar() or 0
    total_count = q.count()
    payments = q.order_by(Payment.date_posted.desc()).paginate(page=page, per_page=per_page)
    accounts = Account.query.filter(func.coalesce(Account.is_active, True) == True).order_by(Account.name.asc()).all()
    payments_readonly = not (current_user.role in ('admin', 'root') or getattr(current_user, 'can_manage_payments', False))
    can_delete_payments = current_user.role in ('admin', 'root')

    return render_template('accounts/client_payments.html', payments=payments,
                           date_from=date_from, date_to=date_to_excl - timedelta(days=1),
                           search=search, method_f=method_f,
                           show_mode=show_mode,
                           total_amount=total_amount, total_count=total_count,
                           payments_readonly=payments_readonly,
                           can_delete_payments=can_delete_payments,
                           accounts=accounts)


@accounts_bp.route('/payments/suppliers')
@login_required
def supplier_payments():
    """View and manage payments to suppliers."""
    page = request.args.get('page', 1, type=int)
    per_page = 50
    search = (request.args.get('q') or '').strip()
    method_f = (request.args.get('method') or '').strip()
    date_from, date_to_excl = _parse_date_range()

    q = SupplierPayment.query.filter(
        SupplierPayment.is_void == False,
        SupplierPayment.date_posted >= date_from,
        SupplierPayment.date_posted < date_to_excl
    )
    if search:
        like = f'%{search}%'
        q = q.join(Supplier).filter(or_(Supplier.name.ilike(like), SupplierPayment.note.ilike(like), SupplierPayment.account_name.ilike(like)))
    if method_f:
        q = q.filter(func.lower(SupplierPayment.method) == method_f.lower())

    total_amount = q.with_entities(func.coalesce(func.sum(SupplierPayment.amount), 0)).scalar() or 0
    total_count = q.count()
    payments = q.order_by(SupplierPayment.date_posted.desc()).paginate(page=page, per_page=per_page)

    return render_template('accounts/supplier_payments.html', payments=payments,
                           date_from=date_from, date_to=date_to_excl - timedelta(days=1),
                           search=search, method_f=method_f,
                           total_amount=total_amount, total_count=total_count)


@accounts_bp.route('/payments/clients/void/<int:id>', methods=['POST'])
@login_required
def client_payment_void(id):
    if not (current_user.role in ('admin', 'root') or getattr(current_user, 'can_manage_payments', False)):
        flash('Permission denied', 'danger')
        return redirect(request.referrer or url_for('accounts.client_payments'))

    from app.services.void_rebuild import _set_payment_void_state, rebuild_pending_bills
    from app.services.lookups import get_client_by_input

    payment = Payment.query.get_or_404(id)
    if not payment.is_void:
        if _set_payment_void_state(payment, True):
            client = get_client_by_input(payment.client_name or '')
            if client:
                rebuild_pending_bills(client_id=client.id)
            audit_log(current_user, 'transaction.delete.Payment', f'id={id}')
            db.session.commit()
            flash('Payment deleted successfully.', 'success')
        else:
            flash('Payment could not be deleted.', 'warning')
    else:
        flash('Payment already deleted.', 'warning')

    return redirect(request.referrer or url_for('accounts.client_payments'))


@accounts_bp.route('/payments/clients/restore/<int:id>', methods=['POST'])
@login_required
def client_payment_restore(id):
    if not (current_user.role in ('admin', 'root') or getattr(current_user, 'can_manage_payments', False)):
        flash('Permission denied', 'danger')
        return redirect(request.referrer or url_for('accounts.client_payments'))

    from app.services.void_rebuild import _set_payment_void_state, rebuild_pending_bills
    from app.services.lookups import get_client_by_input

    payment = Payment.query.get_or_404(id)
    if payment.is_void:
        if _set_payment_void_state(payment, False):
            client = get_client_by_input(payment.client_name or '')
            if client:
                rebuild_pending_bills(client_id=client.id)
            audit_log(current_user, 'transaction.unvoid.Payment', f'id={id}')
            db.session.commit()
            flash('Payment restored successfully.', 'success')
        else:
            flash('Payment could not be restored.', 'warning')
    else:
        flash('Payment is already active.', 'warning')

    return redirect(request.referrer or url_for('accounts.client_payments'))


@accounts_bp.route('/expenditures')
@login_required
def expenditures():
    """View and manage personal expenditures."""
    page = request.args.get('page', 1, type=int)
    per_page = 50
    search = (request.args.get('q') or '').strip()
    category_f = (request.args.get('category') or '').strip() # Filter for category/description
    method_f = (request.args.get('method') or '').strip() # Filter for payment method/account category
    date_from, date_to_excl = _parse_date_range()

    # Fetch FbmCashDrawerEntry expenditures
    fbm_q = FbmCashDrawerEntry.query.filter(
        FbmCashDrawerEntry.entry_type == 'out',
        FbmCashDrawerEntry.is_void == False,
        FbmCashDrawerEntry.date_posted >= date_from,
        FbmCashDrawerEntry.date_posted < date_to_excl
    )
    if search:
        like = f'%{search}%'
        fbm_q = fbm_q.filter(or_(FbmCashDrawerEntry.note.ilike(like), FbmCashDrawerEntry.category.ilike(like)))
    if category_f:
        fbm_q = fbm_q.filter(FbmCashDrawerEntry.category == category_f)
    if method_f:
        fbm_q = fbm_q.filter(func.lower(FbmCashDrawerEntry.method) == method_f.lower())
    fbm_expenditures = fbm_q.all()

    # Fetch AccountTransaction expenditures (Expenses and Payments)
    tx_q = AccountTransaction.query.filter(
        AccountTransaction.date_posted >= date_from,
        AccountTransaction.date_posted < date_to_excl,
        AccountTransaction.is_void == False,
        AccountTransaction.transaction_type.in_(['Expense', 'Payment']),
        AccountTransaction.from_account_id.isnot(None)
    )
    if search:
        like = f'%{search}%'
        tx_q = tx_q.filter(or_(AccountTransaction.description.ilike(like), AccountTransaction.note.ilike(like)))
    if category_f:
        tx_q = tx_q.filter(AccountTransaction.description == category_f)
    if method_f:
        # Filter AccountTransactions by the category of their 'from' account
        tx_q = tx_q.join(Account, AccountTransaction.from_account_id == Account.id).filter(func.lower(Account.category) == method_f.lower())
    tx_expenditures = tx_q.all()

    all_expenditures = []
    for e in fbm_expenditures:
        all_expenditures.append({
            'date_posted': e.date_posted,
            'category': e.category or '',
            'amount': float(e.amount or 0),
            'method': e.method or '',
            'note': e.note or '',
            'type': 'FBM Cash Drawer'
        })
    for tx in tx_expenditures:
        acc = Account.query.get(tx.from_account_id)
        all_expenditures.append({
            'date_posted': tx.date_posted,
            'category': tx.description or 'Expense',
            'amount': float(tx.amount or 0),
            'method': (acc.category.capitalize() if acc else 'Other'), # Use account category as method
            'note': tx.note or '',
            'type': 'Account Transaction'
        })

    all_expenditures.sort(key=lambda x: x['date_posted'], reverse=True)

    total_amount = sum(item['amount'] for item in all_expenditures)
    total_count = len(all_expenditures)

    # Manual pagination
    start = (page - 1) * per_page
    end = start + per_page
    paginated_expenditures = all_expenditures[start:end]
    
    # Wrap in a SimpleNamespace to mimic a Pagination object for the template
    pagination_wrapper = SimpleNamespace(
        items=paginated_expenditures,
        page=page,
        per_page=per_page,
        total=total_count,
        pages=(total_count + per_page - 1) // per_page,
        has_prev=(page > 1),
        has_next=(end < total_count),
        prev_num=page - 1,
        next_num=page + 1
    )

    # Collect categories for filter dropdown from both sources
    all_categories = set()
    for r in db.session.query(FbmCashDrawerEntry.category).filter(
        FbmCashDrawerEntry.entry_type == 'out',
        FbmCashDrawerEntry.is_void == False,
        FbmCashDrawerEntry.category.isnot(None),
        FbmCashDrawerEntry.category != ''
    ).distinct(FbmCashDrawerEntry.category).all():
        all_categories.add(r[0])
    for r in db.session.query(AccountTransaction.description).filter(
        AccountTransaction.is_void == False,
        AccountTransaction.transaction_type.in_(['Expense', 'Payment']),
        AccountTransaction.description.isnot(None),
        AccountTransaction.description != ''
    ).distinct(AccountTransaction.description).all():
        all_categories.add(r[0])
    categories = sorted(list(all_categories))

    # Collect methods for filter dropdown from both sources
    all_methods = set()
    for r in db.session.query(FbmCashDrawerEntry.method).filter(
        FbmCashDrawerEntry.entry_type == 'out',
        FbmCashDrawerEntry.is_void == False,
        FbmCashDrawerEntry.method.isnot(None),
        FbmCashDrawerEntry.method != ''
    ).distinct(FbmCashDrawerEntry.method).all():
        all_methods.add(r[0])
    for r in db.session.query(Account.category).filter(
        Account.is_active == True,
        Account.category.isnot(None),
        Account.category != ''
    ).distinct(Account.category).all():
        all_methods.add(r[0].capitalize()) # Capitalize to match 'Cash', 'Bank' etc.
    methods = sorted(list(all_methods))

    return render_template('accounts/expenditures.html', expenditures=pagination_wrapper,
                           date_from=date_from, date_to=date_to_excl - timedelta(days=1),
                           search=search, category_f=category_f, method_f=method_f,
                           categories=categories, methods=methods,
                           total_amount=total_amount, total_count=total_count,
                           page=page, per_page=per_page,
                           has_prev=(page > 1), has_next=(end < total_count))


@accounts_bp.route('/receipts')
@login_required
def receipts():
    """View receipts from sales and GRN paid amounts within a date range."""
    date_from, date_to_excl = _parse_date_range(default_days=0)

    sales = DirectSale.query.filter(
        DirectSale.date_posted >= date_from,
        DirectSale.date_posted < date_to_excl,
        DirectSale.is_void == False
    ).order_by(DirectSale.date_posted.desc()).all()

    grns = GRN.query.filter(
        GRN.date_posted >= date_from,
        GRN.date_posted < date_to_excl,
        GRN.is_void == False,
        GRN.paid_amount > 0
    ).order_by(GRN.date_posted.desc()).all()

    return render_template('accounts/receipts.html', sales=sales, grns=grns,
                           date_from=date_from, date_to=date_to_excl - timedelta(days=1))


