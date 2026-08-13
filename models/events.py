from .__base import *  # noqa
from .sales import *  # noqa
from .stock import *  # noqa
from .parties import *  # noqa
from .helpers import (
    _normalize_auto_bill_model,
    _normalize_manual_bill_model,
    _normalize_namespace_model,
    _parse_bill_kind_model,
)

@event.listens_for(db.session, 'before_flush')
def _normalize_bill_identities(session, flush_context, instances):
    # Normalize bill identities before writing any changed/new objects.
    for obj in list(session.new) + list(session.dirty):
        if isinstance(obj, Booking):
            obj.auto_bill_no = _normalize_auto_bill_model(getattr(obj, 'auto_bill_no', None), namespace='BK')
            obj.manual_bill_no = _normalize_manual_bill_model(getattr(obj, 'manual_bill_no', None))
        elif isinstance(obj, Payment):
            obj.auto_bill_no = _normalize_auto_bill_model(getattr(obj, 'auto_bill_no', None), namespace='CP')
            obj.manual_bill_no = _normalize_manual_bill_model(getattr(obj, 'manual_bill_no', None))
        elif isinstance(obj, SupplierPayment):
            obj.auto_bill_no = _normalize_auto_bill_model(getattr(obj, 'auto_bill_no', None), namespace='SP')
            obj.manual_bill_no = _normalize_manual_bill_model(getattr(obj, 'manual_bill_no', None))
        elif isinstance(obj, DirectSale):
            obj.auto_bill_no = _normalize_auto_bill_model(getattr(obj, 'auto_bill_no', None), namespace='SL')
            obj.manual_bill_no = _normalize_manual_bill_model(getattr(obj, 'manual_bill_no', None))
        elif isinstance(obj, MaterialReturn):
            obj.auto_bill_no = _normalize_auto_bill_model(getattr(obj, 'auto_bill_no', None), namespace='RTN')
            obj.manual_bill_no = _normalize_manual_bill_model(getattr(obj, 'manual_bill_no', None))
        elif isinstance(obj, GRN):
            obj.auto_bill_no = _normalize_auto_bill_model(getattr(obj, 'auto_bill_no', None), namespace='GRN')
            obj.manual_bill_no = _normalize_manual_bill_model(getattr(obj, 'manual_bill_no', None))
        elif isinstance(obj, Entry):
            obj.auto_bill_no = _normalize_auto_bill_model(getattr(obj, 'auto_bill_no', None), namespace='EN')
        elif isinstance(obj, PendingBill):
            bill_no = (getattr(obj, 'bill_no', None) or '').strip()
            if bill_no:
                if bool(getattr(obj, 'is_manual', False)):
                    obj.bill_no = _normalize_manual_bill_model(bill_no)
                else:
                    obj.bill_no = _normalize_auto_bill_model(bill_no, namespace='GEN') or _normalize_manual_bill_model(bill_no)
            obj.bill_kind = _parse_bill_kind_model(getattr(obj, 'bill_no', None))
        elif isinstance(obj, Invoice):
            inv_no = (getattr(obj, 'invoice_no', None) or '').strip()
            if inv_no and (not inv_no.upper().startswith('INV-')):
                if bool(getattr(obj, 'is_manual', False)):
                    obj.invoice_no = _normalize_manual_bill_model(inv_no)
                else:
                    obj.invoice_no = _normalize_auto_bill_model(inv_no, namespace='EN') or _normalize_manual_bill_model(inv_no)
        elif isinstance(obj, BillCounter):
            obj.namespace = _normalize_namespace_model(getattr(obj, 'namespace', None))

