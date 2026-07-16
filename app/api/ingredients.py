import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.core.deps import CurrentShop, CurrentUser, DbSession
from app.models import Ingredient, IngredientLog
from app.services.audit import changed_fields, record_audit
from app.schemas.inventory import (
    IngredientCreate,
    IngredientOut,
    IngredientUpdate,
    PurchaseLogCreate,
    PurchaseLogOut,
)

router = APIRouter(prefix="/api/shops/{shop_id}/ingredients", tags=["ingredients"])


def _to_out(ingredient: Ingredient) -> IngredientOut:
    return IngredientOut(
        id=ingredient.id,
        name=ingredient.name,
        unit=ingredient.unit,
        current_quantity=float(ingredient.current_quantity),
        reorder_level=float(ingredient.reorder_level),
        last_purchase_price=(
            float(ingredient.last_purchase_price)
            if ingredient.last_purchase_price is not None
            else None
        ),
        supplier_name=ingredient.supplier_name,
        low_stock=ingredient.current_quantity <= ingredient.reorder_level,
    )


async def _get_owned_ingredient(
    db: DbSession, shop_id: uuid.UUID, ingredient_id: uuid.UUID
) -> Ingredient:
    ingredient = await db.scalar(
        select(Ingredient).where(
            Ingredient.id == ingredient_id, Ingredient.shop_id == shop_id
        )
    )
    if ingredient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ingredient not found")
    return ingredient


@router.get("", response_model=list[IngredientOut])
async def list_ingredients(shop: CurrentShop, db: DbSession) -> list[IngredientOut]:
    ingredients = await db.scalars(
        select(Ingredient).where(Ingredient.shop_id == shop.id).order_by(Ingredient.name)
    )
    return [_to_out(i) for i in ingredients]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=IngredientOut)
async def create_ingredient(
    body: IngredientCreate, shop: CurrentShop, user: CurrentUser, db: DbSession
) -> IngredientOut:
    ingredient = Ingredient(
        shop_id=shop.id,
        name=body.name,
        unit=body.unit,
        current_quantity=Decimal(str(body.current_quantity)),
        reorder_level=Decimal(str(body.reorder_level)),
        supplier_name=body.supplier_name,
    )
    db.add(ingredient)
    await db.flush()
    record_audit(
        db, shop.id, user.id, "created", "ingredient", ingredient.id,
        new_value={"name": body.name, "unit": body.unit.value},
    )
    await db.commit()
    return _to_out(ingredient)


@router.patch("/{ingredient_id}", response_model=IngredientOut)
async def update_ingredient(
    ingredient_id: uuid.UUID, body: IngredientUpdate, shop: CurrentShop, user: CurrentUser, db: DbSession
) -> IngredientOut:
    ingredient = await _get_owned_ingredient(db, shop.id, ingredient_id)
    updates = body.model_dump(exclude_unset=True)
    for field in ("current_quantity", "reorder_level"):
        if updates.get(field) is not None:
            updates[field] = Decimal(str(updates[field]))
    old_snapshot = {field: getattr(ingredient, field) for field in updates}
    old, new = changed_fields(old_snapshot, updates)
    for field, value in updates.items():
        setattr(ingredient, field, value)
    if new:
        record_audit(db, shop.id, user.id, "updated", "ingredient", ingredient.id, old, new)
    await db.commit()
    return _to_out(ingredient)


@router.post("/logs", status_code=status.HTTP_201_CREATED, response_model=PurchaseLogOut)
async def log_purchase(
    body: PurchaseLogCreate, shop: CurrentShop, user: CurrentUser, db: DbSession
) -> PurchaseLogOut:
    ingredient = await _get_owned_ingredient(db, shop.id, body.ingredient_id)
    quantity = Decimal(str(body.quantity))
    cost = Decimal(str(body.cost))

    log = IngredientLog(
        ingredient_id=ingredient.id,
        shop_id=shop.id,
        quantity=quantity,
        cost=cost,
        purchase_date=body.purchase_date or datetime.now(timezone.utc),
        supplier_name=body.supplier_name,
        notes=body.notes,
    )
    db.add(log)
    ingredient.current_quantity += quantity
    ingredient.last_purchase_price = cost / quantity
    if body.supplier_name:
        ingredient.supplier_name = body.supplier_name
    await db.flush()
    record_audit(
        db, shop.id, user.id, "created", "ingredient_log", log.id,
        new_value={"ingredient": ingredient.name, "quantity": body.quantity, "cost": body.cost},
    )
    await db.commit()
    return PurchaseLogOut(
        id=log.id,
        ingredient_id=ingredient.id,
        ingredient_name=ingredient.name,
        quantity=float(log.quantity),
        cost=float(log.cost),
        purchase_date=log.purchase_date,
        supplier_name=log.supplier_name,
        notes=log.notes,
    )


@router.get("/logs", response_model=list[PurchaseLogOut])
async def list_purchases(
    shop: CurrentShop,
    db: DbSession,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[PurchaseLogOut]:
    rows = await db.execute(
        select(IngredientLog, Ingredient.name)
        .join(Ingredient, Ingredient.id == IngredientLog.ingredient_id)
        .where(IngredientLog.shop_id == shop.id)
        .order_by(IngredientLog.purchase_date.desc())
        .limit(limit)
        .offset(offset)
    )
    return [
        PurchaseLogOut(
            id=log.id,
            ingredient_id=log.ingredient_id,
            ingredient_name=name,
            quantity=float(log.quantity),
            cost=float(log.cost),
            purchase_date=log.purchase_date,
            supplier_name=log.supplier_name,
            notes=log.notes,
        )
        for log, name in rows.all()
    ]
