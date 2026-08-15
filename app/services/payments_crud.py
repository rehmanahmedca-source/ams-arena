"""Shared Accounts payment CRUD + reconciliation business logic.

Every Accounts payment form (create AND edit) funnels through the helpers in
this module so validation, amount handling, account/supplier/client checks,
accounting sync, pending-bill application and audit logging are implemented
exactly once.  The UI never writes balances directly; it only posts form data
and this module applies the full dependency chain atomically.

All financial values are normalised through :func:`_money` (half-up rounding to
2 decimal places) to avoid floating-point drift.
"""
from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime

from sqlalchemy import func

from models import (
    db,
    Account,
    AccountReconciliation,
    AccountTransaction,
    Client,
    Payment,
    Supplier,
    SupplierPayment,
    WaiveOff,
)
from utils.audit import audit_log

logger = logging.getLogger(__name__)

_MONEY_Q = Decimal("0.01")
_EPS = 0.0001


def _money(value) -> float:
    """Round a value to 2 decimal places using half-up (never raw float)."""
    try:
        d = Decimal(str(value if value is not None else 0))
    except Exception:
        d = Decimal("0")
    d = d.quantize(_MONEY_Q, rounding=ROUND_HALF_UP)
    if d == Decimal("-0.00"):
        d = Decimal("0.00")
    return float(d)


def _actor(user):
    if user is None:
        return None
    return getattr(user, "username", None) or None


# --------------------------------------------------------------------------- #
# Selector helpers (active-only)
# --------------------------------------------------------------------------- #
def active_clients():
    """Clients that may be selected for NEW transactions."""
    return Client.query.filter_by(is_active=True).order_by(Client.name.asc()).all()


def active_suppliers():
    """Suppliers that may be selected for NEW transactions."""
    return Supplier.query.filter_by(is_active=True).order_by(Supplier.name.asc()).all()


def active_cash_bank_accounts():
    """Cash/bank accounts that may receive/send money."""
    return (
        Account.query.filter(func.coalesce(Account.is_active, True) == True)
        .filter(func.lower(func.trim(Account.category)).in_(("cash", "bank")))
        .order_by(Account.name.asc())
        .all()
    )


def _expected_account_category(method: str):
    m = (method or "").strip().lower()
    if m in ("cash", "cash sale"):
        return "cash"
    if m in ("bank", "bank transfer", "check", "cheque", "card", "online"):
        return "bank"
    return None


def _validate_account_for_method(account, method: str):
    if not account:
        raise ValueError("Please select a valid account.")
    if getattr(account, "is_active", True) is False:
        raise ValueError("The selected account is deactivated and cannot be used for new transactions.")
    expected = _expected_account_category(method)
    if expected and (account.category or "").strip().lower() != expected:
        raise ValueError(f"The selected account must be a {expected} account for method '{method}'.")


