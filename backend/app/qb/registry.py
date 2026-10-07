"""Registry of QuickBooks Desktop entities the portal supports.

Each Entity describes how to query, add, modify and delete one qbXML object. The generic sync engine,
the write outbox, the REST API and the Angular forms are all driven from this file.

FIELD ORDER MATTERS: qbXML rejects elements out of sequence, so `fields` (and line fields) are listed in the
order of the Intuit OSR for the Add request. Paths with "/" ("SalesAndPurchase/SalesDesc") become nested
elements; consecutive fields with the same prefix share one wrapper element.
"""

from dataclasses import dataclass, field

# field types: str text int decimal money date bool enum ref address txnref
ADDRESS_PARTS = ["Addr1", "Addr2", "Addr3", "Addr4", "Addr5", "City", "State", "PostalCode", "Country", "Note"]


@dataclass(frozen=True)
class F:
    path: str
    label: str
    type: str = "str"
    ref: str | None = None  # entity key (or "item" / "entity" / "account") for ref pickers
    add: bool = True
    mod: bool = True
    required: bool = False
    max: int | None = None
    options: tuple[str, ...] = ()
    list: bool = False  # show as a column in list views
    min: float | None = None  # lowest allowed value for numbers (QuickBooks rejects e.g. negative credit limits)


@dataclass(frozen=True)
class LineType:
    key: str  # "item", "expense", "debit" ...
    label: str
    add_tag: str  # e.g. InvoiceLineAdd
    mod_tag: str | None  # e.g. InvoiceLineMod (None = lines cannot be edited)
    ret_tag: str  # e.g. InvoiceLineRet
    fields: tuple[F, ...]
    amount: str | None = "Amount"  # how to total a line: "Quantity*Rate", "Quantity*Cost" or a field


@dataclass(frozen=True)
class Entity:
    key: str
    label: str
    plural: str
    module: str
    kind: str  # list | txn
    base: str  # qbXML base name, e.g. "Customer" -> CustomerQueryRq / CustomerAdd / CustomerRet
    fields: tuple[F, ...]
    lines: tuple[LineType, ...] = ()
    can_add: bool = True
    can_mod: bool = True
    del_type: str | None = None  # ListDelType / TxnDelType; None = cannot delete
    can_void: bool = False
    iterator: bool = True
    include_lines: bool = True  # send IncludeLineItems on queries (transactions)
    name_path: str = "Name"  # what to show as the record title
    party_path: str | None = None  # CustomerRef / VendorRef / PayeeEntityRef ...
    amount_path: str | None = None
    query_rq: str | None = None  # override (e.g. StandardTermsQueryRq)

    @property
    def id_field(self) -> str:
        return "ListID" if self.kind == "list" else "TxnID"

    @property
    def query(self) -> str:
        return self.query_rq or f"{self.base}QueryRq"

    @property
    def ret_tag(self) -> str:
        return f"{self.base}Ret"


# ---------------------------------------------------------------- shared field sets

ACCOUNT_TYPES = ("AccountsPayable", "AccountsReceivable", "Bank", "CostOfGoodsSold", "CreditCard", "Equity",
                 "Expense", "FixedAsset", "Income", "LongTermLiability", "NonPosting", "OtherAsset",
                 "OtherCurrentAsset", "OtherCurrentLiability", "OtherExpense", "OtherIncome")

SALES_LINE = (F("ItemRef", "Item", "ref", ref="item", required=True), F("Desc", "Description", "text", max=4095),
              F("Quantity", "Qty", "decimal", min=0), F("Rate", "Rate", "money"), F("ClassRef", "Class", "ref", ref="class"))


def sales_line(base: str) -> LineType:
    return LineType("item", "Item", f"{base}LineAdd", f"{base}LineMod", f"{base}LineRet", SALES_LINE, "Quantity*Rate")


ITEM_LINE = LineType("item", "Item", "ItemLineAdd", "ItemLineMod", "ItemLineRet", (
    F("ItemRef", "Item", "ref", ref="item", required=True), F("Desc", "Description", "text", max=4095),
    F("Quantity", "Qty", "decimal", min=0), F("Cost", "Cost", "money"), F("CustomerRef", "Customer:Job", "ref", ref="customer"),
    F("ClassRef", "Class", "ref", ref="class")), "Quantity*Cost")

EXPENSE_LINE = LineType("expense", "Expense", "ExpenseLineAdd", "ExpenseLineMod", "ExpenseLineRet", (
    F("AccountRef", "Account", "ref", ref="account", required=True), F("Amount", "Amount", "money", required=True),
    F("Memo", "Memo", "str", max=4095), F("CustomerRef", "Customer:Job", "ref", ref="customer"),
    F("ClassRef", "Class", "ref", ref="class")))

NAME = F("Name", "Name", required=True, max=41, list=True)
ACTIVE = F("IsActive", "Active", "bool")


def item_entity(key: str, label: str, base: str, extra: tuple[F, ...]) -> Entity:
    return Entity(key, label, label + " items", "lists", "list", base, (
        F("Name", "Item name / code", required=True, max=31, list=True), ACTIVE,
        F("ParentRef", "Subitem of", "ref", ref="item"),
    ) + extra, del_type=base, name_path="FullName")


