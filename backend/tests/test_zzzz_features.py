"""Aging, customer overview, stock alerts, smart look-ups, duplicates, activity, preferences, approval diff,
bulk actions and the daily summary."""

import io
import zipfile
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import QBRecord, QBWrite

client = TestClient(app)
client.__enter__()
H = {"Authorization": "Bearer " + client.post("/api/auth/login", data={"username": "admin", "password": "Admin@123"}
                                              ).json()["access_token"], "X-Company-Id": "1"}
T = date.today()
IDS: dict[str, int] = {}


def add(db, key, entity, qb_id, **kw):
    r = QBRecord(company_id=1, entity=entity, qb_id=qb_id, **kw)
    db.add(r)
    db.flush()
    IDS[key] = r.record_id


def setup_module():
    with SessionLocal() as db:
        add(db, "cust", "customer", "FX-C1", name="Fx Customer", data={
            "FullName": "Fx Customer", "TotalBalance": "1500.00", "Email": "fx@example.com",
            "TermsRef": {"ListID": "T1", "FullName": "Net 30"},
            "BillAddress": {"Addr1": "1 Main St", "City": "Colombo"}})
        add(db, "nomail", "customer", "FX-C2", name="Fx NoMail", data={"FullName": "Fx NoMail"})
        add(db, "inv_cur", "invoice", "FX-I1", name="FX-1001", party_id="FX-C1", party_name="Fx Customer",
            txn_date=T, amount=500, data={"DueDate": (T + timedelta(days=10)).isoformat(), "BalanceRemaining": "500.00"})
        add(db, "inv_45", "invoice", "FX-I2", name="FX-1002", party_id="FX-C1", party_name="Fx Customer",
            txn_date=T - timedelta(days=75), amount=1000, data={"DueDate": (T - timedelta(days=45)).isoformat(),
                                                                  "BalanceRemaining": "1000.00"})
        add(db, "inv_paid", "invoice", "FX-I3", name="FX-1003", party_id="FX-C1", party_name="Fx Customer",
            txn_date=T, amount=99, data={"IsPaid": "true", "BalanceRemaining": "0"})
        add(db, "inv_nomail", "invoice", "FX-I4", name="FX-1004", party_id="FX-C2", party_name="Fx NoMail",
            txn_date=T, amount=10, data={"BalanceRemaining": "10"})
        add(db, "pay", "receive_payment", "FX-P1", name="FX-PAY", party_id="FX-C1", party_name="Fx Customer",
            txn_date=T, amount=200, data={})
        add(db, "low", "item_inventory", "FX-IT1", name="Fx Widget", data={
            "ReorderPoint": "10", "QuantityOnHand": "3", "QuantityOnOrder": "0", "PurchaseCost": "4.50",
            "SalesPrice": "9.99", "SalesDesc": "Widget", "PrefVendorRef": {"ListID": "V9", "FullName": "Fx Vendor"}})
        add(db, "ok", "item_inventory", "FX-IT2", name="Fx Plenty", data={"ReorderPoint": "5", "QuantityOnHand": "50"})
        db.commit()


def test_aging_buckets():
    r = client.get("/api/insights/aging", headers=H, params={"side": "ar"}).json()
    p = next(x for x in r["parties"] if x["name"] == "Fx Customer")
    assert p["current"] == 500 and p["d31_60"] == 1000 and p["total"] == 1500 and p["docs"] == 2
    assert p["record_id"] == IDS["cust"]
    assert r["overdue"] >= 1000
    assert client.get("/api/insights/aging", headers=H, params={"side": "xx"}).status_code == 422


def test_party_overview():
    r = client.get(f"/api/insights/party/customer/{IDS['cust']}", headers=H).json()
    assert r["balance"] == 1500 and r["open_total"] == 1500 and r["overdue_total"] == 1000
    assert r["open_docs"][0]["name"] == "FX-1002" and r["open_docs"][0]["days_overdue"] == 45
    assert r["terms"] == "Net 30" and r["email"] == "fx@example.com"
    assert r["payments"][0]["name"] == "FX-PAY" and len(r["monthly"]) == 12
    assert client.get(f"/api/insights/party/invoice/{IDS['inv_cur']}", headers=H).status_code == 404


