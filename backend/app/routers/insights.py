"""Read-only helpers that make the portal easier to use: aging, customer / vendor overview, stock alerts,
smart form look-ups, duplicate warnings, record activity and the daily summary e-mail."""

import math
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import accessible_companies, get_company, get_current_user
from ..models import AuditLog, Company, QBRecord, QBWrite, User
from ..qb import builder
from ..qb.registry import BY_KEY
from ..services import audit
from ..services.notify import send_email_now

router = APIRouter(prefix="/api/insights", tags=["Insights"])

BUCKETS = ("current", "d1_30", "d31_60", "d61_90", "d90_plus")
SIDES = {"ar": ("invoice", "customer", "sales"), "ap": ("bill", "vendor", "purchasing")}
STOCK_ITEMS = ("item_inventory", "item_assembly")


def can(user: User, perm: str) -> bool:
    return perm in (user.role.permissions or [])


def _need(user: User, module: str) -> None:
    if not can(user, f"{module}.view"):
        raise HTTPException(403, f"Missing permission: {module}.view")


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _date(v) -> date | None:
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def open_amount(rec: QBRecord) -> float:
    """What is still unpaid on an invoice or bill."""
    d = rec.data or {}
    if builder.get(d, "IsPaid") == "true":
        return 0.0
    if rec.entity == "invoice":
        return _num(builder.get(d, "BalanceRemaining"))
    open_ = builder.get(d, "OpenAmount")
    return _num(open_) if open_ is not None else _num(rec.amount)


def due_date(rec: QBRecord) -> date | None:
    return _date(builder.get(rec.data or {}, "DueDate")) or rec.txn_date


def bucket(days_overdue: int) -> str:
    if days_overdue <= 0:
        return "current"
    if days_overdue <= 30:
        return "d1_30"
    if days_overdue <= 60:
        return "d31_60"
    if days_overdue <= 90:
        return "d61_90"
    return "d90_plus"


def _open_docs(db: Session, co: Company, entity: str, party_id: str | None = None) -> list[QBRecord]:
    q = db.query(QBRecord).filter(QBRecord.company_id == co.company_id, QBRecord.entity == entity, QBRecord.deleted.is_(False))
    if party_id:
        q = q.filter(QBRecord.party_id == party_id)
    return [r for r in q.all() if open_amount(r) > 0.005]


def _doc_row(r: QBRecord, today: date) -> dict:
    due = due_date(r)
    days = (today - due).days if due else 0
    return {"record_id": r.record_id, "entity": r.entity, "name": r.name, "party_name": r.party_name, "txn_date": r.txn_date,
            "due_date": due, "days_overdue": max(days, 0), "amount": _num(r.amount), "open": round(open_amount(r), 2),
            "bucket": bucket(days)}


# ---------------------------------------------------------------- aging

@router.get("/aging")
def aging(side: str = Query("ar", pattern="^(ar|ap)$"), as_of: date | None = None, db: Session = Depends(get_db),
          user: User = Depends(get_current_user), co: Company = Depends(get_company)):
    """Who owes what (A/R) or what we owe (A/P), split by how late it is."""
    doc, party_entity, module = SIDES[side]
    _need(user, module)
    today = as_of or date.today()
    totals = dict.fromkeys(BUCKETS, 0.0)
    parties: dict[str, dict] = {}
    for r in _open_docs(db, co, doc):
        row = _doc_row(r, today)
        key = r.party_id or r.party_name or "?"
        p = parties.setdefault(key, {"party_id": r.party_id, "name": r.party_name, **dict.fromkeys(BUCKETS, 0.0),
                                     "total": 0.0, "docs": 0, "oldest_due": None})
        p[row["bucket"]] += row["open"]
        p["total"] += row["open"]
        p["docs"] += 1
        if row["due_date"] and (not p["oldest_due"] or row["due_date"] < p["oldest_due"]):
            p["oldest_due"] = row["due_date"]
        totals[row["bucket"]] += row["open"]
    ids = {r.qb_id: r.record_id for r in db.query(QBRecord.qb_id, QBRecord.record_id).filter(
        QBRecord.company_id == co.company_id, QBRecord.entity == party_entity,
        QBRecord.qb_id.in_([p["party_id"] for p in parties.values() if p["party_id"]]))} if parties else {}
    rows = sorted(parties.values(), key=lambda p: -p["total"])
    for p in rows:
        p["record_id"] = ids.get(p["party_id"])
        for k in (*BUCKETS, "total"):
            p[k] = round(p[k], 2)
    return {"side": side, "as_of": today, "party_entity": party_entity, "doc_entity": doc,
            "totals": {k: round(v, 2) for k, v in totals.items()}, "total": round(sum(totals.values()), 2),
            "overdue": round(sum(v for k, v in totals.items() if k != "current"), 2), "parties": rows[:500]}