SALES_AND_PURCHASE = (
    F("SalesAndPurchase/SalesDesc", "Sales description", "text", max=4095, list=True),
    F("SalesAndPurchase/SalesPrice", "Sales price", "money", min=0, list=True),
    F("SalesAndPurchase/IncomeAccountRef", "Income account", "ref", ref="account", required=True),
    F("SalesAndPurchase/PurchaseDesc", "Purchase description", "text", max=4095),
    F("SalesAndPurchase/PurchaseCost", "Purchase cost", "money", min=0, list=True),
    F("SalesAndPurchase/ExpenseAccountRef", "Expense account", "ref", ref="account", required=True),
    F("SalesAndPurchase/PrefVendorRef", "Preferred vendor", "ref", ref="vendor"),
)

# ---------------------------------------------------------------- entities

ENTITIES: list[Entity] = [
    # ----- lists
    Entity("customer", "Customer", "Customers", "sales", "list", "Customer", (
        F("Name", "Customer name", required=True, max=41, list=True), ACTIVE,
        F("ParentRef", "Job of (parent customer)", "ref", ref="customer"),
        F("CompanyName", "Company", max=41, list=True), F("FirstName", "First name", max=25),
        F("LastName", "Last name", max=25), F("BillAddress", "Bill to", "address"), F("ShipAddress", "Ship to", "address"),
        F("Phone", "Phone", max=21, list=True), F("AltPhone", "Alt. phone", max=21), F("Fax", "Fax", max=21),
        F("Email", "Email", max=1023, list=True), F("Contact", "Contact", max=41),
        F("TermsRef", "Terms", "ref", ref="terms"), F("AccountNumber", "Account no.", max=99),
        F("CreditLimit", "Credit limit", "money", min=0), F("Notes", "Notes", "text", max=4095),
        F("CurrencyRef", "Currency (multi-currency files)", "ref", ref="currency", mod=False),
    ), del_type="Customer", name_path="FullName", amount_path="TotalBalance"),

    Entity("vendor", "Vendor", "Vendors", "purchasing", "list", "Vendor", (
        NAME, ACTIVE, F("CompanyName", "Company", max=41, list=True), F("FirstName", "First name", max=25),
        F("LastName", "Last name", max=25), F("VendorAddress", "Address", "address"),
        F("Phone", "Phone", max=21, list=True), F("AltPhone", "Alt. phone", max=21), F("Fax", "Fax", max=21),
        F("Email", "Email", max=1023, list=True), F("Contact", "Contact", max=41),
        F("NameOnCheck", "Print on check as", max=41), F("AccountNumber", "Account no.", max=99),
        F("Notes", "Notes", "text", max=4095), F("TermsRef", "Terms", "ref", ref="terms"),
        F("CreditLimit", "Credit limit", "money", min=0),
        F("CurrencyRef", "Currency (multi-currency files)", "ref", ref="currency", mod=False),
    ), del_type="Vendor", amount_path="Balance"),

    Entity("account", "Account", "Chart of accounts", "accounting", "list", "Account", (
        NAME, ACTIVE, F("ParentRef", "Subaccount of", "ref", ref="account"),
        F("AccountType", "Type", "enum", options=ACCOUNT_TYPES, required=True, list=True),
        F("AccountNumber", "Number", max=7, list=True), F("Desc", "Description", "text", max=200),
    ), del_type="Account", iterator=False, name_path="FullName", amount_path="Balance"),

    Entity("class", "Class", "Classes", "accounting", "list", "Class", (
        NAME, ACTIVE, F("ParentRef", "Subclass of", "ref", ref="class"),
    ), del_type="Class", iterator=False, name_path="FullName"),

    Entity("terms", "Terms", "Payment terms", "accounting", "list", "StandardTerms", (
        F("Name", "Name", required=True, max=31, list=True), ACTIVE,
        F("StdDueDays", "Due in days", "int", min=0, list=True), F("StdDiscountDays", "Discount if paid within (days)", "int", min=0),
        F("DiscountPct", "Discount %", "decimal", min=0),
    ), can_mod=False, del_type="StandardTerms", iterator=False),

    Entity("payment_method", "Payment method", "Payment methods", "accounting", "list", "PaymentMethod", (
        F("Name", "Name", required=True, max=31, list=True), ACTIVE,
        F("PaymentMethodType", "Type", "enum", list=True, options=(
            "AmericanExpress", "Cash", "Check", "DebitCard", "Discover", "ECheck", "GiftCard", "MasterCard", "Other",
            "OtherCreditCard", "Visa")),
    ), can_mod=False, del_type="PaymentMethod", iterator=False),

    item_entity("item_inventory", "Inventory", "ItemInventory", (
        F("ManufacturerPartNumber", "Manufacturer part no.", max=31),
        F("SalesDesc", "Sales description", "text", max=4095, list=True),
        F("SalesPrice", "Sales price", "money", min=0, list=True),
        F("IncomeAccountRef", "Income account", "ref", ref="account", required=True),
        F("PurchaseDesc", "Purchase description", "text", max=4095), F("PurchaseCost", "Purchase cost", "money", min=0, list=True),
        F("COGSAccountRef", "COGS account", "ref", ref="account", required=True),
        F("PrefVendorRef", "Preferred vendor", "ref", ref="vendor"),
        F("AssetAccountRef", "Asset account", "ref", ref="account", required=True),
        F("ReorderPoint", "Reorder point", "decimal", min=0),
        F("QuantityOnHand", "Qty on hand", "decimal", mod=False, list=True),
    )),
    item_entity("item_noninventory", "Non-inventory", "ItemNonInventory",
                (F("ManufacturerPartNumber", "Manufacturer part no.", max=31),) + SALES_AND_PURCHASE),
    item_entity("item_service", "Service", "ItemService", SALES_AND_PURCHASE),
    item_entity("item_othercharge", "Other charge", "ItemOtherCharge", SALES_AND_PURCHASE),

    # ----- sales
    Entity("estimate", "Estimate", "Estimates", "sales", "txn", "Estimate", (
        F("CustomerRef", "Customer:Job", "ref", ref="customer", required=True, list=True),
        F("ClassRef", "Class", "ref", ref="class"), F("TxnDate", "Date", "date", list=True),
        F("RefNumber", "Estimate no.", max=11, list=True), F("BillAddress", "Bill to", "address"),
        F("PONumber", "P.O. no.", max=25), F("TermsRef", "Terms", "ref", ref="terms"),
        F("DueDate", "Expiration date", "date"), F("Memo", "Memo", "text", max=4095),
        F("ExchangeRate", "Exchange rate (foreign currency only)", "decimal", min=0),
    ), lines=(sales_line("Estimate"),), del_type="Estimate", name_path="RefNumber",
        party_path="CustomerRef", amount_path="TotalAmount"),

    Entity("sales_order", "Sales order", "Sales orders", "sales", "txn", "SalesOrder", (
        F("CustomerRef", "Customer:Job", "ref", ref="customer", required=True, list=True),
        F("ClassRef", "Class", "ref", ref="class"), F("TxnDate", "Date", "date", list=True),
        F("RefNumber", "S.O. no.", max=11, list=True), F("BillAddress", "Bill to", "address"),
        F("ShipAddress", "Ship to", "address"), F("PONumber", "P.O. no.", max=25),
        F("TermsRef", "Terms", "ref", ref="terms"), F("DueDate", "Due date", "date"),
        F("ShipDate", "Ship date", "date"), F("Memo", "Memo", "text", max=4095),
    ), lines=(sales_line("SalesOrder"),), del_type="SalesOrder", name_path="RefNumber",
        party_path="CustomerRef", amount_path="TotalAmount"),

    Entity("invoice", "Invoice", "Invoices", "sales", "txn", "Invoice", (
        F("CustomerRef", "Customer:Job", "ref", ref="customer", required=True, list=True),
        F("ClassRef", "Class", "ref", ref="class"), F("ARAccountRef", "A/R account", "ref", ref="account"),
        F("TxnDate", "Date", "date", list=True), F("RefNumber", "Invoice no.", max=11, list=True),
        F("BillAddress", "Bill to", "address"), F("ShipAddress", "Ship to", "address"),
        F("PONumber", "P.O. no.", max=25), F("TermsRef", "Terms", "ref", ref="terms"),
        F("DueDate", "Due date", "date", list=True), F("ShipDate", "Ship date", "date"),
        F("Memo", "Memo", "text", max=4095),
        F("ExchangeRate", "Exchange rate (foreign currency only)", "decimal", min=0),
    ), lines=(sales_line("Invoice"),), del_type="Invoice", can_void=True, name_path="RefNumber",
        party_path="CustomerRef", amount_path="Subtotal"),

    Entity("sales_receipt", "Sales receipt", "Sales receipts", "sales", "txn", "SalesReceipt", (
        F("CustomerRef", "Customer:Job", "ref", ref="customer", list=True),
        F("ClassRef", "Class", "ref", ref="class"), F("TxnDate", "Date", "date", list=True),
        F("RefNumber", "Sale no.", max=11, list=True), F("BillAddress", "Sold to", "address"),
        F("CheckNumber", "Check no.", max=25), F("PaymentMethodRef", "Payment method", "ref", ref="payment_method"),
        F("Memo", "Memo", "text", max=4095), F("DepositToAccountRef", "Deposit to", "ref", ref="account"),
        F("ExchangeRate", "Exchange rate (foreign currency only)", "decimal", min=0),
    ), lines=(sales_line("SalesReceipt"),), del_type="SalesReceipt", can_void=True, name_path="RefNumber",
        party_path="CustomerRef", amount_path="TotalAmount"),

    Entity("credit_memo", "Credit memo", "Credit memos", "sales", "txn", "CreditMemo", (
        F("CustomerRef", "Customer:Job", "ref", ref="customer", required=True, list=True),
        F("ClassRef", "Class", "ref", ref="class"), F("ARAccountRef", "A/R account", "ref", ref="account"),
        F("TxnDate", "Date", "date", list=True), F("RefNumber", "Credit no.", max=11, list=True),
        F("BillAddress", "Customer address", "address"), F("PONumber", "P.O. no.", max=25),
        F("Memo", "Memo", "text", max=4095),
        F("ExchangeRate", "Exchange rate (foreign currency only)", "decimal", min=0),
    ), lines=(sales_line("CreditMemo"),), del_type="CreditMemo", can_void=True, name_path="RefNumber",
        party_path="CustomerRef", amount_path="TotalAmount"),

    Entity("receive_payment", "Customer payment", "Received payments", "sales", "txn", "ReceivePayment", (
        F("CustomerRef", "Received from", "ref", ref="customer", required=True, list=True),
        F("ARAccountRef", "A/R account", "ref", ref="account"), F("TxnDate", "Date", "date", list=True),
        F("RefNumber", "Reference / check no.", max=20, list=True),
        F("TotalAmount", "Amount", "money", min=0, required=True, list=True), F("ExchangeRate", "Exchange rate (foreign currency only)", "decimal", min=0),
        F("PaymentMethodRef", "Payment method", "ref", ref="payment_method"), F("Memo", "Memo", "text", max=4095),
        F("DepositToAccountRef", "Deposit to", "ref", ref="account"),
        F("IsAutoApply", "Apply to oldest invoices automatically (when no invoices are picked below)", "bool", mod=False),
    ), lines=(LineType("applied", "Invoice paid", "AppliedToTxnAdd", None, "AppliedToTxnRet", (
        F("TxnID", "Invoice", "txnref", ref="invoice", required=True),
        F("PaymentAmount", "Payment", "money", required=True, min=0)), "PaymentAmount"),),
        can_mod=False, del_type="ReceivePayment", include_lines=False, name_path="RefNumber",
        party_path="CustomerRef", amount_path="TotalAmount"),

    # ----- purchasing
    Entity("purchase_order", "Purchase order", "Purchase orders", "purchasing", "txn", "PurchaseOrder", (
        F("VendorRef", "Vendor", "ref", ref="vendor", required=True, list=True),
        F("ClassRef", "Class", "ref", ref="class"), F("TxnDate", "Date", "date", list=True),
        F("RefNumber", "P.O. no.", max=11, list=True), F("VendorAddress", "Vendor address", "address"),
        F("ShipAddress", "Ship to", "address"), F("TermsRef", "Terms", "ref", ref="terms"),
        F("DueDate", "Due date", "date"), F("ExpectedDate", "Expected date", "date"),
        F("Memo", "Memo", "text", max=4095),
        F("ExchangeRate", "Exchange rate (foreign currency only)", "decimal", min=0),
    ), lines=(LineType("item", "Item", "PurchaseOrderLineAdd", "PurchaseOrderLineMod", "PurchaseOrderLineRet", (
        F("ItemRef", "Item", "ref", ref="item", required=True), F("Desc", "Description", "text", max=4095),
        F("Quantity", "Qty", "decimal", min=0), F("Rate", "Rate", "money"), F("ClassRef", "Class", "ref", ref="class"),
        F("CustomerRef", "Customer:Job", "ref", ref="customer")), "Quantity*Rate"),),
        del_type="PurchaseOrder", name_path="RefNumber", party_path="VendorRef",
        amount_path="TotalAmount"),

    Entity("item_receipt", "Item receipt", "Item receipts", "purchasing", "txn", "ItemReceipt", (
        F("VendorRef", "Vendor", "ref", ref="vendor", required=True, list=True),
        F("APAccountRef", "A/P account", "ref", ref="account"), F("TxnDate", "Date", "date", list=True),
        F("RefNumber", "Ref no.", max=20, list=True), F("Memo", "Memo", "text", max=4095),
    ), lines=(EXPENSE_LINE, ITEM_LINE), del_type="ItemReceipt", name_path="RefNumber", party_path="VendorRef",
        amount_path="TotalAmount"),

    Entity("bill", "Bill", "Bills", "purchasing", "txn", "Bill", (
        F("VendorRef", "Vendor", "ref", ref="vendor", required=True, list=True),
        F("VendorAddress", "Address", "address"), F("APAccountRef", "A/P account", "ref", ref="account"),
        F("TxnDate", "Date", "date", list=True), F("DueDate", "Bill due", "date", list=True),
        F("RefNumber", "Ref no.", max=20, list=True), F("TermsRef", "Terms", "ref", ref="terms"),
        F("Memo", "Memo", "text", max=4095), F("ExchangeRate", "Exchange rate (foreign currency only)", "decimal", min=0),
        F("LinkToTxnID", "Convert item receipt (its lines become this bill)", "txnref", ref="item_receipt", mod=False),
    ), lines=(EXPENSE_LINE, ITEM_LINE), del_type="Bill", can_void=True, name_path="RefNumber",
        party_path="VendorRef", amount_path="AmountDue"),

    Entity("bill_payment", "Bill payment (check)", "Bill payments", "purchasing", "txn", "BillPaymentCheck", (
        F("PayeeEntityRef", "Vendor", "ref", ref="vendor", required=True, list=True),
        F("APAccountRef", "A/P account", "ref", ref="account"), F("TxnDate", "Date", "date", list=True),
        F("BankAccountRef", "Bank account", "ref", ref="account", required=True),
        F("RefNumber", "Check no.", max=11, list=True), F("Memo", "Memo", "text", max=4095),
    ), lines=(LineType("applied", "Bill paid", "AppliedToTxnAdd", None, "AppliedToTxnRet", (
        F("TxnID", "Bill", "txnref", ref="bill", required=True), F("PaymentAmount", "Payment", "money", min=0, required=True),
    ), "PaymentAmount"),), can_mod=False, del_type="BillPaymentCheck", can_void=True, include_lines=False,
        name_path="RefNumber", party_path="PayeeEntityRef", amount_path="Amount"),

    # ----- banking
    Entity("check", "Check / payment", "Checks & payments", "banking", "txn", "Check", (
        F("AccountRef", "Bank account", "ref", ref="account", required=True),
        F("PayeeEntityRef", "Pay to", "ref", ref="entity", list=True), F("RefNumber", "Check no.", max=11, list=True),
        F("TxnDate", "Date", "date", list=True), F("Memo", "Memo", "text", max=4095),
        F("Address", "Address", "address"),
    ), lines=(EXPENSE_LINE, ITEM_LINE), del_type="Check", can_void=True, name_path="RefNumber",
        party_path="PayeeEntityRef", amount_path="Amount"),

    Entity("credit_card_charge", "Credit card charge", "Credit card charges", "banking", "txn", "CreditCardCharge", (
        F("AccountRef", "Credit card", "ref", ref="account", required=True),
        F("PayeeEntityRef", "Purchased from", "ref", ref="entity", list=True), F("TxnDate", "Date", "date", list=True),
        F("RefNumber", "Ref no.", max=20, list=True), F("Memo", "Memo", "text", max=4095),
    ), lines=(EXPENSE_LINE, ITEM_LINE), del_type="CreditCardCharge", can_void=True, name_path="RefNumber",
        party_path="PayeeEntityRef", amount_path="Amount"),

    Entity("deposit", "Deposit", "Deposits", "banking", "txn", "Deposit", (
        F("TxnDate", "Date", "date", list=True),
        F("DepositToAccountRef", "Deposit to", "ref", ref="account", required=True, list=True),
        F("Memo", "Memo", "text", max=4095, list=True),
    ), lines=(LineType("deposit", "Deposit line", "DepositLineAdd", None, "DepositLineRet", (
        F("EntityRef", "Received from", "ref", ref="entity"), F("AccountRef", "From account", "ref", ref="account",
                                                                 required=True),
        F("Memo", "Memo", "str", max=4095), F("CheckNumber", "Check no.", max=25),
        F("PaymentMethodRef", "Payment method", "ref", ref="payment_method"),
        F("ClassRef", "Class", "ref", ref="class"), F("Amount", "Amount", "money", required=True)), "Amount"),),
        can_mod=False, del_type="Deposit", name_path="Memo", amount_path="DepositTotal"),

    Entity("journal_entry", "Journal entry", "Journal entries", "accounting", "txn", "JournalEntry", (
        F("TxnDate", "Date", "date", list=True), F("RefNumber", "Entry no.", max=11, list=True),
        F("IsAdjustment", "Adjusting entry", "bool"),
    ), lines=tuple(LineType(k, k.title(), f"Journal{k.title()}Line", None, f"Journal{k.title()}Line", (
        F("AccountRef", "Account", "ref", ref="account", required=True), F("Amount", "Amount", "money", required=True),
        F("Memo", "Memo", "str", max=4095), F("EntityRef", "Name", "ref", ref="entity"),
        F("ClassRef", "Class", "ref", ref="class"))) for k in ("debit", "credit")),
        can_mod=False, del_type="JournalEntry", name_path="RefNumber"),

    # ----- inventory
    Entity("inventory_adjustment", "Inventory adjustment", "Inventory adjustments", "inventory", "txn",
           "InventoryAdjustment", (
               F("AccountRef", "Adjustment account", "ref", ref="account", required=True),
               F("TxnDate", "Date", "date", list=True), F("RefNumber", "Ref no.", max=11, list=True),
               F("CustomerRef", "Customer:Job", "ref", ref="customer"), F("ClassRef", "Class", "ref", ref="class"),
               F("Memo", "Memo", "text", max=4095, list=True),
           ), lines=(LineType("item", "Item", "InventoryAdjustmentLineAdd", None, "InventoryAdjustmentLineRet", (
               F("ItemRef", "Item", "ref", ref="item", required=True),
               F("QuantityAdjustment/QuantityDifference", "Qty difference (+/-)", "decimal", required=True),
           ), None),), can_mod=False, del_type="InventoryAdjustment", name_path="RefNumber"),
]

