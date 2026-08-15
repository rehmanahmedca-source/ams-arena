from .__base import *  # noqa
from .helpers import *  # noqa

class FbmCashDrawerEntry(db.Model):
    __tablename__ = 'fbm_cash_drawer_entry'
    id = db.Column(db.Integer, primary_key=True)
    entry_type = db.Column(db.String(10), default='out', index=True)  # in | out
    amount = db.Column(db.Float, default=0)
    category = db.Column(db.String(100))
    method = db.Column(db.String(20), default='Cash', index=True)  # Cash | Bank | Check
    note = db.Column(db.String(500))
    source = db.Column(db.String(20), default='manual', index=True)
    date_posted = db.Column(db.DateTime, default=pk_model_now, index=True)
    created_by = db.Column(db.String(80))
    is_void = db.Column(db.Boolean, default=False, index=True)


class FbmCashDrawerCategory(db.Model):
    __tablename__ = 'fbm_cash_drawer_category'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True, index=True)
    created_at = db.Column(db.DateTime, default=pk_model_now, index=True)


class Account(db.Model):
    """Financial accounts for managing cash flow"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    # Legacy/compat column: existing SQLite DBs may require this field (NOT NULL).
    # Keep in sync with `account_type` to support mixed schemas.
    type = db.Column(db.String(50), nullable=False, default='Unknown')
    category = db.Column(db.String(20), nullable=False, default='cash')  # cash or bank
    source_category = db.Column(db.String(100), index=True)
    account_type = db.Column(db.String(50), nullable=False)  # company, supplier, client, personal, etc
    balance = db.Column(db.Float, default=0)
    # Bank details (if category == 'bank')
    bank_name = db.Column(db.String(100))
    account_holder_name = db.Column(db.String(100))
    account_number = db.Column(db.String(50))
    branch_code = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=pk_model_now, index=True)
    note = db.Column(db.String(500))


class AccountCategory(db.Model):
    """Business categories used to group accounts for receive/pay flows."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    note = db.Column(db.String(300))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=pk_model_now, index=True)


class AccountTransaction(db.Model):
    """Transactions between accounts"""
    id = db.Column(db.Integer, primary_key=True)
    from_account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=True)
    to_account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=True)
    amount = db.Column(db.Float, default=0)
    description = db.Column(db.String(200))
    date_posted = db.Column(db.DateTime, default=pk_model_now, index=True)
    is_void = db.Column(db.Boolean, default=False)
    note = db.Column(db.String(500))
    transaction_type = db.Column(db.String(50))  # Transfer, Payment, Receipt, Expense

    from_account = db.relationship('Account', foreign_keys=[from_account_id], backref='outgoing_transactions')
    to_account = db.relationship('Account', foreign_keys=[to_account_id], backref='incoming_transactions')


class CashFlowDifferenceAdjustment(db.Model):
    __tablename__ = 'cash_flow_difference_adjustment'
    id = db.Column(db.Integer, primary_key=True)
    adjustment_date = db.Column(db.Date, nullable=False, index=True)
    # Legacy fields (kept for backward compatibility)
    amount = db.Column(db.Float, default=0)  # Old workflow: user-entered difference
    note = db.Column(db.String(500))  # Old workflow: adjustment note
    # NEW FIELDS: Physical Cash Reconciliation Workflow
    physical_cash_available = db.Column(db.Float)  # NEW: actual cash in drawer (primary input)
    calculated_closing = db.Column(db.Float)  # NEW: system-calculated closing balance
    difference = db.Column(db.Float)  # NEW: calculated_closing - physical_cash_available (auto-computed)
    reason = db.Column(db.String(500))  # NEW: explanation for discrepancy
    # Audit trail fields
    old_physical_cash = db.Column(db.Float)  # Previous physical_cash when edited
    edited_by = db.Column(db.String(80))  # User who last edited
    edited_date = db.Column(db.DateTime)  # Last edit timestamp
    edit_count = db.Column(db.Integer, default=0)  # Number of edits
    # Standard fields
    created_by = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=pk_model_now, index=True)
    updated_at = db.Column(db.DateTime, default=pk_model_now, onupdate=pk_model_now, index=True)
    __table_args__ = (
        UniqueConstraint('adjustment_date', name='uq_cash_flow_difference_adjustment_date'),
    )

    def is_legacy(self):
        """Check if this is a legacy record (old difference-entry workflow)."""
        return self.physical_cash_available is None

    def get_opening_for_next_day(self, calculated_closing):
        """Return the opening balance that should be used for the next day."""
        if self.physical_cash_available is not None:
            # NEW WORKFLOW: Use physical cash as next day opening
            return self.physical_cash_available
        elif self.amount is not None:
            # LEGACY WORKFLOW: Use calculated closing minus difference
            return calculated_closing - self.amount
        else:
            # NO RECONCILIATION: Use calculated closing as-is
            return calculated_closing


