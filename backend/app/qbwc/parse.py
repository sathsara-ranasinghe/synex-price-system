"""Parse qbXML responses returned by the Web Connector."""

import re
from dataclasses import dataclass, field

from lxml import etree

_XML_DECL = re.compile(r"^\s*<\?xml[^>]*\?>", re.IGNORECASE)


@dataclass
class ParsedResponse:
    request_id: str | None
    status_code: int
    status_severity: str
    status_message: str
    iterator_id: str | None
    iterator_remaining: int
    rets: list = field(default_factory=list)


def parse_response(xml: str) -> ParsedResponse:
    root = etree.fromstring(_XML_DECL.sub("", xml, count=1))
    rs = root.find("QBXMLMsgsRs")
    rs = rs[0] if rs is not None and len(rs) else None
    if rs is None:
        raise ValueError("No response element in qbXML")
    return ParsedResponse(
        request_id=rs.get("requestID"),
        status_code=int(rs.get("statusCode", "0")),
        status_severity=rs.get("statusSeverity", ""),
        status_message=rs.get("statusMessage", ""),
        iterator_id=rs.get("iteratorID"),
        iterator_remaining=int(rs.get("iteratorRemainingCount", "0") or 0),
        rets=[r for r in rs if isinstance(r.tag, str)],
    )
