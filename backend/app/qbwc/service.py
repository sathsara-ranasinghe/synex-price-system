"""QuickBooks Web Connector session logic.

Flow (QBWC runs on the VPS next to QuickBooks Desktop 2024 and polls this server):

  authenticate  -> decide whether a sync is due; create a SyncLog with a ticket
  sendRequestXML -> return the next qbXML request (one step / one iterator page)
  receiveResponseXML -> store the data, advance the state, return % complete
  ... repeat until 100 ...
  closeConnection -> mark the SyncLog finished

The sync is due when the configured interval has passed since the last successful sync,
or when somebody pressed "Sync now" in the web app (a SyncRequest row).
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..config import get_settings
from ..services import audit
from ..models import Company, QBWrite, SyncCheckpoint, SyncLog, SyncRequest
from ..security import verify_password
from ..qb import store
from . import writes
from .parse import parse_all, parse_response
from .qbxml import STEP_BY_NAME, STEPS, build_request, envelope

WRITES_STEP = "writes"  # pseudo-step that runs approved qb_writes before the read steps
BATCH_STEP = "batch"  # pseudo-step: every incremental read in ONE qbXML message (fast, used once all steps have checkpoints)

log = logging.getLogger(__name__)

SERVER_VERSION = "Synex Price Management 1.0"
CHECKPOINT_MARGIN = timedelta(minutes=10)  # overlap so edits made during a sync are not missed


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------- authenticate

def authenticate(db: Session, username: str, password: str) -> list[str]:
    s = get_settings()
    # Each company has its own Web Connector login, so the username tells us which company is polling.
    company = db.query(Company).filter_by(qbwc_username=username, is_active=True).first()
    if company is None or not verify_password(password, company.qbwc_password_hash):
        return ["", "nvu"]  # not valid user
    cid = company.company_id

    # A sync left "running" (e.g. QB crashed) is closed so it does not block forever.
    for stale in db.query(SyncLog).filter(SyncLog.status == "running", SyncLog.company_id == cid).all():
        if _aware(stale.started_at) < _now() - timedelta(hours=2):
            stale.status, stale.finished_at = "failed", _now()
            stale.error_message = (stale.error_message or "") + "\nAbandoned (no response from Web Connector)."

    pending = db.query(SyncRequest).filter_by(consumed=False, company_id=cid).order_by(SyncRequest.request_id).all()
    last_ok = db.query(SyncLog).filter_by(status="success", company_id=cid).order_by(SyncLog.started_at.desc()).first()
    due = last_ok is None or _aware(last_ok.started_at) <= _now() - timedelta(minutes=s.qbwc_run_every_minutes)

    approved = [w.write_id for w in db.query(QBWrite).filter_by(status="approved", company_id=cid)
                .order_by(QBWrite.write_id)]
    if not pending and not due and not approved:
        db.commit()
        return ["none", "none"]  # nothing to do this poll

    full = any(r.full_resync for r in pending)
    for r in pending:
        r.consumed = True

    ticket = secrets.token_hex(16)
    started = _now()
    off = set(company.disabled_entities or [])
    steps = [st for st in STEPS if st.name not in off]
    since = {}
    have_all = True
    for step in steps:
        cp = None if full else db.get(SyncCheckpoint, (cid, step.name))
        have_all = have_all and cp is not None
        if cp:
            since[step.name] = (_aware(cp.last_synced_at) - CHECKPOINT_MARGIN).isoformat()
        elif step.kind != "list":  # transactions and deletions: limited history on the first sync
            since[step.name] = (started - timedelta(days=s.qbwc_history_days)).isoformat()
        else:
            since[step.name] = None  # first run: whole list

    db.add(SyncLog(
        company_id=cid,
        ticket=ticket,
        started_at=started,
        triggered_by="manual" if pending or (approved and not due) else "schedule",
        state={"steps": ([WRITES_STEP] if approved else []) + ([BATCH_STEP] if have_all else [st.name for st in steps]),
               "batch_steps": [st.name for st in steps] if have_all else [], "idx": 0,
               "writes": approved, "write_idx": 0, "write_phase": None, "iterator_id": None, "since": since,
               "page": 0, "warnings": [], "last_error": None},
    ))
    db.commit()
    # Path = Web Connector opens that company file; "" = use the file currently open in QuickBooks.
    return [ticket, company.company_file or ""]


# ---------------------------------------------------------------- send / receive

def _get(db: Session, ticket: str) -> SyncLog | None:
    return db.query(SyncLog).filter_by(ticket=ticket).first()


def _same_file(a: str, b: str) -> bool:
    return a.replace("/", "\\").strip().lower() == b.replace("/", "\\").strip().lower()


def _save_state(sync: SyncLog, **changes) -> None:
    state = dict(sync.state or {})
    state.update(changes)
    sync.state = state  # reassign so SQLAlchemy sees the JSON change


def send_request_xml(db: Session, ticket: str, company_file: str, major: str, minor: str) -> str:
    sync = _get(db, ticket)
    if not sync or sync.status != "running":
        return ""
    st = sync.state
    if st["idx"] >= len(st["steps"]):
        return ""
    if company_file and not sync.qb_company_file:
        sync.qb_company_file = company_file
        company = db.get(Company, sync.company_id)
        if company.company_file is None:  # first sync: this company is now bound to this file
            company.company_file = company_file
        elif _same_file(company.company_file, company_file) is False:
            sync.status, sync.finished_at = "failed", _now()
            sync.error_message = (f"Wrong company file open in QuickBooks: '{company_file}'. Company "
                                  f"'{company.name}' syncs with '{company.company_file}'. Nothing was read or written.")
            db.commit()
            return ""

    s = get_settings()
    version = s.qbxml_version
    try:  # never ask for a newer qbXML than this QuickBooks supports
        if major and float(f"{major}.{minor or 0}") < float(version):
            version = f"{major}.{minor or 0}"
    except ValueError:
        pass

    if st["steps"][st["idx"]] == WRITES_STEP:
        body = _next_write_request(db, sync)
        if body is not None:
            db.commit()
            return envelope(body, version)
        st = sync.state  # all writes done; continue with the first read step

    if st["steps"][st["idx"]] == BATCH_STEP:
        bodies = []
        for name in st.get("batch_steps", []):
            since = st["since"].get(name)
            bodies.append(build_request(STEP_BY_NAME[name], since=datetime.fromisoformat(since) if since else None,
                                        max_returned=s.qbwc_max_returned, iterator_id=None, request_id=name, batch=True))
        db.commit()
        return envelope("".join(bodies), version)

    step = STEP_BY_NAME[st["steps"][st["idx"]]]
    since = st["since"].get(step.name)
    body = build_request(
        step,
        since=datetime.fromisoformat(since) if since else None,
        max_returned=s.qbwc_max_returned,
        iterator_id=st.get("iterator_id"),
        request_id=f"{step.name}:{st.get('page', 0)}",
    )
    db.commit()
    return envelope(body, version)


def receive_response_xml(db: Session, ticket: str, response: str, hresult: str, message: str) -> int:
    sync = _get(db, ticket)
    if not sync or sync.status != "running":
        return -1
    st = sync.state

    if hresult:
        _save_state(sync, last_error=f"{hresult}: {message}")
        sync.status, sync.finished_at = "failed", _now()
        sync.error_message = f"QuickBooks returned an error ({hresult}): {message}"
        db.commit()
        return -101

    step_name = st["steps"][st["idx"]]
    if step_name == BATCH_STEP:
        _receive_batch(db, sync, response)
        _save_state(sync, idx=sync.state["idx"] + 1)
        done = sync.state["idx"] >= len(sync.state["steps"])
        if done:
            _finish(sync)
        db.commit()
        return 100 if done else 99
    if step_name == WRITES_STEP:
        _receive_write(db, sync, response)
        db.commit()
        return max(1, min(99, int(sync.state["idx"] * 100 / len(sync.state["steps"]))))
    try:
        parsed = parse_response(response)
        # statusCode 0 = OK, 1 = no matching records; anything else is a warning for this step
        _note_feature(db, sync.company_id, step_name, parsed.status_code, parsed.status_message)
        if parsed.status_code not in (0, 1):
            warn = f"{step_name}: [{parsed.status_code}] {parsed.status_message}"
            _save_state(sync, warnings=st.get("warnings", []) + [warn])
            log.warning("QB sync warning %s", warn)
        ins, upd = store.process(db, parsed.rets, sync.company_id)
        sync.records_inserted += ins
        sync.records_updated += upd
    except Exception as exc:  # keep the sync alive; record and move to the next step
        db.rollback()
        sync = _get(db, ticket)
        st = sync.state
        log.exception("Failed to process %s", step_name)
        _save_state(sync, warnings=st.get("warnings", []) + [f"{step_name}: {exc}"])
        parsed = None

    st = sync.state
    if parsed is not None and parsed.iterator_id and parsed.iterator_remaining > 0:
        _save_state(sync, iterator_id=parsed.iterator_id, page=st.get("page", 0) + 1)
    else:
        if parsed is not None and parsed.status_code in (0, 1):
            cp = db.get(SyncCheckpoint, (sync.company_id, step_name))
            if cp:
                cp.last_synced_at = sync.started_at
            else:
                db.add(SyncCheckpoint(company_id=sync.company_id, entity=step_name, last_synced_at=sync.started_at))
        _save_state(sync, idx=st["idx"] + 1, iterator_id=None, page=0)

    st = sync.state
    done = st["idx"] >= len(st["steps"])
    if done:
        _finish(sync)
    db.commit()
    if done:
        return 100
    # progress: whole steps done, plus a little for pages within the current step
    return max(1, min(99, int(st["idx"] * 100 / len(st["steps"]))))


def _receive_batch(db: Session, sync: SyncLog, response: str) -> None:
    """Store every response of a batched read; each successful step moves its checkpoint forward."""
    warnings = list(sync.state.get("warnings", []))
    try:
        responses = parse_all(response)
    except Exception as exc:
        log.exception("Could not parse batched response")
        _save_state(sync, warnings=warnings + [f"batch: {exc}"])
        return
    for parsed in responses:
        name = parsed.request_id or ""
        if name not in STEP_BY_NAME:
            continue
        _note_feature(db, sync.company_id, name, parsed.status_code, parsed.status_message)
        if parsed.status_code not in (0, 1):
            warnings.append(f"{name}: [{parsed.status_code}] {parsed.status_message}")
            continue
        try:
            ins, upd = store.process(db, parsed.rets, sync.company_id)
        except Exception as exc:
            log.exception("Failed to store %s", name)
            warnings.append(f"{name}: {exc}")
            continue
        sync.records_inserted += ins
        sync.records_updated += upd
        cp = db.get(SyncCheckpoint, (sync.company_id, name))
        if cp:
            cp.last_synced_at = sync.started_at
        else:
            db.add(SyncCheckpoint(company_id=sync.company_id, entity=name, last_synced_at=sync.started_at))
    _save_state(sync, warnings=warnings)


def _current_write(db: Session, sync: SyncLog) -> QBWrite | None:
    st = sync.state
    ids = st.get("writes") or []
    return db.get(QBWrite, ids[st["write_idx"]]) if st["write_idx"] < len(ids) else None


def _advance_write(sync: SyncLog) -> None:
    st = sync.state
    _save_state(sync, write_idx=st["write_idx"] + 1, write_phase=None, edit_sequence=None)
    if sync.state["write_idx"] >= len(st.get("writes") or []):
        _save_state(sync, idx=sync.state["idx"] + 1)


def _next_write_request(db: Session, sync: SyncLog) -> str | None:
    """Body of the next write request, skipping writes that cannot be built. None when there are no more."""
    while sync.state["steps"][sync.state["idx"]] == WRITES_STEP:
        w = _current_write(db, sync)
        if w is None or w.status not in ("approved", "sent"):
            _advance_write(sync)
            continue
        phase = writes.phase_for(w, sync.state)
        try:
            body = writes.build(db, w, phase, dict(sync.state))
        except Exception as exc:
            writes.mark_failed(db, w, str(exc))
            _save_state(sync, warnings=sync.state.get("warnings", []) + [f"write #{w.write_id}: {exc}"])
            _advance_write(sync)
            continue
        w.status, w.attempts = "sent", w.attempts + 1
        _save_state(sync, write_phase=phase)
        return body
    return None


def _receive_write(db: Session, sync: SyncLog, response: str) -> None:
    w = _current_write(db, sync)
    if w is None:
        _advance_write(sync)
        return
    state = dict(sync.state)
    phase = state.get("write_phase") or "send"
    try:
        nxt = writes.handle(db, w, phase, parse_response(response), state)
    except Exception as exc:
        db.rollback()
        sync, w = _get(db, sync.ticket), db.get(QBWrite, w.write_id)
        writes.mark_failed(db, w, str(exc))
        _save_state(sync, warnings=sync.state.get("warnings", []) + [f"write #{w.write_id} ({w.kind}): {exc}"])
        _advance_write(sync)
        return
    if nxt:  # e.g. query done -> now send the Mod with the fresh EditSequence
        w.status = "approved"
        _save_state(sync, write_phase=nxt, edit_sequence=state.get("edit_sequence"))
    else:
        audit.log(db, None, "qb_write", w.write_id, "written", None, {"kind": w.kind, "qb_ref": w.qb_ref})
        _advance_write(sync)


FEATURE_OFF_CODES = {3250, 3251, 3255, 3262}  # "feature not enabled / not available in this edition"


def _note_feature(db: Session, company_id: int, step: str, code: int, message: str) -> None:
    """Remember which entities this company file cannot use, so the portal can hide them."""
    company = db.get(Company, company_id)
    off = set(company.disabled_entities or [])
    unavailable = code in FEATURE_OFF_CODES or ("not enabled" in message.lower() and code not in (0, 1))
    if unavailable and step not in off:
        company.disabled_entities = sorted(off | {step})
    elif code in (0, 1) and step in off:
        company.disabled_entities = sorted(off - {step})


def _finish(sync: SyncLog) -> None:
    sync.finished_at = _now()
    warnings = (sync.state or {}).get("warnings") or []
    sync.status = "success"
    if warnings:
        sync.error_message = "\n".join(warnings)


def connection_error(db: Session, ticket: str, hresult: str, message: str) -> str:
    sync = _get(db, ticket)
    if sync and sync.status == "running":
        sync.status, sync.finished_at = "failed", _now()
        sync.error_message = f"Could not open QuickBooks company file ({hresult}): {message}"
        db.commit()
    return "done"


def get_last_error(db: Session, ticket: str) -> str:
    sync = _get(db, ticket)
    if not sync:
        return "Unknown ticket"
    return sync.error_message or (sync.state or {}).get("last_error") or "Sync finished"


def close_connection(db: Session, ticket: str) -> str:
    sync = _get(db, ticket)
    if not sync:
        return "OK"
    if sync.status == "running":  # QBWC closed before we finished
        sync.status, sync.finished_at = "failed", _now()
        sync.error_message = (sync.error_message or "") + "\nConnection closed before sync completed."
        db.commit()
    return f"Sync {sync.status}: {sync.records_inserted} new, {sync.records_updated} updated"
