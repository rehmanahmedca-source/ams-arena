"""accounts_crud — split from accounts.py."""
from ._common import *  # noqa

@accounts_bp.route('/accounts')
@login_required
def manage_accounts():
    """Manage financial accounts."""
    _ensure_default_account_categories()
    _backfill_legacy_account_groups()
    accounts = _active_accounts().order_by(Account.name).all()
    categories = _account_categories()
    
    # Group accounts by category and type for better organization
    account_summary = {}
    for account in accounts:
        category_name = (account.category or 'Unknown').upper()
        account_type_name = account.account_type or 'Unknown'
        key = f"{category_name} - {account_type_name}"
        if key not in account_summary:
            account_summary[key] = []
        account_summary[key].append(account)
    
    return render_template('accounts/manage_accounts.html', accounts=accounts, account_summary=account_summary, categories=categories)


@accounts_bp.route('/categories/add', methods=['POST'])
@login_required
def add_account_category():
    name = (request.form.get('name') or '').strip()
    note = (request.form.get('note') or '').strip()

    if not name:
        flash('Category name is required.', 'danger')
        return redirect(url_for('accounts.manage_accounts'))

    existing = AccountCategory.query.filter(
        func.lower(func.trim(AccountCategory.name)) == name.lower(),
        AccountCategory.is_active == True
    ).first()
    if existing:
        flash('This account category already exists.', 'warning')
        return redirect(url_for('accounts.manage_accounts'))

    db.session.add(AccountCategory(name=name, note=note or None))
    db.session.commit()
    audit_log(current_user, 'account.category.create', f'name={name}')
    flash('Account category created successfully.', 'success')
    return redirect(url_for('accounts.manage_accounts'))


@accounts_bp.route('/accounts/add', methods=['GET', 'POST'])
@login_required
def add_account():
    """Add a new account."""
    _ensure_default_account_categories()
    _backfill_legacy_account_groups()
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        category = (request.form.get('category') or '').strip().lower()
        source_category = (request.form.get('source_category') or '').strip()
        account_type = (request.form.get('account_type') or '').strip()
        note = request.form.get('note')
        initial_balance_raw = request.form.get('initial_balance', '0')

        if not name:
            flash('Account name is required.', 'danger')
            return redirect(url_for('accounts.add_account'))
        if category not in ('cash', 'bank'):
            flash('Please select Cash or Bank.', 'danger')
            return redirect(url_for('accounts.add_account'))
        if not account_type:
            flash('Please select an account type.', 'danger')
            return redirect(url_for('accounts.add_account'))
        if not source_category:
            flash('Please select an account category first.', 'danger')
            return redirect(url_for('accounts.add_account'))
        category_exists = AccountCategory.query.filter(
            func.lower(func.trim(AccountCategory.name)) == source_category.lower(),
            AccountCategory.is_active == True
        ).first()
        if not category_exists:
            flash('Please select a valid account category.', 'danger')
            return redirect(url_for('accounts.add_account'))

        try:
            initial_balance = float(initial_balance_raw or 0)
        except ValueError:
            flash('Initial balance must be a valid number.', 'danger')
            return redirect(url_for('accounts.add_account'))

        if category == 'bank':
            bank_name = (request.form.get('bank_name') or '').strip()
            account_holder_name = (request.form.get('account_holder_name') or '').strip()
            account_number = (request.form.get('account_number') or '').strip()
            branch_code = (request.form.get('branch_code') or '').strip()
            if not bank_name or not account_holder_name or not account_number:
                flash('Bank account name, holder and number are required for bank accounts.', 'danger')
                return redirect(url_for('accounts.add_account'))
        else:
            bank_name = None
            account_holder_name = None
            account_number = None
            branch_code = None

        account = Account(
            name=name,
            category=category,
            source_category=category_exists.name,
            account_type=account_type,
            type=account_type,
            balance=initial_balance,
            bank_name=bank_name,
            account_holder_name=account_holder_name,
            account_number=account_number,
            branch_code=branch_code,
            note=note
        )
        try:
            db.session.add(account)
            db.session.commit()
        except IntegrityError as exc:
            db.session.rollback()
            flash(f'Unable to add account due to database constraint: {exc.orig}', 'danger')
            return redirect(url_for('accounts.add_account'))
        except Exception as exc:
            db.session.rollback()
            logger.exception('Add account failed')
            flash(f'Unable to add account: {exc}', 'danger')
            return redirect(url_for('accounts.add_account'))

        audit_log(current_user, 'account.create', f'name={name}, category={category}, source_category={category_exists.name}, account_type={account_type}')
        flash('Account added successfully!', 'success')
        return redirect(url_for('accounts.manage_accounts'))

    return render_template('accounts/add_account.html', categories=_account_categories())


