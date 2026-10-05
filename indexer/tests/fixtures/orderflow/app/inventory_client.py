"""Client for the inventory/warehouse system."""

from dataclasses import dataclass


@dataclass
class ReservationResult:
    success: bool
    reservation_id: str | None
    error_message: str | None = None


class InsufficientStockError(Exception):
    pass


class InventoryClient:
    """Reserves stock for an order before payment is confirmed."""

    def __init__(self):
        # In-memory stub warehouse for the capstone demo.
        self._stock = {
            "SKU-100": 50,
            "SKU-200": 12,
            "SKU-300": 0,
        }

    def reserve_stock(self, sku: str, quantity: int) -> ReservationResult:
        available = self._stock.get(sku, 0)
        if available < quantity:
            return ReservationResult(
                success=False,
                reservation_id=None,
                error_message=f"insufficient stock for {sku}: requested {quantity}, available {available}",
            )
        self._stock[sku] = available - quantity
        return ReservationResult(success=True, reservation_id=f"RSV-{sku}-{quantity}")
