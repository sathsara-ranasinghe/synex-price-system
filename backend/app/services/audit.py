from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from ..models import AuditLog


def _jsonable(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def snapshot(obj) -> dict:
    return {c.key: _jsonable(getattr(obj, c.key)) for c in inspect(obj).mapper.column_attrs}


def log(db: Session, user_id: int | None, entity: str, entity_id, action: str,
        old: dict | None = None, new: dict | None = None):
    if old and new:  # keep only the fields that changed
        changed = {k for k in new if old.get(k) != new.get(k)}
        old = {k: old.get(k) for k in changed}
        new = {k: new[k] for k in changed}
    db.add(AuditLog(user_id=user_id, entity=entity, entity_id=None if entity_id is None else str(entity_id),
                    action=action, old_value=old, new_value=new))
