"""Synex QB Portal: generic create / edit / delete / report through a simulated Web Connector session.

Runs after test_qbwc_flow (same database), which already loaded vendors, items and a bill."""

import re
from html import unescape

from fastapi.testclient import TestClient
from lxml import etree

from app.main import app
from tests.sample_qbxml import RESPONSES, empty
from tests.test_qbwc_flow import soap

CUSTOMERS = """<?xml version="1.0" ?><QBXML><QBXMLMsgsRs>
<CustomerQueryRs requestID="customer:0" statusCode="0" statusSeverity="Info" statusMessage="OK">
<CustomerRet><ListID>C-1</ListID><EditSequence>1</EditSequence><Name>Hilton Colombo</Name><FullName>Hilton Colombo</FullName>
<IsActive>true</IsActive><Phone>011 111</Phone><TotalBalance>0.00</TotalBalance></CustomerRet>
</CustomerQueryRs></QBXMLMsgsRs></QBXML>"""

ACCOUNTS = """<?xml version="1.0" ?><QBXML><QBXMLMsgsRs>
<AccountQueryRs requestID="account:0" statusCode="0" statusSeverity="Info" statusMessage="OK">
<AccountRet><ListID>A-1</ListID><Name>Sales</Name><FullName>Sales</FullName><IsActive>true</IsActive>
<AccountType>Income</AccountType></AccountRet>
</AccountQueryRs></QBXMLMsgsRs></QBXML>"""

READS = {**RESPONSES, "CustomerQueryRq": CUSTOMERS, "AccountQueryRq": ACCOUNTS}
counter = {"n": 0}


def fake_qb(xml: str) -> tuple[str, str]:
    root = etree.fromstring(re.sub(r"^<\?xml[^>]*\?>", "", xml))
    rq = root.find("QBXMLMsgsRq")[0]
    tag, rid = rq.tag, rq.get("requestID")
    rs = tag[:-2] + "Rs"

    def wrap(inner: str) -> str:
        return (f'<?xml version="1.0" ?><QBXML><QBXMLMsgsRs><{rs} requestID="{rid}" statusCode="0" '
                f'statusSeverity="Info" statusMessage="Status OK">{inner}</{rs}></QBXMLMsgsRs></QBXML>')

    if tag == "ReceivePaymentAddRq":
        body = rq[0]
        assert body.find("IsAutoApply") is None and body.find("AppliedToTxnAdd/PaymentAmount").text == "150.00"
        assert [c.tag for c in body][-1] == "AppliedToTxnAdd"
    if tag.endswith("AddRq") or tag.endswith("ModRq"):
        base = tag[:-5]
        body = rq[0]
        counter["n"] += 1
        idf = "ListID" if base in ("Customer", "Vendor", "Account") else "TxnID"
        new_id = body.findtext(idf) or f"NEW-{counter['n']}"
        fields = "".join(etree.tostring(c, encoding="unicode") for c in body if c.tag not in (idf, "EditSequence")
                         and not c.tag.endswith(("LineAdd", "LineMod")))
        lines = "".join(f"<{base}LineRet><TxnLineID>L-{i}</TxnLineID>"
                        + "".join(etree.tostring(x, encoding="unicode") for x in ln if x.tag != "TxnLineID")
                        + f"</{base}LineRet>" for i, ln in enumerate(body) if ln.tag.endswith(("LineAdd", "LineMod")))
        name = f"<Name>{body.findtext('Name')}</Name><FullName>{body.findtext('Name')}</FullName>" if idf == "ListID" else ""
        ref = "" if body.find("RefNumber") is not None or idf == "ListID" else "<RefNumber>INV-9</RefNumber>"
        return tag, wrap(f"<{base}Ret><{idf}>{new_id}</{idf}><EditSequence>{counter['n']}</EditSequence>"
                         f"{name}{ref}{fields.replace('<Name>', '<X>').replace('</Name>', '</X>') if name else fields}"
                         f"<Subtotal>150.00</Subtotal>{lines}</{base}Ret>")
    if tag.endswith("QueryRq") and (rq.find("TxnID") is not None or rq.find("ListID") is not None):
        base = tag[:-7]
        idf = "TxnID" if rq.find("TxnID") is not None else "ListID"
        return tag, wrap(f"<{base}Ret><{idf}>{rq.findtext(idf)}</{idf}><EditSequence>55</EditSequence>"
                         f"<RefNumber>INV-9</RefNumber></{base}Ret>")
    if tag in ("TxnDelRq", "ListDelRq", "TxnVoidRq"):
        return tag, wrap("".join(etree.tostring(c, encoding="unicode") for c in rq))
    if tag == "GeneralSummaryReportQueryRq":
        return tag, wrap(
            '<ReportRet><ReportTitle>Profit &amp; Loss</ReportTitle><ReportSubtitle>Oct 2026</ReportSubtitle>'
            '<ColDesc colID="1"><ColTitle titleRow="1" /><ColType>Label</ColType></ColDesc>'
            '<ColDesc colID="2"><ColTitle titleRow="1" value="TOTAL" /><ColType>Amount</ColType></ColDesc>'
            '<ReportData><TextRow rowNumber="1" value="Income" />'
            '<DataRow rowNumber="2"><ColData colID="1" value="Sales" /><ColData colID="2" value="1500.00" /></DataRow>'
            '<TotalRow rowNumber="3"><ColData colID="1" value="Net Income" /><ColData colID="2" value="1500.00" /></TotalRow>'
            '</ReportData></ReportRet>')
    return tag, READS.get(tag, empty(rs))


