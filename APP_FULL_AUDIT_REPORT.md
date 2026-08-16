# AMS Full Application Audit Report

Date: 2026-08-16

## Scope

- Python compilation and import/bootstrap checks
- Route registration
- Full automated regression suite
- Sales transaction smoke flows
- Stock, pending-bill, accounting and ledger consistency
- Duplicate-submit protection
- Global polling and modal layering
- Static scan for TODOs, local-only URLs and broad exception handling

## Results

### Automated tests

| Check | Result |
|---|---:|
| Full pytest suite | **92 passed** |
| Sales/application smoke tests | **8 passed** |
| Python compilation | **Passed** |
| Git whitespace check | **Passed** |
| Application bootstrap/import | **Passed** |
| Registered routes | **99 routes** |

The sales smoke coverage includes cash, credit/due, partial-payment, booked,
mixed booked/due, material returns, booked returns, payments, duplicate-submit
idempotency, stock reconciliation, pending bills, accounting entries, voids and
ledger consistency.

## Confirmed working areas

- Direct-sale save uses one finalized transaction path.
- Stock rebuild uses grouped aggregate queries rather than one query per material.
- Duplicate sale requests are rejected/replayed using idempotency keys.
- Save controls and progress state are released after failures.
- Financial-summary requests are scoped to the requested client.
- Background reminder polling is visibility-aware and cross-tab coordinated.
- Global progress/result/reminder dialogs are promoted above in-page Bootstrap
  modals.
- Python modules compile successfully and the application creates its route map.

## Findings

### P1/P2 defects

No P1 or P2 defects were reproduced by the available automated and smoke tests.

### Low-priority observations

1. `app/services/wipe.py` contains a TODO for additional journal snapshot and
   recalculation work. This is maintenance scope, not a failing transaction path.
2. `blueprints/module_template.py` contains localhost URLs in documentation
   comments only; no production browser request uses localhost.
3. The codebase has deliberate defensive `except Exception` blocks around legacy
   data, optional exports and recovery paths. They should be reviewed gradually,
   but changing them globally would risk breaking import/recovery behavior.
4. A real browser/network test is still useful for visual confirmation of modal
   stacking, rapid double-click timing and interrupted requests. These are not
   available through the current headless test suite.

## Changes made during this audit

`templates/layout.html` was strengthened so the three global dialogs use
`z-index: 2600 !important`, their active backdrops use a dedicated
`ams-top-modal-backdrop` class at z-index 2590, and the correct active backdrop
is promoted instead of relying solely on DOM order.

## Conclusion

The application passed the complete available automated regression suite and the
sales-focused smoke suite. No additional functional defect was found that could
be safely fixed based on the current evidence. Remaining observations are
contained, low-risk maintenance items rather than confirmed production failures.
