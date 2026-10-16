# FastPOS: Multi-Tenant Offline-First Python Billing Architecture

## 1. Executive Summary
**FastPOS** is a lightweight, keyboard-centric desktop billing application built with **Python (PyQt6)** and **SQLite**, designed to act as a universal offline/online point-of-sale terminal for multiple cloud-hosted **Laravel** backends (e.g., `dbl.webxkey.lk`, `jaffnagold.webxkey.lk`, `rnz.webxkey.lk`).

The core philosophy of this system is **Zero-Latency Local Execution with Asynchronous Cloud Synchronization**:
1. **UI Speed:** The cashier always interacts with the local SQLite database for product lookups and bill saving, ensuring a response time of $< 5\text{ ms}$ regardless of internet speed.
2. **Dynamic Multi-Tenancy:** By simply changing the tenant prefix (e.g., `dbl`, `jaffnagold`, `rnz`) and API key in the Settings screen, the app dynamically binds to `https://{system_name}.webxkey.lk/api/v1/pos`.
3. **Hybrid Online/Offline Sync:** When online, bills push live in the background immediately upon checkout and product price/stock changes stream down via delta syncs. When offline, bills queue safely in SQLite and automatically batch-sync the moment connectivity returns.

---

## 2. Complete Feature List

### A. Multi-Tenant & System Configuration Features
* **Dynamic Domain Binding:** Input field for `System Name / Subdomain` (e.g., entering `jaffnagold` automatically targets `https://jaffnagold.webxkey.lk`).
* **Sanctum / API Token Authentication:** Secure token storage in local encrypted settings to authenticate with the target Laravel system.
* **Terminal Registration:** Unique `Terminal ID` (e.g., `POS-01`, `POS-02`) to prevent invoice number collisions when multiple computers are used in the same shop.
* **One-Click Connection & Sync Test:** Verifies connection to `{system_name}.webxkey.lk`, pulls shop metadata (Shop Name, Address, Phone, Tax %, Currency, Receipt Footer), and performs an initial full catalog download.
* **Tenant Switch / Reset Utility:** Safely clears local cache if re-deploying the app to a different client domain (blocked if unsynced offline bills exist).