# --------------------------------------------------------------------------- #
# Client payments
# --------------------------------------------------------------------------- #
def save_client_payment(*, payment_id=None, client_name="", client_code="", amount=0, discount=0,
                        discount_reason="", method="Cash", payment_account_id=None,
                        bank_name="", account_name="", account_no="",
                        manual_bill_no="", date_posted=None, note="", actor=None):
    """Create or update a client payment. Returns (payment, created: bool)."""
    from app.services.accounting import _sync_payment_accounting
    from app.services.billing import normalize_manual_bill, find_bill_conflict
    from app.services.time_money import resolve_posted_datetime
    from app.services.void_rebuild import rebuild_pending_bills
    from app.services.waive import _sync_payment_waive_off
    from app.services.lookups import get_client_by_input
    from app.services.billing import get_next_bill_no, AUTO_BILL_NAMESPACES

    amount = _money(amount)
    discount = _money(discount)
    if amount < 0:
        raise ValueError("Amount cannot be negative.")
    if discount < 0:
        raise ValueError("Discount cannot be negative.")
    if (amount + discount) <= 0:
        raise ValueError("Amount and discount cannot both be zero.")

    method = (method or "Cash").strip()
    expected = _expected_account_category(method)

    # Resolve account first so account_name/account_no mirror the selected account.
    account = None
    if payment_account_id:
        try:
            account = db.session.get(Account, int(payment_account_id))
        except (TypeError, ValueError):
            account = None
    if amount > 0 and expected in ("cash", "bank") and not account:
        raise ValueError(f"Select a {expected} account to post this payment into Accounts.")
    if account:
        _validate_account_for_method(account, method)
        bank_name = account.bank_name or ""
        account_name = account.account_holder_name or account.name or ""
        account_no = account.account_number or ""
        payment_account_id = account.id
    else:
        payment_account_id = None

    manual_bill_no = normalize_manual_bill(manual_bill_no) if (manual_bill_no or "").strip() else ""
    if manual_bill_no:
        conflict = find_bill_conflict(manual_bill_no)
        if conflict and not (payment_id and conflict[0] == "Payment" and conflict[1] == payment_id):
            raise ValueError(f"Manual bill '{manual_bill_no}' already exists in {conflict[0]} #{conflict[1]}.")

    if payment_id:
        payment = db.session.get(Payment, int(payment_id))
        if payment is None:
            raise ValueError("Payment not found.")
        if payment.is_void:
            raise ValueError("This payment is deleted. Restore it before editing.")
        created = False
        old = _client_payment_snapshot(payment)
        old_client_obj = get_client_by_input(payment.client_name or "")
    else:
        payment = Payment()
        created = True
        old = None
        old_client_obj = None

    # Resolve client (active-only for new/changed selections; preserve historical
    # client if it is unchanged and now suspended).
    client_obj = None
    search_input = (client_code or "").strip() or (client_name or "").strip()
    if search_input:
        client_obj = get_client_by_input(search_input)
    if client_obj is None and old_client_obj is not None and (client_name or "").strip().lower() == (payment.client_name or "").strip().lower():
        client_obj = old_client_obj
    if client_obj is None:
        raise ValueError("Client not found. Select a valid client from the search list.")
    if getattr(client_obj, "is_active", True) is False and client_obj.id != (old_client_obj.id if old_client_obj else None):
        raise ValueError("The selected client is suspended and cannot be used for new transactions.")

    posted = resolve_posted_datetime(date_posted, fallback_dt=(payment.date_posted if not created else None))

    payment.client_name = client_obj.name
    payment.amount = amount
    payment.discount = discount
    payment.discount_reason = (discount_reason or "").strip() if discount > 0 else ""
    payment.method = method
    payment.payment_account_id = payment_account_id
    payment.bank_name = bank_name or ""
    payment.account_name = account_name or ""
    payment.account_no = account_no or ""
    payment.manual_bill_no = manual_bill_no or ""
    payment.date_posted = posted
    payment.note = (note or "").strip()
    payment.is_void = False

    if created:
        payment.auto_bill_no = get_next_bill_no(AUTO_BILL_NAMESPACES["PAYMENT"])
        db.session.add(payment)
        db.session.flush()

    _sync_payment_waive_off(payment)
    _sync_payment_accounting(payment)

    # Rebuild pending bills for both the previous and the new client so the
    # settlement replay reflects the edit (idempotent — rebuild is authoritative).
    for cid in {old_client_obj.id if old_client_obj else None, client_obj.id}:
        if cid:
            try:
                rebuild_pending_bills(client_id=cid)
            except Exception:
                logger.exception("rebuild_pending_bills failed for client %s", cid)

    db.session.flush()

    if created:
        audit_log(actor, "account.payment.create",
                  f"id={payment.id}, client={client_obj.name}, account={account_name or '-'}, "
                  f"amount={amount:.2f}, discount={discount:.2f}, method={method}, bill={manual_bill_no or payment.auto_bill_no}")
    else:
        audit_log(actor, "account.payment.edit",
                  f"id={payment.id}, client_before={old['client_name']}, client_after={client_obj.name}, "
                  f"amount_before={old['amount']:.2f}, amount_after={amount:.2f}, "
                  f"account_before={old['account_name']}, account_after={account_name or '-'}, "
                  f"method={method}, bill={manual_bill_no or payment.auto_bill_no}")
    return payment, created


