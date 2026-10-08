import base64
import io
import secrets
import time

import pyotp
import qrcode
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require
from ..models import Company, Role, User
from ..permissions import USERS_MANAGE
from ..schemas import Me, PasswordChange, Token, UserCreate, UserOut, UserUpdate
from ..security import (create_access_token, create_mfa_token, decode_token, decrypt, encrypt, hash_password,
                        verify_password)
from ..services import audit

router = APIRouter(prefix="/api", tags=["Auth & users"])

ISSUER = "Synex QB Portal"
MAX_CODE_FAILURES = 5
LOCK_SECONDS = 300
_failures: dict[int, tuple[int, float]] = {}  # user_id -> (failed codes, locked until)


def _me(u: User) -> Me:
    return Me(user_id=u.user_id, username=u.username, full_name=u.full_name, email=u.email,
              role=u.role.role_name, permissions=u.role.permissions or [], totp_enabled=bool(u.totp_enabled))


def _user_out(u: User) -> UserOut:
    return UserOut(user_id=u.user_id, username=u.username, full_name=u.full_name, email=u.email,
                   role_name=u.role.role_name, is_active=u.is_active, receive_alerts=u.receive_alerts,
                   created_at=u.created_at, company_ids=[c.company_id for c in u.companies],
                   totp_enabled=bool(u.totp_enabled))


def _companies(db: Session, ids: list[int]) -> list[Company]:
    found = db.query(Company).filter(Company.company_id.in_(ids)).all() if ids else []
    if len(found) != len(set(ids)):
        raise HTTPException(400, "Unknown company")
    return found


def _email_taken(db: Session, email: str, except_id: int | None = None) -> bool:
    q = db.query(User).filter(func.lower(User.email) == email.lower())
    if except_id:
        q = q.filter(User.user_id != except_id)
    return q.first() is not None


# ---------------------------------------------------------------- two-factor helpers

def _new_recovery_codes() -> tuple[list[str], list[str]]:
    codes = [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}".upper() for _ in range(8)]
    return codes, [hash_password(c) for c in codes]


def _check_second_factor(db: Session, user: User, code: str) -> bool:
    """Authenticator code (30 s window, one step either side) or an unused recovery code (used up)."""
    code = (code or "").strip().replace(" ", "")
    secret = decrypt(user.totp_secret)
    if secret and code.isdigit() and len(code) == 6 and pyotp.TOTP(secret).verify(code, valid_window=1):
        return True
    for i, h in enumerate(user.recovery_codes or []):
        if verify_password(code.upper(), h):
            user.recovery_codes = [x for j, x in enumerate(user.recovery_codes) if j != i]
            audit.log(db, user.user_id, "user", user.user_id, "recovery_code_used", None,
                      {"remaining": len(user.recovery_codes)})
            return True
    return False


def _locked(user_id: int) -> bool:
    fails, until = _failures.get(user_id, (0, 0))
    return until > time.time()


def _register_failure(user_id: int) -> None:
    fails, _ = _failures.get(user_id, (0, 0))
    fails += 1
    _failures[user_id] = (0, time.time() + LOCK_SECONDS) if fails >= MAX_CODE_FAILURES else (fails, 0)


# ---------------------------------------------------------------- login

