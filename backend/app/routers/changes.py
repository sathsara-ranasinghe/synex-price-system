"""Changes waiting to be written to QuickBooks: list, approve, reject, retry."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_company, get_current_user
from ..models import Company, QBRecord, QBWrite, User
from ..qb import builder
from ..qb.registry import BY_KEY
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


def _show(v) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, dict):
        if "ListID" in v or "FullName" in v:
            return str(v.get("FullName") or v.get("ListID"))
        return ", ".join(str(x) for x in v.values() if x)  # addresses
    if isinstance(v, bool) or v in ("true", "false"):
        return "Yes" if v in (True, "true") else "No"
    return str(v)


def _line_text(ent, ln: dict) -> str:
    lt = next((t for t in ent.lines if t.key == ln.get("type")), None)
    vals = ln.get("values") or {}
    parts = [f"{f.label}: {_show(vals.get(f.path))}" for f in (lt.fields if lt else []) if _show(vals.get(f.path))]
    return " · ".join(parts)


@router.get("/qb-writes/{write_id}/diff")
def diff(write_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user), co: Company = Depends(get_company)):
    """Before / after of a change, field by field, so approvers see exactly what will change in QuickBooks."""
    w = db.get(QBWrite, write_id)
    if not w or w.company_id != co.company_id or not _can_see(user, w):
        raise HTTPException(404, "Not found")
    ent = BY_KEY.get((w.payload or {}).get("entity"))
    if not ent:
        return {"fields": [], "lines_old": [], "lines_new": [], "record": None}
    rec = db.get(QBRecord, w.entity_id) if w.kind in ("qb_mod", "qb_delete", "qb_void") and w.entity_id else None
    old = builder.to_form(ent, rec.data or {}) if rec and rec.company_id == co.company_id else {"values": {}, "lines": []}
    new_vals = (w.payload or {}).get("values") or {}
    fields = []
    for f in ent.fields:
        o, n = _show(old["values"].get(f.path)), _show(new_vals.get(f.path)) if f.path in new_vals else None
        if w.kind == "qb_add" and n:
            fields.append({"label": f.label, "old": None, "new": n})
        elif w.kind == "qb_mod" and n is not None and n != o:
            fields.append({"label": f.label, "old": o or None, "new": n or None})
        elif w.kind in ("qb_delete", "qb_void") and o:
            fields.append({"label": f.label, "old": o, "new": None})
    new_lines = (w.payload or {}).get("lines")
    return {
        "kind": w.kind, "entity": ent.key, "label": ent.label,
        "record": {"record_id": rec.record_id, "name": rec.name, "amount": float(rec.amount) if rec.amount is not None else None}
        if rec else None,
        "fields": fields,
        "lines_old": [_line_text(ent, ln) for ln in old["lines"]] if (w.kind != "qb_add" and new_lines is not None)
        or w.kind in ("qb_delete", "qb_void") else [],
        "lines_new": [_line_text(ent, ln) for ln in (new_lines or [])],
    }


class Many(BaseModel):
    ids: list[int]


@router.post("/qb-writes/approve-many")
def approve_many(body: Many, db: Session = Depends(get_db), user: User = Depends(get_current_user),
                 co: Company = Depends(get_company)):
    done, skipped = [], []
    for wid in body.ids[:200]:
        try:
            w = _get(db, wid, user, co, "pending")
        except HTTPException as e:
            skipped.append({"write_id": wid, "reason": e.detail})
            continue
        w.status, w.approved_by, w.approved_at = "approved", user.user_id, datetime.now(timezone.utc)
        audit.log(db, user.user_id, "qb_write", w.write_id, "approve", None, {"kind": w.kind, "bulk": True})
        done.append(wid)
    db.commit()
    return {"approved": done, "skipped": skipped}


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
