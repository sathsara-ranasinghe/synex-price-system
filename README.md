# Synex QB Portal

Web portal for **QuickBooks Desktop 2024** (through QuickBooks Web Connector). Every module is role-based.

## Portal modules

| Module | QuickBooks entities |
|---|---|
| Sales & customers | Customers, Estimates, Sales orders, Invoices, Sales receipts, Credit memos, Received payments (auto-apply or pick invoices), Statement charges |
| Purchasing & vendors | Vendors, Purchase orders, Item receipts, Bills, Vendor credits, Bill payments (check / credit card) |
| Banking | Checks, Credit card charges & credits, Deposits, Transfers |
| Accounting | Chart of accounts, Classes, Terms, Payment methods, Sales tax codes, Journal entries |
| Inventory | Inventory adjustments, Assembly builds |
| Items & lists | Inventory, Non-inventory, Service, Other-charge, Assembly, Group, Discount, Subtotal, Payment and Sales-tax items; Customer/Vendor/Job types, Shipping methods, Other names, Employees (view) |
| Reports | 36 QuickBooks reports: P&L, Balance Sheet, Trial Balance, General Ledger, Journal, Open Invoices, Unpaid Bills, Open POs, sales/purchase/balance summaries and details, A/R & A/P aging |

* Everything is defined in `backend/app/qb/registry.py`. To support another QuickBooks object, add an `Entity`
  there with fields in qbXML (OSR) order. Sync, API, forms, lists and permissions pick it up automatically.
* Every module has the permissions `view / create / edit / delete / approve / direct`. **direct** means that role's
  changes go to QuickBooks without approval. Otherwise they wait on **QuickBooks → Changes & approvals**.
  Roles are edited in **Administration → Roles & permissions**.
* Writes are queued and sent on the next Web Connector poll, so they take a few minutes. Reports work the same way.
* Not possible through qbXML: payroll processing, bank reconciliation, bank feeds, closing the books, most
  preferences, QuickBooks users, form templates and memorized reports.

## More than QuickBooks screens

* **Multi-company**: every QuickBooks company file is a company in the portal (Administration → Companies) with its
  own Web Connector login, `.qwc` file and data. A company is bound to its `.qbw` on the first sync; syncs from any
  other file are refused. Users only see the companies ticked for them.
* **Excel export** of every list and report, **PDF print** and **e-mail** of transactions (e-mail needs `SMTP_*` in `.env`).
* **Attachments** on any record (stored by the portal in `backend/data/attachments`, not in QuickBooks).
* **Create invoice** from an estimate / sales order, **receive items** from a PO, **convert an item receipt to a bill**.
* **Custom fields** (QuickBooks "Define fields") are shown read-only.
* Features a company file does not have (e.g. sales orders in Pro) are detected on sync and hidden for that company.
* **Installable app (PWA)** on phones and PCs. Browsers only allow installing over HTTPS or on `localhost`.

## Production on Windows

Once, in an Administrator PowerShell on the computer that hosts the portal:

```powershell
powershell -ExecutionPolicy Bypass -File deploy/windows/install.ps1
```

This registers the **Synex QB Portal** task (starts with Windows, restarts if it stops), a **daily backup** at 01:00
of the database and attachments into `backups/` (14 days kept) and a firewall rule for port 8000.
`deploy/windows/uninstall.ps1` removes them again (data is kept). Restore a backup with
`pg_restore -c -d synex_prices backups/<file>.dump`.

## Run (development)

```bash
# backend
cd backend
python -m venv .venv && .venv/Scripts/activate
pip install -r requirements.txt
# .env: DATABASE_URL, JWT_SECRET, QBWC_PASSWORD, QBWC_PUBLIC_URL, STATIC_DIR=../frontend/dist/frontend/browser
uvicorn app.main:app --host 0.0.0.0 --port 8000

# frontend (build once; the backend serves it when STATIC_DIR is set)
cd frontend
npm install
node node_modules/@angular/cli/bin/ng.js build
```

> The project path contains `&`, which breaks `npx`/`ng` shims on Windows. Call `node node_modules/@angular/cli/bin/ng.js` directly.

QuickBooks / Web Connector setup: [docs/QUICKBOOKS_DESKTOP_SETUP.md](docs/QUICKBOOKS_DESKTOP_SETUP.md).

Tests (`cd backend && python -m pytest`) simulate Web Connector sessions and use a throw-away SQLite database
(see `tests/conftest.py`). **Never point tests or `scripts/seed_test_data.py` at a live company file.**

## Project layout

```
backend/app
  qb/registry.py     every supported QuickBooks entity, report and module (fields in qbXML order)
  qb/builder.py      qbXML <-> JSON, Add/Mod/Del/Void/report builders
  qb/store.py        saves Rets into qb_records
  qbwc/soap.py       Web Connector SOAP endpoint + .qwc file
  qbwc/service.py    sync session: approved writes first, then incremental reads of every entity
  qbwc/writes.py     the outbox (qb_writes) -> QuickBooks
  routers/portal.py  /api/qb/... list, detail, create, edit, delete, void, pickers, reports, roles
  routers/changes.py approvals for changes waiting to go to QuickBooks
frontend/src/app
  pages/qb-list, qb-record   generic list and form for every entity
  pages/qb-reports, qb-changes, sync, users, roles, audit
```
