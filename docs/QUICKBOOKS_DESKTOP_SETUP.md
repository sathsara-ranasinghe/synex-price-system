# Connecting QuickBooks Desktop 2024 (on the VPS)

The proposal assumed QuickBooks **Online**. Synex uses QuickBooks **Desktop 2024** on a Windows VPS,
which has no cloud API. The supported way to read it from another system is
**QuickBooks Web Connector (QBWC)**, Intuit's free connector:

```
 Windows VPS                                    App server (Linux or the same VPS)
┌──────────────────────────────┐               ┌──────────────────────────────────┐
│ QuickBooks Desktop 2024      │               │ FastAPI  /qbwc  (SOAP service)   │
│   ▲ qbXML (read-only)        │   HTTPS poll  │   - decides if a sync is due     │
│ QuickBooks Web Connector ────┼──────────────►│   - sends qbXML queries          │
│   (every 5 min)              │◄──────────────┤   - stores results in PostgreSQL │
└──────────────────────────────┘               └──────────────────────────────────┘
```

* Web Connector makes **outbound** calls only, so you don't need to open any port on the QuickBooks VPS.
* The app only sends query requests and never changes QuickBooks data. The .qwc asks for read/write access only because Web Connector 2.2+ must store a FileID marker in the company file.
* Web Connector polls every 5 minutes. The server only runs a sync when `QBWC_RUN_EVERY_MINUTES`
  has passed, or when someone presses **Sync now** in the web app.

## What gets read

| QuickBooks data | Request | Stored as |
|---|---|---|
| Vendors | `VendorQueryRq` | `suppliers` |
| Inventory, Assembly, Non-inventory, Service, Other-charge items | `Item…QueryRq` | `items`, `categories` (from parent items), `units` |
| Item *Purchase Cost* + *Preferred Vendor* | from the item | a supplier price (`source = qb_item`) |
| Purchase Orders (line *Rate*) | `PurchaseOrderQueryRq` | supplier price (`qb_po`) |
| Item Receipts (line *Cost*) | `ItemReceiptQueryRq` | supplier price (`qb_receipt`) |
| Bills (line *Cost*) | `BillQueryRq` | supplier price (`qb_bill`) |

Each purchase transaction line gives a real vendor + item + unit price. Together they produce the
multi-supplier price list and the price history. An older transaction never overwrites a newer price.

The first sync reads all list data and the last `QBWC_HISTORY_DAYS` (default 365) of purchase transactions.
Later syncs are incremental: they read only records modified since the last sync, using `FromModifiedDate`.
**Full re-sync** on the sync page reads everything again.

## Option A: app on a separate Linux server (recommended)

1. Deploy with Docker on the Linux server (see the main README) and put it behind HTTPS,
   for example `https://prices.synex.lk`. **Web Connector only accepts HTTPS** for any host other than `localhost`,
   so you need a valid certificate (Let's Encrypt is fine).
2. In `.env` set `QBWC_PUBLIC_URL=https://prices.synex.lk/qbwc` and a strong `QBWC_PASSWORD`.

## Option B: everything on the same Windows VPS

QuickBooks Desktop needs Windows. You can run the app on the same VPS with Docker Desktop or WSL2,
or natively with Python and PostgreSQL for Windows. Then set `QBWC_PUBLIC_URL=http://localhost:8080/qbwc`.
Web Connector allows plain HTTP for `localhost`.
In this setup, users reach the web UI through the VPS's public HTTPS address (IIS or Nginx reverse proxy).

## One-time setup on the VPS

1. Sign in to the VPS as the Windows user that runs QuickBooks.
2. Open QuickBooks Desktop 2024 as the **Admin** user, open the Synex company file, and switch to **single-user mode**
   (needed only for the first authorisation).
3. Web Connector is installed with QuickBooks (*File → Update Web Services*). If it's missing, download it from Intuit.
4. In the web app, go to **QuickBooks sync → Download SynexPriceSync.qwc** and copy the file to the VPS.
5. In Web Connector choose **Add an application** and select the `.qwc` file.
6. QuickBooks asks for access. Choose
   **"Yes, always; allow access even if QuickBooks is not running"** and select the Admin user (or a dedicated user).
7. Back in Web Connector, enter the password (the value of `QBWC_PASSWORD`), tick **Auto-Run**, and click **Update Selected** to test.
8. Watch progress on the **QuickBooks sync** page in the web app.

### Keeping it running unattended

* Web Connector must stay running in the VPS user session. Add it to *Startup* and don't sign out
  of the RDP session; disconnect instead.
* With "allow access even if QuickBooks is not running", Web Connector opens the company file in the background.
  If another user has QuickBooks open in single-user mode, the sync fails and is logged. Multi-user mode works.
* Set `QBWC_COMPANY_FILE` to the full `.qbw` path if more than one company file exists on the VPS.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Web Connector: *"Authentication failed"* | `QBWC_USERNAME` / `QBWC_PASSWORD` don't match the `.qwc` user and the password entered in Web Connector. |
| *"The certificate is not trusted"* / connection error | Web Connector needs a valid public HTTPS certificate (or `localhost`). |
| Sync log: *"Could not open QuickBooks company file"* | The file is open in single-user mode by someone else, or the path in `QBWC_COMPANY_FILE` is wrong. |
| Sync log warning for one step, e.g. `item_assembly: [3250] …` | That feature isn't enabled in your QB edition. Other steps continue. |
| Prices look old | The price comes from the newest PO, receipt, or bill. Check *Price history → Source* on the item page. |

## Testing without QuickBooks

```bash
cd backend
python -m scripts.simulate_qbwc http://localhost:8000 qbwc <QBWC_PASSWORD>
```

This sends the same SOAP calls Web Connector would, with sample vendors, items and a bill.