# ---------------------------------------------------------------- more lists

def simple_list(key: str, label: str, plural: str, base: str, extra: tuple[F, ...] = (), parent: bool = True,
                max_len: int = 31) -> Entity:
    fields = (F("Name", "Name", required=True, max=max_len, list=True), ACTIVE)
    if parent:
        fields += (F("ParentRef", "Subtype of", "ref", ref=key),)
    return Entity(key, label, plural, "lists", "list", base, fields + extra, can_mod=False, del_type=base,
                  iterator=False, name_path="FullName" if parent else "Name")


ASSEMBLY_LINE = LineType("component", "Component", "ItemInventoryAssemblyLine", None, "ItemInventoryAssemblyLine", (
    F("ItemInventoryRef", "Component item", "ref", ref="item", required=True),
    F("Quantity", "Qty", "decimal", required=True, min=0)), None)

ENTITIES += [
    simple_list("customer_type", "Customer type", "Customer types", "CustomerType"),
    simple_list("vendor_type", "Vendor type", "Vendor types", "VendorType"),
    simple_list("job_type", "Job type", "Job types", "JobType"),
    simple_list("ship_method", "Shipping method", "Shipping methods", "ShipMethod", parent=False, max_len=15),
    Entity("sales_tax_code", "Sales tax code", "Sales tax codes", "accounting", "list", "SalesTaxCode", (
        F("Name", "Code", required=True, max=3, list=True), ACTIVE,
        F("IsTaxable", "Taxable", "bool", list=True), F("Desc", "Description", max=31, list=True),
    ), del_type="SalesTaxCode", iterator=False),
    Entity("other_name", "Other name", "Other names", "lists", "list", "OtherName", (
        NAME, ACTIVE, F("CompanyName", "Company", max=41, list=True), F("FirstName", "First name", max=25),
        F("LastName", "Last name", max=25), F("OtherNameAddress", "Address", "address"),
        F("Phone", "Phone", max=21, list=True), F("AltPhone", "Alt. phone", max=21), F("Fax", "Fax", max=21),
        F("Email", "Email", max=1023, list=True), F("Contact", "Contact", max=41),
        F("AccountNumber", "Account no.", max=99), F("Notes", "Notes", "text", max=4095),
    ), del_type="OtherName", iterator=False),
    Entity("employee", "Employee", "Employees", "lists", "list", "Employee", (
        ACTIVE, F("FirstName", "First name", required=True, max=25, list=True),
        F("LastName", "Last name", max=25, list=True), F("EmployeeAddress", "Address", "address"),
        F("Phone", "Phone", max=21, list=True), F("Mobile", "Mobile", max=21), F("AltPhone", "Alt. phone", max=21),
        F("Email", "Email", max=1023, list=True), F("HiredDate", "Hired", "date"),
    ), del_type="Employee", iterator=False),

    # ----- special item types
    Entity("item_discount", "Discount", "Discount items", "lists", "list", "ItemDiscount", (
        F("Name", "Item name", required=True, max=31, list=True), ACTIVE,
        F("ParentRef", "Subitem of", "ref", ref="item"),
        F("ItemDesc", "Description", "text", max=4095, list=True),
        F("DiscountRate", "Discount amount", "money", min=0, list=True),
        F("DiscountRatePercent", "Discount % (instead of amount)", "decimal", min=0),
        F("AccountRef", "Account", "ref", ref="account", required=True),
    ), del_type="ItemDiscount", name_path="FullName"),
    Entity("item_subtotal", "Subtotal", "Subtotal items", "lists", "list", "ItemSubtotal", (
        F("Name", "Item name", required=True, max=31, list=True), ACTIVE,
        F("ItemDesc", "Description", "text", max=4095, list=True),
    ), del_type="ItemSubtotal"),
    Entity("item_payment", "Payment item", "Payment items", "lists", "list", "ItemPayment", (
        F("Name", "Item name", required=True, max=31, list=True), ACTIVE,
        F("ItemDesc", "Description", "text", max=4095, list=True),
        F("DepositToAccountRef", "Deposit to", "ref", ref="account"),
        F("PaymentMethodRef", "Payment method", "ref", ref="payment_method"),
    ), del_type="ItemPayment"),
    Entity("item_sales_tax", "Sales tax item", "Sales tax items", "lists", "list", "ItemSalesTax", (
        F("Name", "Item name", required=True, max=31, list=True), ACTIVE,
        F("ItemDesc", "Description", "text", max=4095),
        F("TaxRate", "Tax rate %", "decimal", min=0, list=True),
        F("TaxVendorRef", "Tax agency (vendor)", "ref", ref="vendor"),
    ), del_type="ItemSalesTax"),
    Entity("item_group", "Group", "Group items", "lists", "list", "ItemGroup", (
        F("Name", "Item name", required=True, max=31, list=True), ACTIVE,
        F("ItemDesc", "Description", "text", max=4095, list=True),
        F("IsPrintItemsInGroup", "Print items in group", "bool"),
    ), lines=(LineType("item", "Item in group", "ItemGroupLine", None, "ItemGroupLine", (
        F("ItemRef", "Item", "ref", ref="item", required=True), F("Quantity", "Qty", "decimal", min=0)), None),),
        del_type="ItemGroup"),
    Entity("item_assembly", "Inventory assembly", "Inventory assembly items", "lists", "list", "ItemInventoryAssembly", (
        F("Name", "Item name / code", required=True, max=31, list=True), ACTIVE,
        F("ParentRef", "Subitem of", "ref", ref="item"),
        F("SalesDesc", "Sales description", "text", max=4095, list=True),
        F("SalesPrice", "Sales price", "money", min=0, list=True),
        F("IncomeAccountRef", "Income account", "ref", ref="account", required=True),
        F("PurchaseDesc", "Purchase description", "text", max=4095), F("PurchaseCost", "Cost", "money", min=0),
        F("COGSAccountRef", "COGS account", "ref", ref="account", required=True),
        F("PrefVendorRef", "Preferred vendor", "ref", ref="vendor"),
        F("AssetAccountRef", "Asset account", "ref", ref="account", required=True),
        F("BuildPoint", "Build point", "decimal", min=0),
        F("QuantityOnHand", "Qty on hand", "decimal", add=False, mod=False, list=True),
    ), lines=(ASSEMBLY_LINE,), del_type="ItemInventoryAssembly", name_path="FullName"),
]

