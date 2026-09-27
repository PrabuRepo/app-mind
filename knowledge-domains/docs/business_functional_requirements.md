# OrderFlow — Business & Functional Requirements

## Business context
OrderFlow supports the checkout experience for the storefront. Every order a
customer places, from a single item to a full cart, is processed through this
service. Reliability here directly affects revenue (failed orders) and
customer trust (billing correctness).

## Core functional requirements
1. **A customer must never be charged more than once for a single order.**
   This is treated as a critical invariant — customer billing disputes
   arising from duplicate charges are escalated as Sev-1 incidents.
2. **Inventory must be reserved before payment is captured.** We do not
   charge customers for items we cannot fulfill.
3. **If payment fails, no confirmation notification is sent**, and the
   customer is shown a clear failure reason.
4. **Transient payment gateway failures should be retried automatically**,
   since a single dropped connection to the gateway should not require the
   customer to re-attempt checkout manually.

## Known tension
Requirements 1 and 4 are in tension: automatic retries (req. 4) must not
result in a duplicate charge (req. 1). The payment retry design is expected
to guarantee this via an idempotency mechanism at the gateway level. See
`architecture_overview.md` and the incident history for whether this
guarantee currently holds in the implementation.

## SLA
- Order placement (API response) should complete within 3 seconds under
  normal load.
- Payment gateway timeouts are expected roughly 1–2% of the time under
  normal conditions; the retry logic exists specifically to absorb this.
