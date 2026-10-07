from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import Company, User
from .security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.query(User).filter(User.username == payload.get("sub")).first()
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive or not found")
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
