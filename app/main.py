from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    analytics,
    auth,
    campaigns,
    customers,
    ingredients,
    menu,
    orders,
    public,
    settings as settings_api,
    webhooks,
)
from app.core.config import get_settings

app = FastAPI(title="MenuHub API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(menu.router)
app.include_router(ingredients.router)
app.include_router(orders.router)
app.include_router(customers.router)
app.include_router(analytics.router)
app.include_router(campaigns.router)
app.include_router(settings_api.router)
app.include_router(public.router)
app.include_router(webhooks.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
