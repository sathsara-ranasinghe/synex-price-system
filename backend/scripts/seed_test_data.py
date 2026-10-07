"""Put sample data into a TEST QuickBooks company file through the portal API.

Phase 1 creates lists (customers, vendors, bank account, items). Run Web Connector "Update Selected",
then phase 2 creates transactions that reference them.

    python -m scripts.seed_test_data 1 --test-company-file
    python -m scripts.seed_test_data 2 --test-company-file

Never run this against a real company file.
"""

import sys
from datetime import date, timedelta

import httpx

BASE = "http://localhost:8000/api"
TODAY = date.today()


def d(days: int = 0) -> str:
    return (TODAY - timedelta(days=days)).isoformat()


def login(c: httpx.Client, user: str, password: str) -> None:
    r = c.post(f"{BASE}/auth/login", data={"username": user, "password": password})
    r.raise_for_status()
    c.headers["Authorization"] = "Bearer " + r.json()["access_token"]


def create(c: httpx.Client, entity: str, values: dict, lines: list | None = None) -> None:
    r = c.post(f"{BASE}/qb/{entity}", json={"values": values, "lines": lines})
    label = values.get("Name") or values.get("RefNumber") or entity
    print(f"{'OK ' if r.status_code == 201 else 'ERR'} {entity:20} {label:35} {r.json().get('message') or r.json().get('detail')}")


def ref(c: httpx.Client, target: str, name: str) -> dict:
    r = c.get(f"{BASE}/qb/options/{target}", params={"q": name, "limit": 50}).json()
    hit = next((o for o in r if (o["FullName"] or "").lower() == name.lower()), None)
    if not hit:
        raise SystemExit(f"'{name}' ({target}) is not in the portal yet - run Web Connector 'Update Selected' first")
    return {"ListID": hit["ListID"], "FullName": hit["FullName"]}


CUSTOMERS = [
    ("Hilton Colombo", "Hilton Colombo (Pvt) Ltd", "Nimal Perera", "011 249 2492", "projects@hilton.lk", "2 Sir Chittampalam A Gardiner Mw", "Colombo 02"),
    ("Cargills Ceylon PLC", "Cargills Ceylon PLC", "Kamal Silva", "011 242 7777", "facilities@cargills.lk", "40 York Street", "Colombo 01"),
    ("John Keells Properties", "John Keells Properties", "Dilini Fernando", "011 230 6000", "build@keells.com", "117 Sir Chittampalam A Gardiner Mw", "Colombo 02"),
    ("Kandy City Centre", "Kandy City Centre (Pvt) Ltd", "Ruwan Bandara", "081 220 3000", "admin@kcc.lk", "5 Dalada Veediya", "Kandy"),
]
VENDORS = [
    ("ABC Hardware", "ABC Hardware (Pvt) Ltd", "Sunil Jayasinghe", "011 234 5678", "sales@abchardware.lk", "12 Main Street", "Colombo 11"),
    ("Lanka Electricals", "Lanka Electricals Ltd", "Pradeep Kumara", "011 255 8899", "orders@lankaelec.lk", "88 Galle Road", "Dehiwala"),
    ("Tokyo Cement", "Tokyo Cement Company (Lanka) PLC", "Asanka Wijesinghe", "011 250 0466", "sales@tokyocement.lk", "469-1/1 Galle Road", "Colombo 03"),
    ("S-Lon Lanka", "S-Lon Lanka (Pvt) Ltd", "Chamari Dias", "011 291 5600", "info@slon.lk", "Kotugoda", "Ja-Ela"),
]


