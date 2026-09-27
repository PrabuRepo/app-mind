# INC-1001 — Customer charged twice for a single order

**Severity:** Sev-1 (billing correctness)
**Status:** Open — root cause under investigation
**Reported by:** Customer support (3 separate customer reports over 48h)

## Symptom
Three customers reported two charges on their card statement for what
should have been a single OrderFlow order. In each case, the order was
ultimately marked CONFIRMED and the customer received one confirmation
email — but their payment provider shows two separate authorizations for
the same amount, seconds apart.

## Timeline (customer #2, most detailed report)
- 14:02:03 — Order placed, inventory reserved successfully.
- 14:02:04 — Payment gateway call initiated.
- 14:02:07 — Customer's bank shows a completed authorization at this
  timestamp (confirmed via customer's bank statement).
- 14:02:09 — OrderFlow logs show a gateway timeout on the same request.
- 14:02:09 — A second charge attempt is logged immediately after.
- 14:02:10 — Second authorization appears on customer's bank statement.
- 14:02:11 — Order marked CONFIRMED, single confirmation email sent.

## What we've ruled out
- Not a duplicate API call from the frontend — request logs show exactly
  one `POST /orders` call per affected order.
- Not an inventory double-reservation — inventory logs show a single
  reservation per order in all three cases.
- Notification service sent exactly one email per order, so this is not a
  notification-layer bug.

## Open question
The pattern above (gateway timeout logged, followed immediately by a
second charge attempt) suggests the retry behavior in the payment path may
be resubmitting a charge that the gateway had, in fact, already processed
successfully — the timeout was on our side receiving the response, not on
the gateway failing to charge. Needs confirmation against the actual retry
implementation before we can call this the root cause.
