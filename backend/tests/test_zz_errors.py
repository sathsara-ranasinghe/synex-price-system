"""Error paths: QuickBooks errors, Web Connector connection problems, rejected writes, e-mail delivery."""

import re
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Notification, QBWrite, SyncLog, SyncRequest
from app.services import notify
from tests.test_qbwc_flow import soap

client = TestClient(app)
client.__enter__()
ADMIN = {"Authorization": "Bearer " + client.post("/api/auth/login", data={"username": "admin", "password": "Admin@123"}
                                                  ).json()["access_token"], "X-Company-Id": "1"}
QBW = r"C:\QB\synex.qbw"


def start_session(clean: bool = True) -> str:
    with SessionLocal() as db:
        db.add(SyncRequest(company_id=1, full_resync=False))
        if clean:
            db.query(SyncLog).filter_by(status="running").update({"status": "failed"})
        db.commit()
    out = soap(client, "authenticate", strUserName="qbwc", strPassword="secret")
    ticket = re.findall(r"<string>(.*?)</string>", out)[0]
    assert ticket not in ("", "none", "nvu")
    return ticket


def last_sync() -> SyncLog:
    with SessionLocal() as db:
        return db.query(SyncLog).order_by(SyncLog.sync_id.desc()).first()


def test_quickbooks_hresult_error_fails_the_sync():
    t = start_session()
    soap(client, "sendRequestXML", ticket=t, strHCPResponse="", strCompanyFileName=QBW, qbXMLCountry="US",
         qbXMLMajorVers="16", qbXMLMinorVers="0")
    out = soap(client, "receiveResponseXML", ticket=t, response="", hresult="0x80040400", message="QuickBooks found an error")
    assert "<receiveResponseXMLResult>-101<" in out
    assert "QuickBooks found an error" in soap(client, "getLastError", ticket=t)
    assert last_sync().status == "failed"


def test_connection_error_and_early_close():
    t = start_session()
    assert "done" in soap(client, "connectionError", ticket=t, hresult="0x80040408", message="Could not start QuickBooks")
    s = last_sync()
    assert s.status == "failed" and "Could not open" in s.error_message
    t2 = start_session()
    assert "failed" in soap(client, "closeConnection", ticket=t2)
    assert "closed before" in last_sync().error_message
    assert "Unknown ticket" in soap(client, "getLastError", ticket="nope")
    assert "OK" in soap(client, "closeConnection", ticket="nope")


def test_stale_running_sync_is_closed():
    with SessionLocal() as db:
        db.add(SyncLog(company_id=1, ticket="stale-1", status="running", state={"steps": []},
                       started_at=datetime.now(timezone.utc) - timedelta(hours=5)))
        db.commit()
    start_session(clean=False)
    with SessionLocal() as db:
        stale = db.query(SyncLog).filter_by(ticket="stale-1").one()
        assert stale.status == "failed" and "Abandoned" in stale.error_message


def test_unknown_soap_method_and_bad_xml():
    assert client.post("/qbwc", content=b"not xml", headers={"Content-Type": "text/xml"}).status_code == 500
    body = ('<?xml version="1.0"?><soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>'
            '<doSomething xmlns="http://developer.intuit.com/"/></soap:Body></soap:Envelope>')
    assert client.post("/qbwc", content=body, headers={"Content-Type": "text/xml"}).status_code == 500
    assert "Synex" in client.get("/qbwc").text
    assert "<clientVersionResult></clientVersionResult>" in soap(client, "clientVersion", strVersion="2.2")


def test_rejected_write_notifies_requester():
    with SessionLocal() as db:  # only this test's change should be queued
        db.query(QBWrite).filter(QBWrite.status.in_(["approved", "sent"])).update({"status": "rejected"})
        db.commit()
    w = client.post("/api/qb/customer", headers=ADMIN, json={"values": {"Name": "Will Fail"}}).json()
    assert w["status"] == "approved"
    t = start_session()
    req = soap(client, "sendRequestXML", ticket=t, strHCPResponse="", strCompanyFileName=QBW, qbXMLCountry="US",
               qbXMLMajorVers="16", qbXMLMinorVers="0")
    assert "CustomerAddRq" in req
    err = ('<?xml version="1.0" ?><QBXML><QBXMLMsgsRs><CustomerAddRs requestID="x" statusCode="3100" statusSeverity="Error" '
           'statusMessage="The name &quot;Will Fail&quot; of the list element is already in use."/></QBXMLMsgsRs></QBXML>')
    soap(client, "receiveResponseXML", ticket=t, response=err, hresult="", message="")
    with SessionLocal() as db:
        wr = db.get(QBWrite, w["write_id"])
        assert wr.status == "failed" and "already in use" in wr.error_message
        assert db.query(Notification).filter(Notification.message.like("%already in use%")).count() == 1
    soap(client, "closeConnection", ticket=t)


def test_email(monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self): pass
        def login(self, *a): pass
        def send_message(self, msg): sent.append(msg)

    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(s, "smtp_user", "u")
    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    notify.send_email_now(["a@b.lk"], "Hello", "Body", attachment=("doc.pdf", b"%PDF", "application/pdf"))
    assert sent and sent[0]["Subject"] == "Hello" and any(p.get_filename() == "doc.pdf" for p in sent[0].iter_attachments())

    class BrokenSMTP(FakeSMTP):
        def send_message(self, msg): raise OSError("connection refused")

    monkeypatch.setattr(notify.smtplib, "SMTP", BrokenSMTP)
    try:
        notify.send_email_now(["a@b.lk"], "x", "y")
        raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "connection refused" in str(e)