def delete_client_payment(payment, actor=None) -> bool:
    """Soft-delete (void) a client payment, reversing all accounting effects."""
    if payment is None:
        raise ValueError("Payment not found.")
    if payment.is_void:
        return False
    from app.services.void_rebuild import _set_payment_void_state, rebuild_pending_bills
    from app.services.lookups import get_client_by_input

    before = _client_payment_snapshot(payment)
    ok = _set_payment_void_state(payment, True)
    if not ok:
        return False
    client = get_client_by_input(payment.client_name or "")
    if client:
        rebuild_pending_bills(client_id=client.id)
    audit_log(actor, "account.payment.delete",
              f"id={payment.id}, client={before['client_name']}, amount={before['amount']:.2f}, "
              f"account={before['account_name']}")
    return True


def restore_client_payment(payment, actor=None) -> bool:
    """Restore a voided client payment and re-apply its accounting effects."""
    if payment is None:
        raise ValueError("Payment not found.")
    if not payment.is_void:
        return False
    from app.services.void_rebuild import _set_payment_void_state, rebuild_pending_bills
    from app.services.lookups import get_client_by_input

    ok = _set_payment_void_state(payment, False)
    if not ok:
        return False
    client = get_client_by_input(payment.client_name or "")
    if client:
        rebuild_pending_bills(client_id=client.id)
    audit_log(actor, "account.payment.restore",
              f"id={payment.id}, client={payment.client_name or ''}, amount={(payment.amount or 0):.2f}")
    return True


def _client_payment_snapshot(payment):
    return {
        "client_name": payment.client_name or "",
        "amount": _money(payment.amount),
        "account_name": payment.account_name or "",
        "payment_account_id": payment.payment_account_id,
        "method": payment.method or "",
    }


