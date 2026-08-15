"""transactions — split from accounts.py."""
from ._common import *  # noqa

@accounts_bp.route('/transfers')
@login_required
def transfers():
    """View account transfers."""
    page = request.args.get('page', 1, type=int)
    per_page = 50
    search = (request.args.get('q') or '').strip()
    date_from, date_to_excl = _parse_date_range()

    q = AccountTransaction.query.filter(
        AccountTransaction.is_void == False,
        AccountTransaction.transaction_type == 'Transfer',
        AccountTransaction.date_posted >= date_from,
        AccountTransaction.date_posted < date_to_excl
    )
    if search:
        like = f'%{search}%'
        q = q.filter(or_(AccountTransaction.description.ilike(like), AccountTransaction.note.ilike(like)))

    total_amount = q.with_entities(func.coalesce(func.sum(AccountTransaction.amount), 0)).scalar() or 0
    total_count = q.count()
    transfers = q.order_by(AccountTransaction.date_posted.desc()).paginate(page=page, per_page=per_page)

    return render_template('accounts/transfers.html', transfers=transfers,
                           date_from=date_from, date_to=date_to_excl - timedelta(days=1),
                           search=search, total_amount=total_amount, total_count=total_count)


@accounts_bp.route('/transactions/<int:tx_id>/void', methods=['POST'])
@login_required
def void_transaction(tx_id):
    """Legacy URL — permanently deletes the account entry."""
    return delete_account_transaction(tx_id)


@accounts_bp.route('/transactions/<int:tx_id>/delete', methods=['POST'])
@login_required
def delete_account_transaction(tx_id):
    tx = AccountTransaction.query.get_or_404(tx_id)
    try:
        if not tx.is_void:
            _reverse_balance_effect(tx)
        note_txt = tx.note or ''
        pay_match = re.search(r'\[SRC:Payment:(\d+)\]', note_txt, flags=re.IGNORECASE)
        if pay_match:
            p = Payment.query.get(int(pay_match.group(1)))
            if p:
                from app.services.void_rebuild import hard_delete_transaction
                hard_delete_transaction('Payment', p.id)
        sp_match = re.search(r'\[SRC:SupplierPayment:(\d+)\]', note_txt, flags=re.IGNORECASE)
        if sp_match:
            sp = SupplierPayment.query.get(int(sp_match.group(1)))
            if sp:
                sp.is_void = True
        if db.session.get(AccountTransaction, tx_id):
            db.session.delete(tx)
        db.session.commit()
        audit_log(current_user, 'account.transaction.delete',
                  f'tx_id={tx_id}, type={tx.transaction_type}, amount={tx.amount}')
        flash('Account entry deleted and balances corrected.', 'success')
    except Exception as exc:
        db.session.rollback()
        logger.exception('Delete account transaction failed')
        flash(f'Unable to delete transaction: {exc}', 'danger')
    return redirect(request.referrer or url_for('accounts.dashboard'))


@accounts_bp.route('/transactions/<int:tx_id>/edit', methods=['POST'])
@login_required
def edit_account_transaction(tx_id):
    tx = AccountTransaction.query.get_or_404(tx_id)
    try:
        new_amount = float(request.form.get('amount', tx.amount) or 0)
        if new_amount <= 0:
            raise ValueError('Amount must be greater than zero.')
        new_desc = (request.form.get('description') or tx.description or '').strip()
        new_note = (request.form.get('note') or tx.note or '').strip()
        date_raw = (request.form.get('date_posted') or '').strip()
        if date_raw:
            try:
                new_dt = datetime.strptime(date_raw, '%Y-%m-%dT%H:%M')
            except ValueError:
                new_dt = tx.date_posted
        else:
            new_dt = tx.date_posted

        if not tx.is_void:
            _reverse_balance_effect(tx)
        tx.amount = new_amount
        tx.description = new_desc
        tx.note = new_note
        tx.date_posted = new_dt
        tx.is_void = False
        from_id = request.form.get('from_account_id', type=int)
        to_id = request.form.get('to_account_id', type=int)
        if from_id:
            tx.from_account_id = from_id
        if to_id:
            tx.to_account_id = to_id
        if tx.to_account_id:
            a = Account.query.get(tx.to_account_id)
            if a:
                a.balance = float(a.balance or 0) + float(tx.amount or 0)
        if tx.from_account_id:
            a = Account.query.get(tx.from_account_id)
            if a:
                a.balance = float(a.balance or 0) - float(tx.amount or 0)
        db.session.commit()
        audit_log(current_user, 'account.transaction.edit', f'tx_id={tx.id}, amount={tx.amount}')
        flash('Account entry updated.', 'success')
    except Exception as exc:
        db.session.rollback()
        logger.exception('Edit account transaction failed')
        flash(f'Unable to edit transaction: {exc}', 'danger')
    return redirect(request.referrer or url_for('accounts.dashboard'))


