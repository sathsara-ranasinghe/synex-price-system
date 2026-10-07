from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require
from ..models import Company, Role, User
from ..permissions import USERS_MANAGE
from ..schemas import Me, PasswordChange, Token, UserCreate, UserOut, UserUpdate
from ..security import create_access_token, hash_password, verify_password
from ..services import audit

router = APIRouter(prefix="/api", tags=["Auth & users"])


def _me(u: User) -> Me:
    return Me(user_id=u.user_id, username=u.username, full_name=u.full_name, email=u.email,
              role=u.role.role_name, permissions=u.role.permissions or [])


def _user_out(u: User) -> UserOut:
    return UserOut(user_id=u.user_id, username=u.username, full_name=u.full_name, email=u.email,
                   role_name=u.role.role_name, is_active=u.is_active, receive_alerts=u.receive_alerts,
                   created_at=u.created_at, company_ids=[c.company_id for c in u.companies])


def _companies(db: Session, ids: list[int]) -> list[Company]:
    found = db.query(Company).filter(Company.company_id.in_(ids)).all() if ids else []
    if len(found) != len(set(ids)):
        raise HTTPException(400, "Unknown company")
    return found


@router.post("/auth/login", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form.username).first()
    if not user or not user.is_active or not verify_password(form.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect username or password")
    audit.log(db, user.user_id, "user", user.user_id, "login")
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
    if data.get("is_active") is False and u.user_id == actor.user_id:
        raise HTTPException(400, "You cannot deactivate yourself")
    for k, v in data.items():
        setattr(u, k, v)
    new = audit.snapshot(u)
    old.pop("password_hash"), new.pop("password_hash")
    audit.log(db, actor.user_id, "user", u.user_id, "update", old, new)
    db.commit()
    db.refresh(u)
    return _user_out(u)
