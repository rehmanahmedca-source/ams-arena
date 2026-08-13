import os
import sys
from datetime import date

sys.path.insert(0, os.getcwd())

import cash_flow_audit as c
from main import app
from models import Payment, DirectSale, SupplierPayment, AccountTransaction
from sqlalchemy import func, or_


def print_day_detail(d):
    print('DATE', d)
    print('CASH_FLOW', c.cash_flow_day(d))
    pay = Payment.query.filter(
        Payment.is_void == False,
        func.date(Payment.date_posted) == d,
        or_(
            func.lower(func.trim(func.coalesce(Payment.method, ''))) == 'cash',
            func.lower(func.trim(func.coalesce(Payment.method, ''))) == 'cash sale',
        ),
    ).all()
\ \ \ \ print\('PAYMENTS',\ \[\(p\.id,\ p\.amount,\ p\.method,\ p\.date_posted\)\ for\ p\ in\ pay]\)\r\n\ \ \ \ print\('PAYMENT_SUM',\ sum\(float\(p\.amount\ or\ 0\)\ for\ p\ in\ pay\)\)\r\n\ \ \ \ print\('PAYMENTS_GT0',\ \[\(p\.id,\ p\.amount,\ p\.method,\ p\.date_posted\)\ for\ p\ in\ pay\ if\ float\(p\.amount\ or\ 0\)\ >\ 0]\)\r\n\ \ \ \ sales\ =\ DirectSale\.query\.filter\(\r\n\ \ \ \ \ \ \ \ DirectSale\.is_void\ ==\ False,\r\n\ \ \ \ \ \ \ \ func\.date\(DirectSale\.date_posted\)\ ==\ d,\r\n\ \ \ \ \ \ \ \ or_\(\r\n\ \ \ \ \ \ \ \ \ \ \ \ func\.lower\(func\.trim\(func\.coalesce\(DirectSale\.category,\ ''\)\)\)\ ==\ 'cash',\r\n\ \ \ \ \ \ \ \ \ \ \ \ func\.lower\(func\.trim\(func\.coalesce\(DirectSale\.category,\ ''\)\)\)\ ==\ 'cash\ sale',\r\n\ \ \ \ \ \ \ \ \ \ \ \ func\.lower\(func\.trim\(func\.coalesce\(DirectSale\.payment_method,\ ''\)\)\)\ ==\ 'cash',\r\n\ \ \ \ \ \ \ \ \ \ \ \ func\.lower\(func\.trim\(func\.coalesce\(DirectSale\.payment_method,\ ''\)\)\)\ ==\ 'cash\ sale',\r\n\ \ \ \ \ \ \ \ \),\r\n\ \ \ \ \)\.all\(\)\r\n\ \ \ \ print\('SALES',\ \[\(s\.id,\ s\.paid_amount,\ s\.category,\ s\.payment_method,\ s\.date_posted\)\ for\ s\ in\ sales]\)\r\n\ \ \ \ print\('SALES_GT0',\ \[\(s\.id,\ s\.paid_amount,\ s\.category,\ s\.payment_method,\ s\.date_posted\)\ for\ s\ in\ sales\ if\ float\(s\.paid_amount\ or\ 0\)\ >\ 0]\)\r\n\ \ \ \ print\('SALES_SUM',\ sum\(float\(s\.paid_amount\ or\ 0\)\ for\ s\ in\ sales\)\)
    sp = SupplierPayment.query.filter(
        SupplierPayment.is_void == False,
        func.date(SupplierPayment.date_posted) == d,
    ).all()
    print('SUPPLIER', [(s.id, s.amount, s.method, s.date_posted) for s in sp])
    txs = AccountTransaction.query.filter(
        AccountTransaction.is_void == False,
        func.date(AccountTransaction.date_posted) == d,
        AccountTransaction.transaction_type.in_(['Expense', 'Payment', 'Transfer']),
    ).all()
    print('TXS', [(tx.id, tx.transaction_type, tx.amount, tx.from_account_id, tx.to_account_id, tx.description, tx.note) for tx in txs])
    print('---')


def main():
    with app.app_context():
        for d in [date(2026, 5, 20), date(2026, 5, 21), date(2026, 5, 23), date(2026, 5, 24), date(2026, 5, 29), date(2026, 5, 30)]:
            print_day_detail(d)


if __name__ == '__main__':
    main()
