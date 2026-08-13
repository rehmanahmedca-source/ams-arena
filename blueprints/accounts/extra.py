"""extra — split from accounts.py."""
from ._common import *  # noqa

def get_next_bill_no(namespace):
    ns = _normalize_namespace(namespace)
    counter = _get_or_create_bill_counter(ns)
    current = _sync_bill_counter_with_db(ns)
    bill_no = _format_auto_bill(ns, current)
    counter.count = current + 1
    db.session.flush()
    return bill_no


def pk_now():
    return datetime.now(PK_TZ).replace(tzinfo=None)


def pk_today():
    return pk_now().date()


@accounts_bp.route('/audit')
@login_required
def audit_trail():
    """Full audit trail across all account-affecting transactions."""
    page = request.args.get('page', 1, type=int)
    per_page = 60
    search = (request.args.get('q') or '').strip()
    type_f = (request.args.get('type') or '').strip()
    account_id_f = request.args.get('account_id', type=int)
    show_voided = request.args.get('show_voided') == '1'
    date_from, date_to_excl = _parse_date_range(default_days=30)

    q = AccountTransaction.query.filter(
        AccountTransaction.date_posted >= date_from,
        AccountTransaction.date_posted < date_to_excl
    )
    if not show_voided:
        q = q.filter(AccountTransaction.is_void == False)
    if search:
        like = f'%{search}%'
        q = q.filter(or_(AccountTransaction.description.ilike(like), AccountTransaction.note.ilike(like)))
    if type_f:
        q = q.filter(AccountTransaction.transaction_type == type_f)
    if account_id_f:
        q = q.filter(or_(AccountTransaction.from_account_id == account_id_f,
                         AccountTransaction.to_account_id == account_id_f))

    total_in = q.with_entities(func.coalesce(func.sum(AccountTransaction.amount), 0)).filter(
        AccountTransaction.to_account_id.isnot(None), AccountTransaction.is_void == False
    ).scalar() or 0
    total_out = q.with_entities(func.coalesce(func.sum(AccountTransaction.amount), 0)).filter(
        AccountTransaction.from_account_id.isnot(None), AccountTransaction.is_void == False
    ).scalar() or 0

    rows = q.order_by(AccountTransaction.date_posted.desc(), AccountTransaction.id.desc()).paginate(page=page, per_page=per_page)
    types = ['Receipt', 'Payment', 'Transfer', 'Supplier Payment', 'Expense', 'Loss', 'Adjustment']
    accounts = _active_accounts().order_by(Account.name.asc()).all()

    return render_template('accounts/audit.html', rows=rows, accounts=accounts, types=types,
                           date_from=date_from, date_to=date_to_excl - timedelta(days=1),
                           search=search, type_f=type_f, account_id_f=account_id_f,
                           show_voided=show_voided, total_in=total_in, total_out=total_out)


