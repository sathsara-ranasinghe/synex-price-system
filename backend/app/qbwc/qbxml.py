"""qbXML read-request builders for QuickBooks Desktop (2024 = qbXML 16.0/17.0).

The read steps come from the entity registry (app/qb/registry.py), plus two steps that pick up
records deleted in QuickBooks. Element order follows the Intuit OSR.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from ..qb.registry import CUSTOM_FIELD_ENTITIES, ENTITIES


@dataclass(frozen=True)
class Step:
    name: str  # checkpoint key = entity key
    request: str  # e.g. "VendorQueryRq"
    kind: str  # "list" | "txn" | "deleted_list" | "deleted_txn"
    iterator: bool = True
    include_lines: bool = True
    custom_fields: bool = False  # add OwnerID 0 so QuickBooks returns custom field values (DataExtRet)


LIST_DEL_TYPES = [e.del_type for e in ENTITIES if e.kind == "list" and e.del_type]
TXN_DEL_TYPES = [e.del_type for e in ENTITIES if e.kind == "txn" and e.del_type]

# Lists before transactions (vendors/items must exist before POs and bills reference them).
STEPS: list[Step] = (
    [Step(e.key, e.query, "list", e.iterator, custom_fields=e.key in CUSTOM_FIELD_ENTITIES)
     for e in ENTITIES if e.kind == "list"]
    + [Step(e.key, e.query, "txn", e.iterator, e.include_lines, e.key in CUSTOM_FIELD_ENTITIES)
       for e in ENTITIES if e.kind == "txn"]
    + [Step("deleted_lists", "ListDeletedQueryRq", "deleted_list", False),
       Step("deleted_txns", "TxnDeletedQueryRq", "deleted_txn", False)]
)
STEP_BY_NAME = {s.name: s for s in STEPS}


def qb_datetime(dt: datetime) -> str:
    """qbXML DATETIMETYPE, e.g. 2026-10-07T08:30:00+00:00"""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def envelope(body: str, version: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<?qbxml version="{version}"?>'
        '<QBXML><QBXMLMsgsRq onError="continueOnError">'
        f"{body}"
        "</QBXMLMsgsRq></QBXML>"
    )


def build_request(step: Step, *, since: datetime | None, max_returned: int, iterator_id: str | None,
                  request_id: str) -> str:
    attrs = f'requestID="{escape(request_id)}"'
    if step.iterator:
        attrs += (f' iterator="Continue" iteratorID="{escape(iterator_id)}"' if iterator_id
                  else ' iterator="Start"')

    if step.kind in ("deleted_list", "deleted_txn"):
        types, tag = (LIST_DEL_TYPES, "ListDelType") if step.kind == "deleted_list" else (TXN_DEL_TYPES, "TxnDelType")
        body = "".join(f"<{tag}>{t}</{tag}>" for t in types)
        if since:
            body += f"<DeletedDateRangeFilter><FromDeletedDate>{qb_datetime(since)}</FromDeletedDate></DeletedDateRangeFilter>"
        return f"<{step.request} {attrs}>{body}</{step.request}>"

    parts = [f"<MaxReturned>{max_returned}</MaxReturned>"] if step.iterator else []
    if step.kind == "list":
        parts.append("<ActiveStatus>All</ActiveStatus>")
        if since:
            parts.append(f"<FromModifiedDate>{qb_datetime(since)}</FromModifiedDate>")
    else:
        if since:
            parts.append(f"<ModifiedDateRangeFilter><FromModifiedDate>{qb_datetime(since)}</FromModifiedDate>"
                         "</ModifiedDateRangeFilter>")
        if step.include_lines:
            parts.append("<IncludeLineItems>true</IncludeLineItems>")
    if step.custom_fields:
        parts.append("<OwnerID>0</OwnerID>")  # always the last element of a query
    return f"<{step.request} {attrs}>{''.join(parts)}</{step.request}>"
