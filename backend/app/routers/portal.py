"""Synex QB Portal: generic QuickBooks modules driven by app/qb/registry.py."""

from dataclasses import asdict
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_company, get_current_user, require
from ..models import Company, QBRecord, QBReport, QBWrite, Role, User
from ..permissions import USERS_MANAGE, catalog
from ..qb import builder
from ..qb.registry import BY_KEY, ENTITIES, MODULES, REF_GROUPS, REPORTS, Entity
from ..services import audit

router = APIRouter(prefix="/api/qb", tags=["QB Portal"])
roles_router = APIRouter(prefix="/api", tags=["Roles"])


def can(user: User, perm: str) -> bool:
    return perm in (user.role.permissions or [])


def _entity(key: str, user: User, action: str = "view") -> Entity:
    ent = BY_KEY.get(key)
    if not ent:
        raise HTTPException(404, f"Unknown QuickBooks entity '{key}'")
    if not can(user, f"{ent.module}.{action}"):
        raise HTTPException(403, f"Missing permission: {ent.module}.{action}")
    return ent


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


# ---------------------------------------------------------------- schemas

class WriteIn(BaseModel):
    values: dict = Field(default_factory=dict)
    lines: list[dict] | None = None


class RecordOut(BaseModel):
    record_id: int
    entity: str
    qb_id: str
    name: str | None
    party_name: str | None
    txn_date: date | None
    amount: float | None
    is_active: bool
    deleted: bool
    time_modified: datetime | None
    columns: dict


class ReportIn(BaseModel):
    report_type: str
    from_date: date | None = None
    to_date: date | None = None


def _columns(ent: Entity, rec: QBRecord) -> dict:
    data = builder.normalize(ent, rec.data or {})
    out = {}
    for f in ent.fields:
        if f.list:
            v = builder.get(data, f.path)
            out[f.path] = (v.get("FullName") or v.get("ListID")) if isinstance(v, dict) else v
    return out


def _rec_out(ent: Entity, rec: QBRecord) -> RecordOut:
    return RecordOut(record_id=rec.record_id, entity=rec.entity, qb_id=rec.qb_id, name=rec.name,
                     party_name=rec.party_name, txn_date=rec.txn_date,
                     amount=float(rec.amount) if rec.amount is not None else None, is_active=rec.is_active,
                     deleted=rec.deleted, time_modified=rec.time_modified, columns=_columns(ent, rec))


# ---------------------------------------------------------------- metadata

@router.get("/meta")
def meta(user: User = Depends(get_current_user), co: Company = Depends(get_company)):
    visible = {m for m in MODULES if can(user, f"{m}.view")}
    off = set(co.disabled_entities or [])  # features this company file does not have
    entities = []
    for e in ENTITIES:
        if e.module not in visible or e.key in off:
            continue
        d = asdict(e)
        d.update(id_field=e.id_field,
                 permissions={a: can(user, f"{e.module}.{a}") for a in ("create", "edit", "delete", "direct")})
        entities.append(d)
    return {"modules": [{"key": k, "label": v} for k, v in MODULES.items() if k in visible],
            "entities": entities,
            "reports": [{"key": k, "family": f, "label": l} for k, (f, l) in REPORTS.items()]
            if can(user, "reports.view") else []}


# ---------------------------------------------------------------- dashboard

@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(get_current_user), co: Company = Depends(get_company)):
    keys = [e.key for e in ENTITIES if can(user, f"{e.module}.view")]
    counts = dict(db.query(QBRecord.entity, func.count()).filter(QBRecord.company_id == co.company_id,
                                                                 QBRecord.entity.in_(keys), QBRecord.deleted.is_(False))
                  .group_by(QBRecord.entity).all()) if keys else {}
    txn_keys = [k for k in keys if BY_KEY[k].kind == "txn"]
    recent = (db.query(QBRecord).filter(QBRecord.company_id == co.company_id, QBRecord.entity.in_(txn_keys),
                                        QBRecord.deleted.is_(False))
              .order_by(QBRecord.time_modified.desc().nullslast()).limit(12).all()) if txn_keys else []
    open_ar = open_ap = None
    if "invoice" in keys:
        open_ar = sum(float(builder.get(r.data, "BalanceRemaining") or 0)
                      for r in db.query(QBRecord).filter_by(company_id=co.company_id, entity="invoice", deleted=False).all()
                      if builder.get(r.data, "IsPaid") != "true")
    if "bill" in keys:
        open_ap = sum(float(r.amount or 0) for r in db.query(QBRecord).filter_by(company_id=co.company_id, entity="bill", deleted=False).all()
                      if builder.get(r.data, "IsPaid") != "true")
    pending = db.query(QBWrite).filter(QBWrite.status == "pending", QBWrite.company_id == co.company_id).count()
    return {"company": co.name, "counts": counts, "open_ar": open_ar, "open_ap": open_ap, "pending_changes": pending,
            "recent": [{**_rec_out(BY_KEY[r.entity], r).model_dump(), "label": BY_KEY[r.entity].label} for r in recent]}


