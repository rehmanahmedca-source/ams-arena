"""client — split from ledgers.py."""
from ._common import *  # noqa

@bp.route('/client_toggle_active/<int:client_id>', methods=['POST'])
@login_required
def client_toggle_active(client_id):
    client = db.session.get(Client, client_id)
    if not client:
        flash('Client not found', 'danger')
        return redirect(url_for('clients'))
    client.is_active = not client.is_active
    db.session.commit()
    if client.is_active:
        flash('Client reactivated. Deliveries are allowed.', 'success')
    else:
        flash('Client suspended. Deliveries are blocked.', 'warning')
    return redirect(request.referrer or url_for('clients'))

