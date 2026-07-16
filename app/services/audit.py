import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog

MASK = "***"


def record_audit(
    db: AsyncSession,
    shop_id: uuid.UUID,
    user_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    old_value: dict | None = None,
    new_value: dict | None = None,
) -> None:
    """Adds an audit row to the session; the caller's commit persists it."""
    db.add(
        AuditLog(
            shop_id=shop_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            old_value=old_value,
            new_value=new_value,
        )
    )


def changed_fields(old: dict, updates: dict) -> tuple[dict, dict]:
    """(old-values, new-values) restricted to keys that actually change, JSON-safe."""
    old_out, new_out = {}, {}
    for key, new in updates.items():
        previous = old.get(key)
        if previous != new:
            old_out[key] = _jsonable(previous)
            new_out[key] = _jsonable(new)
    return old_out, new_out


def _jsonable(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)