# ---------------------------------------------------------------- customer / vendor overview

def _month_add(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


@router.get("/party/{entity}/{record_id}")
def party(entity: str, record_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user),
          co: Company = Depends(get_company)):
    """Customer or vendor at a glance: balance, open documents, aging, payments and monthly totals."""
    if entity not in ("customer", "vendor"):
        raise HTTPException(404, "Only customers and vendors have an overview")
    side = "ar" if entity == "customer" else "ap"
    doc, _, module = SIDES[side]
    _need(user, module)
    rec = db.get(QBRecord, record_id)
    if not rec or rec.entity != entity or rec.company_id != co.company_id:
        raise HTTPException(404, "Record not found")
    today = date.today()
    d = rec.data or {}
    docs = sorted((_doc_row(r, today) for r in _open_docs(db, co, doc, rec.qb_id)),
                  key=lambda x: (x["due_date"] or date.max))
    buckets = dict.fromkeys(BUCKETS, 0.0)
    for x in docs:
        buckets[x["bucket"]] += x["open"]

    pay_entities = ("receive_payment",) if side == "ar" else ("bill_payment", "check")
    flow_entities = ("invoice", "sales_receipt") if side == "ar" else ("bill", "check", "item_receipt")
    base = db.query(QBRecord).filter(QBRecord.company_id == co.company_id, QBRecord.party_id == rec.qb_id,
                                     QBRecord.deleted.is_(False))
    payments = base.filter(QBRecord.entity.in_(pay_entities)).order_by(QBRecord.txn_date.desc().nullslast()).limit(10).all()
    flows = base.filter(QBRecord.entity.in_(flow_entities)).with_entities(QBRecord.txn_date, QBRecord.amount).all()
    last = max((t for t, _ in flows if t), default=None)
    end = _month_add((last or today).replace(day=1), 1)
    start = _month_add(end, -12)
    monthly = [0.0] * 12
    lifetime = 0.0
    for t, a in flows:
        lifetime += _num(a)
        if t and start <= t < end:
            monthly[(t.year - start.year) * 12 + t.month - start.month] += _num(a)
    return {
        "entity": entity, "record_id": rec.record_id, "name": rec.name,
        "balance": _num(builder.get(d, "TotalBalance") if entity == "customer" else builder.get(d, "Balance")),
        "credit_limit": _num(builder.get(d, "CreditLimit")) or None,
        "email": builder.get(d, "Email"), "phone": builder.get(d, "Phone"),
        "terms": (builder.get(d, "TermsRef") or {}).get("FullName") if isinstance(builder.get(d, "TermsRef"), dict) else None,
        "open_total": round(sum(x["open"] for x in docs), 2),
        "overdue_total": round(sum(x["open"] for x in docs if x["bucket"] != "current"), 2),
        "buckets": {k: round(v, 2) for k, v in buckets.items()},
        "open_docs": docs[:50], "open_count": len(docs),
        "payments": [{"record_id": p.record_id, "entity": p.entity, "label": BY_KEY[p.entity].label, "name": p.name,
                      "txn_date": p.txn_date, "amount": _num(p.amount)} for p in payments],
        "months": [_month_add(start, i).isoformat() for i in range(12)], "monthly": [round(v, 2) for v in monthly],
        "lifetime": round(lifetime, 2), "last_activity": last, "doc_entity": doc,
    }


# ---------------------------------------------------------------- stock alerts