class CashFlowCategory(db.Model):
    """User-managed cash-flow categories (Fuel, Food, Loan Received, …)."""
    __tablename__ = 'cash_flow_category'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, index=True)
    direction = db.Column(db.String(10), default='both', index=True)  # in | out | both
    is_active = db.Column(db.Boolean, default=True, index=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=pk_model_now)


class CashFlowSubcategory(db.Model):
    __tablename__ = 'cash_flow_subcategory'
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('cash_flow_category.id'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True, index=True)
    created_at = db.Column(db.DateTime, default=pk_model_now)
    category = db.relationship('CashFlowCategory', backref='subcategories')


class CashFlowParty(db.Model):
    """Reusable names: person, outsider, bank, loan, other."""
    __tablename__ = 'cash_flow_party'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False, index=True)
    party_type = db.Column(db.String(40), default='person', index=True)
    phone = db.Column(db.String(40))
    note = db.Column(db.String(300))
    is_active = db.Column(db.Boolean, default=True, index=True)
    created_at = db.Column(db.DateTime, default=pk_model_now)


class CashFlowEntry(db.Model):
    """Recorded cash in/out that is not a client or supplier payment."""
    __tablename__ = 'cash_flow_entry'
    id = db.Column(db.Integer, primary_key=True)
    direction = db.Column(db.String(10), nullable=False, index=True)  # in | out
    amount = db.Column(db.Float, default=0)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=True, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey('cash_flow_category.id'), nullable=True, index=True)
    subcategory_id = db.Column(db.Integer, db.ForeignKey('cash_flow_subcategory.id'), nullable=True, index=True)
    party_id = db.Column(db.Integer, db.ForeignKey('cash_flow_party.id'), nullable=True, index=True)
    party_name = db.Column(db.String(160), index=True)
    party_type = db.Column(db.String(40), index=True)
    description = db.Column(db.String(200))
    note = db.Column(db.String(500))
    date_posted = db.Column(db.DateTime, default=pk_model_now, index=True)
    created_by = db.Column(db.String(80))
    account_tx_id = db.Column(db.Integer, db.ForeignKey('account_transaction.id'), nullable=True)
    is_void = db.Column(db.Boolean, default=False, index=True)
    created_at = db.Column(db.DateTime, default=pk_model_now)

    account = db.relationship('Account', foreign_keys=[account_id])
    category = db.relationship('CashFlowCategory', foreign_keys=[category_id])
    subcategory = db.relationship('CashFlowSubcategory', foreign_keys=[subcategory_id])
    party = db.relationship('CashFlowParty', foreign_keys=[party_id])


class AccountReconciliation(db.Model):
    """Per-account reconciliation: expected (ledger) vs actual (physical) balance.

    Each reconcile creates an immutable snapshot row.  The balancing entry is
    posted to AccountTransaction as an 'Adjustment' (transparent, auditable)
    and the account balance is moved to the actual value, which then serves as
    the next period's opening balance.
    """
    __tablename__ = 'account_reconciliation'
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False, index=True)
    reconciliation_date = db.Column(db.Date, nullable=False, index=True)
    expected_balance = db.Column(db.Float, default=0)   # ledger/calculated balance
    actual_balance = db.Column(db.Float, default=0)     # physically entered balance
    difference = db.Column(db.Float, default=0)         # actual - expected
    difference_type = db.Column(db.String(20), default='Matched')  # Matched | Loss | Excess
    status = db.Column(db.String(20), default='Reconciled')
    note = db.Column(db.String(500))
    created_by = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=pk_model_now, index=True)
    updated_at = db.Column(db.DateTime, default=pk_model_now, onupdate=pk_model_now, index=True)

    account = db.relationship('Account', foreign_keys=[account_id], backref='reconciliations')


class CashFlowReconciliationAudit(db.Model):
    """Audit trail for all physical cash reconciliation changes."""
    __tablename__ = 'cash_flow_reconciliation_audit'
    id = db.Column(db.Integer, primary_key=True)
    reconciliation_id = db.Column(
        db.Integer,
        db.ForeignKey('cash_flow_difference_adjustment.id'),
        nullable=False,
        index=True
    )
    adjustment_date = db.Column(db.Date, nullable=False, index=True)
    change_type = db.Column(db.String(20), nullable=False)  # 'CREATE', 'EDIT', 'DELETE', 'MIGRATE'
    old_physical_cash = db.Column(db.Float)
    new_physical_cash = db.Column(db.Float)
    old_difference = db.Column(db.Float)
    new_difference = db.Column(db.Float)
    old_reason = db.Column(db.String(500))
    new_reason = db.Column(db.String(500))
    changed_by = db.Column(db.String(80))
    changed_at = db.Column(db.DateTime, default=pk_model_now, index=True)

    reconciliation = db.relationship(
        'CashFlowDifferenceAdjustment',
        backref='audit_trail',
        foreign_keys=[reconciliation_id]
    )

