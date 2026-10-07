"""Pretend to be QuickBooks Web Connector so you can see data in the UI without QuickBooks.

Usage (backend running on :8000 with QBWC_PASSWORD=secret):
    python -m scripts.simulate_qbwc http://localhost:8000 qbwc secret
"""

import re
import sys
from xml.sax.saxutils import escape

import httpx

from tests.sample_qbxml import RESPONSES, empty


def call(client: httpx.Client, url: str, method: str, **args) -> str:
    inner = "".join(f"<{k}>{escape(v)}</{k}>" for k, v in args.items())
    body = ('<?xml version="1.0"?><soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>'
            f'<{method} xmlns="http://developer.intuit.com/">{inner}</{method}></soap:Body></soap:Envelope>')
    return client.post(url, content=body, headers={"Content-Type": "text/xml"}).text


def main(base: str, user: str, password: str) -> None:
    url = base.rstrip("/") + "/qbwc"
    with httpx.Client(timeout=60) as c:
        ticket, status = re.findall(r"<string>(.*?)</string>", call(c, url, "authenticate", strUserName=user, strPassword=password))
        if status in ("none", "nvu"):
            print("Server says:", "nothing to do" if status == "none" else "invalid user")
            return
        pct = 0
        while pct < 100:
            req = call(c, url, "sendRequestXML", ticket=ticket, strHCPResponse="", strCompanyFileName="demo.qbw",
                       qbXMLCountry="US", qbXMLMajorVers="16", qbXMLMinorVers="0")
            rq = re.search(r"&lt;(\w+QueryRq) ", req).group(1)
            out = call(c, url, "receiveResponseXML", ticket=ticket, response=RESPONSES.get(rq, empty(rq[:-2] + "Rs")),
                       hresult="", message="")
            pct = int(re.search(r"Result>(-?\d+)<", out).group(1))
            print(f"{rq:32} -> {pct}%")
        print(re.search(r"Result>(.*?)<", call(c, url, "closeConnection", ticket=ticket)).group(1))


if __name__ == "__main__":
    main(*(sys.argv[1:4] if len(sys.argv) >= 4 else ["http://localhost:8000", "qbwc", "secret"]))
