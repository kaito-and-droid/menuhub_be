import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import IngredientUnit


class IngredientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    unit: IngredientUnit
    current_quantity: float = Field(default=0, ge=0)
    reorder_level: float = Field(default=0, ge=0)
    supplier_name: str | None = Field(default=None, max_length=255)


class IngredientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    unit: IngredientUnit | None = None
    current_quantity: float | None = None
    reorder_level: float | None = Field(default=None, ge=0)
    supplier_name: str | None = Field(default=None, max_length=255)


class IngredientOut(BaseModel):
    id: uuid.UUID
    name: str
    unit: IngredientUnit
    current_quantity: float
    reorder_level: float
    last_purchase_price: float | None
    supplier_name: str | None
    low_stock: bool


class PurchaseLogCreate(BaseModel):
    ingredient_id: uuid.UUID
    quantity: float = Field(gt=0)
    cost: float = Field(ge=0)
    purchase_date: datetime | None = None
    supplier_name: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=1000)


class PurchaseLogOut(BaseModel):
    id: uuid.UUID
    ingredient_id: uuid.UUID
    ingredient_name: str
    quantity: float
    cost: float
    purchase_date: datetime
    supplier_name: str | None
    notes: str | None