@accounts_bp.route('/transactions/new', methods=['POST'])
@login_required
def add_transaction():
    _ensure_default_account_categories()
    _backfill_legacy_account_groups()
    tx_mode = (request.form.get('tx_mode') or '').strip().lower()
    note = (request.form.get('note') or '').strip()
    method = (request.form.get('method') or 'Cash').strip()
    tx_date_raw = (request.form.get('date_posted') or '').strip()
    tx_date = pk_now()
    if tx_date_raw:
        try:
            tx_date = datetime.strptime(tx_date_raw, '%Y-%m-%dT%H:%M')
        except ValueError:
            tx_date = pk_now()

    try:
        if tx_mode == 'receive':
            receive_account_id = request.form.get('receive_account_id', type=int)
            receive_from_category = (request.form.get('receive_from_category') or 'client_ledger').strip()
            client_input = (request.form.get('client_input') or '').strip()
            receive_from_account_id = request.form.get('receive_from_account_id', type=int)
            receive_source_label = (request.form.get('receive_source_label') or '').strip()
            amount = float(request.form.get('amount', 0) or 0)
            discount = float(request.form.get('discount', 0) or 0)

            if amount < 0:
                raise ValueError('Received amount cannot be negative.')
            if discount < 0:
                raise ValueError('Discount cannot be negative.')
            if (amount + discount) <= 0:
                raise ValueError('Received amount and discount cannot both be zero.')

            receive_account = Account.query.get(receive_account_id) if receive_account_id else None
            if amount > 0:
                if not _is_account_active(receive_account):
                    raise ValueError('Please select a valid destination account.')
                _validate_account_matches_method(receive_account, method, 'Destination')

            if receive_from_category == 'client_ledger':
                client = _resolve_client(client_input, active_only=True)
                if not client:
                    raise ValueError('Client not found or suspended. Please select a valid client from the dues list.')

                if amount > 0:
                    receive_account.balance = float(receive_account.balance or 0) + amount

                payment = Payment(
                    client_name=client.name,
                    amount=amount,
                    method=(method or 'Cash') if amount > 0 else 'Waive-Off',
                    note=note,
                    discount=discount,
                    discount_reason='Accounts receive transaction',
                    date_posted=tx_date,
                    account_name=(receive_account.name if receive_account else ''),
                    bank_name=((receive_account.bank_name or '') if receive_account else ''),
                    account_no=((receive_account.account_number or '') if receive_account else ''),
                    payment_account_id=(receive_account.id if receive_account else None),
                    auto_bill_no=get_next_bill_no(AUTO_BILL_NAMESPACES['PAYMENT'])
                )
                db.session.add(payment)
                db.session.flush()
                pay_marker = f"[SRC:Payment:{payment.id}]"

                if amount > 0:
                    account_tx = AccountTransaction(
                        from_account_id=None,
                        to_account_id=receive_account.id,
                        amount=amount,
                        description=f"Client payment received from {client.name}",
                        note=" ".join([x for x in [(note or '').strip(), pay_marker] if x]).strip(),
                        transaction_type='Receipt',
                        date_posted=tx_date
                    )
                    db.session.add(account_tx)

                if discount > 0:
                    discount_tx = AccountTransaction(
                        from_account_id=None,
                        to_account_id=None,
                        amount=discount,
                        description=f"Waive-off loss for {client.name}",
                        note=" ".join([x for x in [(note or 'Discount as company loss').strip(), f"{pay_marker}:LOSS"] if x]).strip(),
                        transaction_type='Loss',
                        date_posted=tx_date
                    )
                    db.session.add(discount_tx)

                _apply_payment_to_pending_bills(client, amount, discount)
                account_label = receive_account.name if receive_account else 'discount-only'
                audit_log(current_user, 'account.transaction.receive', f'source_category=client_ledger, client={client.name}, account={account_label}, amount={amount}, discount={discount}')

            elif receive_from_category == 'other_source':
                if amount <= 0:
                    raise ValueError('Received amount must be greater than zero.')
                if not receive_source_label:
                    raise ValueError('Please enter who or what this money was received from.')

                receive_account.balance = float(receive_account.balance or 0) + amount
                account_tx = AccountTransaction(
                    from_account_id=None,
                    to_account_id=receive_account.id,
                    amount=amount,
                    description=f"Money received from {receive_source_label}",
                    note=note,
                    transaction_type='Receipt',
                    date_posted=tx_date
                )
                db.session.add(account_tx)
                audit_log(current_user, 'account.transaction.receive', f'source_category=other_source, source={receive_source_label}, to={receive_account.name}, amount={amount}')

            else:
                category_exists = AccountCategory.query.filter(
                    func.lower(func.trim(AccountCategory.name)) == receive_from_category.lower(),
                    AccountCategory.is_active == True
                ).first()
                if not category_exists:
                    raise ValueError('Please select a valid receive source category.')
                if amount <= 0:
                    raise ValueError('Received amount must be greater than zero.')

                from_account = Account.query.get(receive_from_account_id) if receive_from_account_id else None
                if not _is_account_active(from_account):
                    raise ValueError('Please select a valid source account.')
                if (from_account.source_category or '').strip().lower() != category_exists.name.lower():
                    raise ValueError('Selected source account does not belong to the chosen category.')
                if from_account.id == receive_account.id:
                    raise ValueError('Source and destination accounts cannot be the same.')
                # Allow loan accounts to go negative: do not enforce insufficient-balance check for Loan group
                is_loan_source = ((from_account.source_category or '').strip().lower() == 'loan') or ((category_exists.name or '').strip().lower() == 'loan')
                if not is_loan_source and float(from_account.balance or 0) < amount:
                    raise ValueError('Insufficient balance in selected source account.')

                # For normal accounts this subtracts the amount; for Loan accounts this will produce a MORE NEGATIVE balance
                from_account.balance = float(from_account.balance or 0) - amount
                receive_account.balance = float(receive_account.balance or 0) + amount
                account_tx = AccountTransaction(
                    from_account_id=from_account.id,
                    to_account_id=receive_account.id,
                    amount=amount,
                    description=f"Funds received from account {from_account.name}",
                    note=note,
                    transaction_type='Transfer',
                    date_posted=tx_date
                )
                db.session.add(account_tx)
                audit_log(current_user, 'account.transaction.receive', f'source_category={category_exists.name}, from={from_account.name}, to={receive_account.name}, amount={amount}')

            db.session.commit()
            flash('Receive transaction recorded successfully.', 'success')

        elif tx_mode == 'pay':
            from_account_id = request.form.get('pay_from_account_id', type=int)
            to_account_id = request.form.get('pay_to_account_id', type=int)
            pay_target = (request.form.get('pay_target') or '').strip().lower()
            amount = float(request.form.get('amount', 0) or 0)

            if amount <= 0:
                raise ValueError('Payment amount must be greater than zero.')

            from_account = Account.query.get(from_account_id) if from_account_id else None
            if not _is_account_active(from_account):
                raise ValueError('Please select a valid source account.')
            _validate_account_matches_method(from_account, method, 'Source')
            if float(from_account.balance or 0) < amount:
                raise ValueError('Insufficient balance in selected source account.')

            from_account.balance = float(from_account.balance or 0) - amount

            if pay_target == 'company_transfer':
                to_account = Account.query.get(to_account_id) if to_account_id else None
                if not _is_account_active(to_account):
                    raise ValueError('Please select a valid destination account.')
                if to_account.id == from_account.id:
                    raise ValueError('Source and destination accounts cannot be the same.')

                to_account.balance = float(to_account.balance or 0) + amount
                tx = AccountTransaction(
                    from_account_id=from_account.id,
                    to_account_id=to_account.id,
                    amount=amount,
                    description='Intra-company transfer',
                    note=note,
                    transaction_type='Transfer',
                    date_posted=tx_date
                )
                db.session.add(tx)
                audit_log(current_user, 'account.transaction.transfer', f'from={from_account.name}, to={to_account.name}, amount={amount}')
                flash('Transfer transaction recorded successfully.', 'success')

            elif pay_target == 'supplier':
                supplier_id = request.form.get('supplier_id', type=int)
                supplier_input = (request.form.get('supplier_input') or '').strip()
                supplier = Supplier.query.get(supplier_id) if supplier_id else None
                if not supplier and supplier_input:
                    supplier = _resolve_supplier(supplier_input)
                if not supplier:
                    raise ValueError('Please select a valid supplier.')

                sp = SupplierPayment(
                    supplier_id=supplier.id,
                    amount=amount,
                    method=method or 'Cash',
                    note=note,
                    date_posted=tx_date,
                    bank_name=(from_account.bank_name or ''),
                    account_name=(from_account.account_holder_name or from_account.name or ''),
                    account_no=(from_account.account_number or ''),
                    payment_account_id=from_account.id
                )
                db.session.add(sp)
                db.session.flush()
                sp_marker = f"[SRC:SupplierPayment:{sp.id}]"

                tx = AccountTransaction(
                    from_account_id=from_account.id,
                    to_account_id=None,
                    amount=amount,
                    description=f'Supplier payment to {supplier.name}',
                    note=" ".join([x for x in [(note or '').strip(), sp_marker] if x]).strip(),
                    transaction_type='Supplier Payment',
                    date_posted=tx_date
                )
                db.session.add(tx)
                audit_log(current_user, 'account.transaction.supplier_payment', f'from={from_account.name}, supplier={supplier.name}, amount={amount}')
                flash('Supplier payment recorded successfully.', 'success')
            elif pay_target == 'client_refund':
                # Refund issued to a client: record refund audit (Payment negative for client ledger),
                # create account transaction for cash out so cash flow reflects it, and keep everything atomic.
                client_id = request.form.get('client_id_refund', type=int)
                client_input = (request.form.get('client_input_refund') or '').strip()
                client = Client.query.get(client_id) if client_id else None
                if not client and client_input:
                    client = _resolve_client(client_input, active_only=True)
                if not client:
                    raise ValueError('Please select a valid client.')

                # Create a real ledger Payment row (negative) so client ledger shows
                # the refund, and then create the AccountTransaction cash-out.
                # Do NOT generate an auto_bill_no for this refund Payment so no SB-CP
                # rows are created. Mark it as method='Refund' so cash reports skip it.
                payment = Payment(
                    client_name=client.name,
                    amount=-float(amount or 0),
                    method='Refund',
                    note=note,
                    discount=0,
                    discount_reason='Client refund',
                    date_posted=tx_date,
                    account_name=(from_account.name or ''),
                    bank_name=(from_account.bank_name or ''),
                    account_no=(from_account.account_number or ''),
                    payment_account_id=from_account.id,
                    auto_bill_no=None
                )
                db.session.add(payment)
                db.session.flush()
                pay_marker = f"[SRC:ClientRefund:{payment.id}]"

                tx = AccountTransaction(
                    from_account_id=from_account.id,
                    to_account_id=None,
                    amount=amount,
                    description=f'Client refund to {client.name}',
                    note=" ".join([x for x in [(note or '').strip(), pay_marker] if x]).strip(),
                    transaction_type='Payment',
                    date_posted=tx_date
                )
                db.session.add(tx)
                # Rebuild pending bills for the client so ledger/pending view reflects this refund
                try:
                    from app.services.void_rebuild import rebuild_pending_bills
                    rebuild_pending_bills(client_id=client.id)
                except Exception:
                    pass
                audit_log(current_user, 'account.transaction.client_refund', f'from={from_account.name}, client={client.name}, amount={amount}')
                flash('Client refund recorded successfully.', 'success')
            elif pay_target == 'loan':
                # Repayment to a Loan account: credit the loan account (moves negative toward zero)
                to_account = Account.query.get(to_account_id) if to_account_id else None
                if not _is_account_active(to_account):
                    raise ValueError('Please select a valid loan account.')
                if (to_account.source_category or '').strip().lower() != 'loan':
                    raise ValueError('Selected destination is not a Loan account.')
                if to_account.id == from_account.id:
                    raise ValueError('Source and destination accounts cannot be the same.')

                # from_account already debited above; now credit loan account so negative liability decreases
                to_account.balance = float(to_account.balance or 0) + amount

                tx = AccountTransaction(
                    from_account_id=from_account.id,
                    to_account_id=to_account.id,
                    amount=amount,
                    description=f'Loan repayment to {to_account.name}',
                    note=note,
                    transaction_type='Payment',
                    date_posted=tx_date
                )
                db.session.add(tx)
                audit_log(current_user, 'account.transaction.loan_payment', f'from={from_account.name}, to_loan={to_account.name}, amount={amount}')
                flash('Loan payment recorded successfully.', 'success')

            else:
                target_label = (request.form.get('target_label') or '').strip()
                if not target_label:
                    if pay_target == 'loan':
                        target_label = 'Loan Payment'
                    elif pay_target == 'personal_expense':
                        target_label = 'Personal Expense'
                    else:
                        target_label = 'Other Payment'

                tx_type = 'Expense' if pay_target in ['personal_expense', 'other_expense'] else 'Payment'
                tx = AccountTransaction(
                    from_account_id=from_account.id,
                    to_account_id=None,
                    amount=amount,
                    description=target_label,
                    note=note,
                    transaction_type=tx_type,
                    date_posted=tx_date
                )
                db.session.add(tx)
                audit_log(current_user, 'account.transaction.pay', f'from={from_account.name}, target={target_label}, amount={amount}')
                flash('Outgoing payment recorded successfully.', 'success')

            db.session.commit()
        else:
            raise ValueError('Invalid transaction type selected.')

    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    except Exception as exc:
        db.session.rollback()
        logger.exception('Accounts transaction save failed')
        flash(f'Unable to save transaction: {exc}', 'danger')

    return redirect(url_for('accounts.dashboard'))