# ---------------------------------------------------------------- reports (declared before /{entity} routes)

@router.post("/reports", status_code=201)
def run_report(body: ReportIn, db: Session = Depends(get_db), user: User = Depends(require("reports.view")),
               co: Company = Depends(get_company)):
    if body.report_type not in REPORTS:
        raise HTTPException(422, "Unknown report")
    r = QBReport(company_id=co.company_id, report_type=body.report_type, from_date=body.from_date, to_date=body.to_date,
                 requested_by=user.user_id)
    db.add(r)
    db.flush()
    db.add(QBWrite(company_id=co.company_id, kind="report", entity_id=r.report_id, summary=f"Report: {REPORTS[body.report_type][1]}",
                   payload={"module": "reports"}, status="approved", requested_by=user.user_id,
                   approved_by=user.user_id, approved_at=datetime.now(timezone.utc)))
    db.commit()
    return {"report_id": r.report_id, "status": r.status}


@router.get("/reports")
def list_reports(db: Session = Depends(get_db), user: User = Depends(require("reports.view")), co: Company = Depends(get_company)):
    rows = (db.query(QBReport).filter_by(company_id=co.company_id).order_by(QBReport.report_id.desc())
            .limit(50).all())
    return [{"report_id": r.report_id, "report_type": r.report_type, "label": REPORTS.get(r.report_type, ("", r.report_type))[1],
             "from_date": r.from_date, "to_date": r.to_date, "status": r.status, "requested_at": r.requested_at,
             "finished_at": r.finished_at, "error_message": r.error_message} for r in rows]


@router.get("/reports/{report_id}")
def get_report(report_id: int, db: Session = Depends(get_db), user: User = Depends(require("reports.view")),
               co: Company = Depends(get_company)):
    r = db.get(QBReport, report_id)
    if not r or r.company_id != co.company_id:
        raise HTTPException(404, "Report not found")
    return {"report_id": r.report_id, "label": REPORTS.get(r.report_type, ("", r.report_type))[1],
            "status": r.status, "result": r.result, "error_message": r.error_message,
            "from_date": r.from_date, "to_date": r.to_date, "finished_at": r.finished_at}


# ---------------------------------------------------------------- ref pickers

@router.get("/options/{target}")
def options(target: str, q: str = "", party_id: str | None = None, limit: int = Query(25, le=100),
            db: Session = Depends(get_db), user: User = Depends(get_current_user), co: Company = Depends(get_company)):
    keys = REF_GROUPS.get(target, [target])
    if not all(k in BY_KEY for k in keys):
        raise HTTPException(404, "Unknown picker")
    query = db.query(QBRecord).filter(QBRecord.company_id == co.company_id, QBRecord.entity.in_(keys),
                                      QBRecord.deleted.is_(False))
    if BY_KEY[keys[0]].kind == "list":
        query = query.filter(QBRecord.is_active.is_(True))
    if party_id:
        query = query.filter(QBRecord.party_id == party_id)
    if q:
        query = query.filter(or_(QBRecord.name.ilike(_like(q)), QBRecord.party_name.ilike(_like(q))))
    rows = query.order_by(QBRecord.name).limit(limit * 4 if target in ("bill", "invoice") else limit).all()
    if target in ("bill", "invoice"):  # only open bills / invoices can be paid
        rows = [r for r in rows if builder.get(r.data, "IsPaid") != "true"][:limit]
    out = []
    for r in rows:
        label = r.name or r.qb_id
        if BY_KEY[r.entity].kind == "txn":
            label = f"{r.name or ''} · {r.party_name or ''} · {r.txn_date or ''} · {r.amount or ''}"
        out.append({"ListID": r.qb_id, "FullName": r.name, "label": label, "entity": r.entity,
                    "amount": float(r.amount) if r.amount is not None else None})
    return out


# ---------------------------------------------------------------- records

