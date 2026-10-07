from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..deps import get_company, get_current_user, require
from ..models import AuditLog, Company, Notification, QBWrite, SyncLog, SyncRequest, User
from ..permissions import AUDIT_VIEW, SYNC_RUN
from ..schemas import AuditOut, NotificationOut, Page, SyncLogOut, SyncRequestIn, SyncStatus
from ..services import audit

router = APIRouter(prefix="/api", tags=["Sync, notifications, audit"])


# ---------------------------------------------------------------- QuickBooks sync

def _sync_out(s: SyncLog) -> SyncLogOut:
    out = SyncLogOut.model_validate(s)
    st = s.state or {}
    steps = st.get("steps") or []
    out.progress = 100 if s.status != "running" else int(st.get("idx", 0) * 100 / max(1, len(steps)))
    return out


@router.get("/sync/status", response_model=SyncStatus)
def sync_status(db: Session = Depends(get_db), _: User = Depends(get_current_user), co: Company = Depends(get_company)):
    s = get_settings()
    ok = db.query(SyncLog).filter_by(status="success", company_id=co.company_id).order_by(SyncLog.started_at.desc()).first()
    running = (db.query(SyncLog).filter_by(status="running", company_id=co.company_id)
               .order_by(SyncLog.started_at.desc()).first())
    return SyncStatus(last_success=_sync_out(ok) if ok else None, running=_sync_out(running) if running else None,
                      pending_request=db.query(SyncRequest).filter_by(consumed=False, company_id=co.company_id).count() > 0,
                      pending_writes=db.query(QBWrite).filter(QBWrite.status == "approved",
                                                              QBWrite.company_id == co.company_id).count(),
                      run_every_minutes=s.qbwc_run_every_minutes, qbwc_url=s.qbwc_public_url)


@router.get("/sync/logs", response_model=list[SyncLogOut])
def sync_logs(limit: int = Query(50, le=500), db: Session = Depends(get_db), _: User = Depends(require(SYNC_RUN)),
              co: Company = Depends(get_company)):
    return [_sync_out(s) for s in db.query(SyncLog).filter_by(company_id=co.company_id)
            .order_by(SyncLog.started_at.desc()).limit(limit).all()]


@router.post("/sync/request", status_code=202)
def request_sync(body: SyncRequestIn, db: Session = Depends(get_db), user: User = Depends(require(SYNC_RUN)),
                 co: Company = Depends(get_company)):
    """QuickBooks Desktop cannot be called directly; the Web Connector picks this up on its next poll."""
    db.add(SyncRequest(company_id=co.company_id, requested_by=user.user_id, full_resync=body.full_resync))
    audit.log(db, user.user_id, "sync", None, "request", None, {"full_resync": body.full_resync})
    db.commit()
    return {"message": "Sync requested. It will start the next time Web Connector polls (within a few minutes)."}


# ---------------------------------------------------------------- notifications

@router.get("/notifications", response_model=list[NotificationOut])
def notifications(unread_only: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(Notification).filter_by(user_id=user.user_id)
    if unread_only:
        q = q.filter_by(is_read=False)
    return q.order_by(Notification.created_at.desc()).limit(100).all()


@router.get("/notifications/unread-count")
def unread_count(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"count": db.query(Notification).filter_by(user_id=user.user_id, is_read=False).count()}


@router.post("/notifications/read-all", status_code=204)
def read_all(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.query(Notification).filter_by(user_id=user.user_id, is_read=False).update({"is_read": True})
    db.commit()


@router.post("/notifications/{notification_id}/read", status_code=204)
def read_one(notification_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.query(Notification).filter_by(user_id=user.user_id, notification_id=notification_id).update({"is_read": True})
    db.commit()


# ---------------------------------------------------------------- audit log

@router.get("/audit", response_model=Page[AuditOut])
def audit_log(
    entity: str | None = None,
    user_id: int | None = None,
    action: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require(AUDIT_VIEW)),
):
    q = db.query(AuditLog)
    if entity:
        q = q.filter(AuditLog.entity == entity)
    if user_id:
        q = q.filter(AuditLog.user_id == user_id)
    if action:
        q = q.filter(AuditLog.action == action)
    total = q.count()
    rows = q.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    items = [AuditOut(audit_id=a.audit_id, username=a.user.username if a.user else "QuickBooks sync",
                      entity=a.entity, entity_id=a.entity_id, action=a.action, old_value=a.old_value,
                      new_value=a.new_value, created_at=a.created_at) for a in rows]
    return Page(items=items, total=total, page=page, page_size=page_size)