@router.post("/auth/login", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Sign in with username OR e-mail. With two-factor on, returns an mfa_token for /auth/login/verify."""
    ident = form.username.strip()
    user = db.query(User).filter(or_(User.username == ident, func.lower(User.email) == ident.lower())).first()
    if not user or not user.is_active or not verify_password(form.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect e-mail / username or password")
    if user.totp_enabled:
        return Token(mfa_required=True, mfa_token=create_mfa_token(user.username))
    audit.log(db, user.user_id, "user", user.user_id, "login")
    db.commit()
    return Token(access_token=create_access_token(user.username, user.role.role_name))


class VerifyIn(BaseModel):
    mfa_token: str
    code: str = Field(min_length=6, max_length=12)


@router.post("/auth/login/verify", response_model=Token)
def login_verify(body: VerifyIn, db: Session = Depends(get_db)):
    payload = decode_token(body.mfa_token, "mfa")
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign-in expired, enter your password again")
    user = db.query(User).filter_by(username=payload.get("sub")).first()
    if not user or not user.is_active or not user.totp_enabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign-in expired, enter your password again")
    if _locked(user.user_id):
        raise HTTPException(429, "Too many wrong codes. Wait 5 minutes and try again.")
    if not _check_second_factor(db, user, body.code):
        _register_failure(user.user_id)
        audit.log(db, user.user_id, "user", user.user_id, "2fa_failed")
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong authenticator code")
    _failures.pop(user.user_id, None)
    audit.log(db, user.user_id, "user", user.user_id, "login", None, {"2fa": True})
    db.commit()
    return Token(access_token=create_access_token(user.username, user.role.role_name))


@router.get("/auth/me", response_model=Me)
def me(user: User = Depends(get_current_user)):
    return _me(user)


@router.post("/auth/change-password", status_code=204)
def change_password(body: PasswordChange, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    audit.log(db, user.user_id, "user", user.user_id, "password_change")
    db.commit()


# ---------------------------------------------------------------- personal preferences

PREF_KEYS = {"columns", "views", "daily_summary"}


@router.get("/auth/prefs")
def get_prefs(user: User = Depends(get_current_user)):
    p = user.prefs or {}
    return {"columns": p.get("columns") or {}, "views": p.get("views") or {}, "daily_summary": p.get("daily_summary", True)}


@router.put("/auth/prefs")
def put_prefs(body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Merge list columns {entity: [paths]}, saved views {entity: [{name, params}]} and daily_summary on/off."""
    unknown = set(body) - PREF_KEYS
    if unknown:
        raise HTTPException(422, f"Unknown preference: {', '.join(sorted(unknown))}")
    if "columns" in body and not (isinstance(body["columns"], dict)
                                  and all(isinstance(v, list) and len(v) <= 60 for v in body["columns"].values())):
        raise HTTPException(422, "columns must be {entity: [field paths]}")
    if "views" in body and not (isinstance(body["views"], dict)
                                and all(isinstance(v, list) and len(v) <= 30 for v in body["views"].values())):
        raise HTTPException(422, "views must be {entity: [up to 30 views]}")
    if "daily_summary" in body and not isinstance(body["daily_summary"], bool):
        raise HTTPException(422, "daily_summary must be true or false")
    if len(str(body)) > 50_000:
        raise HTTPException(413, "Preferences too large")
    user.prefs = {**(user.prefs or {}), **body}
    db.commit()
    return get_prefs(user)


# ---------------------------------------------------------------- two-factor setup (own account)

class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=12)


class DisableIn(BaseModel):
    password: str
    code: str = Field(min_length=6, max_length=12)


