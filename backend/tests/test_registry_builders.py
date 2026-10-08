"""Every registry entity and report produces well-formed qbXML with elements in registry (OSR) order."""

import re
from datetime import datetime, timezone

import pytest
from lxml import etree

from app.qb import builder
from app.qb.registry import BY_KEY, ENTITIES, REF_GROUPS, REPORTS, F
from app.qbwc.qbxml import STEPS, build_request, envelope

SAMPLE = {"str": "Test", "text": "Some text", "int": 3, "decimal": "2.5", "money": "125.5", "date": "2026-10-08",
          "bool": True, "ref": {"ListID": "80000001-1", "FullName": "Test"}, "address": {"Addr1": "1 Main St", "City": "Colombo"},
          "txnref": "TXN-1"}


def sample(f: F):
    if f.type == "enum":
        return f.options[0]
    v = SAMPLE[f.type]
    if f.max and isinstance(v, str):
        v = v[: f.max]
    return v


def values_for(fields, required_only=False):
    return {f.path: sample(f) for f in fields if f.add and (f.required or not required_only)}


def lines_for(ent):
    return [{"type": lt.key, "values": values_for(lt.fields)} for lt in ent.lines]


def parse(xml: str):
    return etree.fromstring(f"<root>{xml}</root>")[0]


def expected_order(fields, mode: str) -> list[str]:
    tags = []
    for f in fields:
        if (mode == "add" and not f.add) or (mode == "mod" and not f.mod):
            continue
        tag = f.path.split("/")[0]
        if mode == "mod":
            tag = builder.MOD_WRAPPERS.get(tag, tag) if "/" in f.path else tag
        if not tags or tags[-1] != tag:
            tags.append(tag)
    return tags


ENTITY_IDS = [e.key for e in ENTITIES]


def test_registry_is_consistent():
    assert len(ENTITIES) >= 50 and len(set(ENTITY_IDS)) == len(ENTITY_IDS)
    for e in ENTITIES:
        for f in e.fields + tuple(f for lt in e.lines for f in lt.fields):
            if f.type in ("ref", "txnref"):
                targets = REF_GROUPS.get(f.ref, [f.ref])
                assert all(t in BY_KEY for t in targets), f"{e.key}.{f.path} -> unknown ref {f.ref}"
            if f.type == "enum":
                assert f.options, f"{e.key}.{f.path} enum without options"
        assert e.module in {"sales", "purchasing", "banking", "accounting", "inventory", "lists"}


@pytest.mark.parametrize("key", [e.key for e in ENTITIES if e.can_add])
def test_add_request_is_ordered(key):
    ent = BY_KEY[key]
    values = values_for(ent.fields)
    xml = builder.build_add(ent, values, lines_for(ent) or None, "r1")
    rq = parse(xml)
    assert rq.tag == f"{ent.base}AddRq" and rq.get("requestID") == "r1"
    body = rq[0]
    assert body.tag == f"{ent.base}Add"
    header = [c.tag for c in body if not c.tag.endswith(tuple(lt.add_tag for lt in ent.lines))]
    expected = [t for t in expected_order(ent.fields, "add") if t in header]
    assert header == expected, f"{key}: {header} != {expected}"
    # lines come after the header, grouped by type in registry order
    line_tags = [c.tag for c in body if c.tag in {lt.add_tag for lt in ent.lines}]
    assert line_tags == [lt.add_tag for lt in ent.lines if lt.add_tag in line_tags]
    for lt in ent.lines:
        for ln in body.findall(lt.add_tag):
            got = [c.tag for c in ln]
            assert got == [t for t in expected_order(lt.fields, "add") if t in got], f"{key} line {lt.key}: {got}"


@pytest.mark.parametrize("key", [e.key for e in ENTITIES if e.can_add])
def test_add_requires_required_fields(key):
    ent = BY_KEY[key]
    required = [f for f in ent.fields if f.add and f.required and f.type != "bool"]
    if not required:
        pytest.skip("no required fields")
    with pytest.raises(builder.BuildError):
        builder.build_add(ent, {}, lines_for(ent) or None, "r")


