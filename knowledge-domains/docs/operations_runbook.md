# OrderFlow — Operations Runbook

## Common on-call scenarios

### "Order stuck in RESERVED status"
Inventory was reserved but payment never completed or failed silently.
Check payment gateway logs for the associated customer/order. Usually
resolves once the payment gateway's own incident clears.

### "Customer reports being charged twice"
See `incidents/INC-1001_duplicate_charge.md` for the known pattern and
current status. This is the single most common billing-related page.

### "Order rejected — insufficient stock"
Expected behavior per `business_functional_requirements.md` requirement 2 —
not a bug. Confirm the SKU's stock level is accurate; if stock looks wrong,
escalate to the Inventory team, not OrderFlow on-call.

## Retry and timeout configuration
The payment gateway client retries up to 3 times on timeout, with
increasing backoff between attempts. This is intentional (see business
requirement 4) to absorb transient gateway blips without failing the order
outright. On-call should not disable retries as a quick fix for gateway
slowness — see the open question in the incident history about whether
retries are currently safe under all failure modes.
