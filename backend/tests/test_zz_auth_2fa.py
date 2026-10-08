"""E-mail sign-in and two-factor authentication (Google Authenticator / TOTP)."""

import pyotp
from fastapi.testclient import TestClient

from app.main import app
from app.routers import auth as auth_router

client = TestClient(app)
client.__enter__()
ADMIN = {"Authorization": "Bearer " + client.post("/api/auth/login", data={"username": "admin", "password": "Admin@123"}
                                                  ).json()["access_token"], "X-Company-Id": "1"}


def create(username: str, email: str):
    r = client.post("/api/users", headers=ADMIN, json={"username": username, "email": email, "password": "Passw0rd!",
                                                        "role_name": "viewer", "company_ids": [1]})
    assert r.status_code == 201, r.text
    return r.json()["user_id"]


def test_login_with_email_or_username():
    create("mailuser", "Mail.User@Synex.lk")
    for ident in ("mailuser", "mail.user@synex.lk", "MAIL.USER@SYNEX.LK"):
        r = client.post("/api/auth/login", data={"username": ident, "password": "Passw0rd!"}).json()
        assert r["access_token"] and not r["mfa_required"]
    assert client.post("/api/auth/login", data={"username": "mail.user@synex.lk", "password": "x"}).status_code == 401
    # e-mails must be unique because they sign people in
    assert client.post("/api/users", headers=ADMIN, json={"username": "other", "email": "MAIL.USER@synex.lk",
                       "password": "Passw0rd!", "role_name": "viewer"}).status_code == 409


def test_two_factor_full_cycle():
    uid = create("totpuser", "totp@synex.lk")
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", data={"username": "totp@synex.lk",
                                                                           "password": "Passw0rd!"}).json()["access_token"]}
    setup = client.post("/api/auth/2fa/setup", headers=h).json()
    assert setup["qr"].startswith("data:image/png;base64,") and "issuer=Synex%20QB%20Portal" in setup["otpauth_url"]
    totp = pyotp.TOTP(setup["secret"])
    assert client.post("/api/auth/2fa/enable", headers=h, json={"code": "000000"}).status_code == 400
    codes = client.post("/api/auth/2fa/enable", headers=h, json={"code": totp.now()}).json()["recovery_codes"]
    assert len(codes) == 8 and client.get("/api/auth/me", headers=h).json()["totp_enabled"] is True

    # password alone no longer signs in; the mfa token cannot call the API
    step1 = client.post("/api/auth/login", data={"username": "totpuser", "password": "Passw0rd!"}).json()
    assert step1["mfa_required"] and step1["access_token"] is None
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer " + step1["mfa_token"]}).status_code == 401
    assert client.post("/api/auth/login/verify", json={"mfa_token": step1["mfa_token"], "code": "123456"}).status_code == 401
    ok = client.post("/api/auth/login/verify", json={"mfa_token": step1["mfa_token"], "code": totp.now()}).json()
    assert ok["access_token"]
    # an access token cannot be used as an mfa token
    assert client.post("/api/auth/login/verify", json={"mfa_token": ok["access_token"], "code": totp.now()}).status_code == 401

    # recovery codes work once
    step1 = client.post("/api/auth/login", data={"username": "totpuser", "password": "Passw0rd!"}).json()
    assert client.post("/api/auth/login/verify", json={"mfa_token": step1["mfa_token"], "code": codes[0].lower()}).status_code == 200
    assert client.post("/api/auth/login/verify", json={"mfa_token": step1["mfa_token"], "code": codes[0]}).status_code == 401

    # lock-out after repeated wrong codes
    auth_router._failures.clear()
    for _ in range(auth_router.MAX_CODE_FAILURES):
        client.post("/api/auth/login/verify", json={"mfa_token": step1["mfa_token"], "code": "999999"})
    assert client.post("/api/auth/login/verify", json={"mfa_token": step1["mfa_token"], "code": totp.now()}).status_code == 429
    auth_router._failures.clear()

    # new recovery codes, then turning it off needs password + code
    assert len(client.post("/api/auth/2fa/recovery-codes", headers=h, json={"code": totp.now()}).json()["recovery_codes"]) == 8
    assert client.post("/api/auth/2fa/disable", headers=h, json={"password": "bad", "code": totp.now()}).status_code == 400
    assert client.post("/api/auth/2fa/disable", headers=h, json={"password": "Passw0rd!", "code": totp.now()}).status_code == 204
    assert client.post("/api/auth/login", data={"username": "totpuser", "password": "Passw0rd!"}).json()["access_token"]

    # admin can reset a user who lost the phone
    setup = client.post("/api/auth/2fa/setup", headers=h).json()
    client.post("/api/auth/2fa/enable", headers=h, json={"code": pyotp.TOTP(setup["secret"]).now()})
    assert client.patch(f"/api/users/{uid}", headers=ADMIN, json={"reset_2fa": True}).json()["totp_enabled"] is False
    assert client.post("/api/auth/login", data={"username": "totpuser", "password": "Passw0rd!"}).json()["access_token"]


def test_secret_is_encrypted_at_rest():
    from app.database import SessionLocal
    from app.models import User
    create("encuser", "enc@synex.lk")
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", data={"username": "encuser",
                                                                           "password": "Passw0rd!"}).json()["access_token"]}
    secret = client.post("/api/auth/2fa/setup", headers=h).json()["secret"]
    with SessionLocal() as db:
        stored = db.query(User).filter_by(username="encuser").one().totp_secret
    assert secret not in stored