# ---------------------------------------------------------------- more transactions

ENTITIES += [
    Entity("vendor_credit", "Vendor credit", "Vendor credits", "purchasing", "txn", "VendorCredit", (
        F("VendorRef", "Vendor", "ref", ref="vendor", required=True, list=True),
        F("APAccountRef", "A/P account", "ref", ref="account"), F("TxnDate", "Date", "date", list=True),
        F("RefNumber", "Ref no.", max=20, list=True), F("Memo", "Memo", "text", max=4095),
    ), lines=(EXPENSE_LINE, ITEM_LINE), del_type="VendorCredit", can_void=True, name_path="RefNumber",
        party_path="VendorRef", amount_path="CreditAmount"),

    Entity("bill_payment_cc", "Bill payment (credit card)", "Bill payments by card", "purchasing", "txn",
           "BillPaymentCreditCard", (
               F("PayeeEntityRef", "Vendor", "ref", ref="vendor", required=True, list=True),
               F("APAccountRef", "A/P account", "ref", ref="account"), F("TxnDate", "Date", "date", list=True),
               F("CreditCardAccountRef", "Credit card", "ref", ref="account", required=True),
               F("RefNumber", "Ref no.", max=11, list=True), F("Memo", "Memo", "text", max=4095),
           ), lines=(LineType("applied", "Bill paid", "AppliedToTxnAdd", None, "AppliedToTxnRet", (
               F("TxnID", "Bill", "txnref", ref="bill", required=True),
               F("PaymentAmount", "Payment", "money", required=True, min=0)), "PaymentAmount"),),
        can_mod=False, del_type="BillPaymentCreditCard", can_void=True, include_lines=False, name_path="RefNumber",
        party_path="PayeeEntityRef", amount_path="Amount"),

    Entity("credit_card_credit", "Credit card credit", "Credit card credits", "banking", "txn", "CreditCardCredit", (
        F("AccountRef", "Credit card", "ref", ref="account", required=True),
        F("PayeeEntityRef", "Received from", "ref", ref="entity", list=True), F("TxnDate", "Date", "date", list=True),
        F("RefNumber", "Ref no.", max=20, list=True), F("Memo", "Memo", "text", max=4095),
    ), lines=(EXPENSE_LINE, ITEM_LINE), del_type="CreditCardCredit", can_void=True, name_path="RefNumber",
        party_path="PayeeEntityRef", amount_path="Amount"),

    Entity("transfer", "Transfer", "Transfers", "banking", "txn", "Transfer", (
        F("TxnDate", "Date", "date", list=True),
        F("TransferFromAccountRef", "From account", "ref", ref="account", required=True, list=True),
        F("TransferToAccountRef", "To account", "ref", ref="account", required=True, list=True),
        F("ClassRef", "Class", "ref", ref="class"), F("Amount", "Amount", "money", required=True, min=0, list=True),
        F("Memo", "Memo", "text", max=4095),
    ), include_lines=False, name_path="TxnNumber", amount_path="Amount"),  # "Transfer" is not a valid TxnDelType

    Entity("statement_charge", "Statement charge", "Statement charges", "sales", "txn", "Charge", (
        F("CustomerRef", "Customer:Job", "ref", ref="customer", required=True, list=True),
        F("TxnDate", "Date", "date", list=True), F("RefNumber", "Ref no.", max=11, list=True),
        F("ItemRef", "Item", "ref", ref="item", required=True), F("Quantity", "Qty", "decimal", min=0),
        F("Rate", "Rate", "money"), F("Desc", "Description", "text", max=4095),
        F("ARAccountRef", "A/R account", "ref", ref="account"), F("ClassRef", "Class", "ref", ref="class"),
        F("DueDate", "Due date", "date"),
    ), del_type="Charge", can_void=True, include_lines=False, name_path="RefNumber", party_path="CustomerRef",
        amount_path="Amount"),

    Entity("build_assembly", "Build assembly", "Assembly builds", "inventory", "txn", "BuildAssembly", (
        F("ItemInventoryAssemblyRef", "Assembly", "ref", ref="item_assembly", required=True, list=True),
        F("TxnDate", "Date", "date", list=True), F("RefNumber", "Ref no.", max=11, list=True),
        F("Memo", "Memo", "text", max=4095),
        F("QuantityToBuild", "Quantity to build", "decimal", required=True, min=0, list=True),
    ), del_type="BuildAssembly", include_lines=False, name_path="RefNumber"),
]

