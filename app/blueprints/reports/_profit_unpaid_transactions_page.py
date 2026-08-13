"""profit — split from reports.py."""
from ._common import *  # noqa

@bp.route('/unpaid_transactions')
@login_required
def unpaid_transactions_page():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    material = request.args.get('material')
    bill_no = request.args.get('bill_no')
    status = request.args.get('status', 'unpaid')
    include_booking = request.args.get('include_booking', '0')

    query = PendingBill.query.filter(PendingBill.is_void == False)

    if start_date:
        query = query.filter(PendingBill.created_at >= start_date)
    if end_date:
        query = query.filter(PendingBill.created_at <= f"{end_date} 23:59:59")
    if material:
        query = query.filter(PendingBill.reason.ilike(f'%{material}%'))
    if bill_no:
        query = query.filter((PendingBill.bill_no.ilike(f'%{bill_no}%')) | (PendingBill.nimbus_no.ilike(f'%{bill_no}%')))

    if status == 'paid':
        query = query.filter(PendingBill.is_paid == True)
    elif status == 'unpaid':
        query = query.filter(PendingBill.is_paid == False)

    # Hide 0-amount unpaid bills (Booking Deliveries)
    query = query.filter(or_(PendingBill.amount > 0, PendingBill.is_paid == True))

    # Exclude clients who have bookings unless explicitly included
    if include_booking not in ['1', 'true', 'on', 'yes']:
        booked_names = [r[0] for r in db.session.query(Booking.client_name).filter(Booking.is_void == False).distinct().all() if r[0]]
        booked_codes = set()
        if booked_names:
            booked_codes = {c.code for c in Client.query.filter(Client.name.in_(booked_names)).all()}
        if booked_codes:
            query = query.filter(~PendingBill.client_code.in_(booked_codes))
        if booked_names:
            query = query.filter(~PendingBill.client_name.in_(booked_names))

    transactions = query.order_by(PendingBill.id.desc()).all()
    effective_map = _compute_pending_effective_amount_map(transactions)
    for t in transactions:
        t.effective_amount = float(effective_map.get(t.id, float(t.amount or 0)) or 0)

    # For unpaid view, hide rows fully neutralized by cancellation credits.
    if status == 'unpaid':
        transactions = [t for t in transactions if float(getattr(t, 'effective_amount', 0) or 0) > 0]

    materials = Material.query.order_by(Material.name.asc()).all()
    clients = Client.query.filter_by(is_active=True).order_by(Client.name.asc()).all()

    return render_template('unpaid_transactions.html',
                           transactions=transactions,
                           materials=materials,
                           clients=clients,
                           filters={
                               'start_date': start_date,
                               'end_date': end_date,
                               'material': material,
                               'bill_no': bill_no,
                               'status': status,
                               'include_booking': include_booking
                           })

