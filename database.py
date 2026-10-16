"""
database.py - Local SQLite Database Management for FastPOS.
Handles high-performance local queries, schema initialization, 
WAL journal mode for concurrent read/write, and full CRUD operations.
"""

import sqlite3
import json
import os
import sys
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple


if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "pos_local.db")

# If pos_local.db does not exist in BASE_DIR (e.g. dist/FastPOS), check if pos_default.db or pos_local.db is available
if not os.path.exists(DEFAULT_DB_PATH):
    for candidate_name in ["pos_default.db", "pos_local.db"]:
        cur_c = os.path.join(BASE_DIR, candidate_name)
        if os.path.exists(cur_c) and cur_c != DEFAULT_DB_PATH:
            try:
                import shutil
                shutil.copy2(cur_c, DEFAULT_DB_PATH)
                break
            except Exception:
                pass
        parent_c = os.path.join(os.path.dirname(BASE_DIR), candidate_name)
        if os.path.exists(parent_c):
            try:
                import shutil
                shutil.copy2(parent_c, DEFAULT_DB_PATH)
                break
            except Exception:
                pass


class DatabaseManager:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._mem_conn = None
        if db_path == ":memory:":
            self._mem_conn = sqlite3.connect(":memory:", timeout=10.0, check_same_thread=False)
            self._mem_conn.row_factory = sqlite3.Row
            self._mem_conn.execute("PRAGMA foreign_keys=ON;")
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        """Create or reuse connection with WAL mode and row factory."""
        if self._mem_conn is not None:
            return self._mem_conn
        conn = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # Optimize for high concurrency and speed
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def init_db(self):
        """Creates the required tables and indexes if they do not exist."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Settings Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
            """)

            # 2. Products Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY,
                    sku TEXT,
                    barcode TEXT,
                    name TEXT NOT NULL,
                    price REAL NOT NULL DEFAULT 0.0,
                    stock REAL NOT NULL DEFAULT 0.0,
                    tax_percent REAL NOT NULL DEFAULT 0.0,
                    updated_at TEXT
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_sku ON products(sku);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_barcode ON products(barcode);")

            # 3. Invoices Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bill_no TEXT UNIQUE NOT NULL,
                    customer_name TEXT,
                    subtotal REAL NOT NULL,
                    discount REAL DEFAULT 0.0,
                    tax REAL DEFAULT 0.0,
                    grand_total REAL NOT NULL,
                    payment_method TEXT DEFAULT 'CASH',
                    items_json TEXT NOT NULL,
                    is_synced INTEGER DEFAULT 0,
                    customer_phone TEXT,
                    sms_sent INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_sync ON invoices(is_synced);")

            # Dynamic migrations for existing databases
            cursor.execute("PRAGMA table_info(invoices);")
            columns = [row["name"] for row in cursor.fetchall()]
            if "customer_phone" not in columns:
                cursor.execute("ALTER TABLE invoices ADD COLUMN customer_phone TEXT;")
            if "sms_sent" not in columns:
                cursor.execute("ALTER TABLE invoices ADD COLUMN sms_sent INTEGER DEFAULT 0;")
            if "paid_amount" not in columns:
                cursor.execute("ALTER TABLE invoices ADD COLUMN paid_amount REAL;")
            if "due_amount" not in columns:
                cursor.execute("ALTER TABLE invoices ADD COLUMN due_amount REAL DEFAULT 0.0;")

            # 4. Held / Parked Bills Table (for F3 Hold / F4 Recall)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS held_bills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bill_no TEXT NOT NULL,
                    customer_name TEXT,
                    customer_phone TEXT,
                    items_json TEXT NOT NULL,
                    grand_total REAL NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)
            cursor.execute("PRAGMA table_info(held_bills);")
            h_columns = [row["name"] for row in cursor.fetchall()]
            if "customer_phone" not in h_columns:
                cursor.execute("ALTER TABLE held_bills ADD COLUMN customer_phone TEXT;")

            conn.commit()

        # Seed initial settings and sample grocery items if table is empty
        self._seed_default_settings()
        self._seed_sample_products()

    def _seed_default_settings(self):
        """Sets up default configuration if not present."""
        defaults = {
            "tenant_subdomain": "dbl",
            "base_domain": "webxkey.lk",
            "api_token": "",
            "terminal_id": "POS-01",
            "cashier_name": "Admin",
            "currency_symbol": "Rs.",
            "auto_discount_percent": "10.0",
            "auto_discount_enabled": "1",
            "auto_sms_enabled": "1",
            "auto_sync_enabled": "1",
            "shop_name": "Jaffna Gold",
            "sms_sender_id": "Jaffna Gold",
            "sms_api_key": "9b60385e-e599-49f3-a30b-fee08a8aa52a",
            "sms_user_id": "1644",
            "sms_send_url": "https://smslenz.lk/api/send-sms",
            "last_product_sync": "",
            "last_sales_sync": ""
        }
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for key, val in defaults.items():
                cursor.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                    (key, val)
                )
            conn.commit()

    def _seed_sample_products(self):
        """Seeds 10 realistic grocery products if database is fresh."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM products")
            count = cursor.fetchone()[0]
            if count == 0:
                sample_products = [
                    (1, "BREAD-001", "8901001", "Whole Wheat Bread", 2.50, 50.0, 0.0, datetime.now().isoformat()),
                    (2, "MILK-001", "8901002", "Organic Milk 1L", 3.80, 35.0, 0.0, datetime.now().isoformat()),
                    (3, "APP-RED", "8901003", "Apple Red (Local) - [Box]", 1.50, 12.0, 0.0, datetime.now().isoformat()),
                    (4, "APP-GRN", "8901004", "Apple Green - [Bag]", 1.80, 8.0, 0.0, datetime.now().isoformat()),
                    (5, "JAM-001", "8901005", "Apricot Jam - [300g]", 4.20, 5.0, 0.0, datetime.now().isoformat()),
                    (6, "JUICE-001", "8901006", "Apple Juice - [1L]", 2.90, 20.0, 0.0, datetime.now().isoformat()),
                    (7, "BAN-001", "8901007", "Fresh Banana (Dozen)", 1.20, 45.0, 0.0, datetime.now().isoformat()),
                    (8, "EGG-001", "8901008", "Brown Eggs (10pk)", 3.40, 18.0, 0.0, datetime.now().isoformat()),
                    (9, "RICE-001", "8901009", "Basmati Rice 5kg", 9.50, 15.0, 5.0, datetime.now().isoformat()),
                    (10, "TEA-001", "8901010", "Ceylon Black Tea 200g", 4.50, 30.0, 0.0, datetime.now().isoformat()),
                ]
                cursor.executemany("""
                    INSERT INTO products (id, sku, barcode, name, price, stock, tax_percent, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, sample_products)
                conn.commit()

    # --- Settings CRUD ---
    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, (key, value))
            conn.commit()

    def get_all_settings(self) -> Dict[str, str]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM settings")
            rows = cursor.fetchall()
            return {row["key"]: row["value"] for row in rows}

    def clear_local_storage(self, preserve_settings: bool = True) -> Dict[str, int]:
        """
        Clears local storage tables (products, invoices, held_bills).
        Resets last_product_sync and last_sales_sync timestamps to enable a clean, full live re-sync.
        Preserves core system settings unless preserve_settings=False.
        Returns counts of deleted items.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM products")
            prod_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM invoices")
            inv_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM held_bills")
            held_count = cursor.fetchone()[0]

            cursor.execute("DELETE FROM products;")
            cursor.execute("DELETE FROM invoices;")
            cursor.execute("DELETE FROM held_bills;")

            # Reset sync timestamps so next sync downloads fresh full catalog & sales
            cursor.execute("INSERT INTO settings (key, value) VALUES ('last_product_sync', '') ON CONFLICT(key) DO UPDATE SET value = '';")
            cursor.execute("INSERT INTO settings (key, value) VALUES ('last_sales_sync', '') ON CONFLICT(key) DO UPDATE SET value = '';")

            if not preserve_settings:
                cursor.execute("DELETE FROM settings;")
                self._seed_default_settings()

            conn.commit()
            cursor.execute("VACUUM;")

            return {
                "products": prod_count,
                "invoices": inv_count,
                "held_bills": held_count,
                "products_cleared": prod_count,
                "invoices_cleared": inv_count,
                "held_bills_cleared": held_count
            }

    # --- Products CRUD ---
    def search_products(self, query: str, limit: int = 8) -> List[Dict[str, Any]]:
        """Fast instant search matching name, sku, or barcode."""
        if not query or not query.strip():
            return []
        term = f"%{query.strip()}%"
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, sku, barcode, name, price, stock, tax_percent
                FROM products
                WHERE name LIKE ? OR sku LIKE ? OR barcode LIKE ?
                ORDER BY 
                    CASE 
                        WHEN barcode = ? THEN 1
                        WHEN sku = ? THEN 2
                        WHEN name LIKE ? THEN 3
                        ELSE 4
                    END,
                    name ASC
                LIMIT ?
            """, (term, term, term, query.strip(), query.strip(), f"{query.strip()}%", limit))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_product_by_id(self, product_id: int) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def _extract_scan_code(raw: str) -> List[str]:
        """Returns candidate codes from a barcode/QR payload (plain, URL, JSON, AIM prefix, 'BARCODE:xxx')."""
        from urllib.parse import urlparse, parse_qs
        import re
        # Strip non-printable control characters
        raw_clean = re.sub(r"[\x00-\x1f\x7f]", "", raw or "").replace("\xa0", " ").strip()
        candidates = [raw_clean]

        # Handle AIM symbology prefixes common on 2D QR/barcode scanners (e.g. ']Q1', ']Q2', ']E0', ']C0', ']d1')
        aim_match = re.match(r"^\][a-zA-Z0-9]{2,3}(.+)$", raw_clean)
        if aim_match:
            stripped = aim_match.group(1).strip()
            if stripped:
                candidates.insert(0, stripped)

        for text in list(candidates):
            if text.startswith("{") and text.endswith("}"):
                try:
                    data = json.loads(text)
                    for k in ("barcode", "code", "sku", "product_code", "id"):
                        if data.get(k):
                            candidates.append(str(data[k]).strip())
                except Exception:
                    pass
            if text.lower().startswith(("http://", "https://")):
                try:
                    parsed = urlparse(text)
                    qs = parse_qs(parsed.query)
                    for k in ("barcode", "code", "sku", "id", "search"):
                        if qs.get(k):
                            candidates.append(qs[k][0].strip())
                    parts = [p for p in parsed.path.split("/") if p]
                    if parts:
                        candidates.append(parts[-1].strip())
                except Exception:
                    pass
            m = re.match(r"^(?:barcode|sku|code|prod|id)[\s:=]+(.*)$", text, re.IGNORECASE)
            if m:
                candidates.append(m.group(1).strip())

        return [c for c in dict.fromkeys(candidates) if c]

    def get_product_count(self) -> int:
        """Returns total active products count in SQLite."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM products")
            row = cursor.fetchone()
            return row[0] if row else 0

    def get_product_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        """Lookup by barcode/SKU/ID/name (case-insensitive); supports QR payloads, exact, suffix, and prefix matching."""
        if not code:
            return None
        with self.get_connection() as conn:
            cursor = conn.cursor()
            candidates = self._extract_scan_code(code)

            # Pass 1: Exact match on barcode, SKU, ID, or Name
            for cand in candidates:
                cand_clean = cand.strip()
                if not cand_clean:
                    continue
                cursor.execute("""
                    SELECT * FROM products 
                    WHERE LOWER(TRIM(barcode)) = LOWER(?) 
                       OR LOWER(TRIM(sku)) = LOWER(?) 
                       OR CAST(id AS TEXT) = ?
                       OR LOWER(TRIM(name)) = LOWER(?)
                    ORDER BY CASE WHEN LOWER(TRIM(barcode)) = LOWER(?) THEN 0
                                  WHEN LOWER(TRIM(sku)) = LOWER(?) THEN 1 ELSE 2 END
                    LIMIT 1
                """, (cand_clean, cand_clean, cand_clean, cand_clean, cand_clean, cand_clean))
                row = cursor.fetchone()
                if row:
                    return dict(row)

            # Pass 2: Suffix match (Common for EAN-13 barcodes where internal item code is last digits, e.g. 91249 -> 2001106191249)
            for cand in candidates:
                cand_clean = cand.strip()
                if len(cand_clean) >= 3 and any(c.isalnum() for c in cand_clean):
                    cursor.execute("""
                        SELECT * FROM products 
                        WHERE barcode LIKE ? 
                           OR sku LIKE ?
                        ORDER BY LENGTH(barcode) ASC
                        LIMIT 1
                    """, (f"%{cand_clean}", f"%{cand_clean}"))
                    row = cursor.fetchone()
                    if row:
                        return dict(row)

            # Pass 3: Prefix match (e.g. barcode starts with scanned code)
            for cand in candidates:
                cand_clean = cand.strip()
                if len(cand_clean) >= 3 and any(c.isalnum() for c in cand_clean):
                    cursor.execute("""
                        SELECT * FROM products 
                        WHERE barcode LIKE ? 
                           OR sku LIKE ?
                        ORDER BY LENGTH(barcode) ASC
                        LIMIT 1
                    """, (f"{cand_clean}%", f"{cand_clean}%"))
                    row = cursor.fetchone()
                    if row:
                        return dict(row)

            return None

    def upsert_products(self, product_list: List[Dict[str, Any]]) -> int:
        """Batch upsert products retrieved from the remote API."""
        now = datetime.now().isoformat()
        upserted = 0
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for p in product_list:
                p_id = p.get("remote_id") or p.get("id")
                sku = p.get("sku") or p.get("product_sku") or p.get("product_code") or ""
                barcode = p.get("barcode") or p.get("code") or ""
                name = p.get("name") or p.get("product_name") or ""
                price = float(p.get("selling_price") or p.get("product_selling_price") or p.get("retail_price") or p.get("price") or 0.0)
                stock = float(p.get("stock_qty") or p.get("available_stock") or p.get("stock") or 0.0)
                tax_pct = float(p.get("tax_percentage") or p.get("tax_percent") or 0.0)
                updated_at = p.get("updated_at") or now

                cursor.execute("""
                    INSERT INTO products (id, sku, barcode, name, price, stock, tax_percent, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        sku = excluded.sku,
                        barcode = excluded.barcode,
                        name = excluded.name,
                        price = excluded.price,
                        stock = excluded.stock,
                        tax_percent = excluded.tax_percent,
                        updated_at = excluded.updated_at
                """, (p_id, sku, barcode, name, price, stock, tax_pct, updated_at))
                upserted += 1
            conn.commit()
        return upserted

    def deduct_stock(self, product_id: int, qty: float):
        """Locally decrement product stock upon billing."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE products 
                SET stock = MAX(0.0, stock - ?) 
                WHERE id = ?
            """, (qty, product_id))
            conn.commit()

    # --- Invoices CRUD ---
    def create_invoice(self, data: Dict[str, Any], is_synced: int = 0) -> int:
        """Creates an invoice record and deducts local inventory."""
        items_json = data.get("items_json")
        if isinstance(items_json, (list, dict)):
            items_json = json.dumps(items_json)

        with self.get_connection() as conn:
            cursor = conn.cursor()

            bill_no = data.get("bill_no")
            # Ensure bill_no is unique if collision happens
            if not bill_no:
                bill_no = self.get_next_bill_number()
            else:
                cursor.execute("SELECT 1 FROM invoices WHERE bill_no = ?", (bill_no,))
                if cursor.fetchone():
                    bill_no = self.get_next_bill_number()
            data["bill_no"] = bill_no

            paid_amount = float(data.get("paid_amount", data["grand_total"]))
            due_amount = float(data.get("due_amount", 0.0))

            cursor.execute("""
                INSERT INTO invoices (
                    bill_no, customer_name, customer_phone, subtotal, discount, tax, 
                    grand_total, paid_amount, due_amount, payment_method, items_json, is_synced, sms_sent, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                bill_no,
                data.get("customer_name", "Walk-In"),
                data.get("customer_phone", ""),
                float(data["subtotal"]),
                float(data.get("discount", 0.0)),
                float(data.get("tax", 0.0)),
                float(data["grand_total"]),
                paid_amount,
                due_amount,
                data.get("payment_method", "CASH"),
                items_json,
                is_synced,
                int(data.get("sms_sent", 0)),
                data.get("created_at") or datetime.now().isoformat()
            ))
            invoice_id = cursor.lastrowid

            # Deduct stock for each line item
            try:
                items = json.loads(items_json)
                for item in items:
                    pid = item.get("product_id") or item.get("id")
                    qty = float(item.get("qty", 1.0))
                    if pid:
                        cursor.execute("""
                            UPDATE products 
                            SET stock = MAX(0.0, stock - ?) 
                            WHERE id = ?
                        """, (qty, pid))
            except Exception as e:
                print(f"[DatabaseManager] Stock deduction warning: {e}")

            conn.commit()
            return invoice_id

    def get_pending_invoices(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch unsynced invoices (is_synced = 0)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM invoices 
                WHERE is_synced = 0 
                ORDER BY id ASC 
                LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            result = []
            for r in rows:
                item_dict = dict(r)
                try:
                    item_dict["items"] = json.loads(item_dict["items_json"])
                except Exception:
                    item_dict["items"] = []
                result.append(item_dict)
            return result

    def mark_invoices_synced(self, bill_numbers: List[str]):
        """Marks specified bills as synced (is_synced = 1)."""
        if not bill_numbers:
            return
        placeholders = ",".join(["?"] * len(bill_numbers))
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                UPDATE invoices 
                SET is_synced = 1 
                WHERE bill_no IN ({placeholders})
            """, bill_numbers)
            conn.commit()

    def get_pending_invoice_count(self) -> int:
        """Returns the number of bills pending cloud sync."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM invoices WHERE is_synced = 0")
            return cursor.fetchone()[0]

    def get_unsynced_invoices_count(self) -> int:
        """Alias for get_pending_invoice_count."""
        return self.get_pending_invoice_count()

    def get_next_bill_number(self, terminal_id: Optional[str] = None) -> str:
        """Generates sequential clean bill number e.g. #2026-0014 guaranteed to be unique."""
        now = datetime.now()
        year = now.strftime("%Y")
        prefix = f"#{year}-"
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT bill_no FROM invoices WHERE bill_no LIKE ? ORDER BY id DESC", (f"{prefix}%",))
            rows = cursor.fetchall()
            max_seq = 0
            for r in rows:
                b_no = r[0]
                if b_no and b_no.startswith(prefix):
                    suffix = b_no[len(prefix):]
                    try:
                        seq = int(suffix)
                        if seq > max_seq:
                            max_seq = seq
                    except ValueError:
                        pass

            next_seq = max_seq + 1
            while True:
                candidate = f"{prefix}{next_seq:04d}"
                cursor.execute("SELECT 1 FROM invoices WHERE bill_no = ?", (candidate,))
                if not cursor.fetchone():
                    return candidate
                next_seq += 1

    def upsert_synced_invoice(self, inv_data: Dict[str, Any]) -> bool:
        """
        Upserts an invoice fetched from the live domain into local SQLite.
        Does NOT deduct stock (stock was already deducted on the server).
        If the invoice already exists (by bill_no), updates fields and is_synced=1.
        If it does not exist, inserts it with is_synced=1.
        Returns True if new invoice was inserted.
        """
        bill_no = inv_data.get("bill_no")
        if not bill_no:
            return False

        items_json = inv_data.get("items_json")
        if items_json is None:
            items = inv_data.get("items", [])
            items_json = json.dumps(items)
        elif isinstance(items_json, (list, dict)):
            items_json = json.dumps(items_json)

        cust_name = inv_data.get("customer_name") or "Walk-In"
        cust_phone = inv_data.get("customer_phone") or ""
        subtotal = float(inv_data.get("subtotal", 0.0))
        discount = float(inv_data.get("discount", 0.0))
        tax = float(inv_data.get("tax", 0.0))
        grand_total = float(inv_data.get("grand_total", 0.0))
        pay_method = inv_data.get("payment_method") or "CASH"
        created_at = inv_data.get("created_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sms_sent = int(inv_data.get("sms_sent", 1 if cust_phone else 0))

        due_amount = float(inv_data.get("due_amount", 0.0))
        paid_amount = float(inv_data.get("paid_amount", grand_total - due_amount))

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM invoices WHERE bill_no = ?", (bill_no,))
            row = cursor.fetchone()
            if row:
                cursor.execute("""
                    UPDATE invoices SET
                        customer_name = ?,
                        customer_phone = CASE WHEN ? != '' THEN ? ELSE customer_phone END,
                        subtotal = ?,
                        discount = ?,
                        tax = ?,
                        grand_total = ?,
                        paid_amount = ?,
                        due_amount = ?,
                        payment_method = ?,
                        items_json = CASE WHEN ? != '[]' THEN ? ELSE items_json END,
                        is_synced = 1
                    WHERE id = ?
                """, (
                    cust_name,
                    cust_phone, cust_phone,
                    subtotal, discount, tax, grand_total,
                    paid_amount, due_amount,
                    pay_method,
                    items_json, items_json,
                    row[0]
                ))
                conn.commit()
                return False
            else:
                cursor.execute("""
                    INSERT INTO invoices (
                        bill_no, customer_name, customer_phone, subtotal, discount, tax,
                        grand_total, paid_amount, due_amount, payment_method, items_json, is_synced, sms_sent, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    bill_no, cust_name, cust_phone, subtotal, discount, tax,
                    grand_total, paid_amount, due_amount, pay_method, items_json, 1, sms_sent, created_at
                ))
                conn.commit()
                return True

    def get_todays_invoices(self, date_str: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch all invoices for today (or specified date YYYY-MM-DD / 'all'), with parsed items."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if date_str in ["all", "recent"]:
                cursor.execute("""
                    SELECT * FROM invoices 
                    ORDER BY created_at DESC, id DESC 
                    LIMIT 50
                """)
            else:
                if not date_str:
                    date_str = datetime.now().strftime("%Y-%m-%d")
                cursor.execute("""
                    SELECT * FROM invoices 
                    WHERE created_at LIKE ? 
                    ORDER BY created_at DESC, id DESC
                """, (f"{date_str}%",))

            rows = cursor.fetchall()
            result = []
            for r in rows:
                item_dict = dict(r)
                try:
                    item_dict["items"] = json.loads(item_dict["items_json"])
                except Exception:
                    item_dict["items"] = []
                result.append(item_dict)
            return result

    def get_invoice_by_bill_no(self, bill_no: str) -> Optional[Dict[str, Any]]:
        """Fetch single invoice by bill number with parsed line items."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM invoices WHERE bill_no = ?", (bill_no,))
            row = cursor.fetchone()
            if not row:
                return None
            item_dict = dict(row)
            try:
                item_dict["items"] = json.loads(item_dict["items_json"])
            except Exception:
                item_dict["items"] = []
            return item_dict

    def prepare_invoice_for_edit(self, bill_no: str) -> Optional[Dict[str, Any]]:
        """
        Prepares an invoice for editing: restores stock and removes old invoice from local DB
        so that re-billing will not duplicate inventory deductions.
        """
        inv = self.get_invoice_by_bill_no(bill_no)
        if not inv:
            return None

        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Restore stock for line items
            for item in inv.get("items", []):
                pid = item.get("product_id") or item.get("id")
                qty = float(item.get("qty", 1.0))
                if pid:
                    cursor.execute("""
                        UPDATE products 
                        SET stock = stock + ? 
                        WHERE id = ?
                    """, (qty, pid))

            # Delete the invoice record from local DB so it can be re-saved fresh
            cursor.execute("DELETE FROM invoices WHERE bill_no = ?", (bill_no,))
            conn.commit()

        return inv

    def mark_invoice_sms_sent(self, bill_no: str):
        """Marks invoice as having SMS dispatched successfully."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE invoices SET sms_sent = 1 WHERE bill_no = ?", (bill_no,))
            conn.commit()

    # --- Held Bills (F3 Hold / F4 Recall) ---
    def hold_bill(self, bill_no: str, customer_name: str, items: List[Dict[str, Any]], grand_total: float, customer_phone: str = "") -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO held_bills (bill_no, customer_name, customer_phone, items_json, grand_total, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                bill_no,
                customer_name,
                customer_phone,
                json.dumps(items),
                grand_total,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ))
            conn.commit()
            return cursor.lastrowid

    def get_held_bills(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM held_bills ORDER BY id DESC")
            rows = cursor.fetchall()
            result = []
            for r in rows:
                d = dict(r)
                try:
                    d["items"] = json.loads(d["items_json"])
                except Exception:
                    d["items"] = []
                result.append(d)
            return result

    def delete_held_bill(self, hold_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM held_bills WHERE id = ?", (hold_id,))
            conn.commit()

    def can_switch_tenant(self) -> Tuple[bool, int]:
        """Safety check: returns (True, 0) if allowed, or (False, count) if pending bills exist."""
        pending = self.get_pending_invoice_count()
        return (pending == 0, pending)