# ---------------------------------------------------------------- people, pricing, time, vehicles, currencies

ENTITIES += [
    Entity("sales_rep", "Sales rep", "Sales reps", "lists", "list", "SalesRep", (
        F("Initial", "Initials", required=True, max=5, list=True), ACTIVE,
        F("SalesRepEntityRef", "Employee / vendor / other name", "ref", ref="entity", required=True, list=True),
    ), del_type="SalesRep", iterator=False, name_path="Initial"),
    Entity("price_level", "Price level", "Price levels", "lists", "list", "PriceLevel", (
        F("Name", "Name", required=True, max=31, list=True), ACTIVE,
        F("PriceLevelFixedPercentage", "Raise (+) or lower (-) prices by %", "decimal", list=True),
    ), del_type="PriceLevel", iterator=False),
    Entity("currency", "Currency", "Currencies", "accounting", "list", "Currency", (
        F("Name", "Name", required=True, max=64, list=True), ACTIVE,
        F("CurrencyCode", "Code", required=True, max=3, list=True, mod=False),
    ), del_type="Currency", iterator=False),
    Entity("vehicle", "Vehicle", "Vehicles", "lists", "list", "Vehicle", (
        F("Name", "Name", required=True, max=31, list=True), ACTIVE, F("Desc", "Description", max=256, list=True),
    ), del_type="Vehicle", iterator=False),
    Entity("time_tracking", "Time entry", "Time tracking", "sales", "txn", "TimeTracking", (
        F("TxnDate", "Date", "date", list=True),
        F("EntityRef", "Who (employee / vendor / other)", "ref", ref="entity", required=True, list=True),
        F("CustomerRef", "Customer:Job", "ref", ref="customer", list=True),
        F("ItemServiceRef", "Service item", "ref", ref="item_service"),
        F("Duration", "Duration (e.g. PT2H30M = 2h 30m)", required=True, list=True),
        F("ClassRef", "Class", "ref", ref="class"), F("Notes", "Notes", "text", max=4095),
        F("BillableStatus", "Billable status", "enum", options=("Billable", "NotBillable", "HasBeenBilled")),
    ), del_type="TimeTracking", include_lines=False, name_path="TxnNumber", party_path="CustomerRef"),
    Entity("vehicle_mileage", "Vehicle mileage", "Vehicle mileage", "banking", "txn", "VehicleMileage", (
        F("VehicleRef", "Vehicle", "ref", ref="vehicle", required=True, list=True),
        F("CustomerRef", "Customer:Job", "ref", ref="customer"), F("ItemRef", "Mileage item", "ref", ref="item"),
        F("ClassRef", "Class", "ref", ref="class"), F("TripStartDate", "Trip start", "date", list=True),
        F("TripEndDate", "Trip end", "date", required=True, list=True),
        F("OdometerStart", "Odometer start", "decimal", min=0), F("OdometerEnd", "Odometer end", "decimal", min=0),
        F("TotalMiles", "Total miles", "decimal", min=0, list=True), F("Notes", "Notes", "text", max=4095),
        F("BillableStatus", "Billable status", "enum", options=("Billable", "NotBillable", "HasBeenBilled")),
    ), can_mod=False, del_type="VehicleMileage", include_lines=False, name_path="TxnID"),
]