def phase1(c: httpx.Client) -> None:
    net30 = ref(c, "terms", "Net 30")
    for name, company, contact, phone, email, addr, city in CUSTOMERS:
        create(c, "customer", {"Name": name, "CompanyName": company, "Contact": contact, "Phone": phone, "Email": email,
                               "BillAddress": {"Addr1": company[:41], "Addr2": addr, "City": city, "Country": "Sri Lanka"},
                               "TermsRef": net30, "CreditLimit": "5000000"})
    for name, company, contact, phone, email, addr, city in VENDORS:
        create(c, "vendor", {"Name": name, "CompanyName": company, "Contact": contact, "Phone": phone, "Email": email,
                             "VendorAddress": {"Addr1": company[:41], "Addr2": addr, "City": city, "Country": "Sri Lanka"},
                             "TermsRef": net30})
    create(c, "account", {"Name": "Commercial Bank", "AccountType": "Bank", "AccountNumber": "1010",
                          "Desc": "Current account 8001234567"})

    income, cogs = ref(c, "account", "Design Income"), ref(c, "account", "Cost of Goods Sold")
    asset, supplies = ref(c, "account", "Inventory Asset"), ref(c, "account", "Blueprints and Reproduction")
    for name, desc, price, cost in [("PVC-20MM", "PVC Pipe 20mm x 6m", "650", "450"),
                                    ("CABLE-2.5", "Electrical cable 2.5mm 100m roll", "11500", "9000"),
                                    ("CEMENT-50KG", "Portland cement 50kg bag", "2650", "2300")]:
        create(c, "item_noninventory", {"Name": name, "SalesAndPurchase/SalesDesc": desc, "SalesAndPurchase/SalesPrice": price,
                                        "SalesAndPurchase/IncomeAccountRef": income, "SalesAndPurchase/PurchaseDesc": desc,
                                        "SalesAndPurchase/PurchaseCost": cost, "SalesAndPurchase/ExpenseAccountRef": supplies})
    for name, desc, price, cost in [("LED-PANEL-60", "LED panel light 60x60 40W", "8500", "6200"),
                                    ("SWITCH-1G", "1-gang light switch", "450", "300")]:
        create(c, "item_inventory", {"Name": name, "SalesDesc": desc, "SalesPrice": price, "IncomeAccountRef": income,
                                     "PurchaseDesc": desc, "PurchaseCost": cost, "COGSAccountRef": cogs,
                                     "AssetAccountRef": asset, "ReorderPoint": "10"})


