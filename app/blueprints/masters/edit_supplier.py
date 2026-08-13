from ._common import *  # noqa

@bp.route('/edit_supplier/<int:id>', methods=['POST'])
@login_required
def edit_supplier(id):
    s = db.session.get(Supplier, id)
    if s:
        s.name = request.form.get('name', '').strip()
        s.phone = request.form.get('phone', '')
        s.address = request.form.get('address', '')
        s.opening_balance = _to_float_or_zero(request.form.get('opening_balance', s.opening_balance))
        s.opening_balance_date = _resolve_opening_balance_date(
            request.form.get('opening_balance_date'),
            fallback_dt=(s.opening_balance_date or s.created_at)
        )
        s.is_active = 'is_active' in request.form
        db.session.commit()
        flash('Supplier Updated', 'success')
    return redirect(url_for('suppliers'))