@router.post("/auth/2fa/setup")
def twofa_setup(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Start setup: a new secret + QR code to scan with Google Authenticator. Not active until confirmed."""
    if user.totp_enabled:
        raise HTTPException(409, "Two-factor authentication is already on")
    secret = pyotp.random_base32()
    user.totp_secret = encrypt(secret)
    db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email or user.username, issuer_name=ISSUER)
    from qrcode.image.pil import PilImage

    img = qrcode.make(uri, box_size=8, border=2, image_factory=PilImage)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return {"secret": secret, "otpauth_url": uri, "qr": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()}


@router.post("/auth/2fa/enable")
def twofa_enable(body: CodeIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    secret = decrypt(user.totp_secret)
    if user.totp_enabled or not secret:
        raise HTTPException(409, "Start the setup first")
    if not pyotp.TOTP(secret).verify(body.code.strip(), valid_window=1):
        raise HTTPException(400, "That code is not right. Check the time on your phone and try the newest code.")
    codes, hashes = _new_recovery_codes()
    user.totp_enabled, user.recovery_codes = True, hashes
    audit.log(db, user.user_id, "user", user.user_id, "2fa_enabled")
    db.commit()
    return {"recovery_codes": codes}


@router.post("/auth/2fa/recovery-codes")
def twofa_new_codes(body: CodeIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.totp_enabled or not _check_second_factor(db, user, body.code):
        raise HTTPException(400, "Wrong authenticator code")
    codes, hashes = _new_recovery_codes()
    user.recovery_codes = hashes
    audit.log(db, user.user_id, "user", user.user_id, "2fa_recovery_codes_renewed")
    db.commit()
    return {"recovery_codes": codes}


@router.post("/auth/2fa/disable", status_code=204)
def twofa_disable(body: DisableIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.totp_enabled:
        raise HTTPException(409, "Two-factor authentication is off")
    if not verify_password(body.password, user.password_hash) or not _check_second_factor(db, user, body.code):
        raise HTTPException(400, "Password or authenticator code is wrong")
    user.totp_enabled, user.totp_secret, user.recovery_codes = False, None, None
    audit.log(db, user.user_id, "user", user.user_id, "2fa_disabled")
    db.commit()


# ---------------------------------------------------------------- users (admin)

@router.get("/roles")
def roles(db: Session = Depends(get_db), _: User = Depends(require(USERS_MANAGE))):
    return [{"role_name": r.role_name, "permissions": r.permissions} for r in db.query(Role).all()]


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require(USERS_MANAGE))):
    return [_user_out(u) for u in db.query(User).order_by(User.username).all()]


def _role(db: Session, name: str) -> Role:
    role = db.query(Role).filter_by(role_name=name).first()
    if not role:
        raise HTTPException(400, f"Unknown role {name}")
    return role


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db), actor: User = Depends(require(USERS_MANAGE))):
    if db.query(User).filter_by(username=body.username).first():
        raise HTTPException(409, "Username already exists")
    if _email_taken(db, body.email):
        raise HTTPException(409, "Another user already has this e-mail (it is used to sign in)")
    u = User(username=body.username, full_name=body.full_name, email=body.email,
             password_hash=hash_password(body.password), role_id=_role(db, body.role_name).role_id,
             receive_alerts=body.receive_alerts)
    u.companies = _companies(db, body.company_ids)
    db.add(u)
    db.flush()
    audit.log(db, actor.user_id, "user", u.user_id, "create", None,
              {"username": u.username, "role": body.role_name})
    db.commit()
    db.refresh(u)
    return _user_out(u)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, db: Session = Depends(get_db),
                actor: User = Depends(require(USERS_MANAGE))):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    old = audit.snapshot(u)
    data = body.model_dump(exclude_unset=True)
    if "password" in data:
        u.password_hash = hash_password(data.pop("password"))
    if "role_name" in data:
        u.role_id = _role(db, data.pop("role_name")).role_id
    if "company_ids" in data:
        ids = data.pop("company_ids")
        if ids is not None:
            u.companies = _companies(db, ids)
    if data.pop("reset_2fa", False):
        u.totp_enabled, u.totp_secret, u.recovery_codes = False, None, None
        audit.log(db, actor.user_id, "user", u.user_id, "2fa_reset_by_admin")
    if data.get("email") and _email_taken(db, data["email"], u.user_id):
        raise HTTPException(409, "Another user already has this e-mail (it is used to sign in)")
    if data.get("is_active") is False and u.user_id == actor.user_id:
        raise HTTPException(400, "You cannot deactivate yourself")
    for k, v in data.items():
        setattr(u, k, v)
    new = audit.snapshot(u)
    for d in (old, new):
        for k in ("password_hash", "totp_secret", "recovery_codes", "prefs"):
            d.pop(k, None)
    audit.log(db, actor.user_id, "user", u.user_id, "update", old, new)
    db.commit()
    db.refresh(u)
    return _user_out(u)
