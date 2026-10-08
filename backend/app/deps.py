from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import Company, User
from .security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# What a user who still has to set up two-step verification may call (to reach the setup page).
SETUP_2FA_ALLOWED = ("/api/auth/", "/api/companies/mine", "/api/notifications/unread-count", "/api/sync/status", "/api/qb/meta")


def needs_2fa(user: User) -> bool:
    """Accounts that can approve, write directly or manage users must use two-step verification."""
    mode = get_settings().require_2fa
    if user.totp_enabled or mode == "off":
        return False
    if mode == "all":
        return True
    perms = user.role.permissions or []
    return user.role.role_name == "admin" or any(p.endswith((".approve", ".direct")) or p == "users.manage" for p in perms)


def get_current_user(request: Request, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    payload = decode_token(token, "access")  # an "mfa" token (password ok, code pending) is not enough
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.query(User).filter(User.username == payload.get("sub")).first()
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive or not found")
    if payload.get("ver", 0) != (user.token_version or 0):  # password changed / signed out everywhere
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Signed out - please sign in again")
    if needs_2fa(user) and not request.url.path.startswith(SETUP_2FA_ALLOWED):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Set up two-step verification first (Account & security)")
    return user


def require(permission: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if permission not in (user.role.permissions or []):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {permission}")
        return user

    return checker


def sees_all_companies(user: User) -> bool:
    return user.role.role_name == "admin"


def accessible_companies(db: Session, user: User) -> list[Company]:
    if sees_all_companies(user):
        return db.query(Company).filter_by(is_active=True).order_by(Company.name).all()
    return sorted((c for c in user.companies if c.is_active), key=lambda c: c.name)


def get_company(
    x_company_id: int | None = Header(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Company:
    """The company this request works on (X-Company-Id header), checked against the user's access."""
    companies = accessible_companies(db, user)
    if not companies:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have access to any company")
    if x_company_id is None:
        return companies[0]
    for c in companies:
        if c.company_id == x_company_id:
            return c
    raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this company")
