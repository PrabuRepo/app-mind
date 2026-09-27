# INC-1004 — Postmortem: brief oversell event on SKU-200

**Severity:** Sev-2
**Status:** Closed

## Summary
During a flash sale, a small number of SKU-200 orders were confirmed and
charged for stock that turned out not to be available, resulting in
customer refunds.

## Root cause (as documented by the on-call engineer at the time)
The postmortem author's write-up states: "the root cause was that payment
is captured before inventory is reserved under high load, allowing two
concurrent orders to both pass the stock check before either reservation
is recorded — this is the opposite of the documented design and should be
corrected."

## Note for future investigators
This root-cause statement should be verified against the current
`OrderService.place_order()` implementation and `architecture_overview.md`
before being treated as confirmed fact — postmortems are written under
time pressure and are not always accurate about implementation order.