def phase2(c: httpx.Client) -> None:
    cust = {n: ref(c, "customer", n) for n, *_ in CUSTOMERS}
    vend = {n: ref(c, "vendor", n) for n, *_ in VENDORS}
    item = {n: ref(c, "item", n) for n in ["PVC-20MM", "CABLE-2.5", "CEMENT-50KG", "LED-PANEL-60", "SWITCH-1G",
                                           "Architectural Design", "Structural Engineering"]}
    bank = ref(c, "account", "Commercial Bank")
    rent, utilities, equity = ref(c, "account", "Rent Expense"), ref(c, "account", "Utilities"), ref(c, "account", "Owners Equity")

    def sl(i: str, q: str, r: str) -> dict:
        return {"type": "item", "values": {"ItemRef": item[i], "Quantity": q, "Rate": r}}

    def il(i: str, q: str, cost: str) -> dict:
        return {"type": "item", "values": {"ItemRef": item[i], "Quantity": q, "Cost": cost}}

    # money in the bank first
    create(c, "journal_entry", {"TxnDate": d(60), "RefNumber": "JE-001"}, [
        {"type": "debit", "values": {"AccountRef": bank, "Amount": "5000000", "Memo": "Capital introduced"}},
        {"type": "credit", "values": {"AccountRef": equity, "Amount": "5000000", "Memo": "Capital introduced"}}])

    # purchasing
    create(c, "purchase_order", {"VendorRef": vend["ABC Hardware"], "TxnDate": d(40), "RefNumber": "PO-1001", "Memo": "Hilton project"},
           [sl("PVC-20MM", "200", "450"), sl("SWITCH-1G", "150", "300")])
    create(c, "purchase_order", {"VendorRef": vend["Lanka Electricals"], "TxnDate": d(38), "RefNumber": "PO-1002"},
           [sl("CABLE-2.5", "20", "8800"), sl("LED-PANEL-60", "60", "6000")])
    create(c, "item_receipt", {"VendorRef": vend["Lanka Electricals"], "TxnDate": d(30), "RefNumber": "GRN-501"},
           [il("LED-PANEL-60", "60", "6000"), il("SWITCH-1G", "100", "290")])
    create(c, "bill", {"VendorRef": vend["ABC Hardware"], "TxnDate": d(35), "RefNumber": "ABC-7781", "DueDate": d(5)},
           [il("PVC-20MM", "200", "440"), il("SWITCH-1G", "50", "300")])
    create(c, "bill", {"VendorRef": vend["Tokyo Cement"], "TxnDate": d(20), "RefNumber": "TC-55120", "DueDate": d(-10)},
           [il("CEMENT-50KG", "400", "2250")])
    create(c, "bill", {"VendorRef": vend["S-Lon Lanka"], "TxnDate": d(15), "RefNumber": "SL-9001", "Memo": "Office rent + utilities"},
           [{"type": "expense", "values": {"AccountRef": rent, "Amount": "250000", "Memo": "October rent"}},
            {"type": "expense", "values": {"AccountRef": utilities, "Amount": "48500", "Memo": "Electricity"}}])
    create(c, "check", {"AccountRef": bank, "PayeeEntityRef": vend["Lanka Electricals"], "RefNumber": "100231",
                        "TxnDate": d(10), "Memo": "Cash purchase"}, [il("CABLE-2.5", "5", "9000")])

    # sales
    create(c, "estimate", {"CustomerRef": cust["Hilton Colombo"], "TxnDate": d(45), "RefNumber": "EST-2001",
                           "Memo": "Lobby electrical refurbishment"},
           [sl("LED-PANEL-60", "40", "8500"), sl("SWITCH-1G", "60", "450"), sl("Architectural Design", "1", "350000")])
    create(c, "estimate", {"CustomerRef": cust["Kandy City Centre"], "TxnDate": d(12), "RefNumber": "EST-2002"},
           [sl("PVC-20MM", "500", "650"), sl("CEMENT-50KG", "300", "2650")])
    create(c, "invoice", {"CustomerRef": cust["Hilton Colombo"], "TxnDate": d(25), "RefNumber": "INV-3001", "PONumber": "HC-PO-88"},
           [sl("LED-PANEL-60", "40", "8500"), sl("SWITCH-1G", "60", "450"), sl("Architectural Design", "1", "350000")])
    create(c, "invoice", {"CustomerRef": cust["Cargills Ceylon PLC"], "TxnDate": d(18), "RefNumber": "INV-3002"},
           [sl("PVC-20MM", "150", "650"), sl("CABLE-2.5", "10", "11500")])
    create(c, "invoice", {"CustomerRef": cust["John Keells Properties"], "TxnDate": d(8), "RefNumber": "INV-3003"},
           [sl("Structural Engineering", "1", "780000"), sl("CEMENT-50KG", "250", "2650")])
    create(c, "sales_receipt", {"CustomerRef": cust["Kandy City Centre"], "TxnDate": d(5), "RefNumber": "SR-401",
                                "DepositToAccountRef": bank}, [sl("SWITCH-1G", "20", "450")])
    create(c, "receive_payment", {"CustomerRef": cust["Hilton Colombo"], "TxnDate": d(3), "RefNumber": "CHQ-55821",
                                  "TotalAmount": "400000", "DepositToAccountRef": bank, "IsAutoApply": True})


if __name__ == "__main__":
    if "--test-company-file" not in sys.argv:
        raise SystemExit("Refusing to run: pass --test-company-file to confirm QuickBooks has a TEST company open.")
    sys.argv.remove("--test-company-file")
    with httpx.Client(timeout=30) as client:
        login(client, "admin", sys.argv[2] if len(sys.argv) > 2 else "Admin@123")
        {"1": phase1, "2": phase2}[sys.argv[1] if len(sys.argv) > 1 else "1"](client)
