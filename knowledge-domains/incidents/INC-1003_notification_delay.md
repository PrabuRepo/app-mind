# INC-1003 — Confirmation emails delayed by several minutes

**Severity:** Sev-4
**Status:** Closed — monitoring

## Symptom
A handful of customers reported their order confirmation email arriving
5–10 minutes after checkout, rather than immediately.

## Investigation
`NotificationService.send_confirmation()` is called synchronously as the
final step of `OrderService.place_order()`, after payment succeeds. The
delay traced to the downstream email provider's own send queue backing up
during a traffic spike, not to OrderFlow's logic — OrderFlow itself invoked
the send call within milliseconds of payment confirmation in every sampled
case.

## Resolution
No OrderFlow code change. Flagged to the email provider's team. Monitoring
for recurrence.
