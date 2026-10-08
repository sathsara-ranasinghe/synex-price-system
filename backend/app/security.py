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


def create_access_token(subject: str, role: str, version: int = 0) -> str:
    """`ver` must match users.token_version; bumping it signs the user out everywhere."""
    return _token({"sub": subject, "role": role, "typ": "access", "ver": version}, get_settings().jwt_expire_minutes)


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


# ---------------------------------------------------------------- password policy

COMMON_PASSWORDS = {
    "password", "password1", "password123", "passw0rd", "p@ssw0rd", "p@ssword", "qwerty", "qwerty123", "qwertyuiop",
    "123456", "12345678", "123456789", "1234567890", "1q2w3e4r", "1qaz2wsx", "abc123", "abcd1234", "admin", "admin123",
    "admin@123", "administrator", "welcome", "welcome1", "welcome123", "letmein", "iloveyou", "changeme", "change-me",
    "synex", "synex123", "synex@123", "synexgroup", "quickbooks", "srilanka", "colombo",
}


def password_problem(password: str, username: str | None = None, email: str | None = None) -> str | None:
    """Why a new password is too weak, or None when it is fine."""
    if len(password) < 10:
        return "Use at least 10 characters"
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        return "Use both letters and numbers"
    low = password.lower()
    core = low.rstrip("0123456789!@#$%^&*.?_-")
    if low in COMMON_PASSWORDS or core in COMMON_PASSWORDS:
        return "This password is too common - choose another"
    for part in (username, (email or "").split("@")[0]):
        if part and len(part) >= 3 and part.lower() in low:
            return "Do not use your name or username in the password"
    return None


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
