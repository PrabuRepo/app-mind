# OrderFlow — Architecture Overview

## Purpose
OrderFlow is the order-placement service for the checkout flow. It coordinates
inventory reservation, payment capture, and customer notification for every
order placed through the storefront API.

## Components
- **API layer (`app/api.py`)** — exposes `POST /orders`, the single entry
  point for placing an order. Validates the request and delegates to
  `OrderService`.
- **OrderService (`app/order_service.py`)** — the central orchestrator.
  `place_order()` runs three sequential steps: reserve inventory, charge
  payment, send confirmation. This is the component most Impact Analysis
  questions will need to trace through, since every downstream client is
  called from here.
- **InventoryClient (`app/inventory_client.py`)** — reserves stock for each
  line item before payment is attempted, so we never charge a customer for
  an item we can't fulfill.
- **PaymentClient (`app/payment_client.py`)** — submits the charge to the
  external payment gateway. Includes retry logic for gateway timeouts (see
  the Operations Runbook and incident history for known issues with this
  retry behavior).
- **NotificationService (`app/notification_service.py`)** — sends the order
  confirmation once payment succeeds. Last step in the flow; nothing
  downstream depends on it.

## Request flow
1. `api.create_order()` receives the request and builds an `Order`.
2. `OrderService.place_order()` reserves stock for every item via
   `InventoryClient.reserve_stock()`. If any item is out of stock, the order
   fails immediately (before any charge is attempted).
3. Once inventory is reserved, `PaymentClient.charge()` is called for the
   order total.
4. If payment succeeds, `NotificationService.send_confirmation()` fires and
   the order is marked `CONFIRMED`.

## Design rule
Inventory is always reserved **before** payment is attempted — the system
is explicitly designed to avoid charging a customer for stock we don't have.
This ordering is a functional requirement, not an implementation detail (see
`business_functional_requirements.md`).
