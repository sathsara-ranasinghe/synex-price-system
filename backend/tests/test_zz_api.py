"""REST API: auth, users, roles, companies, per-module permissions, sync, notifications, audit, exports, PDFs.

Named test_zz_* so it runs after the Web Connector tests that expect an empty database."""

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Notification, QBRecord, QBWrite, User
from app.qb.registry import ENTITIES, MODULES

client = TestClient(app)
client.__enter__()  # run startup (tables, admin user) once for this module


def login(username: str, password: str) -> dict:
    r = client.post("/api/auth/login", data={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


ADMIN = {**login("admin", "Admin@123"), "X-Company-Id": "1"}


def make_user(name: str, perms: list[str], companies: list[int] | None = None) -> dict:
    role = f"r_{name}"
    client.post("/api/roles", headers=ADMIN, json={"role_name": role, "permissions": perms})
    r = client.post("/api/users", headers=ADMIN, json={"username": name, "email": f"{name}@x.lk", "password": "Blue-Mango-73",
                                                        "role_name": role, "company_ids": companies or [1]})
    assert r.status_code == 201, r.text
    return login(name, "Blue-Mango-73")


# ---------------------------------------------------------------- auth & users

def test_login_and_me():
    assert client.post("/api/auth/login", data={"username": "admin", "password": "nope"}).status_code == 401
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    me = client.get("/api/auth/me", headers=ADMIN).json()
    assert me["role"] == "admin" and "users.manage" in me["permissions"]


def test_change_password_and_deactivate():
    h = make_user("pwuser", ["sales.view"])
    assert client.post("/api/auth/change-password", headers=h,
                       json={"current_password": "wrong", "new_password": "NewBlue-Mango-73"}).status_code == 400
    r = client.post("/api/auth/change-password", headers=h,
                    json={"current_password": "Blue-Mango-73", "new_password": "NewBlue-Mango-73"})
    assert r.status_code == 200 and r.json()["access_token"]
    assert client.get("/api/auth/me", headers=h).status_code == 401  # other sessions are signed out
    h2 = login("pwuser", "NewBlue-Mango-73")
    uid = client.get("/api/auth/me", headers=h2).json()["user_id"]
    assert client.patch(f"/api/users/{uid}", headers=ADMIN, json={"is_active": False}).status_code == 200
    assert client.post("/api/auth/login", data={"username": "pwuser", "password": "NewBlue-Mango-73"}).status_code == 401
    assert client.get("/api/auth/me", headers=h2).status_code == 401  # old token stops working too


def test_user_rules():
    assert client.post("/api/users", headers=ADMIN, json={"username": "admin", "email": "a@x.lk", "password": "Blue-Mango-73",
                                                           "role_name": "viewer"}).status_code == 409
    assert client.post("/api/users", headers=ADMIN, json={"username": "badrole", "email": "a@x.lk", "password": "Blue-Mango-73",
                                                           "role_name": "no-such-role"}).status_code == 400
    assert client.post("/api/users", headers=ADMIN, json={"username": "short", "email": "a@x.lk", "password": "123",
                                                           "role_name": "viewer"}).status_code == 422
    admin_id = client.get("/api/auth/me", headers=ADMIN).json()["user_id"]
    assert client.patch(f"/api/users/{admin_id}", headers=ADMIN, json={"is_active": False}).status_code == 400
    h = make_user("nobody", ["sales.view"])
    assert client.get("/api/users", headers=h).status_code == 403


# ---------------------------------------------------------------- roles

def test_roles():
    groups = client.get("/api/permissions", headers=ADMIN).json()
    keys = {p["key"] for g in groups for p in g["permissions"]}
    assert {"sales.direct", "reports.view", "users.manage"} <= keys
    assert client.put("/api/roles/admin", headers=ADMIN, json={"role_name": "admin", "permissions": []}).status_code == 400
    assert client.post("/api/roles", headers=ADMIN, json={"role_name": "Bad Name!", "permissions": []}).status_code == 422
    client.post("/api/roles", headers=ADMIN, json={"role_name": "temp_role", "permissions": ["sales.view"]})
    assert client.post("/api/roles", headers=ADMIN, json={"role_name": "temp_role", "permissions": []}).status_code == 409
    assert client.delete("/api/roles/temp_role", headers=ADMIN).status_code == 204
    make_user("roleuser", ["sales.view"])
    assert client.delete("/api/roles/r_roleuser", headers=ADMIN).status_code == 409  # still assigned


# ---------------------------------------------------------------- per-module permissions

@pytest.mark.parametrize("module", [m for m in MODULES if m != "reports"])
def test_module_permissions(module):
    mine = [e for e in ENTITIES if e.module == module]
    other = next(e for e in ENTITIES if e.module != module)
    h = make_user(f"view_{module}", [f"{module}.view"])
    meta = client.get("/api/qb/meta", headers=h).json()
    assert {m["key"] for m in meta["modules"]} == {module}
    assert all(e["module"] == module for e in meta["entities"]) and not meta["reports"]
    for e in mine:
        assert client.get(f"/api/qb/{e.key}", headers=h).status_code == 200, e.key
    assert client.get(f"/api/qb/{other.key}", headers=h).status_code == 403
    creatable = next((e for e in mine if e.can_add), None)
    if creatable:
        assert client.post(f"/api/qb/{creatable.key}", headers=h, json={"values": {}}).status_code == 403


def test_direct_vs_approval_and_who_may_approve():
    maker = make_user("maker", ["sales.view", "sales.create"])
    approver = make_user("approver", ["sales.view", "sales.approve"])
    direct = make_user("direct", ["sales.view", "sales.create", "sales.direct"])
    w = client.post("/api/qb/customer", headers=maker, json={"values": {"Name": "Approval Test"}}).json()
    assert w["status"] == "pending"
    assert client.post(f"/api/qb-writes/{w['write_id']}/approve", headers=maker).status_code == 403
    assert client.post(f"/api/qb-writes/{w['write_id']}/reject", headers=approver, json={"note": "dup"}).json()["status"] == "rejected"
    assert client.post(f"/api/qb-writes/{w['write_id']}/approve", headers=approver).status_code == 409
    w2 = client.post("/api/qb/customer", headers=direct, json={"values": {"Name": "Direct Test"}}).json()
    assert w2["status"] == "approved"
    # a failed change can be retried by an approver
    with SessionLocal() as db:
        db.get(QBWrite, w2["write_id"]).status = "failed"
        db.commit()
    assert client.post(f"/api/qb-writes/{w2['write_id']}/retry", headers=approver).json()["status"] == "approved"
    # requesters see their own changes even without approve rights
    assert any(x["write_id"] == w["write_id"] for x in client.get("/api/qb-writes", headers=maker).json())


def test_validation_errors_are_422():
    assert client.post("/api/qb/customer", headers=ADMIN, json={"values": {}}).status_code == 422  # Name required
    r = client.post("/api/qb/customer", headers=ADMIN, json={"values": {"Name": "x" * 60}})
    assert r.status_code == 422 and "41" in r.json()["detail"]
    r = client.post("/api/qb/customer", headers=ADMIN, json={"values": {"Name": "Neg", "CreditLimit": "-5"}})
    assert r.status_code == 422 and "less than 0" in r.json()["detail"]
    assert client.post("/api/qb/invoice", headers=ADMIN, json={"values": {"CustomerRef": {"ListID": "C"}}, "lines": []}).status_code == 422
    assert client.get("/api/qb/no_such_entity", headers=ADMIN).status_code == 404


# ---------------------------------------------------------------- companies

def test_companies():
    r = client.post("/api/companies", headers=ADMIN, json={"name": "Second Co", "qbwc_username": "qbwc_second",
                                                            "qbwc_password": "Second-pass1"})
    assert r.status_code == 201
    cid = r.json()["company_id"]
    assert client.post("/api/companies", headers=ADMIN, json={"name": "Dup", "qbwc_username": "QBWC_SECOND",
                                                               "qbwc_password": "Second-pass1"}).status_code == 409
    assert client.patch(f"/api/companies/{cid}", headers=ADMIN, json={"is_active": False}).json()["is_active"] is False
    assert cid not in [c["company_id"] for c in client.get("/api/companies/mine", headers=ADMIN).json()]
    assert client.get("/api/qb/customer", headers={**ADMIN, "X-Company-Id": str(cid)}).status_code == 403
    client.patch(f"/api/companies/{cid}", headers=ADMIN, json={"is_active": True})
    h = make_user("nocompany", ["sales.view"], companies=[])
    client.patch(f"/api/users/{client.get('/api/auth/me', headers=h).json()['user_id']}", headers=ADMIN, json={"company_ids": []})
    assert client.get("/api/qb/customer", headers=h).status_code == 403
    assert client.get("/api/companies", headers=h).status_code == 403


# ---------------------------------------------------------------- sync, notifications, audit

def test_sync_endpoints():
    st = client.get("/api/sync/status", headers=ADMIN).json()
    assert st["run_every_minutes"] == 1 and "qbwc_url" in st
    assert client.post("/api/sync/request", headers=ADMIN, json={"full_resync": False}).status_code == 202
    assert client.get("/api/sync/status", headers=ADMIN).json()["pending_request"] is True
    assert isinstance(client.get("/api/sync/logs", headers=ADMIN).json(), list)
    h = make_user("nosync", ["sales.view"])
    assert client.post("/api/sync/request", headers=h, json={}).status_code == 403
    assert "<QBWCXML>" in client.get("/api/companies/1/qwc", headers=ADMIN).text


def test_notifications_and_audit():
    with SessionLocal() as db:
        uid = db.query(User).filter_by(username="admin").one().user_id
        db.add_all([Notification(user_id=uid, type="t", message=f"n{i}") for i in range(3)])
        db.commit()
    assert client.get("/api/notifications/unread-count", headers=ADMIN).json()["count"] >= 3
    first = client.get("/api/notifications", headers=ADMIN).json()[0]["notification_id"]
    assert client.post(f"/api/notifications/{first}/read", headers=ADMIN).status_code == 204
    assert client.post("/api/notifications/read-all", headers=ADMIN).status_code == 204
    assert client.get("/api/notifications/unread-count", headers=ADMIN).json()["count"] == 0
    page = client.get("/api/audit", headers=ADMIN, params={"entity": "user"}).json()
    assert page["total"] > 0 and all(a["entity"] == "user" for a in page["items"])
    assert client.get("/api/audit", headers=make_user("noaudit", ["sales.view"])).status_code == 403


# ---------------------------------------------------------------- exports and PDFs for every entity

def _seed_record(key: str) -> int:
    ent = next(e for e in ENTITIES if e.key == key)
    data = {ent.id_field: f"{key}-1", "EditSequence": "1", "Name": f"{key} sample", "FullName": f"{key} sample",
            "RefNumber": "R-1", "TxnDate": "2026-10-08", "Memo": "memo", "TotalAmount": "100.00",
            "CustomerRef": {"ListID": "C-1", "FullName": "Customer"}, "VendorRef": {"ListID": "V-1", "FullName": "Vendor"}}
    for lt in ent.lines:
        data[lt.ret_tag] = [{"TxnLineID": "L-1", "ItemRef": {"FullName": "Item"}, "AccountRef": {"FullName": "Acct"},
                             "Desc": "Line", "Quantity": "2", "Rate": "50", "Amount": "100.00"}]
    with SessionLocal() as db:
        rec = QBRecord(company_id=1, entity=key, qb_id=f"{key}-1", name=f"{key} sample", data=data, txn_date=None)
        db.add(rec)
        db.commit()
        return rec.record_id


@pytest.mark.parametrize("key", [e.key for e in ENTITIES])
def test_every_entity_exports_and_opens(key):
    rid = _seed_record(key)
    xl = client.get(f"/api/files/export/{key}", headers=ADMIN)
    assert xl.status_code == 200 and xl.content[:2] == b"PK", xl.text[:200]
    detail = client.get(f"/api/qb/{key}/{rid}", headers=ADMIN)
    assert detail.status_code == 200 and "form" in detail.json()
    ent = next(e for e in ENTITIES if e.key == key)
    if ent.kind == "txn":
        pdf = client.get(f"/api/files/pdf/{key}/{rid}", headers=ADMIN)
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


def test_pickers():
    for target in ("item", "entity", "account", "customer", "invoice", "bill"):
        assert client.get(f"/api/qb/options/{target}", headers=ADMIN).status_code == 200
    assert client.get("/api/qb/options/nonsense", headers=ADMIN).status_code == 404


def test_dashboard():
    d = client.get("/api/qb/dashboard", headers=ADMIN).json()
    assert {"counts", "open_ar", "open_ap", "pending_changes", "recent"} <= set(d)
