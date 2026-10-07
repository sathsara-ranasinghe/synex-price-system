"""qbXML <-> JSON for registry entities: request builders, Ret parsing and record summaries."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from xml.sax.saxutils import escape

from .registry import ADDRESS_PARTS, REPORTS, Entity, F, LineType

LIST_TAG_SUFFIXES = ("LineRet", "LineGroupRet", "DebitLine", "CreditLine", "AppliedToTxnRet", "LinkedTxn",
                     "DataExtRet", "ColDesc", "DataRow", "TextRow", "SubtotalRow", "TotalRow", "ColData")
MOD_WRAPPERS = {"SalesAndPurchase": "SalesAndPurchaseMod", "SalesOrPurchase": "SalesOrPurchaseMod"}


class BuildError(ValueError):
    pass


# ---------------------------------------------------------------- XML -> dict

def to_dict(el) -> dict | str:
    """Convert a Ret element to JSON. Repeating elements (lines, linked txns) are always lists."""
    children = [c for c in el if isinstance(c.tag, str)]
    if not children:
        return (el.text or "").strip()
    out: dict = {}
    if el.attrib:
        out["@"] = dict(el.attrib)
    for c in children:
        v = to_dict(c)
        if c.tag.endswith(LIST_TAG_SUFFIXES):
            out.setdefault(c.tag, []).append(v)
        elif c.tag in out:
            if not isinstance(out[c.tag], list):
                out[c.tag] = [out[c.tag]]
            out[c.tag].append(v)
        else:
            out[c.tag] = v
    return out


def get(data: dict, path: str):
    cur = data
    for part in path.split("/"):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _ref_name(v) -> str | None:
    if isinstance(v, dict):
        return v.get("FullName") or v.get("ListID")
    return v


def _dec(v) -> Decimal | None:
    try:
        return Decimal(str(v)) if v not in (None, "") else None
    except InvalidOperation:
        return None


def summary(entity: Entity, data: dict) -> dict:
    """Columns stored next to the JSON for searching and listing."""
    party = get(data, entity.party_path) if entity.party_path else None
    name = get(data, entity.name_path) or data.get("Name") or data.get("RefNumber")
    if entity.kind == "txn" and not name:
        name = data.get("TxnNumber") or data.get("TxnID")
    td = data.get("TxnDate")
    tm = data.get("TimeModified")
    return {
        "edit_sequence": data.get("EditSequence"),
        "name": str(name)[:400] if name else None,
        "party_id": party.get("ListID") if isinstance(party, dict) else None,
        "party_name": _ref_name(party),
        "txn_date": date.fromisoformat(td[:10]) if td else None,
        "amount": _dec(get(data, entity.amount_path)) if entity.amount_path else None,
        "is_active": data.get("IsActive", "true") != "false",
        "time_modified": datetime.fromisoformat(tm) if tm else None,
    }


# ---------------------------------------------------------------- record -> form values

def normalize(entity: Entity, data: dict) -> dict:
    """Older QB items keep prices in SalesOrPurchase; present them like SalesAndPurchase."""
    if "SalesOrPurchase" in data and "SalesAndPurchase" not in data and any(
            f.path.startswith("SalesAndPurchase/") for f in entity.fields):
        sop = data["SalesOrPurchase"]
        data = {**data, "SalesAndPurchase": {"SalesDesc": sop.get("Desc"), "SalesPrice": sop.get("Price"),
                                             "IncomeAccountRef": sop.get("AccountRef")}}
    return data


def to_form(entity: Entity, data: dict) -> dict:
    data = normalize(entity, data)
    values = {f.path: get(data, f.path) for f in entity.fields}
    lines = []
    for lt in entity.lines:
        for ln in data.get(lt.ret_tag, []) or []:
            if isinstance(ln, dict):
                lines.append({"type": lt.key, "TxnLineID": ln.get("TxnLineID"),
                              "values": {f.path: get(ln, f.path) for f in lt.fields}})
    return {"values": values, "lines": lines}


# ---------------------------------------------------------------- form values -> qbXML

def _scalar(f: F, v) -> str:
    if f.min is not None and f.type in ("money", "decimal", "int"):
        d = _dec(v)
        if d is not None and d < Decimal(str(f.min)):
            raise BuildError(f"{f.label} cannot be less than {f.min:g}")
    if f.type == "money":
        d = _dec(v)
        if d is None:
            raise BuildError(f"{f.label}: not a number")
        return f"{d.quantize(Decimal('0.01'))}"
    if f.type == "decimal":
        d = _dec(v)
        if d is None:
            raise BuildError(f"{f.label}: not a number")
        return format(d.normalize(), "f")
    if f.type == "int":
        try:
            return str(int(v))
        except (TypeError, ValueError):
            raise BuildError(f"{f.label}: not a whole number")
    if f.type == "bool":
        return "true" if v in (True, "true", "1", 1) else "false"
    if f.type == "date":
        return str(v)[:10]
    if f.type == "enum" and f.options and v not in f.options:
        raise BuildError(f"{f.label}: must be one of {', '.join(f.options)}")
    text = str(v)
    if f.max and len(text) > f.max:
        raise BuildError(f"{f.label}: at most {f.max} characters")
    return text


def _element(f: F, tag: str, v) -> str:
    if v is None or v == "" or v == {} or (f.type == "ref" and isinstance(v, dict) and not v.get("ListID")):
        return ""
    if f.type == "ref":
        list_id = v.get("ListID") if isinstance(v, dict) else v
        return f"<{tag}><ListID>{escape(str(list_id))}</ListID></{tag}>"
    if f.type == "address":
        if not isinstance(v, dict):
            return ""
        inner = "".join(f"<{p}>{escape(str(v[p])[:41])}</{p}>" for p in ADDRESS_PARTS if v.get(p))
        return f"<{tag}>{inner}</{tag}>" if inner else ""
    return f"<{tag}>{escape(_scalar(f, v))}</{tag}>"


def build_fields(fields: tuple[F, ...], values: dict, mode: str) -> str:
    """Serialize values in field order; "A/B" paths share an <A> wrapper with neighbouring "A/..." fields."""
    out, group, buf = [], None, []

    def flush():
        if group and buf:
            tag = MOD_WRAPPERS.get(group, group) if mode == "mod" else group
            out.append(f"<{tag}>{''.join(buf)}</{tag}>")

    for f in fields:
        if (mode == "add" and not f.add) or (mode == "mod" and not f.mod):
            continue
        v = values.get(f.path)
        if mode == "add" and f.required and (v is None or v == "" or v == {}):
            if f.type == "bool":
                v = True
            else:
                raise BuildError(f"{f.label} is required")
        parts = f.path.split("/")
        prefix = parts[0] if len(parts) > 1 else None
        if prefix != group:
            flush()
            group, buf = prefix, []
        el = _element(f, parts[-1], v)
        (buf if prefix else out).append(el)
    flush()
    return "".join(out)


def _lines(entity: Entity, lines: list[dict] | None, mode: str) -> str:
    if lines is None:
        return ""
    xml = []
    for lt in entity.lines:  # all lines of one type, in registry order (e.g. Expense before Item)
        for ln in (x for x in lines if x.get("type") == lt.key):
            if mode == "mod":
                if not lt.mod_tag:
                    raise BuildError(f"{lt.label} lines cannot be edited in QuickBooks; delete and re-create")
                body = f"<TxnLineID>{escape(ln.get('TxnLineID') or '-1')}</TxnLineID>"
                xml.append(f"<{lt.mod_tag}>{body}{build_fields(lt.fields, ln.get('values') or {}, 'add')}</{lt.mod_tag}>")
            else:
                xml.append(f"<{lt.add_tag}>{build_fields(lt.fields, ln.get('values') or {}, 'add')}</{lt.add_tag}>")
    return "".join(xml)


def build_add(entity: Entity, values: dict, lines: list[dict] | None, rid: str) -> str:
    if not entity.can_add:
        raise BuildError(f"{entity.plural} cannot be created through the SDK")
    if entity.key == "receive_payment":  # apply to the picked invoices, or let QuickBooks auto-apply
        values = {**values, "IsAutoApply": None if lines else True}
    elif entity.lines and not lines and entity.key not in ("item_group", "item_assembly") \
            and not values.get("LinkToTxnID"):
        raise BuildError("Add at least one line")
    body = build_fields(entity.fields, values, "add") + _lines(entity, lines, "add")
    return f'<{entity.base}AddRq requestID="{rid}"><{entity.base}Add>{body}</{entity.base}Add></{entity.base}AddRq>'


def build_mod(entity: Entity, qb_id: str, edit_sequence: str, values: dict, lines: list[dict] | None, rid: str) -> str:
    if not entity.can_mod:
        raise BuildError(f"{entity.plural} cannot be edited through the SDK; delete and re-create")
    idf = entity.id_field
    body = (f"<{idf}>{escape(qb_id)}</{idf}><EditSequence>{escape(edit_sequence)}</EditSequence>"
            + build_fields(entity.fields, values, "mod") + _lines(entity, lines, "mod"))
    return f'<{entity.base}ModRq requestID="{rid}"><{entity.base}Mod>{body}</{entity.base}Mod></{entity.base}ModRq>'


def build_query_by_id(entity: Entity, qb_id: str, rid: str) -> str:
    idf = entity.id_field
    lines = "<IncludeLineItems>true</IncludeLineItems>" if entity.kind == "txn" and entity.include_lines else ""
    return f'<{entity.query} requestID="{rid}"><{idf}>{escape(qb_id)}</{idf}>{lines}</{entity.query}>'


def build_delete(entity: Entity, qb_id: str, rid: str) -> str:
    if not entity.del_type:
        raise BuildError(f"{entity.plural} cannot be deleted")
    if entity.kind == "list":
        return (f'<ListDelRq requestID="{rid}"><ListDelType>{entity.del_type}</ListDelType>'
                f"<ListID>{escape(qb_id)}</ListID></ListDelRq>")
    return (f'<TxnDelRq requestID="{rid}"><TxnDelType>{entity.del_type}</TxnDelType>'
            f"<TxnID>{escape(qb_id)}</TxnID></TxnDelRq>")


def build_void(entity: Entity, qb_id: str, rid: str) -> str:
    if not entity.can_void:
        raise BuildError(f"{entity.plural} cannot be voided")
    return (f'<TxnVoidRq requestID="{rid}"><TxnVoidType>{entity.del_type}</TxnVoidType>'
            f"<TxnID>{escape(qb_id)}</TxnID></TxnVoidRq>")


def build_report(report_type: str, from_date: date | None, to_date: date | None, rid: str) -> str:
    family, _ = REPORTS[report_type]
    rq, tag = {"General": ("GeneralSummaryReportQueryRq", "GeneralSummaryReportType"),
               "Detail": ("GeneralDetailReportQueryRq", "GeneralDetailReportType"),
               "Aging": ("AgingReportQueryRq", "AgingReportType")}[family]
    period = ""
    if family in ("General", "Detail") and (from_date or to_date):
        period = "<ReportPeriod>" + (f"<FromReportDate>{from_date}</FromReportDate>" if from_date else "") + (
            f"<ToReportDate>{to_date}</ToReportDate>" if to_date else "") + "</ReportPeriod>"
    elif family == "Aging" and to_date:
        period = f"<ReportPeriod><ToReportDate>{to_date}</ToReportDate></ReportPeriod>"
    return f'<{rq} requestID="{rid}"><{tag}>{report_type}</{tag}>{period}</{rq}>'


def parse_report(ret) -> dict:
    """ReportRet -> {title, columns, rows:[{kind, cells}]}."""
    cols = {}
    for cd in ret.findall("ColDesc"):
        titles = [ct.get("value") for ct in cd.findall("ColTitle") if ct.get("value")]
        cols[cd.get("colID")] = " ".join(titles)
    order = sorted(cols, key=lambda c: int(c))
    rows = []
    data = ret.find("ReportData")
    for r in (data if data is not None else []):
        if not isinstance(r.tag, str):
            continue
        cells = {c.get("colID"): c.get("value") for c in r.findall("ColData")}
        if r.tag == "TextRow":
            cells = {order[0] if order else "1": r.get("value")}
        rows.append({"kind": r.tag.replace("Row", "").lower(), "cells": [cells.get(c, "") for c in order]})
    return {"title": (ret.findtext("ReportTitle") or "").strip(), "subtitle": (ret.findtext("ReportSubtitle") or "").strip(),
            "columns": [cols[c] for c in order], "rows": rows}


def line_total(lt: LineType, values: dict) -> Decimal:
    if not lt.amount:
        return Decimal(0)
    if "*" in lt.amount:
        a, b = lt.amount.split("*")
        return (_dec(values.get(a)) or Decimal(0)) * (_dec(values.get(b)) or Decimal(0))
    return _dec(values.get(lt.amount)) or Decimal(0)