@router.get("/stock")
def stock(db: Session = Depends(get_db), user: User = Depends(get_current_user), co: Company = Depends(get_company)):
    """Active inventory items at or below their reorder point."""
    if not (can(user, "inventory.view") or can(user, "lists.view")):
        raise HTTPException(403, "Missing permission: inventory.view")
    out = []
    for r in db.query(QBRecord).filter(QBRecord.company_id == co.company_id, QBRecord.entity.in_(STOCK_ITEMS),
                                       QBRecord.deleted.is_(False), QBRecord.is_active.is_(True)).all():
        d = r.data or {}
        rp = _num(builder.get(d, "ReorderPoint"))
        if rp <= 0:
            continue
        qoh, on_order = _num(builder.get(d, "QuantityOnHand")), _num(builder.get(d, "QuantityOnOrder"))
        if qoh > rp:
            continue
        vendor = builder.get(d, "PrefVendorRef")
        out.append({"record_id": r.record_id, "entity": r.entity, "qb_id": r.qb_id, "name": r.name,
                    "desc": builder.get(d, "PurchaseDesc") or builder.get(d, "SalesDesc"),
                    "qoh": qoh, "reorder_point": rp, "on_order": on_order,
                    "suggested": max(1, math.ceil(rp * 2 - qoh - on_order)),
                    "cost": _num(builder.get(d, "PurchaseCost")),
                    "vendor": vendor if isinstance(vendor, dict) else None,
                    "covered": qoh + on_order > rp})
    out.sort(key=lambda x: (x["covered"], x["qoh"] - x["reorder_point"]))
    return {"items": out, "count": len(out), "uncovered": sum(1 for x in out if not x["covered"])}


# ---------------------------------------------------------------- smart forms

PRICE_PATHS = ("SalesPrice", "SalesAndPurchase/SalesPrice", "SalesOrPurchase/Price")
COST_PATHS = ("PurchaseCost", "SalesAndPurchase/PurchaseCost", "SalesOrPurchase/Price")
SDESC_PATHS = ("SalesDesc", "SalesAndPurchase/SalesDesc", "SalesOrPurchase/Desc", "ItemDesc")
PDESC_PATHS = ("PurchaseDesc", "SalesAndPurchase/PurchaseDesc", "SalesOrPurchase/Desc", "ItemDesc")


def _first(d: dict, paths: tuple[str, ...]):
    for p in paths:
        v = builder.get(d, p)
        if v not in (None, ""):
            return v
    return None


@router.get("/lookup/{target}/{list_id}")
def lookup(target: str, list_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user),
           co: Company = Depends(get_company)):
    """Details of a picked customer, vendor or item so the form can fill terms, address, price, stock."""
    from ..qb.registry import REF_GROUPS

    keys = REF_GROUPS.get(target, [target])
    if not all(k in BY_KEY for k in keys):
        raise HTTPException(404, "Unknown picker")
    rec = db.query(QBRecord).filter(QBRecord.company_id == co.company_id, QBRecord.entity.in_(keys),
                                    QBRecord.qb_id == list_id).first()
    if not rec:
        raise HTTPException(404, "Not found")
    if not can(user, f"{BY_KEY[rec.entity].module}.view"):
        raise HTTPException(403, "No access")
    d = rec.data or {}

    def ref(p):
        v = builder.get(d, p)
        return {"ListID": v.get("ListID"), "FullName": v.get("FullName")} if isinstance(v, dict) and v.get("ListID") else None

    out = {"entity": rec.entity, "record_id": rec.record_id, "name": rec.name, "is_active": rec.is_active}
    if rec.entity in ("customer", "vendor"):
        form = builder.to_form(BY_KEY[rec.entity], d)["values"]
        out.update(terms=ref("TermsRef"), bill_address=form.get("BillAddress") or form.get("VendorAddress"),
                   ship_address=form.get("ShipAddress"), sales_rep=ref("SalesRepRef"), price_level=ref("PriceLevelRef"),
                   balance=_num(builder.get(d, "TotalBalance") if rec.entity == "customer" else builder.get(d, "Balance")),
                   credit_limit=_num(builder.get(d, "CreditLimit")) or None, email=builder.get(d, "Email"))
    else:
        qoh = builder.get(d, "QuantityOnHand")
        out.update(sales_price=_num(_first(d, PRICE_PATHS)) if _first(d, PRICE_PATHS) is not None else None,
                   cost=_num(_first(d, COST_PATHS)) if _first(d, COST_PATHS) is not None else None,
                   sales_desc=_first(d, SDESC_PATHS), purchase_desc=_first(d, PDESC_PATHS),
                   qoh=_num(qoh) if qoh is not None else None, reorder_point=_num(builder.get(d, "ReorderPoint")) or None,
                   pref_vendor=ref("PrefVendorRef"))
    return out