@router.get("/{entity}")
def list_records(entity: str, q: str | None = None, active: bool | None = True, party_id: str | None = None,
                 date_from: date | None = None, date_to: date | None = None,
                 page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=500),
                 db: Session = Depends(get_db), user: User = Depends(get_current_user), co: Company = Depends(get_company)):
    ent = _entity(entity, user)
    query = db.query(QBRecord).filter(QBRecord.company_id == co.company_id, QBRecord.entity == ent.key,
                                      QBRecord.deleted.is_(False))
    if q:
        for word in q.split():
            query = query.filter(or_(QBRecord.name.ilike(_like(word)), QBRecord.party_name.ilike(_like(word))))
    if ent.kind == "list" and active is not None:
        query = query.filter(QBRecord.is_active.is_(active))
    if party_id:
        query = query.filter(QBRecord.party_id == party_id)
    if date_from:
        query = query.filter(QBRecord.txn_date >= date_from)
    if date_to:
        query = query.filter(QBRecord.txn_date <= date_to)
    total = query.count()
    order = (QBRecord.txn_date.desc().nullslast(), QBRecord.record_id.desc()) if ent.kind == "txn" else (QBRecord.name,)
    rows = query.order_by(*order).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [_rec_out(ent, r) for r in rows], "total": total, "page": page, "page_size": page_size}


def _record(db: Session, ent: Entity, record_id: int, co: Company) -> QBRecord:
    rec = db.get(QBRecord, record_id)
    if not rec or rec.entity != ent.key or rec.company_id != co.company_id:
        raise HTTPException(404, "Record not found")
    return rec


@router.get("/{entity}/{record_id}")
def get_record(entity: str, record_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user),
               co: Company = Depends(get_company)):
    ent = _entity(entity, user)
    rec = _record(db, ent, record_id, co)
    pending = (db.query(QBWrite).filter(QBWrite.company_id == co.company_id,
                                        QBWrite.kind.in_(["qb_mod", "qb_delete", "qb_void"]),
                                        QBWrite.status.in_(["pending", "approved", "sent"]))
               .filter(QBWrite.summary.like(f"%#{rec.qb_id}%")).count())
    related = []
    if ent.key in ("customer", "vendor"):
        for r in (db.query(QBRecord).filter(QBRecord.company_id == co.company_id, QBRecord.party_id == rec.qb_id,
                                            QBRecord.deleted.is_(False))
                  .order_by(QBRecord.txn_date.desc().nullslast()).limit(100).all()):
            if can(user, f"{BY_KEY[r.entity].module}.view"):
                related.append({**_rec_out(BY_KEY[r.entity], r).model_dump(), "label": BY_KEY[r.entity].label})
    return {"record": _rec_out(ent, rec), "data": rec.data, "form": builder.to_form(ent, rec.data or {}),
            "pending_changes": pending, "related": related}


def _queue(db: Session, user: User, co: Company, ent: Entity, kind: str, summary: str, payload: dict,
           entity_id: int = 0) -> QBWrite:
    direct = can(user, f"{ent.module}.direct")
    now = datetime.now(timezone.utc)
    w = QBWrite(company_id=co.company_id, kind=kind, entity_id=entity_id, summary=summary[:300], payload={**payload, "entity": ent.key,
                "module": ent.module}, requested_by=user.user_id,
                status="approved" if direct else "pending",
                approved_by=user.user_id if direct else None, approved_at=now if direct else None)
    db.add(w)
    db.flush()
    audit.log(db, user.user_id, "qb_write", w.write_id, "request", None, {"kind": kind, "summary": w.summary})
    db.commit()
    return w


def _write_out(w: QBWrite) -> dict:
    return {"write_id": w.write_id, "status": w.status, "summary": w.summary,
            "message": "Queued - will be written to QuickBooks on the next sync" if w.status == "approved"
            else "Sent for approval"}


def _describe(ent: Entity, values: dict) -> str:
    for p in ("Name", ent.party_path, "RefNumber"):
        v = values.get(p) if p else None
        if v:
            return v.get("FullName") or v.get("ListID") if isinstance(v, dict) else str(v)
    return ""


@router.post("/{entity}", status_code=201)
def create_record(entity: str, body: WriteIn, db: Session = Depends(get_db), user: User = Depends(get_current_user),
                  co: Company = Depends(get_company)):
    ent = _entity(entity, user, "create")
    try:  # validate now so the user sees mistakes immediately, not after the next sync
        builder.build_add(ent, body.values, body.lines, "check")
    except builder.BuildError as e:
        raise HTTPException(422, str(e))
    total = sum((builder.line_total(lt, ln.get("values") or {}) for lt in ent.lines
                 for ln in (body.lines or []) if ln.get("type") == lt.key), start=0)
    extra = f", total {total:,.2f}" if ent.lines and total else ""
    w = _queue(db, user, co, ent, "qb_add", f"New {ent.label.lower()} {_describe(ent, body.values)}{extra}",
               {"values": body.values, "lines": body.lines})
    return _write_out(w)