@accounts_bp.route('/transfers/add', methods=['GET', 'POST'])
@login_required
def add_transfer():
    """Add a new account transfer."""
    if request.method == 'POST':
        from_account_id = request.form.get('from_account')
        to_account_id = request.form.get('to_account')
        amount = float(request.form.get('amount'))
        description = request.form.get('description')
        note = request.form.get('note')
        
        if from_account_id and to_account_id and amount > 0:
            # Update account balances
            from_account = db.session.get(Account, int(from_account_id))
            to_account = db.session.get(Account, int(to_account_id))
            
            if from_account and to_account and from_account.balance >= amount:
                from_account.balance -= amount
                to_account.balance += amount
                
                transaction = AccountTransaction(
                    from_account_id=from_account_id,
                    to_account_id=to_account_id,
                    amount=amount,
                    description=description,
                    note=note,
                    transaction_type='Transfer'
                )
                db.session.add(transaction)
                db.session.commit()
                
                audit_log(current_user, 'account.transfer', f'from={from_account.name}, to={to_account.name}, amount={amount}')
                flash('Transfer completed successfully!', 'success')
            else:
                flash('Insufficient balance or invalid accounts!', 'danger')
        else:
            flash('Invalid transfer details!', 'danger')
        
        return redirect(url_for('accounts.transfers'))
    
    accounts = _active_accounts().all()
    return render_template('accounts/add_transfer.html', accounts=accounts)