def session(client, user: str = "qbwc", password: str = "secret", qbw: str = r"C:\QB\synex.qbw") -> list[str]:
    out = soap(client, "authenticate", strUserName=user, strPassword=password)
    ticket = re.findall(r"<string>(.*?)</string>", out)[0]
    sent, pct = [], 0
    while pct < 100:
        req = soap(client, "sendRequestXML", ticket=ticket, strHCPResponse="", strCompanyFileName=qbw,
                   qbXMLCountry="US", qbXMLMajorVers="17", qbXMLMinorVers="0")
        found = re.search(r"<sendRequestXMLResult>(.*)</sendRequestXMLResult>", req, re.S)
        if not found or not found.group(1).strip():  # empty = server refused (e.g. wrong company file)
            return sent + ["<refused>"]
        xml = unescape(found.group(1))
        tag, resp = fake_qb(xml)
        sent.append(tag)
        out = soap(client, "receiveResponseXML", ticket=ticket, response=resp, hresult="", message="")
        pct = int(re.search(r"Result>(-?\d+)<", out).group(1))
    return sent


def test_portal():
    with TestClient(app) as client:
        h = {"Authorization": "Bearer " + client.post("/api/auth/login", data={"username": "admin",
                                                                               "password": "Admin@123"}).json()["access_token"]}
        client.post("/api/sync/request", headers=h, json={"full_resync": True})
        sent = session(client)
        assert "CustomerQueryRq" in sent and "ListDeletedQueryRq" in sent and "TxnDeletedQueryRq" in sent

        meta = client.get("/api/qb/meta", headers=h).json()
        assert {"sales", "purchasing", "banking", "accounting"} <= {m["key"] for m in meta["modules"]}
        assert "prices" not in {m["key"] for m in meta["modules"]}
        assert len(meta["entities"]) >= 40 and len(meta["reports"]) >= 30

        cust = client.get("/api/qb/customer", headers=h).json()["items"][0]
        assert cust["name"] == "Hilton Colombo" and cust["columns"]["Phone"] == "011 111"
        items = client.get("/api/qb/options/item", params={"q": "PVC"}, headers=h).json()
        assert items[0]["ListID"] == "I-1"

        # validation happens before anything is queued
        bad = client.post("/api/qb/invoice", headers=h, json={"values": {}, "lines": []})
        assert bad.status_code == 422

        # admin has sales.direct -> queued without approval
        r = client.post("/api/qb/invoice", headers=h, json={
            "values": {"CustomerRef": {"ListID": "C-1"}, "TxnDate": "2026-10-07", "Memo": "Site A & B"},
            "lines": [{"type": "item", "values": {"ItemRef": {"ListID": "I-1"}, "Quantity": "3", "Rate": "50"}}]})
        assert r.status_code == 201 and r.json()["status"] == "approved", r.text
        sent = session(client)
        assert sent[0] == "InvoiceAddRq"
        inv = client.get("/api/qb/invoice", headers=h).json()["items"][0]
        detail = client.get(f"/api/qb/invoice/{inv['record_id']}", headers=h).json()
        assert detail["form"]["values"]["Memo"] == "Site A & B"
        assert detail["form"]["lines"][0]["TxnLineID"].startswith("L-")
        assert any(x["entity"] == "invoice" for x in client.get(f"/api/qb/customer/{cust['record_id']}",
                                                               headers=h).json()["related"])

        # edit: query for EditSequence, then InvoiceMod with existing + new line
        lines = detail["form"]["lines"] + [{"type": "item", "values": {"ItemRef": {"ListID": "I-2"}, "Quantity": "1",
                                                                        "Rate": "9000"}}]
        r = client.patch(f"/api/qb/invoice/{inv['record_id']}", headers=h, json={"values": {"Memo": "Changed"},
                                                                                "lines": lines})
        assert r.status_code == 200, r.text
        assert session(client)[:2] == ["InvoiceQueryRq", "InvoiceModRq"]

        # customer payment applied to that invoice (no IsAutoApply when invoices are picked)
        r = client.post("/api/qb/receive_payment", headers=h, json={
            "values": {"CustomerRef": {"ListID": "C-1"}, "TotalAmount": "150", "IsAutoApply": True},
            "lines": [{"type": "applied", "values": {"TxnID": inv["qb_id"], "PaymentAmount": "150"}}]})
        assert r.status_code == 201, r.text
        pay_sent = session(client)
        assert pay_sent[0] == "ReceivePaymentAddRq"

        # printable PDF, Excel export, e-mail without SMTP gives a clear error
        pdf = client.get(f"/api/files/pdf/invoice/{inv['record_id']}", headers=h)
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
        xl = client.get("/api/files/export/customer", headers=h)
        assert xl.status_code == 200 and xl.content[:2] == b"PK"
        em = client.post(f"/api/files/email/invoice/{inv['record_id']}", headers=h, json={"to": ["a@b.lk"]})
        assert em.status_code == 400 and "SMTP" in em.json()["detail"]

        # attachments are kept by the portal
        up = client.post(f"/api/files/attachments/invoice/{inv['record_id']}", headers=h,
                         files={"file": ("quote.pdf", b"%PDF-1.4 test", "application/pdf")})
        assert up.status_code == 201, up.text
        assert client.post(f"/api/files/attachments/invoice/{inv['record_id']}", headers=h,
                           files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 422
        att = client.get(f"/api/files/attachments/invoice/{inv['record_id']}", headers=h).json()
        assert att[0]["filename"] == "quote.pdf"
        assert client.get(f"/api/files/attachment/{att[0]['attachment_id']}", headers=h).content == b"%PDF-1.4 test"
        assert client.delete(f"/api/files/attachment/{att[0]['attachment_id']}", headers=h).status_code == 204

        # void + report
        assert client.post(f"/api/qb/invoice/{inv['record_id']}/void", headers=h).status_code == 200
        rep = client.post("/api/qb/reports", headers=h, json={"report_type": "ProfitAndLossStandard",
                                                              "from_date": "2026-10-01", "to_date": "2026-10-31"}).json()
        sent = session(client)
        assert sent[:2] == ["TxnVoidRq", "GeneralSummaryReportQueryRq"]
        report = client.get(f"/api/qb/reports/{rep['report_id']}", headers=h).json()
        assert report["status"] == "done" and report["result"]["rows"][1]["cells"] == ["Sales", "1500.00"]
        assert client.get(f"/api/files/report/{rep['report_id']}", headers=h).content[:2] == b"PK"
        writes = client.get("/api/qb-writes", headers=h).json()
        assert all(w["status"] == "done" for w in writes if w["kind"].startswith("qb_")), writes

        # a "sales" user: sees sales, not purchasing; changes need approval
        client.post("/api/users", headers=h, json={"username": "salesrep", "email": "s@x.lk", "password": "Sales@1234",
                                                   "role_name": "sales", "company_ids": [1]})
        hs = {"Authorization": "Bearer " + client.post("/api/auth/login", data={"username": "salesrep",
                                                                                "password": "Sales@1234"}).json()["access_token"]}
        assert client.get("/api/qb/vendor", headers=hs).status_code == 403
        r = client.post("/api/qb/customer", headers=hs, json={"values": {"Name": "New Hotel"}}).json()
        assert r["status"] == "pending"
        assert client.post(f"/api/qb-writes/{r['write_id']}/approve", headers=hs).status_code == 403
        assert client.post(f"/api/qb-writes/{r['write_id']}/approve", headers=h).status_code == 200

        # role editor
        assert any(g["group"].startswith("Sales") for g in client.get("/api/permissions", headers=h).json())
        assert client.put("/api/roles/sales", headers=h, json={"role_name": "sales",
                          "permissions": ["sales.view", "sales.create", "sales.direct"]}).status_code == 200
        r = client.post("/api/qb/customer", headers=hs, json={"values": {"Name": "Direct Hotel"}}).json()
        assert r["status"] == "approved"


def test_multi_company():
    with TestClient(app) as client:
        h = {"Authorization": "Bearer " + client.post("/api/auth/login", data={"username": "admin",
                                                                               "password": "Admin@123"}).json()["access_token"]}
        r = client.post("/api/companies", headers=h, json={"name": "Synex Engineering", "qbwc_username": "qbwc_eng",
                                                           "qbwc_password": "Eng-secret-1"})
        assert r.status_code == 201, r.text
        eng = r.json()
        assert "<UserName>qbwc_eng</UserName>" in client.get(f"/api/companies/{eng['company_id']}/qwc", headers=h).text

        # app name and Web Connector address can be edited; plain HTTP is only allowed for localhost
        bad = client.patch(f"/api/companies/{eng['company_id']}", headers=h, json={"qbwc_url": "http://10.0.0.5:8000"})
        assert bad.status_code == 422
        ok = client.patch(f"/api/companies/{eng['company_id']}", headers=h,
                          json={"app_name": "Synex Engineering QB", "qbwc_url": "https://portal.synex.lk"}).json()
        assert ok["effective_qbwc_url"] == "https://portal.synex.lk/qbwc"
        qwc = client.get(f"/api/companies/{eng['company_id']}/qwc", headers=h).text
        assert "<AppURL>https://portal.synex.lk/qbwc</AppURL>" in qwc and "<AppName>Synex Engineering QB</AppName>" in qwc
        assert client.get("/api/companies/url-suggestion", headers=h).json()["url"].endswith("/qbwc")

        # the new company syncs its own file through its own login
        sent = session(client, "qbwc_eng", "Eng-secret-1", r"D:\QB\engineering.qbw")
        assert "CustomerQueryRq" in sent and "<refused>" not in sent
        he = {**h, "X-Company-Id": str(eng["company_id"])}
        assert client.get("/api/qb/customer", headers=he).json()["total"] == 1  # Hilton (sample data)
        # company 1 still has its own records (invoices made in test_portal), company 2 has none
        assert client.get("/api/qb/invoice", headers=h).json()["total"] >= 1
        assert client.get("/api/qb/invoice", headers=he).json()["total"] == 0

        # wrong company file open in QuickBooks -> nothing is read or written
        client.post("/api/sync/request", headers=he, json={"full_resync": False})
        assert session(client, "qbwc_eng", "Eng-secret-1", r"C:\QB\synex.qbw") == ["<refused>"]
        last = client.get("/api/sync/logs", headers=he).json()[0]
        assert last["status"] == "failed" and "Wrong company file" in last["error_message"]

        # a user limited to company 2 cannot see company 1
        client.post("/api/users", headers=h, json={"username": "enguser", "email": "e@x.lk", "password": "Eng-Pass-2468",
                                                   "role_name": "viewer", "company_ids": [eng["company_id"]]})
        hu = {"Authorization": "Bearer " + client.post("/api/auth/login", data={"username": "enguser",
                                                                                "password": "Eng-Pass-2468"}).json()["access_token"]}
        assert [c["name"] for c in client.get("/api/companies/mine", headers=hu).json()] == ["Synex Engineering"]
        assert client.get("/api/qb/customer", headers={**hu, "X-Company-Id": "1"}).status_code == 403
        assert client.get("/api/qb/customer", headers=hu).json()["total"] == 1
