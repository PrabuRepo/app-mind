"""Sends order confirmation notifications to customers."""


class NotificationService:
    def send_confirmation(self, customer_id: str, order_id: str) -> bool:
        # Stubbed for the capstone: in production this calls an email/SMS
        # provider. Kept here so the dependency graph includes a realistic
        # "final step" node for Impact Analysis questions.
        print(f"[notify] order {order_id} confirmed for customer {customer_id}")
        return True
