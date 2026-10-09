"""Login throttling, required two-step verification, signing out everywhere, password rules, headers, uploads."""

import pyotp
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.routers import auth as auth_router

client = TestClient(app)
client.__enter__()


def login(u, p):
    return client.post("/api/auth/login", data={"username": u, "password": p})


ADMIN = {"Authorization": "Bearer " + login("admin", "Admin@123").json()["access_token"], "X-Company-Id": "1"}


def make(username, role="viewer", password="Blue-Mango-73"):
    r = client.post("/api/users", headers=ADMIN, json={"username": username, "email": f"{username}@synex.lk",
                                                       "password": password, "role_name": role, "company_ids": [1]})
    assert r.status_code == 201, r.text
    return r.json()["user_id"]


def test_password_rules():
    for bad, why in (("short1abc", "10 characters"), ("onlyletters", "letters and numbers"), ("Password123!", "too common"),
                     ("Synex@123456", "too common"), ("pwrule-2026x", "name")):
        r = client.post("/api/users", headers=ADMIN, json={"username": "pwrule", "email": "pwrule@synex.lk",
                                                           "password": bad, "role_name": "viewer"})
        assert r.status_code == 422 and why in r.text, (bad, r.text)
    make("pwrule")


def test_login_lockout_per_account():
    make("lockme")
    auth_router._login_failures.clear()
    for _ in range(get_settings().login_max_failures):
        assert login("lockme", "nope").status_code == 401
    assert login("lockme", "Blue-Mango-73").status_code == 429  # even the right password waits
    auth_router._login_failures.clear()
    assert login("lockme", "Blue-Mango-73").status_code == 200


def test_required_2fa_for_approvers():
    make("boss", role="admin")
    make("viewer2")  # created before the rule is on (the test admin has no 2FA)
    s = get_settings()
    s.require_2fa = "approvers"
    try:
        h = {"Authorization": "Bearer " + login("boss", "Blue-Mango-73").json()["access_token"]}
        me = client.get("/api/auth/me", headers=h).json()
        assert me["must_setup_2fa"] is True
        assert client.get("/api/users", headers=h).status_code == 403  # blocked until 2FA is set up
        secret = client.post("/api/auth/2fa/setup", headers=h).json()["secret"]
        assert client.post("/api/auth/2fa/enable", headers=h, json={"code": pyotp.TOTP(secret).now()}).status_code == 200
        assert client.get("/api/users", headers=h).status_code == 200
        # cannot be turned off while the role requires it
        assert client.post("/api/auth/2fa/disable", headers=h,
                           json={"password": "Blue-Mango-73", "code": pyotp.TOTP(secret).now()}).status_code == 400
        # viewers are not forced
        hv = {"Authorization": "Bearer " + login("viewer2", "Blue-Mango-73").json()["access_token"]}
        assert client.get("/api/auth/me", headers=hv).json()["must_setup_2fa"] is False
    finally:
        s.require_2fa = "off"


def test_sign_out_everywhere_and_admin_reset():
    uid = make("roamer")
    h1 = {"Authorization": "Bearer " + login("roamer", "Blue-Mango-73").json()["access_token"]}
    h2 = {"Authorization": "Bearer " + login("roamer", "Blue-Mango-73").json()["access_token"]}
    new = client.post("/api/auth/sign-out-everywhere", headers=h1).json()["access_token"]
    assert client.get("/api/auth/me", headers=h2).status_code == 401
    h3 = {"Authorization": "Bearer " + new}
    assert client.get("/api/auth/me", headers=h3).status_code == 200
    assert client.patch(f"/api/users/{uid}", headers=ADMIN, json={"password": "Fresh-Kiwi-4410"}).status_code == 200
    assert client.get("/api/auth/me", headers=h3).status_code == 401  # admin reset signs the user out


def test_security_headers_and_docs_off():
    r = client.get("/api/health")
    assert r.headers["x-frame-options"] == "DENY" and r.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert client.get("/api/docs").status_code in (404, 200) and client.get("/api/openapi.json").status_code != 200 \
        or get_settings().enable_api_docs


def test_attachment_allow_list():
    from app.database import SessionLocal
    from app.models import QBRecord
    with SessionLocal() as db:
        rec = db.query(QBRecord).filter_by(company_id=1, entity="customer").first()
    assert rec is not None
    bad = client.post(f"/api/files/attachments/customer/{rec.record_id}", headers=ADMIN,
                      files={"file": ("tool.exe.svg", b"<svg/>", "image/svg+xml")})
    assert bad.status_code == 422
    ok = client.post(f"/api/files/attachments/customer/{rec.record_id}", headers=ADMIN,
                     files={"file": ("quote.pdf", b"%PDF-1.4 test", "application/pdf")})
    assert ok.status_code == 201, ok.text


def test_static_files_get_real_content_types(tmp_path, monkeypatch):
    import mimetypes
    assert mimetypes.guess_type("x.woff2")[0] == "font/woff2"
    assert mimetypes.guess_type("x.js")[0] == "text/javascript"