@accounts_bp.route('/ledger/<int:account_id>')
@login_required
def account_ledger(account_id):
    account = Account.query.get_or_404(account_id)
    page = request.args.get('page', 1, type=int)
    per_page = 50
    search = (request.args.get('q') or '').strip()
    type_f = (request.args.get('type') or '').strip()
    show_voided = request.args.get('show_voided') == '1'
    date_from, date_to_excl = _parse_date_range(default_days=90)

    base_filters = [
        or_(AccountTransaction.from_account_id == account.id,
            AccountTransaction.to_account_id == account.id)
    ]
    if not show_voided:
        base_filters.append(AccountTransaction.is_void == False)

    # Opening balance = current balance - net effect of (active) transactions in/after date_from
    after_in = db.session.query(func.coalesce(func.sum(AccountTransaction.amount), 0)).filter(
        AccountTransaction.is_void == False,
        AccountTransaction.to_account_id == account.id,
        AccountTransaction.date_posted >= date_from
    ).scalar() or 0
    after_out = db.session.query(func.coalesce(func.sum(AccountTransaction.amount), 0)).filter(
        AccountTransaction.is_void == False,
        AccountTransaction.from_account_id == account.id,
        AccountTransaction.date_posted >= date_from
    ).scalar() or 0
    opening_balance = float(account.balance or 0) - float(after_in or 0) + float(after_out or 0)

    q = AccountTransaction.query.filter(*base_filters,
        AccountTransaction.date_posted >= date_from,
        AccountTransaction.date_posted < date_to_excl
    )
    if search:
        like = f'%{search}%'
        q = q.filter(or_(AccountTransaction.description.ilike(like), AccountTransaction.note.ilike(like)))
    if type_f:
        q = q.filter(AccountTransaction.transaction_type == type_f)

    period_in = q.with_entities(func.coalesce(func.sum(AccountTransaction.amount), 0)).filter(
        AccountTransaction.to_account_id == account.id, AccountTransaction.is_void == False
    ).scalar() or 0
    period_out = q.with_entities(func.coalesce(func.sum(AccountTransaction.amount), 0)).filter(
        AccountTransaction.from_account_id == account.id, AccountTransaction.is_void == False
    ).scalar() or 0

    # Fetch ALL rows in window (chronological asc) so we can compute running balance
    rows_asc = q.order_by(AccountTransaction.date_posted.asc(), AccountTransaction.id.asc()).all()
    running = opening_balance
    enriched = []
    for r in rows_asc:
        delta = 0.0
        if not r.is_void:
            if r.to_account_id == account.id:
                delta += float(r.amount or 0)
            if r.from_account_id == account.id:
                delta -= float(r.amount or 0)
        running += delta
        enriched.append({'tx': r, 'delta': delta, 'running': running})

    enriched.reverse()  # display newest first

    # Manual pagination over enriched list
    total_rows = len(enriched)
    start = (page - 1) * per_page
    end = start + per_page
    page_rows = enriched[start:end]

    types = ['Receipt', 'Payment', 'Transfer', 'Supplier Payment', 'Expense', 'Loss', 'Adjustment']

    return render_template('accounts/account_ledger.html', account=account, page_rows=page_rows,
                           opening_balance=opening_balance, period_in=period_in, period_out=period_out,
                           date_from=date_from, date_to=date_to_excl - timedelta(days=1),
                           search=search, type_f=type_f, types=types, show_voided=show_voided,
                           page=page, per_page=per_page, total_rows=total_rows,
                           has_prev=page > 1, has_next=end < total_rows)