@router.get("/duplicates/{entity}")
def duplicates(entity: str, ref: str | None = None, party_id: str | None = None, amount: float | None = None,
               txn_date: date | None = None, exclude: int | None = None, db: Session = Depends(get_db),
               user: User = Depends(get_current_user), co: Company = Depends(get_company)):
    """Records that look like the one being entered: same number, or same party + amount within a week."""
    ent = BY_KEY.get(entity)
    if not ent or ent.kind != "txn":
        raise HTTPException(404, "Unknown transaction type")
    _need(user, ent.module)
    q = db.query(QBRecord).filter(QBRecord.company_id == co.company_id, QBRecord.entity == entity, QBRecord.deleted.is_(False))
    if exclude:
        q = q.filter(QBRecord.record_id != exclude)
    conds = []
    if ref and ref.strip():
        same_ref = QBRecord.name == ref.strip()
        conds.append(same_ref if not party_id or entity in ("invoice", "sales_receipt", "estimate", "sales_order",
                                                             "credit_memo", "purchase_order")
                     else (same_ref & (QBRecord.party_id == party_id)))
    if party_id and amount:
        c = (QBRecord.party_id == party_id) & (QBRecord.amount.between(amount - 0.005, amount + 0.005))
        if txn_date:
            c = c & QBRecord.txn_date.between(txn_date - timedelta(days=7), txn_date + timedelta(days=7))
        conds.append(c)
    if not conds:
        return []
    rows = q.filter(or_(*conds)).order_by(QBRecord.txn_date.desc().nullslast()).limit(5).all()
    return [{"record_id": r.record_id, "name": r.name, "party_name": r.party_name, "txn_date": r.txn_date,
             "amount": _num(r.amount), "reason": "same number" if ref and r.name == ref.strip() else "same name and amount"}
            for r in rows]


# ---------------------------------------------------------------- record activity

@router.get("/activity/{entity}/{record_id}")
def activity(entity: str, record_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user),
             co: Company = Depends(get_company)):
    """Who changed, e-mailed or attached what on a record, newest first."""
    ent = BY_KEY.get(entity)
    if not ent:
        raise HTTPException(404, "Unknown entity")
    _need(user, ent.module)
    rec = db.get(QBRecord, record_id)
    if not rec or rec.entity != entity or rec.company_id != co.company_id:
        raise HTTPException(404, "Record not found")
    events = []
    writes = db.query(QBWrite).filter(QBWrite.company_id == co.company_id, QBWrite.kind != "report",
                                      or_(QBWrite.entity_id == record_id, QBWrite.summary.like(f"%#{rec.qb_id})%"),
                                          QBWrite.qb_ref == rec.qb_id)).all()
    for w in writes:
        if (w.payload or {}).get("entity") not in (None, entity):
            continue
        who = (w.requester.full_name or w.requester.username) if w.requester else None
        events.append({"at": w.requested_at, "who": who, "kind": w.kind, "text": w.summary, "status": w.status,
                       "error": w.error_message, "write_id": w.write_id})
    logs = db.query(AuditLog).filter(AuditLog.entity.in_(("email", "attachment")),
                                     AuditLog.created_at.isnot(None)).order_by(AuditLog.audit_id.desc()).limit(2000).all()
    for a in logs:
        nv = a.new_value or {}
        ov = a.old_value or {}
        if a.entity == "email" and a.entity_id == str(record_id) and nv.get("company_id", co.company_id) == co.company_id:
            events.append({"at": a.created_at, "who": a.user.full_name or a.user.username if a.user else None, "kind": "email",
                           "text": f"E-mailed to {', '.join(nv.get('to') or [])}", "status": "done"})
        elif a.entity == "attachment" and (nv.get("qb_id") or ov.get("qb_id")) == rec.qb_id \
                and (nv.get("entity") or ov.get("entity")) == entity:
            events.append({"at": a.created_at, "who": a.user.full_name or a.user.username if a.user else None,
                           "kind": "attachment",
                           "text": f"{'Attached' if a.action == 'upload' else 'Removed'} {nv.get('file') or ov.get('file')}",
                           "status": "done"})
    d = rec.data or {}
    for path, label in (("TimeModified", "Last changed in QuickBooks"), ("TimeCreated", "Created in QuickBooks")):
        t = builder.get(d, path)
        if t:
            try:
                events.append({"at": datetime.fromisoformat(str(t)), "who": None, "kind": "qb", "text": label, "status": "done"})
            except ValueError:
                pass
    events.sort(key=lambda e: e["at"].timestamp() if hasattr(e["at"], "timestamp") else 0, reverse=True)
    return events[:100]


# ---------------------------------------------------------------- daily summary

