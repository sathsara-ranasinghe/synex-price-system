"""Changes waiting to be written to QuickBooks: list, approve, reject, retry."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_company, get_current_user
from ..models import Company, QBWrite, User
from ..services import audit

router = APIRouter(prefix="/api", tags=["QuickBooks changes"])


class QBWriteOut(BaseModel):
    write_id: int
    kind: str
    entity_id: int
    summary: str
    payload: dict
    status: str
    requested_by: str | None
    requested_at: datetime
    approved_at: datetime | None
    sent_at: datetime | None
    attempts: int
    qb_ref: str | None
    error_message: str | None


class Decision(BaseModel):
    note: str | None = None


def _out(w: QBWrite) -> QBWriteOut:
    return QBWriteOut(write_id=w.write_id, kind=w.kind, entity_id=w.entity_id, summary=w.summary, payload=w.payload,
                      status=w.status, requested_by=(w.requester.full_name or w.requester.username) if w.requester else None,
                      requested_at=w.requested_at, approved_at=w.approved_at, sent_at=w.sent_at, attempts=w.attempts,
                      qb_ref=w.qb_ref, error_message=w.error_message)


def _module(w: QBWrite) -> str:
    return (w.payload or {}).get("module") or "admin"


def _can_see(user: User, w: QBWrite) -> bool:
    perms = user.role.permissions or []
    m = _module(w)
    return w.requested_by == user.user_id or f"{m}.approve" in perms or f"{m}.view" in perms


@router.get("/qb-writes", response_model=list[QBWriteOut])
def list_writes(status: str | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user),
                co: Company = Depends(get_company)):
    q = db.query(QBWrite).filter(QBWrite.kind != "report", QBWrite.company_id == co.company_id)
    if status:
        q = q.filter(QBWrite.status.in_(status.split(",")))
    rows = [w for w in q.order_by(QBWrite.write_id.desc()).limit(1000).all() if _can_see(user, w)]
    return [_out(w) for w in rows[:500]]


def _get(db: Session, write_id: int, user: User, co: Company, *statuses: str) -> QBWrite:
    w = db.get(QBWrite, write_id)
    if not w or w.company_id != co.company_id:
        raise HTTPException(404, "Not found")
    perm = f"{_module(w)}.approve"
    if perm not in (user.role.permissions or []):
        raise HTTPException(403, f"Missing permission: {perm}")
    if w.status not in statuses:
        raise HTTPException(409, f"Change is {w.status}")
    return w


@router.post("/qb-writes/{write_id}/approve", response_model=QBWriteOut)
def approve(write_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user), co: Company = Depends(get_company)):
    w = _get(db, write_id, user, co, "pending")
    w.status, w.approved_by, w.approved_at = "approved", user.user_id, datetime.now(timezone.utc)
    audit.log(db, user.user_id, "qb_write", w.write_id, "approve", None, {"kind": w.kind})
    db.commit()
    return _out(w)


@router.post("/qb-writes/{write_id}/reject", response_model=QBWriteOut)
def reject(write_id: int, body: Decision, db: Session = Depends(get_db), user: User = Depends(get_current_user),
           co: Company = Depends(get_company)):
    w = _get(db, write_id, user, co, "pending", "approved", "failed")
    w.status, w.error_message = "rejected", body.note
    audit.log(db, user.user_id, "qb_write", w.write_id, "reject", None, {"note": body.note})
    db.commit()
    return _out(w)


@router.post("/qb-writes/{write_id}/retry", response_model=QBWriteOut)
def retry(write_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user), co: Company = Depends(get_company)):
    w = _get(db, write_id, user, co, "failed")
    w.status, w.error_message = "approved", None
    audit.log(db, user.user_id, "qb_write", w.write_id, "retry")
    db.commit()
    return _out(w)