# --------------------------------------------------------------------------- #
# Supplier payments
# --------------------------------------------------------------------------- #
def save_supplier_payment(*, payment_id=None, supplier_id=None, amount=0, method="Cash",
                          payment_account_id=None, bank_name="", account_name="",
                          account_no="", manual_bill_no="", date_posted=None, note="",
                          actor=None):
    """Create or update a supplier payment. Returns (payment, created: bool)."""
    from app.services.accounting import _sync_supplier_payment_accounting
    from app.services.billing import normalize_manual_bill, find_bill_conflict, get_next_bill_no, AUTO_BILL_NAMESPACES
    from app.services.time_money import resolve_posted_datetime

    amount = _money(amount)
    if amount <= 0:
        raise ValueError("Payment amount must be greater than zero.")

    method = (method or "Cash").strip()
    expected = _expected_account_category(method)

    # Load the existing record (if editing) before validation so balance checks
    # can account for the old payment already reflected in the account balance.
    if payment_id:
        payment = db.session.get(SupplierPayment, int(payment_id))
        if payment is None:
            raise ValueError("Supplier payment not found.")
        if payment.is_void:
            raise ValueError("This supplier payment is deleted. Restore it before editing.")
        created = False
        old = _supplier_payment_snapshot(payment)
        old_account_id = old["payment_account_id"]
        old_amount = old["amount"]
    else:
        payment = SupplierPayment()
        created = True
        old = None
        old_account_id = None
        old_amount = 0.0

    account = None
    if payment_account_id:
        try:
            account = db.session.get(Account, int(payment_account_id))
        except (TypeError, ValueError):
            account = None
    if expected in ("cash", "bank") and not account:
        raise ValueError(f"Select a {expected} account to post this supplier payment from.")
    if account:
        _validate_account_for_method(account, method)
        bank_name = account.bank_name or ""
        account_name = account.account_holder_name or account.name or ""
        account_no = account.account_number or ""
        payment_account_id = account.id
        # When editing and keeping the same account, the current balance already
        # includes the old payment, so allow up to balance + old amount.
        available = _money(account.balance)
        if old_account_id == account.id:
            available += old_amount
        if available + _EPS < amount:
            raise ValueError("Insufficient balance in the selected account.")
    else:
        payment_account_id = None

    manual_bill_no = normalize_manual_bill(manual_bill_no) if (manual_bill_no or "").strip() else ""
    if manual_bill_no:
        conflict = find_bill_conflict(manual_bill_no)
        if conflict and not (payment_id and conflict[0] == "SupplierPayment" and conflict[1] == payment_id):
            raise ValueError(f"Manual bill '{manual_bill_no}' already exists in {conflict[0]} #{conflict[1]}.")

    supplier = None
    if supplier_id:
        try:
            supplier = db.session.get(Supplier, int(supplier_id))
        except (TypeError, ValueError):
            supplier = None
    if supplier is None and payment_id and payment.supplier_id:
        supplier = db.session.get(Supplier, payment.supplier_id)
    if supplier is None:
        raise ValueError("Supplier not found. Select a valid supplier.")
    if getattr(supplier, "is_active", True) is False:
        # Keep the original supplier when editing a historical record; only
        # block selecting a *different* suspended supplier for a new/changed entry.
        same_as_before = bool(old and supplier.id == old["supplier_id"])
        if not same_as_before:
            raise ValueError("The selected supplier is suspended and cannot be used for new transactions.")

    posted = resolve_posted_datetime(date_posted, fallback_dt=(payment.date_posted if not created else None))

    payment.supplier_id = supplier.id
    payment.amount = amount
    payment.method = method
    payment.payment_account_id = payment_account_id
    payment.bank_name = bank_name or ""
    payment.account_name = account_name or ""
    payment.account_no = account_no or ""
    payment.manual_bill_no = manual_bill_no or ""
    payment.date_posted = posted
    payment.note = (note or "").strip()
    payment.is_void = False

    if created:
        payment.auto_bill_no = get_next_bill_no(AUTO_BILL_NAMESPACES["SUPPLIER_PAYMENT"])
        db.session.add(payment)
        db.session.flush()

    _sync_supplier_payment_accounting(payment)
    db.session.flush()

    if created:
        audit_log(actor, "account.supplier_payment.create",
                  f"id={payment.id}, supplier={supplier.name}, account={account_name or '-'}, "
                  f"amount={amount:.2f}, method={method}, bill={manual_bill_no or payment.auto_bill_no}")
    else:
        audit_log(actor, "account.supplier_payment.edit",
                  f"id={payment.id}, supplier_before={old['supplier_name']}, supplier_after={supplier.name}, "
                  f"amount_before={old['amount']:.2f}, amount_after={amount:.2f}, "
                  f"account_before={old['account_name']}, account_after={account_name or '-'}, "
                  f"method={method}, bill={manual_bill_no or payment.auto_bill_no}")
    return payment, created


def delete_supplier_payment(payment, actor=None) -> bool:
    """Soft-delete (void) a supplier payment, reversing its accounting effects."""
    if payment is None:
        raise ValueError("Supplier payment not found.")
    if payment.is_void:
        return False
    from app.services.accounting import _sync_supplier_payment_accounting

    before = _supplier_payment_snapshot(payment)
    payment.is_void = True
    _sync_supplier_payment_accounting(payment)
    audit_log(actor, "account.supplier_payment.delete",
              f"id={payment.id}, supplier={before['supplier_name']}, amount={before['amount']:.2f}, "
              f"account={before['account_name']}")
    return True


def restore_supplier_payment(payment, actor=None) -> bool:
    """Restore a voided supplier payment and re-apply its accounting effects."""
    if payment is None:
        raise ValueError("Supplier payment not found.")
    if not payment.is_void:
        return False
    from app.services.accounting import _sync_supplier_payment_accounting

    payment.is_void = False
    _sync_supplier_payment_accounting(payment)
    audit_log(actor, "account.supplier_payment.restore",
              f"id={payment.id}, supplier={payment.supplier_id}, amount={(payment.amount or 0):.2f}")
    return True


