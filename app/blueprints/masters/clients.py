from ._common import *  # noqa

@bp.route('/clients')
@login_required
def clients():
    search = request.args.get('search', '').strip()
    category = request.args.get('category', '').strip()
    category_normalized = category.lower()
    page_active = request.args.get('page_active', 1, type=int)
    page_inactive = request.args.get('page_inactive', 1, type=int)

    active_query = Client.query.filter(Client.is_active == True)
    if search:
        active_query = active_query.filter(
            db.or_(Client.name.ilike(f'%{search}%'), Client.code.ilike(f'%{search}%')))
    if category:
        active_query = active_query.filter(func.lower(func.trim(Client.category)) == category_normalized)
    active_pagination = active_query.order_by(Client.name.asc()).paginate(page=page_active, per_page=10)

    inactive_query = Client.query.filter(Client.is_active == False)
    if search:
        inactive_query = inactive_query.filter(
            db.or_(Client.name.ilike(f'%{search}%'), Client.code.ilike(f'%{search}%')))
    if category:
        inactive_query = inactive_query.filter(func.lower(func.trim(Client.category)) == category_normalized)
    inactive_pagination = inactive_query.order_by(Client.name.asc()).paginate(page=page_inactive, per_page=10)

    all_visible_clients = active_pagination.items + inactive_pagination.items
    for c in all_visible_clients:
        c.total_bills = db.session.query(func.count(PendingBill.id)).filter_by(client_code=c.code).scalar() or 0
        c.total_deliveries = db.session.query(func.sum(Entry.qty)).filter_by(client=c.name, type='OUT').scalar() or 0

    active_clients_list = Client.query.filter(Client.is_active == True).order_by(Client.name.asc()).all()
    all_clients_list = Client.query.order_by(Client.name.asc()).all()
    categories = [
        row[0] for row in db.session.query(Client.category).distinct().filter(
            Client.category != None,
            func.trim(Client.category) != ''
        ).order_by(Client.category.asc()).all()
    ]
    for default_cat in ['General', 'Open Khata', 'Walking-Customer', 'Misc']:
        if default_cat not in categories:
            categories.append(default_cat)
    categories = sorted(categories, key=lambda x: str(x).lower())

    return render_template('clients.html',
                           active_pagination=active_pagination,
                           inactive_pagination=inactive_pagination,
                           search=search,
                           category=category,
                           active_clients=active_clients_list,
                           all_clients=all_clients_list,
                           categories=categories)

