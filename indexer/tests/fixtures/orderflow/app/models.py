"""Core data models for OrderFlow."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class OrderStatus(str, Enum):
    PENDING = "pending"
    PAID = "paid"
    RESERVED = "reserved"
    CONFIRMED = "confirmed"
    FAILED = "failed"


@dataclass
class OrderItem:
    sku: str
    quantity: int
    unit_price_cents: int


@dataclass
class Order:
    order_id: str
    customer_id: str
    items: list[OrderItem]
    status: OrderStatus = OrderStatus.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def total_cents(self) -> int:
        return sum(item.quantity * item.unit_price_cents for item in self.items)


@dataclass
class PaymentResult:
    success: bool
    transaction_id: str | None
    amount_charged_cents: int
    error_message: str | None = None
