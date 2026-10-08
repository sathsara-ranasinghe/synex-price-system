import base64
import hashlib
from datetime import datetime, timedelta, timezone

import bcrypt
from cryptography.fernet import Fernet, InvalidToken
from jose import JWTError, jwt

from .config import get_settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def _token(claims: dict, minutes: int) -> str:
    s = get_settings()
    claims = {**claims, "exp": datetime.now(timezone.utc) + timedelta(minutes=minutes)}
    return jwt.encode(claims, s.jwt_secret, algorithm=s.jwt_algorithm)


def create_access_token(subject: str, role: str) -> str:
    return _token({"sub": subject, "role": role, "typ": "access"}, get_settings().jwt_expire_minutes)


def create_mfa_token(subject: str) -> str:
    """Short-lived token proving the password was correct; only good for the authenticator-code step."""
    return _token({"sub": subject, "typ": "mfa"}, 5)


def decode_token(token: str, typ: str = "access") -> dict | None:
    s = get_settings()
    try:
        payload = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    except JWTError:
        return None
    return payload if payload.get("typ", "access") == typ else None


# ---------------------------------------------------------------- secrets at rest (2FA keys)

def _fernet() -> Fernet:
    key = hashlib.sha256(("synex-2fa:" + get_settings().jwt_secret).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:  # JWT_SECRET changed: 2FA has to be set up again (admin can reset it)
        return None
