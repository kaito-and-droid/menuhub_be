import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, update

from app.core.cache import delete as cache_delete
from app.core.cache import menu_key
from app.core.deps import CurrentShop, CurrentUser, DbSession
from app.models import Ingredient, MenuCategory, MenuItem
from app.schemas.menu import ItemVariant, RecipeLine
from app.services.audit import changed_fields, record_audit
from app.schemas.menu import (
    AdminCategoryWithItems,
    AdminItemOut,
    AdminMenuResponse,
    CategoryCreate,
    CategoryOut,
    ItemCreate,
    ItemUpdate,
)
from app.services.menu import to_admin_item

router = APIRouter(prefix="/api/shops/{shop_id}/menu", tags=["menu"])


@router.get("", response_model=AdminMenuResponse)
async def get_menu(shop: CurrentShop, db: DbSession) -> AdminMenuResponse:
    categories = (
        await db.scalars(
            select(MenuCategory)
            .where(MenuCategory.shop_id == shop.id)
            .order_by(MenuCategory.display_order, MenuCategory.name)
        )
    ).all()
    items = (
        await db.scalars(
            select(MenuItem).where(MenuItem.shop_id == shop.id).order_by(MenuItem.name)
        )
    ).all()

    by_category: dict[uuid.UUID, list[AdminItemOut]] = {}
    uncategorized: list[AdminItemOut] = []
    for item in items:
        out = to_admin_item(item)
        if item.category_id is None:
            uncategorized.append(out)
        else:
            by_category.setdefault(item.category_id, []).append(out)

    return AdminMenuResponse(
        categories=[
            AdminCategoryWithItems(
                id=c.id,
                name=c.name,
                display_order=c.display_order,
                is_active=c.is_active,
                items=by_category.get(c.id, []),
            )
            for c in categories
        ],
        uncategorized=uncategorized,
    )


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(shop: CurrentShop, db: DbSession) -> list[CategoryOut]:
    categories = await db.scalars(
        select(MenuCategory)
        .where(MenuCategory.shop_id == shop.id)
        .order_by(MenuCategory.display_order, MenuCategory.name)
    )
    return [CategoryOut.model_validate(c) for c in categories]


@router.post("/categories", status_code=status.HTTP_201_CREATED, response_model=CategoryOut)
async def create_category(
    body: CategoryCreate, shop: CurrentShop, user: CurrentUser, db: DbSession
) -> CategoryOut:
    category = MenuCategory(shop_id=shop.id, name=body.name, display_order=body.display_order)
    db.add(category)
    await db.flush()
    record_audit(
        db, shop.id, user.id, "created", "menu_category", category.id,
        new_value={"name": body.name},
    )
    await db.commit()
    await cache_delete(menu_key(shop.slug))
    return CategoryOut.model_validate(category)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: uuid.UUID, shop: CurrentShop, user: CurrentUser, db: DbSession
) -> None:
    category = await db.scalar(
        select(MenuCategory).where(
            MenuCategory.id == category_id, MenuCategory.shop_id == shop.id
        )
    )
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    await db.execute(
        update(MenuItem)
        .where(MenuItem.category_id == category_id, MenuItem.shop_id == shop.id)
        .values(category_id=None)
    )
    record_audit(
        db, shop.id, user.id, "deleted", "menu_category", category.id,
        old_value={"name": category.name},
    )
    await db.delete(category)
    await db.commit()
    await cache_delete(menu_key(shop.slug))


async def _get_owned_category(db: DbSession, shop_id: uuid.UUID, category_id: uuid.UUID) -> MenuCategory:
    category = await db.scalar(
        select(MenuCategory).where(
            MenuCategory.id == category_id, MenuCategory.shop_id == shop_id
        )
    )
    if category is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown category_id")
    return category


async def _validate_recipe(db: DbSession, shop_id: uuid.UUID, lines: list[RecipeLine]) -> None:
    ids = {line.ingredient_id for line in lines}
    if not ids:
        return
    owned = set(
        await db.scalars(
            select(Ingredient.id).where(Ingredient.id.in_(ids), Ingredient.shop_id == shop_id)
        )
    )
    missing = ids - owned
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Recipe references unknown ingredients: {sorted(str(i) for i in missing)}",
        )


def _validate_variants(variants: list[ItemVariant]) -> None:
    names = [v.name for v in variants]
    if len(names) != len(set(names)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Variant names must be unique")


@router.post("/items", status_code=status.HTTP_201_CREATED, response_model=AdminItemOut)
async def create_item(
    body: ItemCreate, shop: CurrentShop, user: CurrentUser, db: DbSession
) -> AdminItemOut:
    if body.category_id is not None:
        await _get_owned_category(db, shop.id, body.category_id)
    await _validate_recipe(db, shop.id, body.ingredients)
    _validate_variants(body.variants)
    item = MenuItem(
        shop_id=shop.id,
        category_id=body.category_id,
        name=body.name,
        description=body.description,
        price=body.price,
        cost=body.cost,
        image_url=body.image_url,
        image_urls=body.image_urls or None,
        is_available=body.is_available,
        ingredients=[line.model_dump(mode="json") for line in body.ingredients],
        variants=[v.model_dump(mode="json") for v in body.variants] if body.variants else None,
    )
    db.add(item)
    await db.flush()
    record_audit(
        db, shop.id, user.id, "created", "menu_item", item.id,
        new_value={"name": body.name, "price": body.price, "cost": body.cost},
    )
    await db.commit()
    await cache_delete(menu_key(shop.slug))
    return to_admin_item(item)


@router.patch("/items/{item_id}", response_model=AdminItemOut)
async def update_item(
    item_id: uuid.UUID, body: ItemUpdate, shop: CurrentShop, user: CurrentUser, db: DbSession
) -> AdminItemOut:
    item = await db.scalar(
        select(MenuItem).where(MenuItem.id == item_id, MenuItem.shop_id == shop.id)
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Menu item not found")

    updates = body.model_dump(exclude_unset=True)
    if "category_id" in updates and updates["category_id"] is not None:
        await _get_owned_category(db, shop.id, updates["category_id"])
    if "ingredients" in updates and updates["ingredients"] is not None:
        await _validate_recipe(db, shop.id, body.ingredients or [])
        updates["ingredients"] = [
            line.model_dump(mode="json") for line in body.ingredients or []
        ]
    if "variants" in updates and updates["variants"] is not None:
        _validate_variants(body.variants)
        updates["variants"] = [v.model_dump(mode="json") for v in body.variants]
    elif "variants" in updates and updates["variants"] is None:
        updates["variants"] = None
    if "image_urls" in updates:
        updates["image_urls"] = updates["image_urls"] or None

    old_snapshot = {field: getattr(item, field) for field in updates}
    old, new = changed_fields(old_snapshot, updates)
    for field, value in updates.items():
        setattr(item, field, value)
    if new:
        record_audit(db, shop.id, user.id, "updated", "menu_item", item.id, old, new)
    await db.commit()
    await cache_delete(menu_key(shop.slug))
    return to_admin_item(item)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: uuid.UUID, shop: CurrentShop, user: CurrentUser, db: DbSession
) -> None:
    item = await db.scalar(
        select(MenuItem).where(MenuItem.id == item_id, MenuItem.shop_id == shop.id)
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Menu item not found")
    record_audit(
        db, shop.id, user.id, "deleted", "menu_item", item.id,
        old_value={"name": item.name, "price": float(item.price)},
    )
    await db.delete(item)
    await db.commit()
    await cache_delete(menu_key(shop.slug))