def _supplier_payment_snapshot(payment):
    supplier_name = ""
    try:
        s = db.session.get(Supplier, payment.supplier_id)
        supplier_name = s.name if s else ""
    except Exception:
        supplier_name = ""
    return {
        "supplier_id": payment.supplier_id,
        "supplier_name": supplier_name,
        "amount": _money(payment.amount),
        "account_name": payment.account_name or "",
        "payment_account_id": payment.payment_account_id,
        "method": payment.method or "",
    }


# --------------------------------------------------------------------------- #
# Account reconciliation
# --------------------------------------------------------------------------- #
def ledger_balance(account_id) -> float:
    """Calculated/expected balance = net effect of all non-void transactions."""
    rows = AccountTransaction.query.filter(
        AccountTransaction.is_void == False,
        (AccountTransaction.from_account_id == account_id) | (AccountTransaction.to_account_id == account_id),
    ).all()
    bal = Decimal("0")
    for tx in rows:
        amt = Decimal(str(tx.amount or 0))
        if tx.to_account_id == account_id:
            bal += amt
        if tx.from_account_id == account_id:
            bal -= amt
    return float(bal.quantize(_MONEY_Q, rounding=ROUND_HALF_UP))


def reconcile_account(*, account_id, actual_balance, reconciliation_date=None, note="", actor=None):
    """Reconcile one account: post a transparent Adjustment for the difference.

    difference = actual - expected.
    - difference == 0  -> Matched (no adjustment)
    - difference  < 0  -> Loss / shortage   (debit the account)
    - difference  > 0  -> Excess / profit   (credit the account)

    Returns the new AccountReconciliation row.
    """
    from app.services.time_money import pk_now

    account = db.session.get(Account, int(account_id)) if account_id else None
    if account is None:
        raise ValueError("Account not found.")

    actual = _money(actual_balance)
    expected = ledger_balance(account.id)
    difference = _money(actual - expected)

    if abs(difference) < 0.005:
        diff_type = "Matched"
    elif difference < 0:
        diff_type = "Loss"
    else:
        diff_type = "Excess"

    rec_date = reconciliation_date or pk_now().date()

    # Transparent adjustment transaction (never mutate underlying history).
    if diff_type != "Matched":
        marker = f"[RECON:ACTUAL:{account.id}]"
        if difference < 0:
            tx = AccountTransaction(
                from_account_id=account.id, to_account_id=None,
                amount=abs(difference),
                description=f"Reconciliation shortage ({account.name})",
                note=f"{marker} actual={actual:.2f}, expected={expected:.2f}, diff={difference:.2f}",
                transaction_type="Adjustment", date_posted=pk_now(),
            )
        else:
            tx = AccountTransaction(
                from_account_id=None, to_account_id=account.id,
                amount=abs(difference),
                description=f"Reconciliation excess ({account.name})",
                note=f"{marker} actual={actual:.2f}, expected={expected:.2f}, diff={difference:.2f}",
                transaction_type="Adjustment", date_posted=pk_now(),
            )
        db.session.add(tx)
    # Move the account balance to the physically verified value so it carries
    # forward as the next period's opening balance.
    account.balance = actual

    rec = AccountReconciliation(
        account_id=account.id,
        reconciliation_date=rec_date,
        expected_balance=expected,
        actual_balance=actual,
        difference=difference,
        difference_type=diff_type,
        status="Reconciled",
        note=(note or "").strip() or None,
        created_by=_actor(actor),
    )
    db.session.add(rec)
    db.session.flush()

    audit_log(actor, "account.reconcile",
              f"id={account.id}, name={account.name}, expected={expected:.2f}, actual={actual:.2f}, "
              f"difference={difference:.2f}, type={diff_type}, date={rec_date}")
    return rec
