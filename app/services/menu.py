from app.models import MenuItem
from app.schemas.menu import AdminItemOut


def calc_margin(price: float, cost: float | None) -> str | None:
    if cost is None or price <= 0:
        return None
    return f"{round((price - cost) / price * 100)}%"


def item_image_urls(item: MenuItem) -> list[str]:
    """Full ordered gallery: primary image_url first, then extra image_urls, deduped."""
    urls: list[str] = []
    if item.image_url:
        urls.append(item.image_url)
    for url in item.image_urls or []:
        if url and url not in urls:
            urls.append(url)
    return urls


def to_admin_item(item: MenuItem) -> AdminItemOut:
    price = float(item.price)
    cost = float(item.cost) if item.cost is not None else None
    return AdminItemOut(
        id=item.id,
        category_id=item.category_id,
        name=item.name,
        description=item.description,
        price=price,
        cost=cost,
        margin=calc_margin(price, cost),
        image_url=item.image_url,
        image_urls=item_image_urls(item),
        is_available=item.is_available,
        ingredients=item.ingredients or [],
        variants=item.variants or [],
    )