# Entities whose QuickBooks custom fields ("Define fields", OwnerID 0) are read on sync.
CUSTOM_FIELD_ENTITIES = {"customer", "vendor", "employee", "other_name", "item_inventory", "item_noninventory",
                         "item_service", "item_othercharge", "item_assembly", "invoice", "estimate", "sales_order",
                         "sales_receipt", "credit_memo", "purchase_order"}

BY_KEY: dict[str, Entity] = {e.key: e for e in ENTITIES}
BY_RET: dict[str, Entity] = {e.ret_tag: e for e in ENTITIES}

# virtual ref targets used by pickers
REF_GROUPS = {
    "item": [e.key for e in ENTITIES if e.key.startswith("item_") and e.kind == "list"],
    "entity": ["customer", "vendor", "other_name", "employee"],
}

MODULES = {
    "sales": "Sales & customers",
    "purchasing": "Purchasing & vendors",
    "banking": "Banking",
    "accounting": "Accounting",
    "inventory": "Inventory",
    "lists": "Items & lists",
    "reports": "Reports",
}
ACTIONS = ("view", "create", "edit", "delete", "approve", "direct")  # direct = write to QB without approval

REPORTS = {
    "ProfitAndLossStandard": ("General", "Profit & Loss"),
    "BalanceSheetStandard": ("General", "Balance Sheet"),
    "TrialBalance": ("General", "Trial Balance"),
    "SalesByCustomerSummary": ("General", "Sales by Customer Summary"),
    "SalesByItemSummary": ("General", "Sales by Item Summary"),
    "PurchaseByVendorSummary": ("General", "Purchases by Vendor Summary"),
    "PurchaseByItemSummary": ("General", "Purchases by Item Summary"),
    "InventoryValuationSummary": ("General", "Inventory Valuation Summary"),
    "CustomerBalanceSummary": ("General", "Customer Balance Summary"),
    "VendorBalanceSummary": ("General", "Vendor Balance Summary"),
    "IncomeByCustomerSummary": ("General", "Income by Customer Summary"),
    "ExpenseByVendorSummary": ("General", "Expenses by Vendor Summary"),
    "ProfitAndLossYTDComp": ("General", "Profit & Loss YTD Comparison"),
    "BalanceSheetPrevYearComp": ("General", "Balance Sheet Previous Year Comparison"),
    "GeneralLedger": ("Detail", "General Ledger"),
    "Journal": ("Detail", "Journal"),
    "ProfitAndLossDetail": ("Detail", "Profit & Loss Detail"),
    "BalanceSheetDetail": ("Detail", "Balance Sheet Detail"),
    "TxnListByDate": ("Detail", "Transaction List by Date"),
    "OpenInvoices": ("Detail", "Open Invoices"),
    "UnpaidBillsDetail": ("Detail", "Unpaid Bills Detail"),
    "OpenPOs": ("Detail", "Open Purchase Orders"),
    "CustomerBalanceDetail": ("Detail", "Customer Balance Detail"),
    "VendorBalanceDetail": ("Detail", "Vendor Balance Detail"),
    "SalesByCustomerDetail": ("Detail", "Sales by Customer Detail"),
    "SalesByItemDetail": ("Detail", "Sales by Item Detail"),
    "PurchaseByVendorDetail": ("Detail", "Purchases by Vendor Detail"),
    "InventoryValuationDetail": ("Detail", "Inventory Valuation Detail"),
    "DepositDetail": ("Detail", "Deposit Detail"),
    "CheckDetail": ("Detail", "Check Detail"),
    "AuditTrail": ("Detail", "Audit Trail"),
    "ARAgingSummary": ("Aging", "A/R Aging Summary"),
    "ARAgingDetail": ("Aging", "A/R Aging Detail"),
    "APAgingDetail": ("Aging", "A/P Aging Detail"),
    "APAgingSummary": ("Aging", "A/P Aging Summary"),
    "CollectionsReport": ("Aging", "Collections Report"),
}


def module_permissions() -> list[str]:
    perms = [f"{m}.{a}" for m in MODULES if m != "reports" for a in ACTIONS]
    return perms + ["reports.view"]
