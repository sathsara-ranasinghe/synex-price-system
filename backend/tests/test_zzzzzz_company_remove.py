"""Removing a company deletes all of its portal data (after a backup) and nothing of other companies."""

import os
import zipfile

from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import SessionLocal
from app.main import app
from app.models import Attachment, AuditLog, Company, QBRecord, QBWrite, SyncLog

client = TestClient(app)
client.__enter__()
ADMIN = {"Authorization": "Bearer " + client.post("/api/auth/login", data={"username": "admin", "password": "Admin@123"}
                                                  ).json()["access_token"], "X-Company-Id": "1"}


def _company_with_data() -> int:
    r = client.post("/api/companies", headers=ADMIN, json={"name": "Gone Ltd", "qbwc_username": "gone_ltd",
                                                           "qbwc_password": "Gone-secret-1"})
    assert r.status_code == 201, r.text
    cid = r.json()["company_id"]
    with SessionLocal() as db:
        db.add_all([QBRecord(company_id=cid, entity="customer", qb_id="G1", name="Gone customer", data={}),
                    QBRecord(company_id=cid, entity="invoice", qb_id="G2", name="G-1", amount=10, data={}),
                    QBWrite(company_id=cid, kind="qb_add", entity_id=0, summary="New customer X", payload={}, status="pending")])
        db.add(SyncLog(company_id=cid, ticket="gone-ticket", started_at=__import__("datetime").datetime.now(),
                       records_inserted=0, records_updated=0, prices_changed=0, status="success", triggered_by="qbwc", state={}))
        folder = os.path.join(get_settings().attachments_dir, str(cid))
        os.makedirs(folder, exist_ok=True)
        open(os.path.join(folder, "note.pdf"), "wb").write(b"%PDF-1.4")
        db.add(Attachment(company_id=cid, entity="customer", qb_id="G1", filename="note.pdf", content_type="application/pdf",
                          size=8, stored_as=os.path.join(str(cid), "note.pdf"), uploaded_by=1))
        db.commit()
    return cid


def test_remove_company_and_its_data():
    cid = _company_with_data()
    with SessionLocal() as db:
        other_before = db.query(QBRecord).filter(QBRecord.company_id != cid).count()

    # must be disabled first, and only by an admin, with the exact name
    assert client.request("DELETE", f"/api/companies/{cid}", headers=ADMIN, json={"confirm_name": "Gone Ltd"}).status_code == 409
    client.patch(f"/api/companies/{cid}", headers=ADMIN, json={"is_active": False})
    prev = client.get(f"/api/companies/{cid}/removal", headers=ADMIN).json()
    assert prev["counts"]["qb_records"] == 2 and prev["counts"]["attachments"] == 1 and prev["counts"]["qb_writes"] == 1
    assert client.request("DELETE", f"/api/companies/{cid}", headers=ADMIN, json={"confirm_name": "gone"}).status_code == 422

    r = client.request("DELETE", f"/api/companies/{cid}", headers=ADMIN, json={"confirm_name": "Gone Ltd"})
    assert r.status_code == 200, r.text
    assert r.json()["deleted"]["qb_records"] == 2

    with SessionLocal() as db:
        assert db.get(Company, cid) is None
        for model in (QBRecord, QBWrite, SyncLog, Attachment):
            assert db.query(model).filter(model.company_id == cid).count() == 0
        assert db.query(QBRecord).filter(QBRecord.company_id != cid).count() == other_before  # others untouched
    assert not os.path.isdir(os.path.join(get_settings().attachments_dir, str(cid)))

    backup = os.path.join(get_settings().company_backups_dir, r.json()["backup"])
    names = zipfile.ZipFile(backup).namelist()
    assert "qb_records.jsonl" in names and "attachments/note.pdf" in names
    with SessionLocal() as db:  # the removal stays in the audit log
        assert db.query(AuditLog).filter_by(entity="company", entity_id=str(cid), action="remove").count() == 1


def test_cannot_remove_last_or_without_admin():
    with SessionLocal() as db:
        ids = [c.company_id for c in db.query(Company).all()]
    if len(ids) == 1:
        client.patch(f"/api/companies/{ids[0]}", headers=ADMIN, json={"is_active": False})
        assert client.request("DELETE", f"/api/companies/{ids[0]}", headers=ADMIN, json={"confirm_name": "x"}).status_code == 409
        client.patch(f"/api/companies/{ids[0]}", headers=ADMIN, json={"is_active": True})
    assert client.request("DELETE", "/api/companies/999999", headers=ADMIN, json={"confirm_name": "x"}).status_code == 404
