# AMS Heavy Audit + Smoke Report

DB wiped and rebuilt. Pages OK: **70**. Failures: **0**.

## Checks
- Login Admin / Admin@fbm12345
- Masters, cash account, GRN 200
- Booking paid (receive account) + unpaid booking (no account required)
- Credit sale vs Booked delivery (rates in form must stay amount=0)
- Cash sale, payment, normal return
- Clearance statement + ledgers/reports
- Hard delete credit sale restores stock
- Hard delete GRN

## Notes
- login Admin ok
- booking flashes: ['Booking added successfully â€” Pending amount: 24000.0 — by Admin']
- unpaid booking flashes: ['Booking added successfully â€” Pending amount: 6000.0 — by Admin']
- credit flashes: ['Direct sale added successfully â€” Invoice: MB NO.CR-AUDIT-1 — by Admin']
- booked delivery flashes: ['Direct sale added successfully — by Admin']
- SALE id=1 code=AUD-001 cat=Credit Customer amt=15000.0 paid=0.0 inv=1 items=[('OPC 53', 12.0, 1250.0)]
- SALE id=2 code=AUD-001 cat=Cash amt=5200.0 paid=5200.0 inv=None items=[('OPC 53', 4.0, 1300.0)]
- SALE id=3 code=AUD-001 cat=Booking Delivery amt=0.0 paid=0.0 inv=None items=[('OPC 53', 10.0, 0.0)]
- BOOKINGS=[(1, 36000.0, 12000.0, 1), (2, 6000.0, 0.0, None)]
- stock=175.0
- ACC_TX=[('Receipt', 12000.0, 'Booking paid now from Audit Client (SB-BK-1000)'), ('Receipt', 5200.0, 'Sale receipt from Audit Client (SB-SL-1001)'), ('Receipt', 3000.0, 'Client payment received from Audit Client (SB-CP-1')]
- ENTRIES=[('IN', 200.0, None, None), ('OUT', 12.0, 'Credit Customer', 'Direct Sale'), ('OUT', 4.0, 'Cash', 'Direct Sale'), ('IN', 1.0, 'Material Return', 'Material Return'), ('OUT', 10.0, 'Booking Delivery', 'Direct Sale')]
- PENDING=[('SB-BK-1000', 19750.0, 'Booking: OPC 53', False), ('SB-BK-1001', 6000.0, 'Booking: OPC 53', False), ('MB NO.CR-AUDIT-1', 15000.0, 'Direct Sale (Credit Customer): OPC 53', False), ('SB-SL-1001', 0.0, 'Direct Sale (Cash): OPC 53', True)]
- after delete credit: sale=None stock=187.0
- after GRN delete: grn=<GRN 1>
- audit_rows_by_Admin=15

## Page failures
- none

## Problems
- None. Heavy smoke passed.