def build_digest(db: Session, user: User, companies: list[Company]) -> tuple[str, str] | None:
    """Plain-text summary of yesterday and what needs attention today, for every company the user can see."""
    today = date.today()
    yesterday = today - timedelta(days=1)
    parts = []
    for co in companies:
        lines = []
        q = db.query(QBRecord).filter(QBRecord.company_id == co.company_id, QBRecord.deleted.is_(False))
        if can(user, "sales.view"):
            sold = q.filter(QBRecord.entity.in_(("invoice", "sales_receipt")), QBRecord.txn_date == yesterday).all()
            got = q.filter(QBRecord.entity == "receive_payment", QBRecord.txn_date == yesterday).all()
            lines.append(f"  Sales yesterday:        {sum(_num(r.amount) for r in sold):>16,.2f}  ({len(sold)} documents)")
            lines.append(f"  Payments received:      {sum(_num(r.amount) for r in got):>16,.2f}  ({len(got)})")
            ar = [_doc_row(r, today) for r in _open_docs(db, co, "invoice")]
            late = [x for x in ar if x["bucket"] != "current"]
            lines.append(f"  Customers owe:          {sum(x['open'] for x in ar):>16,.2f}")
            lines.append(f"  ...of which overdue:    {sum(x['open'] for x in late):>16,.2f}  ({len(late)} invoices)")
        if can(user, "purchasing.view"):
            ap = [_doc_row(r, today) for r in _open_docs(db, co, "bill")]
            due_week = [x for x in ap if x["due_date"] and x["due_date"] <= today + timedelta(days=7)]
            lines.append(f"  We owe vendors:         {sum(x['open'] for x in ap):>16,.2f}")
            lines.append(f"  Bills due within 7 days:{sum(x['open'] for x in due_week):>16,.2f}  ({len(due_week)} bills)")
        if can(user, "inventory.view") or can(user, "lists.view"):
            low = 0
            for r in q.filter(QBRecord.entity.in_(STOCK_ITEMS), QBRecord.is_active.is_(True)).all():
                rp = _num(builder.get(r.data or {}, "ReorderPoint"))
                if rp > 0 and _num(builder.get(r.data or {}, "QuantityOnHand")) <= rp:
                    low += 1
            lines.append(f"  Items to reorder:       {low:>16}")
        pending = db.query(QBWrite).filter(QBWrite.company_id == co.company_id, QBWrite.status == "pending").count()
        failed = db.query(QBWrite).filter(QBWrite.company_id == co.company_id, QBWrite.status == "failed").count()
        lines.append(f"  Changes awaiting approval: {pending}" + (f"   Failed changes: {failed}" if failed else ""))
        parts.append(f"{co.name}\n" + "\n".join(lines))
    if not parts:
        return None
    subject = f"Synex QB Portal - daily summary {today:%d %b %Y}"
    body = (f"Good morning {user.full_name or user.username},\n\nHere is your summary for {today:%A, %d %B %Y}.\n\n"
            + "\n\n".join(parts)
            + "\n\nOpen the portal for details. You can turn this e-mail off under Account & security.\n")
    return subject, body


@router.get("/digest")
def digest_preview(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = build_digest(db, user, accessible_companies(db, user))
    return {"subject": d[0], "body": d[1]} if d else {"subject": None, "body": "Nothing to report."}


@router.post("/digest/send")
def digest_send(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = build_digest(db, user, accessible_companies(db, user))
    if not d:
        raise HTTPException(400, "Nothing to report")
    try:
        send_email_now([user.email], *d)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    audit.log(db, user.user_id, "user", user.user_id, "digest_sent", None, {"to": user.email})
    db.commit()
    return {"message": f"Sent to {user.email}"}


def send_daily_digests(db: Session) -> int:
    """Called by the scheduler once a day. Returns how many e-mails were sent."""
    sent = 0
    today = date.today().isoformat()
    for u in db.query(User).filter(User.is_active.is_(True), User.receive_alerts.is_(True)).all():
        prefs = dict(u.prefs or {})
        if prefs.get("daily_summary") is False or prefs.get("digest_sent") == today or not u.email:
            continue
        d = build_digest(db, u, accessible_companies(db, u))
        if not d:
            continue
        try:
            send_email_now([u.email], *d)
        except RuntimeError:
            return sent  # mail not configured / server down: try again on the next tick
        prefs["digest_sent"] = today
        u.prefs = prefs
        db.commit()
        sent += 1
    return sent