@pytest.mark.parametrize("key", [e.key for e in ENTITIES if e.can_mod])
def test_mod_request_starts_with_id_and_edit_sequence(key):
    ent = BY_KEY[key]
    vals = {f.path: sample(f) for f in ent.fields if f.mod}
    lines = [{"type": lt.key, "TxnLineID": "L-1", "values": values_for(lt.fields)} for lt in ent.lines if lt.mod_tag]
    xml = builder.build_mod(ent, "ID-1", "42", vals, lines or None, "m1")
    body = parse(xml)[0]
    assert body.tag == f"{ent.base}Mod"
    assert [c.tag for c in body][:2] == [ent.id_field, "EditSequence"]
    header = [c.tag for c in body][2:]
    header = [t for t in header if not t.endswith("LineMod")]
    assert header == [t for t in expected_order(ent.fields, "mod") if t in header], f"{key}: {header}"
    for ln in body:
        if ln.tag.endswith("LineMod"):
            assert ln[0].tag == "TxnLineID"


@pytest.mark.parametrize("key", ENTITY_IDS)
def test_query_delete_void(key):
    ent = BY_KEY[key]
    q = parse(builder.build_query_by_id(ent, "ID-1", "q"))
    assert q.tag == ent.query and q[0].tag == ent.id_field
    if ent.del_type:
        d = parse(builder.build_delete(ent, "ID-1", "d"))
        assert d.tag == ("ListDelRq" if ent.kind == "list" else "TxnDelRq") and d[0].text == ent.del_type
    else:
        with pytest.raises(builder.BuildError):
            builder.build_delete(ent, "ID-1", "d")
    if ent.can_void:
        v = parse(builder.build_void(ent, "ID-1", "v"))
        assert v.tag == "TxnVoidRq" and v[0].text == ent.del_type


def test_cannot_edit_or_add_where_quickbooks_does_not_allow():
    for e in ENTITIES:
        if not e.can_mod:
            with pytest.raises(builder.BuildError):
                builder.build_mod(e, "ID", "1", {}, None, "m")
        if not e.can_add:
            with pytest.raises(builder.BuildError):
                builder.build_add(e, {}, None, "a")


@pytest.mark.parametrize("step", STEPS, ids=[s.name for s in STEPS])
def test_sync_read_requests(step):
    since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for batch in (False, True):
        xml = build_request(step, since=since, max_returned=100, iterator_id=None, request_id=step.name, batch=batch)
        rq = parse(xml)
        assert rq.tag == step.request
        if batch:
            assert rq.get("iterator") is None and rq.find("MaxReturned") is None
        elif step.iterator:
            assert rq.get("iterator") == "Start" and rq[0].tag == "MaxReturned"
        if rq.find("OwnerID") is not None:
            assert rq[-1].tag == "OwnerID"  # OwnerID must be the last element
    cont = parse(build_request(step, since=None, max_returned=100, iterator_id="{abc}", request_id="x"))
    if step.iterator:
        assert cont.get("iterator") == "Continue" and cont.get("iteratorID") == "{abc}"


def test_envelope_is_valid_qbxml():
    xml = envelope(builder.build_query_by_id(BY_KEY["invoice"], "T", "1"), "16.0")
    assert xml.startswith('<?xml version="1.0" encoding="utf-8"?><?qbxml version="16.0"?>')
    root = etree.fromstring(re.sub(r"^<\?xml[^>]*\?>", "", xml).encode())
    assert root.find("QBXMLMsgsRq").get("onError") == "continueOnError"


@pytest.mark.parametrize("report", list(REPORTS))
def test_report_requests(report):
    rq = parse(builder.build_report(report, datetime(2026, 1, 1).date(), datetime(2026, 12, 31).date(), "r"))
    family = REPORTS[report][0]
    assert rq.tag == {"General": "GeneralSummaryReportQueryRq", "Detail": "GeneralDetailReportQueryRq",
                      "Aging": "AgingReportQueryRq"}[family]
    assert rq[0].text == report
    period = rq.find("ReportPeriod")
    assert period is not None and period[-1].tag == "ToReportDate"


