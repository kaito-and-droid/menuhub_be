import uuid

from pydantic import BaseModel, Field

from app.schemas.campaigns import PublicCampaign
from app.schemas.settings import OrderPageConfig, SeoConfig


class RecipeLine(BaseModel):
    ingredient_id: uuid.UUID
    quantity: float = Field(gt=0)
    unit: str


class ItemVariant(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    price: float = Field(gt=0)
    cost: float | None = Field(default=None, ge=0)


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    display_order: int = 0


class CategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    display_order: int
    is_active: bool

    model_config = {"from_attributes": True}


class ItemCreate(BaseModel):
    category_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    # Money accepts 2 decimals (SGD cents); VND shops use whole numbers
    price: float = Field(gt=0)
    cost: float | None = Field(default=None, ge=0)
    image_url: str | None = Field(default=None, max_length=1000)
    image_urls: list[str] = Field(default_factory=list, max_length=10)
    is_available: bool = True
    ingredients: list[RecipeLine] = []
    variants: list[ItemVariant] = []


class ItemUpdate(BaseModel):
    category_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    price: float | None = Field(default=None, gt=0)
    cost: float | None = Field(default=None, ge=0)
    image_url: str | None = Field(default=None, max_length=1000)
    image_urls: list[str] | None = Field(default=None, max_length=10)
    is_available: bool | None = None
    ingredients: list[RecipeLine] | None = None
    variants: list[ItemVariant] | None = None


class AdminItemOut(BaseModel):
    id: uuid.UUID
    category_id: uuid.UUID | None
    name: str
    description: str | None
    price: float
    cost: float | None
    margin: str | None
    image_url: str | None
    image_urls: list[str] = []
    is_available: bool
    ingredients: list
    variants: list = []


class AdminCategoryWithItems(BaseModel):
    id: uuid.UUID
    name: str
    display_order: int
    is_active: bool
    items: list[AdminItemOut]


class AdminMenuResponse(BaseModel):
    categories: list[AdminCategoryWithItems]
    uncategorized: list[AdminItemOut]


class PublicItemOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    price: float
    image_url: str | None
    image_urls: list[str] = []
    is_available: bool
    variants: list = []  # [{name, price}] — no cost exposed to public


class PublicCategoryOut(BaseModel):
    name: str
    items: list[PublicItemOut]


class PublicMenuResponse(BaseModel):
    shop_name: str
    facebook_page_id: str | None = None
    estimated_wait_minutes: int = 15
    currency: str = "VND"
    payment_methods: list[str] = []
    campaigns: list[PublicCampaign] = []
    categories: list[PublicCategoryOut]
    order_page: OrderPageConfig | None = None
    seo: SeoConfig | None = None
    menu_layout: str = "grid"  # "grid" | "list" — how items render on the public order page
