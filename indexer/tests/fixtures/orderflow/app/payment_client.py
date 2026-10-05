"""Client for the external payment gateway.

NOTE: contains an intentionally planted bug for the capstone's Incident/RCA
eval question. See knowledge-domains/incidents/INC-1001_duplicate_charge.md
for the symptom report. Do not "fix" this without checking the eval test
set expects the pre-fix behavior for the planted-error question.
"""

import time
import uuid

from app.models import PaymentResult

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 0.5


class PaymentGatewayTimeoutError(Exception):
    pass


class PaymentClient:
    """Talks to the (simulated) external payment gateway."""

    def __init__(self, gateway_url: str = "https://payments.example.internal"):
        self.gateway_url = gateway_url

    def charge(self, customer_id: str, amount_cents: int) -> PaymentResult:
        """Charge a customer's card for the given amount.

        BUG (planted, for capstone RCA question): each retry attempt below
        generates a NEW transaction_id and re-submits the charge, with no
        idempotency key sent to the gateway. If the gateway actually
        processed an earlier attempt but the response timed out before
        reaching this client, the retry causes a second real charge. The
        fix would be to generate ONE idempotency key before the retry loop
        and pass the same key on every attempt, so the gateway can dedupe.
        """
        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return self._submit_charge(customer_id, amount_cents)
            except PaymentGatewayTimeoutError as exc:
                last_error = exc
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue
        return PaymentResult(
            success=False,
            transaction_id=None,
            amount_charged_cents=0,
            error_message=f"payment failed after {MAX_RETRIES} attempts: {last_error}",
        )

    def _submit_charge(self, customer_id: str, amount_cents: int) -> PaymentResult:
        """Simulated network call to the payment gateway. In the real
        service this is an HTTP POST; here it's stubbed for the capstone
        so ingestion/AST tooling has real code to analyze without needing
        network access.
        """
        transaction_id = str(uuid.uuid4())
        return PaymentResult(
            success=True,
            transaction_id=transaction_id,
            amount_charged_cents=amount_cents,
        )
