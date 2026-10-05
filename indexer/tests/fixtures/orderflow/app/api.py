"""HTTP entry points for OrderFlow."""

from fastapi import FastAPI, HTTPException

from app.models import Order, OrderItem
from app.order_service import OrderPlacementError, OrderService

app = FastAPI(title="OrderFlow")
order_service = OrderService()


@app.post("/orders")
def create_order(customer_id: str, items: list[OrderItem]):
    order = Order(order_id=OrderService.new_order_id(), customer_id=customer_id, items=items)
    try:
        confirmed = order_service.place_order(order)
    except OrderPlacementError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return confirmed
