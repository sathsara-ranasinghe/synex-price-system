"""A simulated QuickBooks Web Connector session against the SOAP endpoint."""

import re
from xml.sax.saxutils import escape

from fastapi.testclient import TestClient

from app.main import app
from tests.sample_qbxml import RESPONSES, empty


def soap(client, method: str, **args) -> str:
    inner = "".join(f"<{k}>{escape(v)}</{k}>" for k, v in args.items())
    body = (f'<?xml version="1.0"?><soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
            f'<soap:Body><{method} xmlns="http://developer.intuit.com/">{inner}</{method}></soap:Body></soap:Envelope>')
    r = client.post("/qbwc", content=body, headers={"Content-Type": "text/xml"})
    assert r.status_code == 200, r.text
    return r.text


def run_qbwc_session(client) -> list[str]:
    out = soap(client, "authenticate", strUserName="qbwc", strPassword="secret")
    ticket, status = re.findall(r"<string>(.*?)</string>", out)
    assert status == "", out  # "" = use the open company file
    pct, sent = 0, []
    while pct < 100:
        req = soap(client, "sendRequestXML", ticket=ticket, strHCPResponse="", strCompanyFileName="C:\\QB\\synex.qbw",
                   qbXMLCountry="US", qbXMLMajorVers="16", qbXMLMinorVers="0")
        rq = re.search(r"&lt;(\w+Rq) ", req.split("QBXMLMsgsRq", 1)[1]).group(1)
        sent.append(rq)
        out = soap(client, "receiveResponseXML", ticket=ticket, response=RESPONSES.get(rq, empty(rq[:-2] + "Rs")),
                   hresult="", message="")
        pct = int(re.search(r"<receiveResponseXMLResult>(-?\d+)<", out).group(1))
        assert pct >= 0
    soap(client, "closeConnection", ticket=ticket)
    return sent


def test_sync_session():
    with TestClient(app) as client:
        assert "Synex" in soap(client, "serverVersion")
        assert "nvu" in soap(client, "authenticate", strUserName="qbwc", strPassword="wrong")

        sent = run_qbwc_session(client)
        assert sent[:2] == ["PreferencesQueryRq", "CustomerQueryRq"] and "BillQueryRq" in sent and sent[-1] == "TxnDeletedQueryRq"

        # straight after a sync nothing is due
        out = soap(client, "authenticate", strUserName="qbwc", strPassword="secret")
        assert re.findall(r"<string>(.*?)</string>", out)[1] == "none"

        token = client.post("/api/auth/login", data={"username": "admin", "password": "Admin@123"}).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        status = client.get("/api/sync/status", headers=h).json()
        assert status["last_success"]["records_inserted"] >= 5  # 2 vendors, 2 items, 1 bill

        vendors = client.get("/api/qb/vendor", headers=h).json()
        assert {v["name"] for v in vendors["items"]} == {"ABC Hardware", "Lanka Electricals"}
        bill = client.get("/api/qb/bill", headers=h).json()["items"][0]
        detail = client.get(f"/api/qb/bill/{bill['record_id']}", headers=h).json()
        assert len(detail["form"]["lines"]) == 2

        assert "<UserName>qbwc</UserName>" in client.get("/api/companies/1/qwc", headers=h).text
        assert client.get("/api/audit", headers=h).status_code == 200


def test_incremental_sync_is_one_batched_request():
    """After the first full sync every read goes in ONE qbXML message (fast 1-minute syncs)."""
    import re as _re
    from html import unescape

    from app.database import SessionLocal
    from app.models import SyncCheckpoint, SyncLog

    with TestClient(app) as client:
        with SessionLocal() as db:  # make the last sync look a minute old so a new one is due
            for s in db.query(SyncLog).all():
                s.started_at = s.started_at.replace(year=2000)
            db.commit()
            assert db.query(SyncCheckpoint).filter_by(company_id=1).count() > 40

        out = soap(client, "authenticate", strUserName="qbwc", strPassword="secret")
        ticket = _re.findall(r"<string>(.*?)</string>", out)[0]
        req = soap(client, "sendRequestXML", ticket=ticket, strHCPResponse="", strCompanyFileName=r"C:\QB\synex.qbw",
                   qbXMLCountry="US", qbXMLMajorVers="16", qbXMLMinorVers="0")
        xml = unescape(_re.search(r"<sendRequestXMLResult>(.*)</sendRequestXMLResult>", req, _re.S).group(1))
        requests = _re.findall(r"<(\w+QueryRq) requestID=\"(\w+)\"", xml)
        assert len(requests) > 40 and "iterator=" not in xml  # everything in one message, no iterators

        vendor = ('<VendorQueryRs requestID="vendor" statusCode="0" statusSeverity="Info" statusMessage="OK">'
                  '<VendorRet><ListID>80000009-1</ListID><Name>Batch Vendor</Name><IsActive>true</IsActive></VendorRet>'
                  '</VendorQueryRs>')
        bill = ('<BillQueryRs requestID="bill" statusCode="1" statusSeverity="Info" '
                'statusMessage="A query request did not find a matching object"/>')
        out = soap(client, "receiveResponseXML", ticket=ticket, hresult="", message="",
                   response=f'<?xml version="1.0" ?><QBXML><QBXMLMsgsRs>{vendor}{bill}</QBXMLMsgsRs></QBXML>')
        assert "<receiveResponseXMLResult>100<" in out  # done after a single round trip

        h = {"Authorization": "Bearer " + client.post("/api/auth/login", data={"username": "admin",
                                                                               "password": "Admin@123"}).json()["access_token"]}
        names = {v["name"] for v in client.get("/api/qb/vendor", headers=h).json()["items"]}
        assert "Batch Vendor" in names
