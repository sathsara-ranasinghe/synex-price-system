"""Sample qbXML responses shaped like QuickBooks Desktop 2024 output (used by tests and the simulator)."""

VENDORS = """<?xml version="1.0" ?><QBXML><QBXMLMsgsRs>
<VendorQueryRs requestID="vendors:0" statusCode="0" statusSeverity="Info" statusMessage="Status OK"
  iteratorRemainingCount="0" iteratorID="{abc}">
<VendorRet><ListID>80000001-1</ListID><EditSequence>1</EditSequence><Name>ABC Hardware</Name><IsActive>true</IsActive>
<CompanyName>ABC Hardware (Pvt) Ltd</CompanyName><Phone>011 2345678</Phone><Email>sales@abc.lk</Email>
<VendorAddress><Addr1>12 Main St</Addr1><City>Colombo</City></VendorAddress><TermsRef><FullName>Net 30</FullName></TermsRef>
</VendorRet>
<VendorRet><ListID>80000002-1</ListID><Name>Lanka Electricals</Name><IsActive>true</IsActive></VendorRet>
</VendorQueryRs></QBXMLMsgsRs></QBXML>"""

INVENTORY = """<?xml version="1.0" ?><QBXML><QBXMLMsgsRs>
<ItemInventoryQueryRs requestID="item_inventory:0" statusCode="0" statusSeverity="Info" statusMessage="OK">
<ItemInventoryRet><ListID>I-1</ListID><TimeModified>2026-01-01T10:00:00+05:30</TimeModified><Name>PVC-20MM</Name>
<FullName>Pipes:PVC-20MM</FullName><IsActive>true</IsActive><ParentRef><FullName>Pipes</FullName></ParentRef>
<SalesDesc>PVC Pipe 20mm</SalesDesc><SalesPrice>600.00</SalesPrice><PurchaseDesc>PVC Pipe 20mm x 6m</PurchaseDesc>
<PurchaseCost>450.00</PurchaseCost><PrefVendorRef><ListID>80000001-1</ListID></PrefVendorRef></ItemInventoryRet>
</ItemInventoryQueryRs></QBXMLMsgsRs></QBXML>"""

NONINV = """<?xml version="1.0" ?><QBXML><QBXMLMsgsRs>
<ItemNonInventoryQueryRs requestID="item_noninventory:0" statusCode="0" statusSeverity="Info" statusMessage="OK">
<ItemNonInventoryRet><ListID>I-2</ListID><Name>CABLE-2.5</Name><IsActive>true</IsActive>
<SalesAndPurchase><SalesDesc>Cable 2.5mm</SalesDesc><PurchaseDesc>Cable 2.5mm roll</PurchaseDesc>
<PurchaseCost>8000</PurchaseCost><PrefVendorRef><ListID>80000002-1</ListID></PrefVendorRef></SalesAndPurchase>
</ItemNonInventoryRet></ItemNonInventoryQueryRs></QBXMLMsgsRs></QBXML>"""

BILLS = """<?xml version="1.0" ?><QBXML><QBXMLMsgsRs>
<BillQueryRs requestID="bills:0" statusCode="0" statusSeverity="Info" statusMessage="OK">
<BillRet><TxnID>T-1</TxnID><VendorRef><ListID>80000002-1</ListID></VendorRef><TxnDate>2026-09-01</TxnDate>
<RefNumber>B-100</RefNumber>
<ItemLineRet><ItemRef><ListID>I-1</ListID></ItemRef><Quantity>10</Quantity><Cost>430</Cost><Amount>4300</Amount></ItemLineRet>
<ItemLineRet><ItemRef><ListID>I-2</ListID></ItemRef><Quantity>2</Quantity><Amount>18000</Amount></ItemLineRet>
</BillRet></BillQueryRs></QBXMLMsgsRs></QBXML>"""


def empty(tag: str) -> str:
    return (f'<?xml version="1.0" ?><QBXML><QBXMLMsgsRs><{tag} statusCode="1" statusSeverity="Info" '
            f'statusMessage="A query request did not find a matching object"/></QBXMLMsgsRs></QBXML>')


RESPONSES = {
    "VendorQueryRq": VENDORS,
    "ItemInventoryQueryRq": INVENTORY,
    "ItemNonInventoryQueryRq": NONINV,
    "BillQueryRq": BILLS,
}