@router.patch("/{entity}/{record_id}")
def update_record(entity: str, record_id: int, body: WriteIn, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user), co: Company = Depends(get_company)):
    ent = _entity(entity, user, "edit")
    rec = _record(db, ent, record_id, co)
    try:
        builder.build_mod(ent, rec.qb_id, rec.edit_sequence or "0", body.values, body.lines, "check")
    except builder.BuildError as e:
        raise HTTPException(422, str(e))
    old = builder.to_form(ent, rec.data or {})["values"]
    changed = [f.label for f in ent.fields if f.path in body.values and body.values[f.path] != old.get(f.path)]
    if body.lines is not None:
        changed.append("lines")
    if not changed:
        raise HTTPException(422, "Nothing changed")
    w = _queue(db, user, co, ent, "qb_mod", f"Edit {ent.label.lower()} {rec.name or ''} (#{rec.qb_id}): {', '.join(changed)}",
               {"qb_id": rec.qb_id, "values": body.values, "lines": body.lines}, record_id)
    return _write_out(w)


@router.delete("/{entity}/{record_id}")
def delete_record(entity: str, record_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user),
                  co: Company = Depends(get_company)):
    ent = _entity(entity, user, "delete")
    rec = _record(db, ent, record_id, co)
    if not ent.del_type:
        raise HTTPException(422, f"{ent.plural} cannot be deleted")
    w = _queue(db, user, co, ent, "qb_delete", f"Delete {ent.label.lower()} {rec.name or ''} (#{rec.qb_id})",
               {"qb_id": rec.qb_id}, record_id)
    return _write_out(w)


@router.post("/{entity}/{record_id}/void")
def void_record(entity: str, record_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user),
                co: Company = Depends(get_company)):
    ent = _entity(entity, user, "delete")
    rec = _record(db, ent, record_id, co)
    if not ent.can_void:
        raise HTTPException(422, f"{ent.plural} cannot be voided")
    w = _queue(db, user, co, ent, "qb_void", f"Void {ent.label.lower()} {rec.name or ''} (#{rec.qb_id})",
               {"qb_id": rec.qb_id}, record_id)
    return _write_out(w)


# ---------------------------------------------------------------- roles

class RoleIn(BaseModel):
    role_name: str = Field(min_length=2, max_length=50, pattern=r"^[a-z0-9_\-]+$")
    permissions: list[str]


@roles_router.get("/permissions")
def permission_catalog(_: User = Depends(require(USERS_MANAGE))):
    return catalog()


@roles_router.post("/roles", status_code=201)
def create_role(body: RoleIn, db: Session = Depends(get_db), user: User = Depends(require(USERS_MANAGE))):
    if db.query(Role).filter_by(role_name=body.role_name).first():
        raise HTTPException(409, "Role exists")
    db.add(Role(role_name=body.role_name, permissions=sorted(set(body.permissions))))
    audit.log(db, user.user_id, "role", body.role_name, "create", None, {"permissions": body.permissions})
    db.commit()
    return {"role_name": body.role_name}


@roles_router.put("/roles/{role_name}")
def update_role(role_name: str, body: RoleIn, db: Session = Depends(get_db), user: User = Depends(require(USERS_MANAGE))):
    role = db.query(Role).filter_by(role_name=role_name).first()
    if not role:
        raise HTTPException(404, "Role not found")
    if role_name == "admin":
        raise HTTPException(400, "The admin role always has every permission")
    old = list(role.permissions or [])
    role.permissions = sorted(set(body.permissions))
    audit.log(db, user.user_id, "role", role_name, "update", {"permissions": old}, {"permissions": role.permissions})
    db.commit()
    return {"role_name": role_name, "permissions": role.permissions}


@roles_router.delete("/roles/{role_name}", status_code=204)
def delete_role(role_name: str, db: Session = Depends(get_db), user: User = Depends(require(USERS_MANAGE))):
    role = db.query(Role).filter_by(role_name=role_name).first()
    if not role or role_name == "admin":
        raise HTTPException(400, "Cannot delete this role")
    if db.query(User).filter_by(role_id=role.role_id).count():
        raise HTTPException(409, "Role is assigned to users")
    db.delete(role)
    audit.log(db, user.user_id, "role", role_name, "delete")
    db.commit()