def test_stock_alerts():
    r = client.get("/api/insights/stock", headers=H).json()
    names = [x["name"] for x in r["items"]]
    assert "Fx Widget" in names and "Fx Plenty" not in names
    w = next(x for x in r["items"] if x["name"] == "Fx Widget")
    assert w["suggested"] == 17 and w["vendor"]["FullName"] == "Fx Vendor" and not w["covered"]


def test_lookup_fills_forms():
    c = client.get("/api/insights/lookup/customer/FX-C1", headers=H).json()
    assert c["terms"]["FullName"] == "Net 30" and c["bill_address"]["City"] == "Colombo"
    i = client.get("/api/insights/lookup/item/FX-IT1", headers=H).json()
    assert i["sales_price"] == 9.99 and i["cost"] == 4.5 and i["qoh"] == 3 and i["sales_desc"] == "Widget"
    assert client.get("/api/insights/lookup/item/NOPE", headers=H).status_code == 404


def test_duplicates():
    same_no = client.get("/api/insights/duplicates/invoice", headers=H, params={"ref": "FX-1001"}).json()
    assert same_no[0]["reason"] == "same number"
    same_amt = client.get("/api/insights/duplicates/invoice", headers=H,
                          params={"party_id": "FX-C1", "amount": 500, "txn_date": T.isoformat()}).json()
    assert [x["name"] for x in same_amt] == ["FX-1001"]
    assert client.get("/api/insights/duplicates/invoice", headers=H, params={"ref": "FX-1001",
                      "exclude": IDS["inv_cur"]}).json() == []


def test_activity_and_diff_and_approve_many():
    h = H
    r = client.patch(f"/api/qb/customer/{IDS['cust']}", headers=h, json={"values": {"Email": "new@example.com"}})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:  # make it pending so it needs approval
        w = db.get(QBWrite, r.json()["write_id"])
        w.status = "pending"
        db.commit()
        wid = w.write_id
    d = client.get(f"/api/qb-writes/{wid}/diff", headers=h).json()
    assert {"label": "E-mail", "old": "fx@example.com", "new": "new@example.com"} in d["fields"] or \
        any(f["old"] == "fx@example.com" and f["new"] == "new@example.com" for f in d["fields"])
    ev = client.get(f"/api/insights/activity/customer/{IDS['cust']}", headers=h).json()
    assert any(e["kind"] == "qb_mod" for e in ev)
    m = client.post("/api/qb-writes/approve-many", headers=h, json={"ids": [wid, 999999]}).json()
    assert m["approved"] == [wid] and m["skipped"][0]["write_id"] == 999999


def test_prefs_roundtrip():
    r = client.put("/api/auth/prefs", headers=H, json={"columns": {"invoice": ["DueDate"]},
                                                       "views": {"invoice": [{"name": "Late", "params": {"q": "x"}}]},
                                                       "daily_summary": False}).json()
    assert r["columns"]["invoice"] == ["DueDate"] and r["daily_summary"] is False
    assert client.get("/api/auth/prefs", headers=H).json()["views"]["invoice"][0]["name"] == "Late"
    assert client.put("/api/auth/prefs", headers=H, json={"evil": 1}).status_code == 422
    client.put("/api/auth/prefs", headers=H, json={"daily_summary": True})


def test_bulk_pdf_email_and_export_ids():
    ids = [IDS["inv_cur"], IDS["inv_45"]]
    z = client.post("/api/files/bulk-pdf", headers=H, json={"entity": "invoice", "ids": ids})
    assert z.status_code == 200 and len(zipfile.ZipFile(io.BytesIO(z.content)).namelist()) == 2
    e = client.post("/api/files/bulk-email", headers=H, json={"entity": "invoice", "ids": [IDS["inv_nomail"]]}).json()
    assert e["skipped"][0]["reason"] == "No e-mail address in QuickBooks"
    x = client.get("/api/files/export/invoice", headers=H, params={"ids": ids})
    assert x.status_code == 200 and x.content[:2] == b"PK"
    assert client.post("/api/files/bulk-pdf", headers=H, json={"entity": "customer", "ids": [IDS["cust"]]}).status_code == 400


def test_digest_preview():
    r = client.get("/api/insights/digest", headers=H).json()
    assert "Customers owe" in r["body"] and "Items to reorder" in r["body"]
    assert client.post("/api/insights/digest/send", headers=H).status_code == 400  # SMTP not set up in tests
