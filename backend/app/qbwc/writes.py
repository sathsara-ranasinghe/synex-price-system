"""Approved changes (and report requests) the Web Connector sends to QuickBooks - the qb_writes outbox.

Edits need the record's current EditSequence. Our copy may be stale, so each edit runs in two phases
inside the same Web Connector session: "query" (read the record) then "send" (the Mod request).
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import Notification, QBRecord, QBReport, QBWrite
from ..qb import builder, store
from ..qb.registry import BY_KEY
from .parse import ParsedResponse


class WriteError(Exception):
    pass


def phase_for(w: QBWrite, state: dict) -> str:
    return state.get("write_phase") or ("query" if w.kind == "qb_mod" else "send")


def build(db: Session, w: QBWrite, phase: str, state: dict) -> str:
    """qbXML body for this write and phase."""
    p = w.payload or {}
    rid = f"w{w.write_id}:{phase}"
    if w.kind == "report":
        r = db.get(QBReport, w.entity_id)
        return builder.build_report(r.report_type, r.from_date, r.to_date, rid)
    ent = BY_KEY.get(p.get("entity", ""))
    if ent is None:
        raise WriteError(f"Unsupported change type {w.kind}")
    if phase == "query":
        return builder.build_query_by_id(ent, p["qb_id"], rid)
    if w.kind == "qb_add":
        return builder.build_add(ent, p.get("values") or {}, p.get("lines"), rid)
    if w.kind == "qb_mod":
        return builder.build_mod(ent, p["qb_id"], state["edit_sequence"], p.get("values") or {}, p.get("lines"), rid)
    if w.kind == "qb_delete":
        return builder.build_delete(ent, p["qb_id"], rid)
    if w.kind == "qb_void":
        return builder.build_void(ent, p["qb_id"], rid)
    raise WriteError(f"Unsupported change type {w.kind}")


def handle(db: Session, w: QBWrite, phase: str, parsed: ParsedResponse, state: dict) -> str | None:
    """Process QuickBooks' answer. Returns the next phase, or None when this write is finished."""
    if parsed.status_code != 0:
        raise WriteError(f"QuickBooks [{parsed.status_code}] {parsed.status_message}")
    ret = parsed.rets[0] if parsed.rets else None
    if ret is None:
        raise WriteError("QuickBooks returned no record")
    p = w.payload or {}

    if phase == "query":
        state["edit_sequence"] = ret.findtext("EditSequence")
        store.upsert(db, ret, w.company_id)  # refresh our copy while we have it
        return "send"

    if w.kind in ("qb_add", "qb_mod"):
        rec, _ = store.upsert(db, ret, w.company_id)
        w.qb_ref = (rec.name or rec.qb_id) if rec else None
        if rec:
            w.payload = {**p, "qb_id": rec.qb_id}
    elif w.kind == "qb_delete":
        db.query(QBRecord).filter_by(company_id=w.company_id, entity=p["entity"], qb_id=p["qb_id"]).update(
            {QBRecord.deleted: True})
        w.qb_ref = p["qb_id"]
    elif w.kind == "qb_void":
        w.qb_ref = p["qb_id"]
    elif w.kind == "report":
        r = db.get(QBReport, w.entity_id)
        r.result, r.status, r.finished_at = builder.parse_report(ret), "done", datetime.now(timezone.utc)
    w.status, w.sent_at, w.error_message = "done", datetime.now(timezone.utc), None
    return None


def mark_failed(db: Session, w: QBWrite, message: str) -> None:
    w.status, w.error_message, w.sent_at = "failed", message, datetime.now(timezone.utc)
    if w.kind == "report":
        r = db.get(QBReport, w.entity_id)
        if r:
            r.status, r.error_message = "failed", message
    elif w.requested_by:  # tell the person who asked for the change
        db.add(Notification(user_id=w.requested_by, type="qb_write_failed",
                            message=f"QuickBooks rejected: {w.summary}. {message}", link="/qb-changes"))
