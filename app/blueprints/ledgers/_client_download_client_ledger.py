"""Client ledger export routes backed by the unified ledger projection."""
from ._common import *  # noqa

import csv
from datetime import datetime
from io import StringIO

from app.services.financial_ledgers import build_client_financial_ledger, filter_ledger_rows


def _client_export_filters():
    return {
        'start_date': (request.args.get('start_date') or '').strip(),
        'end_date': (request.args.get('end_date') or '').strip(),
        'type_filter': (request.args.get('type') or request.args.get('transaction_type') or '').strip(),
        'query': (request.args.get('q') or request.args.get('search') or '').strip(),
        'amount_min': (request.args.get('amount_min') or '').strip(),
        'amount_max': (request.args.get('amount_max') or '').strip(),
        'account_filter': (request.args.get('account') or '').strip(),
        'status_filter': (request.args.get('status') or '').strip(),
    }


@bp.route('/download_client_ledger/<int:id>')
@bp.route('/export_client_ledger/<int:id>')
@login_required
def download_client_ledger(id):
    client = Client.query.get_or_404(id)
    filters = _client_export_filters()
    ledger = build_client_financial_ledger(client)
    rows = filter_ledger_rows(ledger['rows'], **filters)
    action = (request.args.get('action') or 'download').strip().lower()
    if action != 'print':
        output = StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(['Date', 'Type', 'Reference', 'Description', 'Debit', 'Credit', 'Balance', 'Account', 'Notes'])
        for row in rows:
            writer.writerow([
                row['date'].strftime('%Y-%m-%d %H:%M') if row.get('date') and row['date'] != datetime.min else '',
                row.get('type', ''), row.get('reference', ''), row.get('description', ''),
                f"{row.get('debit', 0):.2f}", f"{row.get('credit', 0):.2f}",
                f"{row.get('balance', 0):.2f}", row.get('account', ''), row.get('note', ''),
            ])
        output.write(f"\nTOTAL DEBIT,{ledger['total_debit']:.2f}\nTOTAL CREDIT,{ledger['total_credit']:.2f}\nCLOSING BALANCE,{ledger['closing_balance']:.2f}\n")
        response = Response(output.getvalue(), mimetype='text/csv; charset=utf-8')
        response.headers['Content-Disposition'] = 'attachment; filename=client-ledger.csv'
        return response

    rendered = render_template(
        'financial_ledger_print.html',
        entity=client,
        entity_type='client',
        rows=rows,
        ledger=ledger,
        generated_at=pk_now(),
        auto_print=True,
    )
    response = make_response(rendered)
    response.headers['Content-Disposition'] = 'inline; filename=client-ledger.html'
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    return response