@accounts_bp.route('/<int:account_id>/data')
@login_required
def account_data(account_id):
    """JSON data for the edit account modal."""
    a = Account.query.get_or_404(account_id)
    return jsonify({
        'id': a.id,
        'name': a.name,
        'category': a.category,
        'source_category': a.source_category,
        'account_type': a.account_type or (getattr(a, 'type', None) or ''),
        'balance': float(a.balance or 0),
        'bank_name': a.bank_name or '',
        'account_holder_name': a.account_holder_name or '',
        'account_number': a.account_number or '',
        'branch_code': a.branch_code or '',
        'note': a.note or '',
        'is_active': bool(a.is_active),
    })


@accounts_bp.route('/<int:account_id>/edit', methods=['POST'])
@login_required
def edit_account(account_id):
    """Edit an account's metadata. Balance changes are recorded as Adjustment transactions."""
    a = Account.query.get_or_404(account_id)
    try:
        name = (request.form.get('name') or '').strip()
        category = (request.form.get('category') or '').strip().lower()
        source_category = (request.form.get('source_category') or '').strip()
        account_type = (request.form.get('account_type') or '').strip()
        note = (request.form.get('note') or '').strip()
        new_balance_raw = request.form.get('balance', '').strip()

        if not name:
            raise ValueError('Account name is required.')
        if category not in ('cash', 'bank'):
            raise ValueError('Please select Cash or Bank.')
        if not account_type:
            raise ValueError('Please select an account type.')
        if not source_category:
            raise ValueError('Please select an account category.')

        cat = AccountCategory.query.filter(
            func.lower(func.trim(AccountCategory.name)) == source_category.lower(),
            AccountCategory.is_active == True
        ).first()
        if not cat:
            raise ValueError('Selected account category not found.')

        a.name = name
        a.category = category
        a.source_category = cat.name
        a.account_type = account_type
        a.type = account_type
        a.note = note or None

        if category == 'bank':
            a.bank_name = (request.form.get('bank_name') or '').strip() or None
            a.account_holder_name = (request.form.get('account_holder_name') or '').strip() or None
            a.account_number = (request.form.get('account_number') or '').strip() or None
            a.branch_code = (request.form.get('branch_code') or '').strip() or None
        else:
            a.bank_name = None
            a.account_holder_name = None
            a.account_number = None
            a.branch_code = None

        if new_balance_raw != '':
            try:
                new_balance = float(new_balance_raw)
            except ValueError:
                raise ValueError('Balance must be a valid number.')
            old_balance = float(a.balance or 0)
            diff = round(new_balance - old_balance, 2)
            if abs(diff) > 0.001:
                # Record as adjustment transaction so the trail shows it
                if diff > 0:
                    adj = AccountTransaction(
                        from_account_id=None, to_account_id=a.id, amount=abs(diff),
                        description='Balance adjustment (manual edit)',
                        note=f'Adjusted from Rs. {old_balance:.2f} to Rs. {new_balance:.2f}',
                        transaction_type='Adjustment', date_posted=pk_now()
                    )
                else:
                    adj = AccountTransaction(
                        from_account_id=a.id, to_account_id=None, amount=abs(diff),
                        description='Balance adjustment (manual edit)',
                        note=f'Adjusted from Rs. {old_balance:.2f} to Rs. {new_balance:.2f}',
                        transaction_type='Adjustment', date_posted=pk_now()
                    )
                db.session.add(adj)
                a.balance = new_balance

        db.session.commit()
        audit_log(current_user, 'account.update', f'id={a.id}, name={a.name}')
        flash('Account updated successfully.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    except Exception as exc:
        db.session.rollback()
        logger.exception('Edit account failed')
        flash(f'Unable to update account: {exc}', 'danger')

    return redirect(url_for('accounts.manage_accounts'))


@accounts_bp.route('/<int:account_id>/toggle', methods=['POST'])
@login_required
def toggle_account(account_id):
    """Soft-deactivate / reactivate an account."""
    a = Account.query.get_or_404(account_id)
    a.is_active = not bool(a.is_active)
    db.session.commit()
    audit_log(current_user, 'account.toggle', f'id={a.id}, name={a.name}, active={a.is_active}')
    flash(f'Account {"reactivated" if a.is_active else "deactivated"}.', 'success')
    return redirect(url_for('accounts.manage_accounts'))


