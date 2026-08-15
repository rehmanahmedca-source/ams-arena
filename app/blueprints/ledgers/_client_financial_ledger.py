"""Unified client financial ledger page."""
from ._common import *  # noqa

from app.services.financial_ledgers import build_client_financial_ledger, filter_ledger_rows


def _ledger_filter_args():
    return {
        "start_date": (request.args.get("start_date") or request.args.get("date_from") or "").strip(),
        "end_date": (request.args.get("end_date") or request.args.get("date_to") or "").strip(),
        "type_filter": (request.args.get("type") or request.args.get("transaction_type") or "").strip(),
        "query": (request.args.get("q") or request.args.get("search") or "").strip(),
        "amount_min": (request.args.get("amount_min") or "").strip(),
        "amount_max": (request.args.get("amount_max") or "").strip(),
        "account_filter": (request.args.get("account") or "").strip(),
        "status_filter": (request.args.get("status") or "").strip(),
    }


def _page_ledger(ledger, filters):
    selected = filter_ledger_rows(ledger["rows"], **filters)
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    per_page = min(max(request.args.get("per_page", 25, type=int) or 25, 10), 100)
    total = len(selected)
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    start = (page - 1) * per_page
    visible = selected[start:start + per_page]
    closing = visible[-1]["balance"] if visible else ledger["closing_balance"]
    return visible, page, per_page, total, pages, closing


@bp.route('/ledger/<int:client_id>')
@login_required
def financial_ledger(client_id):
    client = Client.query.get_or_404(client_id)
    filters = _ledger_filter_args()
    ledger = build_client_financial_ledger(client)
    rows, page, per_page, total, pages, filtered_closing = _page_ledger(ledger, filters)
    clients = Client.query.filter(Client.is_active == True).order_by(Client.name.asc(), Client.id.asc()).all()
    return render_template(
        'financial_ledger.html',
        entity=client,
        entity_type='client',
        ledger=ledger,
        rows=rows,
        all_rows=ledger['rows'],
        obligations=ledger.get('obligations', []),
        filters=filters,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=pages,
        filtered_closing=filtered_closing,
        selector_entities=clients,
        current_payable=max(0.0, float(ledger['closing_balance'] or 0)),
        back_url=url_for('clients'),
        opening_url=url_for('client_opening_balance', id=client.id),
        today_date=pk_today().strftime('%Y-%m-%d'),
    )
