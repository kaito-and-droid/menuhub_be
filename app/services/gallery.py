import logging
import uuid

import httpx

from app.core.config import get_settings
from app.models import Shop

logger = logging.getLogger(__name__)


async def _graph_get(path: str, token: str, params: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{get_settings().facebook_graph_url}{path}",
            params={"access_token": token, **(params or {})},
        )
        resp.raise_for_status()
        return resp.json()


async def sync_facebook_photos(shop: Shop) -> list[dict]:
    """Fetch recent uploaded photos from the Facebook page.

    Returns a list of GalleryItem-compatible dicts.
    Returns an empty list if Facebook is not configured or the call fails.
    """
    if not (shop.facebook_page_id and shop.facebook_app_access_token):
        return []
    try:
        data = await _graph_get(
            f"/{shop.facebook_page_id}/photos",
            shop.facebook_app_access_token,
            {"fields": "source,images,link", "type": "uploaded", "limit": 30},
        )
        items: list[dict] = []
        for photo in data.get("data", []):
            thumbnail = photo.get("source")
            if not thumbnail:
                images = photo.get("images", [])
                if images:
                    thumbnail = images[0].get("source")
            if not thumbnail:
                continue
            items.append({
                "id": str(uuid.uuid4()),
                "source": "facebook_photo",
                "source_url": photo.get("link"),
                "thumbnail_url": thumbnail,
                "sort_order": len(items),
                "active": True,
            })
        return items
    except Exception:
        logger.exception("Failed to sync Facebook photos for shop %s", shop.id)
        return []


async def fetch_tiktok_oembed(url: str) -> dict | None:
    """Fetch TikTok oEmbed data for a given video URL.

    Returns a GalleryItem-compatible dict, or None on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://www.tiktok.com/oembed",
                params={"url": url},
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "id": str(uuid.uuid4()),
                "source": "tiktok",
                "source_url": url,
                "thumbnail_url": data.get("thumbnail_url"),
                "embed_html": data.get("html"),
                "sort_order": 0,
                "active": True,
            }
    except Exception:
        logger.exception("Failed to fetch TikTok oEmbed for %s", url)
        return None
