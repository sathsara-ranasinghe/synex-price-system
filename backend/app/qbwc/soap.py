"""Minimal SOAP 1.1 server implementing the QuickBooks Web Connector (QBWC) web service."""

import uuid

from fastapi import APIRouter, Depends, Request, Response
from lxml import etree
from sqlalchemy.orm import Session
from xml.sax.saxutils import escape

from ..config import get_settings
from ..database import get_db
from . import service

router = APIRouter(tags=["QuickBooks Web Connector"])

NS = "http://developer.intuit.com/"
SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"


def _soap(method: str, inner: str) -> Response:
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<soap:Envelope xmlns:soap="{SOAP_NS}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema">'
        f'<soap:Body><{method}Response xmlns="{NS}">{inner}</{method}Response></soap:Body></soap:Envelope>'
    )
    return Response(content=xml, media_type="text/xml; charset=utf-8")


def _str_result(method: str, value: str) -> Response:
    return _soap(method, f"<{method}Result>{escape(value or '')}</{method}Result>")


def _fault(message: str) -> Response:
    xml = (
        f'<?xml version="1.0" encoding="utf-8"?><soap:Envelope xmlns:soap="{SOAP_NS}"><soap:Body>'
        f"<soap:Fault><faultcode>soap:Client</faultcode><faultstring>{escape(message)}</faultstring>"
        "</soap:Fault></soap:Body></soap:Envelope>"
    )
    return Response(content=xml, media_type="text/xml; charset=utf-8", status_code=500)


@router.get("/qbwc")
def qbwc_info():
    return Response("Synex QuickBooks Web Connector endpoint. POST SOAP requests here.", media_type="text/plain")


@router.post("/qbwc")
async def qbwc(request: Request, db: Session = Depends(get_db)):
    try:
        root = etree.fromstring(await request.body(), parser=etree.XMLParser(resolve_entities=False, no_network=True))
        body = root.find(f"{{{SOAP_NS}}}Body")
        call = body[0]
    except Exception:
        return _fault("Malformed SOAP request")

    method = etree.QName(call).localname
    args = {etree.QName(c).localname: (c.text or "") for c in call}

    if method == "serverVersion":
        return _str_result(method, service.SERVER_VERSION)
    if method == "clientVersion":
        return _str_result(method, "")  # accept any QBWC version
    if method == "authenticate":
        ticket, status = service.authenticate(db, args.get("strUserName", ""), args.get("strPassword", ""))
        return _soap(method, f"<authenticateResult><string>{escape(ticket)}</string>"
                             f"<string>{escape(status)}</string></authenticateResult>")
    if method == "sendRequestXML":
        xml = service.send_request_xml(db, args.get("ticket", ""), args.get("strCompanyFileName", ""),
                                       args.get("qbXMLMajorVers", ""), args.get("qbXMLMinorVers", ""))
        return _str_result(method, xml)
    if method == "receiveResponseXML":
        pct = service.receive_response_xml(db, args.get("ticket", ""), args.get("response", ""),
                                           args.get("hresult", ""), args.get("message", ""))
        return _soap(method, f"<receiveResponseXMLResult>{pct}</receiveResponseXMLResult>")
    if method == "connectionError":
        return _str_result(method, service.connection_error(db, args.get("ticket", ""), args.get("hresult", ""),
                                                             args.get("message", "")))
    if method == "getLastError":
        return _str_result(method, service.get_last_error(db, args.get("ticket", "")))
    if method == "closeConnection":
        return _str_result(method, service.close_connection(db, args.get("ticket", "")))
    if method == "getInteractiveURL" or method == "interactiveRejected" or method == "interactiveDone":
        return _str_result(method, "")
    return _fault(f"Unknown method {method}")


def company_qbwc_url(company) -> str:
    return company.qbwc_url or get_settings().qbwc_public_url


def build_qwc(company, poll_minutes: int = 5) -> str:
    """The .qwc file opened once in Web Connector to register one company.

    Web Connector 2.2+ requires a FileID and stores it in the company file as a data extension,
    which QuickBooks only allows for read/write apps (status 3263 otherwise), so IsReadOnly is false.
    Company 1 keeps the IDs it was first registered with; every other company gets its own."""
    s = get_settings()
    url = company_qbwc_url(company)
    # Owner/File IDs stay tied to the original setting so editing the URL later does not change them.
    suffix = "" if company.company_id == 1 else f"/company/{company.company_id}"
    owner = uuid.uuid5(uuid.NAMESPACE_URL, s.qbwc_public_url + suffix)
    file_id = uuid.uuid5(uuid.NAMESPACE_URL, s.qbwc_public_url + suffix + "/file")
    return f"""<?xml version="1.0"?>
<QBWCXML>
  <AppName>{escape(company.app_name)}</AppName>
  <AppID></AppID>
  <AppURL>{escape(url)}</AppURL>
  <AppDescription>Synex QB Portal - {escape(company.name)}</AppDescription>
  <AppSupport>{escape(url.rsplit('/qbwc', 1)[0])}/</AppSupport>
  <UserName>{escape(company.qbwc_username)}</UserName>
  <OwnerID>{{{str(owner).upper()}}}</OwnerID>
  <FileID>{{{str(file_id).upper()}}}</FileID>
  <QBType>QBFS</QBType>
  <Scheduler>
    <RunEveryNMinutes>{poll_minutes}</RunEveryNMinutes>
  </Scheduler>
  <IsReadOnly>false</IsReadOnly>
  <UnattendedModePref>umpRequired</UnattendedModePref>
  <PersonalDataPref>pdpOptional</PersonalDataPref>
</QBWCXML>
"""
