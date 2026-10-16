from pydantic import BaseModel, Field


class Product(BaseModel):
    sku: str
    name: str
    price_cents: int
    stock: int


class ReserveRequest(BaseModel):
    sku: str
    quantity: int = Field(gt=0, le=100)


class ReservationOut(BaseModel):
    reservation_id: int
    sku: str
    quantity: int
    unit_price_cents: int
    remaining_stock: int


class CheckoutRequest(BaseModel):
    reservation_id: int


class OrderOut(BaseModel):
    order_id: int
    reservation_id: int
    total_cents: int
