"""Search, home insights, sorting and totals used by the redesigned UI."""

from datetime import date

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import QBRecord

client = TestClient(app)
client.__enter__()
H = {"Authorization": "Bearer " + client.post("/api/auth/login", data={"username": "admin", "password": "Admin@123"}
                                              ).json()["access_token"], "X-Company-Id": "1"}


def setup_module():
    with SessionLocal() as db:
        for i, (ent, d, amt, party) in enumerate([
            ("invoice", date(2031, 1, 10), 100, "Zeta Traders"), ("invoice", date(2031, 3, 5), 250, "Alpha Stores"),
            ("sales_receipt", date(2031, 3, 20), 50, "Alpha Stores"), ("bill", date(2031, 2, 2), 80, "Paper Co"),
        ]):
            db.add(QBRecord(company_id=1, entity=ent, qb_id=f"UI-{i}", name=f"UIX-{i}", party_name=party,
                            txn_date=d, amount=amt, data={}))
        db.commit()


def test_global_search():
    r = client.get("/api/qb/search", headers=H, params={"q": "alpha stores"}).json()
    assert r and {x["party_name"] for x in r} == {"Alpha Stores"} and all(x["label"] for x in r)
    assert client.get("/api/qb/search", headers=H, params={"q": "a"}).status_code == 422


def test_insights_follow_newest_data():
    r = client.get("/api/qb/insights", headers=H, params={"months": 3}).json()
    assert r["months"] == ["2031-01-01", "2031-02-01", "2031-03-01"]
    assert r["sales"][2] == 300 and r["sales"][0] == 100 and r["purchases"][1] == 80
    assert r["top_customers"][0] == {"name": "Alpha Stores", "amount": 300}
    assert r["top_vendors"][0]["name"] == "Paper Co"


def test_list_sort_and_total():
    r = client.get("/api/qb/invoice", headers=H, params={"q": "UIX", "sort": "amount", "dir": "desc"}).json()
    assert [x["amount"] for x in r["items"]] == [250, 100] and r["sum_amount"] == 350
    asc = client.get("/api/qb/invoice", headers=H, params={"q": "UIX", "sort": "amount"}).json()
    assert [x["amount"] for x in asc["items"]] == [100, 250]
    assert client.get("/api/qb/invoice", headers=H, params={"sort": "data"}).status_code == 422
