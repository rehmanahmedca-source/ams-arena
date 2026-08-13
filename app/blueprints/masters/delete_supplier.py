from ._common import *  # noqa

@bp.route('/delete_supplier/<int:id>', methods=['POST'])
@login_required
def delete_supplier(id):
    if not _user_can('can_manage_suppliers'):
        flash('Permission denied', 'danger')
        return redirect(url_for('suppliers'))
    # Soft delete or hard delete logic here. For now, we rely on is_active toggle in edit.
    # Hard delete only if no GRNs attached, otherwise warn.
    s = db.session.get(Supplier, id)
    if s:
        if s.grns:
            flash('Cannot delete supplier with existing GRNs. Deactivate instead.', 'danger')
        else:
            db.session.delete(s)
            db.session.commit()
            flash('Supplier Deleted', 'warning')
    return redirect(url_for('suppliers'))

