# INC-1002 — Orders being rejected for SKU-300

**Severity:** Sev-3
**Status:** Closed — working as intended

## Symptom
Support flagged a spike in failed orders for SKU-300, all failing with an
"insufficient stock" error before any payment was attempted.

## Investigation
Confirmed SKU-300 has had zero available stock for the affected period.
`InventoryClient.reserve_stock()` correctly rejects the reservation before
payment is attempted, per the functional requirement that inventory must be
reserved before a customer is charged.

## Resolution
Not a defect. This is the system behaving exactly as designed —
customers are not charged for out-of-stock items, and the failure happens
at the reservation step rather than after a charge. Closed with no code
change. Escalated to the Inventory team to investigate why SKU-300 has been
out of stock, which is outside OrderFlow's scope.
