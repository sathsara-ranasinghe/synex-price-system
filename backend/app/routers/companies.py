"""QuickBooks company files the portal works with (one Web Connector login per company)."""

import re
from datetime import datetime

from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import accessible_companies, get_current_user, require
from ..models import Company, QBRecord, SyncLog, User
from ..permissions import SYNC_RUN, USERS_MANAGE
from ..qbwc.soap import build_qwc, company_qbwc_url
from ..security import hash_password
from ..services import audit

router = APIRouter(prefix="/api/companies", tags=["Companies"])


class CompanyOut(BaseModel):
    company_id: int
    name: str
    qbwc_username: str
    app_name: str
    qbwc_url: str | None
    effective_qbwc_url: str = ""
    company_file: str | None
    is_active: bool
    created_at: datetime
    last_sync: datetime | None = None
    records: int = 0


class CompanyIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    qbwc_username: str = Field(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9_.\-]+$")
    qbwc_password: str = Field(min_length=8)


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    qbwc_password: str | None = Field(default=None, min_length=8)
    is_active: bool | None = None
    app_name: str | None = Field(default=None, min_length=3, max_length=100)
    qbwc_url: str | None = None  # "" = use the server default (QBWC_PUBLIC_URL)
    reset_company_file: bool = False  # allow the company to bind to a different .qbw on its next sync


def check_qbwc_url(url: str) -> str:
    """Web Connector only accepts HTTPS, except plain HTTP to localhost."""
    url = url.strip().rstrip("/")
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise HTTPException(422, "Enter a full address such as https://portal.synex.lk/qbwc")
    if u.scheme == "http" and u.hostname not in ("localhost", "127.0.0.1"):
        raise HTTPException(422, "Web Connector needs HTTPS unless the address is localhost")
    if not u.path.endswith("/qbwc"):
        url += "/qbwc"
    return url


def _out(db: Session, c: Company, details: bool) -> CompanyOut:
    out = CompanyOut.model_validate(c, from_attributes=True)
    out.effective_qbwc_url = company_qbwc_url(c)
    if details:
        out.last_sync = db.query(func.max(SyncLog.started_at)).filter_by(company_id=c.company_id, status="success").scalar()
        out.records = db.query(QBRecord).filter_by(company_id=c.company_id, deleted=False).count()
    return out


@router.get("/mine", response_model=list[CompanyOut])
def my_companies(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Companies the signed-in user can switch between."""
    return [_out(db, c, False) for c in accessible_companies(db, user)]


@router.get("/url-suggestion")
def url_suggestion(request: Request, _: User = Depends(require(USERS_MANAGE))):
    """Web Connector address based on how this browser reached the portal."""
    host = request.url.hostname or "localhost"
    port = request.url.port
    if host in ("localhost", "127.0.0.1"):
        url = f"http://localhost{':' + str(port) if port else ''}/qbwc"
        note = "QuickBooks must run on the same computer as the portal (or reach it through a port forward)."
    else:
        url = f"https://{host}/qbwc"
        note = "Web Connector needs HTTPS on this address (a certificate for " + host + ")."
    return {"url": url, "note": note}


@router.get("", response_model=list[CompanyOut])
def list_companies(db: Session = Depends(get_db), _: User = Depends(require(USERS_MANAGE))):
    return [_out(db, c, True) for c in db.query(Company).order_by(Company.name).all()]


@router.post("", response_model=CompanyOut, status_code=201)
def create_company(body: CompanyIn, db: Session = Depends(get_db), user: User = Depends(require(USERS_MANAGE))):
    if db.query(Company).filter(func.lower(Company.qbwc_username) == body.qbwc_username.lower()).first():
        raise HTTPException(409, "That Web Connector username is already used by another company")
    app_name = "Synex QB Portal - " + re.sub(r"[^A-Za-z0-9 ]", "", body.name)[:60]
    if db.query(Company).filter_by(app_name=app_name).first():
        app_name += f" {db.query(Company).count() + 1}"
    c = Company(name=body.name, qbwc_username=body.qbwc_username, qbwc_password_hash=hash_password(body.qbwc_password),
                app_name=app_name)
    db.add(c)
    db.flush()
    audit.log(db, user.user_id, "company", c.company_id, "create", None, {"name": c.name, "qbwc_username": c.qbwc_username})
    db.commit()
    return _out(db, c, True)


@router.patch("/{company_id}", response_model=CompanyOut)
def update_company(company_id: int, body: CompanyUpdate, db: Session = Depends(get_db),
                   user: User = Depends(require(USERS_MANAGE))):
    c = db.get(Company, company_id)
    if not c:
        raise HTTPException(404, "Company not found")
    changes = {}
    if body.name:
        c.name = changes["name"] = body.name
    if body.qbwc_password:
        c.qbwc_password_hash = hash_password(body.qbwc_password)
        changes["qbwc_password"] = "changed"
    if body.is_active is not None:
        c.is_active = changes["is_active"] = body.is_active
    if body.app_name and body.app_name != c.app_name:
        if db.query(Company).filter(Company.app_name == body.app_name, Company.company_id != c.company_id).first():
            raise HTTPException(409, "Another company already uses that Web Connector app name")
        changes["app_name"] = f"{c.app_name} -> {body.app_name}"
        c.app_name = body.app_name
    if body.qbwc_url is not None:
        new = check_qbwc_url(body.qbwc_url) if body.qbwc_url.strip() else None
        if new != c.qbwc_url:
            changes["qbwc_url"] = f"{c.qbwc_url or 'default'} -> {new or 'default'}"
            c.qbwc_url = new
    if body.reset_company_file:
        changes["company_file"] = f"reset (was {c.company_file})"
        c.company_file = None
    audit.log(db, user.user_id, "company", c.company_id, "update", None, changes)
    db.commit()
    return _out(db, c, True)


@router.get("/{company_id}/qwc")
def download_qwc(company_id: int, poll_minutes: int = Query(5, ge=1, le=1440), db: Session = Depends(get_db),
                 user: User = Depends(require(SYNC_RUN))):
    c = next((x for x in accessible_companies(db, user) if x.company_id == company_id), None)
    if not c:
        raise HTTPException(404, "Company not found")
    fname = re.sub(r"[^A-Za-z0-9]+", "_", c.name).strip("_") or "company"
    return Response(build_qwc(c, poll_minutes), media_type="application/xml",
                    headers={"Content-Disposition": f"attachment; filename=Synex_{fname}.qwc"})