### B. High-Speed Keyboard UI/UX Features
* **100% Mouse-Free Operation:** Full workflow executable via keyboard.
* **Smart Auto-Suggest (`QCompleter`):** Instant dropdown search by **Product Name**, **SKU/Code**, or **Barcode** showing live price and available stock: `Apple Red - $1.50 [Stk: 42]`.
* **Strict `Enter`-Key Navigation Loop:**
  * Type Product $\rightarrow$ `Enter` (Selects product, populates default Qty = $1$ and unit price, moves cursor to `Qty`).
  * Edit/Confirm Qty $\rightarrow$ `Enter` (Moves cursor to `Price`).
  * Edit/Confirm Price $\rightarrow$ `Enter` (Calculates row total, creates a new row below, moves cursor to new row's `Product Name`).
* **Double-Enter Instant Checkout:** Pressing `Enter` **twice** on an empty `Product Name` cell immediately opens/triggers the **Finalize & Print** checkout action.
* **Global Function Hotkeys:**
  * `F1`: Help / Shortcut Guide
  * `F2`: Focus Global Barcode / Product Search Bar
  * `F3`: Hold Current Bill (Park bill locally to serve another walk-in customer)
  * `F4`: Recall Held Bill (List parked bills and restore to grid)
  * `F5`: Quick Pay & Print (Cash exact amount)
  * `F6`: Void / Clear Entire Bill
  * `F7`: Delete Selected Line Item
  * `F8`: Select / Add Customer (Walk-in by default)
  * `F9`: Toggle Payment Method (Cash / Card / Credit / Split)
  * `F10`: Force Manual Cloud Sync
  * `F12`: Open Tenant & Printer Settings

### C. Hybrid Online/Offline Synchronization Features
* **Live Network Heartbeat:** A non-blocking background thread (`QThread`) pings `https://{system_name}.webxkey.lk/api/v1/pos/health` every $T_{ping} = 10\text{ s}$.
* **Live Mode (Online):**
  * Immediately dispatches completed invoices to the Laravel server in a background worker the exact second the bill is finalized.
  * Polls for product/price updates every $T_{delta} = 2\text{ min}$ using a `last_synced_at` timestamp so price changes on the Laravel web panel reflect automatically on the desktop app.
* **Offline Mode (Disconnected):**
  * Displays an unmistakable amber banner: `OFFLINE MODE (X bills pending sync)`.
  * Deducts stock locally inside SQLite so cashiers still see accurate remaining stock counts during an outage.
  * Queues finalized invoices with status `PENDING`.
* **Auto-Recovery Batch Sync:** Upon detecting internet restoration, pushes pending invoices in batches of $25$ using **UUIDv4 idempotency keys** (preventing duplicate bills if the connection drops mid-upload).

### D. Hardware & Receipt Printing Features
* **Direct Thermal Printing (ESC/POS):** Zero-dialog raw printing to $80\text{ mm}$ or $58\text{ mm}$ USB/LAN thermal printers so receipts print in $< 1\text{ s}$ after hitting Double-Enter.
* **Cash Drawer Kick:** Sends standard RJ11 pulse via the thermal printer upon cash checkout.

---

## 3. System Architecture & Flowcharts

### 3.1 Multi-Tenant Architecture Diagram

```
+-----------------------------------------------------------------------------------+
|                      CLOUD INFRASTRUCTURE (*.webxkey.lk)                          |
|                                                                                   |
|  +-------------------------+ +-------------------------+ +----------------------+ |
|  |   dbl.webxkey.lk        | | jaffnagold.webxkey.lk   | |   rnz.webxkey.lk     | |
|  |   (Laravel + MySQL)     | |   (Laravel + MySQL)     | |   (Laravel + MySQL)  | |
|  +------------+------------+ +------------+------------+ +-----------+----------+ |
+---------------|---------------------------|--------------------------|------------+
                |                           |                          |
                +---------------------------+--------------------------+
                                            |
                              HTTPS REST API (JSON / Sanctum)
                        Dynamic Endpoint: https://{tenant}.webxkey.lk
                                            |
+-------------------------------------------|---------------------------------------+
|                       PYTHON DESKTOP APP (PyQt6 Client)                           |
|                                           v                                       |
|  +-----------------------------------------------------------------------------+  |
|  |                  Background Sync Manager (PyQt6 QThread)                    |  |
|  |  1. Network Heartbeat (10s)   2. Invoice Push Queue   3. Product Delta Pull |  |
|  +----------------------------------------+------------------------------------+  |
|                                           |                                       |
|                                  Read / Write (WAL Mode)                          |
|                                           v                                       |
|  +-----------------------------------------------------------------------------+  |
|  |                        Local SQLite Database (pos_local.db)                 |  |
|  |   [app_settings]       [products_cache]       [invoices]    [invoice_items] |  |
|  +----------------------------------------+------------------------------------+  |
|                                           ^                                       |
|                                  0ms Local Queries                                |
|                                           |                                       |
|  +----------------------------------------+------------------------------------+  |
|  |                     High-Speed Billing UI (Main Thread)                     |  |
|  |  - POSBillingTable (Enter/Double-Enter State Machine)                       |  |
|  |  - Instant Local QCompleter (Auto-suggest Name, Price, Stock)               |  |
|  |  - Direct ESC/POS Thermal Receipt Engine                                    |  |
|  +-----------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------+
```

---

### 3.2 Flowchart 1: High-Speed Keyboard Billing Loop (`Enter` & `Double-Enter` Logic)

```
[Start New Bill: Focus on Row 0, Col 0 (Product Name)]
                         |
                         v
          [Cashier Presses a Key in Col 0]
                         |
         +---------------+---------------+
         |                               |
   (Typing Text)                 (Presses ENTER Key)
         |                               |
         v                               v
[Query Local SQLite]          {Is Product Cell Empty?}
[Show Auto-Suggest]              |                |
         |                      YES               NO
         v                       |                |
[Select Item via Arrow/Enter]    v                v
                        [empty_enter_count++]  [Reset empty_enter_count = 0]
                                 |             [Load Price & Tax from SQLite]
                                 v             [Move Focus -> Col 1 (Qty)]
                        {Is count >= 2?}          |
                         |            |           v
                        YES           NO    [Cashier Confirms/Edits Qty + ENTER]
                         |            |           |
                         |            |           v
                         |            |     [Move Focus -> Col 2 (Price)]
                         |            |           |
                         |            |           v
                         |            |     [Cashier Confirms/Edits Price + ENTER]
                         |            |           |
                         |            |           v
                         |            |     [Calculate Row Total & Grand Total]
                         |            |     [Insert New Empty Row (Row + 1)]
                         |            |     [Move Focus -> Row + 1, Col 0]
                         |            |           |
                         |            +-----+-----+
                         v                  |
            [TRIGGER CHECKOUT MODAL / PRINT] (Loop back to wait for next key)
```

---

### 3.3 Flowchart 2: Hybrid Online / Offline Sync Lifecycle

```
                  [Cashier Finalizes Bill (Double-Enter or F5)]
                                        |
                                        v
             [Generate UUIDv4 & Local Invoice No (e.g., POS1-00492)]
             [Save Invoice to Local SQLite with sync_status = 'PENDING']
             [Deduct Sold Qty from Local SQLite `products_cache` Table]
             [Print Thermal Receipt Immediately (0ms Wait)]
                                        |
                                        v
                     {Is Network Status Currently ONLINE?}
                         /                           \
                       YES                            NO
                       /                               \
                      v                                 v
    [Wake Background Sync QThread Immediately]   [Keep in SQLite Queue]
                      |                          [Increment UI Badge: "X Pending"]
                      v                                 |
    [POST Invoice JSON to:                              v
     https://{tenant}.webxkey.lk/api/v1/pos/invoices]  (Background Thread Pings
                      |                                 /api/v1/pos/health every 10s)
           +----------+----------+                      |
           |                     |                      v
     (HTTP 200 OK)       (Timeout / 5xx Error)   {Ping Successful?}
           |                     |                  /          \
           v                     v                YES           NO (Wait 10s)
  [Update SQLite:       [Keep 'PENDING' Status]    |
   sync_status='SYNCED'] [Switch UI to OFFLINE]    +-----> [Fetch All 'PENDING' Bills]
   [Update Last Synced]                                    [Batch Upload to Laravel]
                                                           [Pull Delta Product Updates]
```

---

## 4. Multi-Tenant Settings & Laravel API Specification

To connect seamlessly to `dbl.webxkey.lk`, `jaffnagold.webxkey.lk`, `rnz.webxkey.lk`, or any future client domain, your Python app builds the API base URL dynamically from the Settings configuration.

### 4.1 Python Dynamic Endpoint Builder
When the user opens **Settings (`F12`)**, they configure:
* **System Subdomain (`tenant_key`):** e.g., `dbl`, `jaffnagold`, `rnz` (or full domain override).
* **Base Domain:** `webxkey.lk` (Default).
* **API Token:** Laravel Sanctum token generated from your web admin panel.
* **Terminal Code:** e.g., `COUNTER-01`.

The Python app constructs all endpoints using:
$$\text{Base URL} = \text{https://}\{\text{tenant\_key}\}\text{.webxkey.lk/api/v1/pos}$$

### 4.2 Required Endpoints on Your Laravel Systems (`routes/api.php`)

Add these 4 standardized routes to your core Laravel POS codebase so every `*.webxkey.lk` deployment supports the desktop app:

| Method | Endpoint | Purpose |
| :--- | :--- | :--- |
| `GET` | `/api/v1/pos/health` | Lightweight ping returning `{"status": "ok", "server_time": "..."}` to verify online status. |
| `POST` | `/api/v1/pos/settings/verify` | Validates API token and returns tenant metadata (Shop Name, Address, Tax settings, Receipt header/footer). |
| `GET` | `/api/v1/pos/products/sync` | Accepts `?updated_after=YYYY-MM-DD HH:MM:SS`. Returns all created/updated products, prices, barcodes, and current stock. |
| `POST` | `/api/v1/pos/invoices/sync` | Accepts an array of offline/online invoices (with `uuid`) to insert into Laravel's sales tables and deduct cloud inventory. |

---

### 4.3 Payload Contracts (JSON)

#### 1. Product Delta Sync Response (`GET https://jaffnagold.webxkey.lk/api/v1/pos/products/sync?updated_after=2026-10-15T00:00:00Z`)
```json
{
  "status": "success",
  "tenant": "jaffnagold.webxkey.lk",
  "sync_timestamp": "2026-10-15T12:30:00Z",
  "products": [
    {
      "remote_id": 1042,
      "sku": "JG-001",
      "barcode": "8901234567890",
      "name": "Apple Red (Local) - Box",
      "unit": "Box",
      "selling_price": 1.50,
      "min_selling_price": 1.35,
      "tax_percentage": 0.00,
      "stock_qty": 42.0,
      "is_active": true,
      "updated_at": "2026-10-15T11:20:00Z"
    }
  ]
}
```

#### 2. Invoice Batch Sync Request (`POST https://jaffnagold.webxkey.lk/api/v1/pos/invoices/sync`)
```json
{
  "terminal_id": "COUNTER-01",
  "invoices": [
    {
      "uuid": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
      "local_invoice_no": "COUNTER01-20261015-0089",
      "customer_remote_id": null,
      "cashier_name": "Admin",
      "subtotal": 8.80,
      "discount_amount": 0.00,
      "tax_amount": 0.00,
      "grand_total": 8.80,
      "payment_method": "CASH",
      "paid_amount": 10.00,
      "change_amount": 1.20,
      "billed_at": "2026-10-15 15:41:22",
      "items": [
        {
          "product_remote_id": 501,
          "product_name": "Whole Wheat Bread",
          "qty": 2,
          "unit_price": 2.50,
          "discount_percent": 0,
          "tax_percent": 0,
          "line_total": 5.00
        },
        {
          "product_remote_id": 508,
          "product_name": "Organic Milk 1L",
          "qty": 1,
          "unit_price": 3.80,
          "discount_percent": 0,
          "tax_percent": 0,
          "line_total": 3.80
        }
      ]
    }
  ]
}
```

#### 3. Laravel Controller Best Practice (Idempotency)
In your Laravel `PosSyncController.php`, always check the `uuid` so that if a shop's internet drops right after Laravel saves the bill (before Python receives the `200 OK`), the subsequent retry will not duplicate the sale or double-deduct stock:

```php
// Inside Laravel PosSyncController@syncInvoices
DB::transaction(function () use ($invoiceData, &$syncedUuids) {
    $existing = Sale::where('uuid', $invoiceData['uuid'])->first();
    if ($existing) {
        // Already synced previously! Mark as synced so Python updates its local DB.
        $syncedUuids[] = $invoiceData['uuid'];
        return;
    }

    // Create Sale, SaleItems, and decrement Product stock...
    $sale = Sale::create([...]);
    $syncedUuids[] = $invoiceData['uuid'];
});
```

---

## 5. Local SQLite Database Schema (`pos_local.db`)

To guarantee high concurrency between the UI thread and the background sync thread, initialize SQLite with **Write-Ahead Logging (`PRAGMA journal_mode=WAL;`)**.

```sql
-- 1. Multi-Tenant & Terminal Settings
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
-- Example rows:
-- ('tenant_subdomain', 'jaffnagold')
-- ('base_domain', 'webxkey.lk')
-- ('api_token', '14|laravel_sanctum_token_xyz')
-- ('terminal_id', 'POS-01')
-- ('last_product_sync', '2026-10-15T12:00:00Z')

-- 2. Local Product Cache (Indexed for 0ms Auto-Suggest)
CREATE TABLE IF NOT EXISTS products (
    remote_id INTEGER PRIMARY KEY,
    sku TEXT,
    barcode TEXT,
    name TEXT NOT NULL,
    unit TEXT DEFAULT 'Pcs',
    selling_price REAL NOT NULL DEFAULT 0.0,
    min_selling_price REAL DEFAULT 0.0,
    tax_percentage REAL DEFAULT 0.0,
    stock_qty REAL DEFAULT 0.0,
    is_active INTEGER DEFAULT 1,
    updated_at TEXT
);
CREATE INDEX idx_products_name ON products(name);
CREATE INDEX idx_products_barcode ON products(barcode);
CREATE INDEX idx_products_sku ON products(sku);

-- 3. Local Invoices Header (Offline/Online Queue)
CREATE TABLE IF NOT EXISTS invoices (
    uuid TEXT PRIMARY KEY,
    local_invoice_no TEXT UNIQUE NOT NULL,
    tenant_subdomain TEXT NOT NULL,
    customer_remote_id INTEGER,
    cashier_name TEXT,
    subtotal REAL NOT NULL,
    discount_amount REAL DEFAULT 0.0,
    tax_amount REAL DEFAULT 0.0,
    grand_total REAL NOT NULL,
    payment_method TEXT DEFAULT 'CASH',
    paid_amount REAL DEFAULT 0.0,
    change_amount REAL DEFAULT 0.0,
    sync_status TEXT DEFAULT 'PENDING', -- 'PENDING', 'SYNCED', 'FAILED'
    sync_error TEXT,
    billed_at TEXT NOT NULL
);
CREATE INDEX idx_invoices_sync ON invoices(sync_status);

-- 4. Local Invoice Line Items
CREATE TABLE IF NOT EXISTS invoice_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_uuid TEXT NOT NULL,
    product_remote_id INTEGER NOT NULL,
    product_name TEXT NOT NULL,
    qty REAL NOT NULL,
    unit_price REAL NOT NULL,
    discount_percent REAL DEFAULT 0.0,
    tax_percent REAL DEFAULT 0.0,
    line_total REAL NOT NULL,
    FOREIGN KEY(invoice_uuid) REFERENCES invoices(uuid) ON DELETE CASCADE
);

-- 5. Held / Parked Bills (F3 / F4 Feature)
CREATE TABLE IF NOT EXISTS held_bills (
    hold_id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_note TEXT,
    cart_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

---

## 6. Best Practices for Fast Python UI/UX Implementation

1. **Never Make HTTP Requests on the Main UI Thread:**
   * Even when the system is **ONLINE**, typing in the product box (`App...`) must **never** query `https://{tenant}.webxkey.lk` directly. It must always query the local SQLite `products` table (or an in-memory Python dictionary/list refreshed from SQLite). This prevents UI micro-stutters when rural or mobile broadband connections fluctuate.
2. **Custom `QStyledItemDelegate` for Grid Auto-Suggest:**
   * In PyQt6, attach a custom `QStyledItemDelegate` to Column 0 (`Product Name`). Inside `createEditor()`, return a `QLineEdit` equipped with a `QCompleter` backed by a `QStandardItemModel` containing `Product Name | Price | Stock` and storing the `remote_id` in `Qt.ItemDataRole.UserRole`.
3. **Math & Precision:**
   * Calculating row totals and taxes must use Python's `Decimal` module (`from decimal import Decimal, ROUND_HALF_UP`) rather than standard floating-point math to avoid rounding errors on large invoices:
     $$\text{Line Total} = \text{round}\left(\text{Qty} \times \text{Price} \times \left(1 - \frac{\text{Disc\%}}{100}\right) \times \left(1 + \frac{\text{Tax\%}}{100}\right), 2\right)$$
4. **Tenant Isolation Safety Guard:**
   * If an administrator opens `F12 Settings` and changes the tenant from `dbl.webxkey.lk` to `rnz.webxkey.lk`, the app must first check:
     ```sql
     SELECT COUNT(*) FROM invoices WHERE sync_status = 'PENDING';
     ```
   * If pending bills $> 0$, block the domain switch until those bills are synced or exported, ensuring sales from `dbl` are never accidentally uploaded to `rnz`.
5. **Single-Executable Packaging:**
   * Package the final application using `PyInstaller` (`pyinstaller --noconsole --onefile main.py`) so your clients receive a standalone `FastPOS.exe` installer that runs without needing to install Python manually.