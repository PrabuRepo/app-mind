"""Orchestrates the order placement flow.

Call order: place_order() -> InventoryClient.reserve_stock()
                            -> PaymentClient.charge()
                            -> NotificationService.send_confirmation()

This is the central node in the dependency graph most Impact Analysis
questions will traverse through.
"""

import uuid

from app.inventory_client import InventoryClient
from app.models import Order, OrderStatus
from app.notification_service import NotificationService
from app.payment_client import PaymentClient


class OrderPlacementError(Exception):
    pass


class OrderService:
    def __init__(self):
        self.payment_client = PaymentClient()
        self.inventory_client = InventoryClient()
        self.notification_service = NotificationService()

    def place_order(self, order: Order) -> Order:
        for item in order.items:
            reservation = self.inventory_client.reserve_stock(item.sku, item.quantity)
            if not reservation.success:
                order.status = OrderStatus.FAILED
                raise OrderPlacementError(reservation.error_message)
        order.status = OrderStatus.RESERVED

        payment = self.payment_client.charge(order.customer_id, order.total_cents)
        if not payment.success:
            order.status = OrderStatus.FAILED
            raise OrderPlacementError(payment.error_message)
        order.status = OrderStatus.PAID

        self.notification_service.send_confirmation(order.customer_id, order.order_id)
        order.status = OrderStatus.CONFIRMED
        return order

    @staticmethod
    def new_order_id() -> str:
        return f"ORD-{uuid.uuid4().hex[:8]}"