def test_scalar_validation():
    f_money = F("Amount", "Amount", "money", min=0)
    with pytest.raises(builder.BuildError):
        builder._scalar(f_money, "-1")
    with pytest.raises(builder.BuildError):
        builder._scalar(F("X", "X", "int"), "abc")
    with pytest.raises(builder.BuildError):
        builder._scalar(F("X", "X", max=3), "abcd")
    with pytest.raises(builder.BuildError):
        builder._scalar(F("X", "X", "enum", options=("A",)), "B")
    assert builder._scalar(f_money, "10") == "10.00"
    assert builder._scalar(F("Q", "Q", "decimal"), "2.50") == "2.5"
    assert builder._scalar(F("B", "B", "bool"), True) == "true"


def test_ret_to_form_round_trip():
    ent = BY_KEY["invoice"]
    ret = etree.fromstring(
        "<InvoiceRet><TxnID>T-1</TxnID><EditSequence>7</EditSequence><TxnNumber>9</TxnNumber>"
        "<CustomerRef><ListID>C-1</ListID><FullName>Hilton</FullName></CustomerRef><TxnDate>2026-10-08</TxnDate>"
        "<RefNumber>INV-1</RefNumber><BillAddress><Addr1>1 Main</Addr1></BillAddress><Subtotal>150.00</Subtotal>"
        "<InvoiceLineRet><TxnLineID>L-1</TxnLineID><ItemRef><ListID>I-1</ListID></ItemRef><Quantity>3</Quantity>"
        "<Rate>50</Rate></InvoiceLineRet><InvoiceLineRet><TxnLineID>L-2</TxnLineID><Desc>Note</Desc></InvoiceLineRet>"
        "<LinkedTxn><TxnID>P-1</TxnID></LinkedTxn></InvoiceRet>")
    data = builder.to_dict(ret)
    assert isinstance(data["InvoiceLineRet"], list) and len(data["InvoiceLineRet"]) == 2
    assert isinstance(data["LinkedTxn"], list)
    summary = builder.summary(ent, data)
    assert summary["name"] == "INV-1" and summary["party_name"] == "Hilton" and float(summary["amount"]) == 150
    form = builder.to_form(ent, data)
    assert form["values"]["CustomerRef"]["ListID"] == "C-1" and form["lines"][0]["TxnLineID"] == "L-1"
    # rebuilding a Mod from the form keeps the line ids
    mod = parse(builder.build_mod(ent, "T-1", "7", form["values"], form["lines"], "m"))
    assert [ln.findtext("TxnLineID") for ln in mod[0].findall("InvoiceLineMod")] == ["L-1", "L-2"]


def test_report_parsing():
    ret = etree.fromstring(
        '<ReportRet><ReportTitle>P&amp;L</ReportTitle><ReportSubtitle>2026</ReportSubtitle>'
        '<ColDesc colID="1"><ColTitle titleRow="1"/></ColDesc><ColDesc colID="2"><ColTitle titleRow="1" value="TOTAL"/></ColDesc>'
        '<ReportData><TextRow rowNumber="1" value="Income"/>'
        '<DataRow rowNumber="2"><ColData colID="1" value="Sales"/><ColData colID="2" value="10.00"/></DataRow>'
        '<SubtotalRow rowNumber="3"><ColData colID="1" value="Total"/><ColData colID="2" value="10.00"/></SubtotalRow>'
        '</ReportData></ReportRet>')
    r = builder.parse_report(ret)
    assert r["title"] == "P&L" and r["columns"] == ["", "TOTAL"]
    assert [x["kind"] for x in r["rows"]] == ["text", "data", "subtotal"]
    assert r["rows"][1]["cells"] == ["Sales", "10.00"]
