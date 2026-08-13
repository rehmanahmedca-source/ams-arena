from ._common import *  # noqa

@bp.route('/delete_client/<int:id>', methods=['POST'])
@login_required
def delete_client(id):
    if not _user_can('can_manage_clients'):
        flash('Permission denied', 'danger')
        return redirect(url_for('clients'))
    c = db.session.get(Client, id)
    if c:
        c.is_active = False
        db.session.commit()
        flash('Client suspended', 'warning')
    return redirect(url_for('clients'))

