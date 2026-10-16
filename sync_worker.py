"""
sync_worker.py - Background QThread Synchronization Engine for FastPOS.
Handles non-blocking network heartbeats, online/offline state machine,
asynchronous invoice pushes with idempotency, and product catalog delta syncs.
"""

import time
import json
from datetime import datetime
import requests
import urllib3
from typing import Dict, Any, List, Optional, Tuple
from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QWaitCondition
from database import DatabaseManager

# Suppress SSL certificate verification warnings for subdomains
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class SyncWorker(QThread):
    # Signals emitted to UI
    # status_changed(is_online: bool, pending_count: int, message: str)
    status_changed = pyqtSignal(bool, int, str)
    # product_sync_completed(count: int, message: str)
    product_sync_completed = pyqtSignal(int, str)
    # invoice_pushed(bill_no: str, success: bool, message: str)
    invoice_pushed = pyqtSignal(str, bool, str)
    # sales_synced(count: int, total_amount: float, message: str)
    sales_synced = pyqtSignal(int, float, str)
    # sync_finished(success: bool, message: str)
    sync_finished = pyqtSignal(bool, str)

    def __init__(self, db: DatabaseManager, interval_seconds: int = 15, parent=None):
        super().__init__(parent)
        self.db = db
        self.interval = interval_seconds
        self._is_running = True
        self._mutex = QMutex()
        self._cond = QWaitCondition()
        self._trigger_now = False
        self._sync_products_requested = False
        self._pull_sales_requested = False
        self.is_online = False

    def stop(self):
        """Cleanly stop the background worker thread."""
        self._mutex.lock()
        self._is_running = False
        self._cond.wakeAll()
        self._mutex.unlock()
        self.wait(2000)

    def request_immediate_sync(self, sync_products: bool = False):
        """Wake up the worker immediately for an urgent sync or heartbeat check."""
        self._mutex.lock()
        self._trigger_now = True
        if sync_products:
            self._sync_products_requested = True
        self._cond.wakeAll()
        self._mutex.unlock()

    def request_sales_sync(self):
        """Wake up worker to immediately pull today's sales from domain."""
        self._mutex.lock()
        self._trigger_now = True
        self._pull_sales_requested = True
        self._cond.wakeAll()
        self._mutex.unlock()

    def get_headers(self, token: str, terminal_id: str) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"FastPOS-Desktop/{terminal_id}",
            "X-Terminal-ID": terminal_id,
        }
        if token and token.strip():
            headers["Authorization"] = f"Bearer {token.strip()}"
        return headers

    def build_base_url(self, tenant: str, base_domain: str = "webxkey.lk") -> str:
        tenant = (tenant or "").strip()
        base_domain = (base_domain or "").strip()

        # If user entered a full URL
        if tenant.startswith("http://") or tenant.startswith("https://"):
            clean = tenant.rstrip("/")
            if "/api" in clean:
                return clean
            return f"{clean}/api/v1"

        # Local development on 127.0.0.1 or localhost
        if "127.0.0.1" in base_domain or "localhost" in base_domain:
            host = base_domain if base_domain.startswith("http") else f"http://{base_domain}"
            return f"{host.rstrip('/')}/api/v1"

        if "127.0.0.1" in tenant or "localhost" in tenant:
            host = tenant if tenant.startswith("http") else f"http://{tenant}"
            return f"{host.rstrip('/')}/api/v1"

        if "." in tenant:
            return f"https://{tenant}/api/v1"
        return f"https://{tenant}.{base_domain}/api/v1"

    def check_health(self, base_url: str, headers: Dict[str, str]) -> bool:
        """Pings the remote API with a 3-second timeout."""
        alt_base = base_url.replace("/api/v1", "/api") if "/api/v1" in base_url else base_url
        candidate_endpoints = [
            f"{base_url}/pos/health",
            f"{base_url}/ping",
            f"{base_url}/health",
            f"{alt_base}/pos/health",
            f"{alt_base}/ping",
            f"{alt_base}/products"
        ]
        for url in candidate_endpoints:
            try:
                resp = requests.get(url, headers=headers, timeout=3.0, verify=False)
                if resp.status_code in [200, 204]:
                    return True
                # If server replied with 401/403 or 404, server is alive online
                if resp.status_code in [401, 403, 404, 405]:
                    return True
            except requests.RequestException:
                continue
        return False

    def push_invoices_batch(self, base_url: str, headers: Dict[str, str], terminal_id: str) -> Tuple[int, List[str]]:
        """Pushes pending local invoices to the Laravel cloud backend."""
        pending = self.db.get_pending_invoices(limit=25)
        if not pending:
            return (0, [])

        # Format payload following the architecture plan
        payload = {
            "terminal_id": terminal_id,
            "invoices": []
        }
        for inv in pending:
            gt = float(inv["grand_total"])
            due = float(inv.get("due_amount", 0.0) or 0.0)
            paid = float(inv.get("paid_amount", gt - due) if inv.get("paid_amount") is not None else gt - due)
            payload["invoices"].append({
                "uuid": inv.get("bill_no"), # Can act as idempotency key
                "local_invoice_no": inv["bill_no"],
                "customer_name": inv.get("customer_name", "Walk-In"),
                "customer_phone": inv.get("customer_phone", ""),
                "send_sms": 1 if (inv.get("customer_phone") and not inv.get("sms_sent")) else 0,
                "subtotal": inv["subtotal"],
                "discount_amount": inv["discount"],
                "tax_amount": inv["tax"],
                "grand_total": gt,
                "paid_amount": paid,
                "due_amount": due,
                "payment_method": inv["payment_method"],
                "items": inv.get("items", []),
                "billed_at": inv["created_at"]
            })

        endpoints = [
            f"{base_url}/pos/invoices/sync",
            f"{base_url}/pos/invoices"
        ]

        synced_bills = []
        for ep in endpoints:
            try:
                resp = requests.post(ep, json=payload, headers=headers, timeout=8.0, verify=False)
                if resp.status_code in [200, 201]:
                    data = resp.json() if resp.content else {}
                    # If backend returns synced uuids or list of IDs
                    synced_ids = data.get("synced_uuids") or [inv["bill_no"] for inv in pending]
                    self.db.mark_invoices_synced(synced_ids)
                    return (len(synced_ids), synced_ids)
            except requests.RequestException as e:
                print(f"[SyncWorker] Invoice push error at {ep}: {e}")
                continue

        return (0, [])

    def sync_product_catalog(self, base_url: str, headers: Dict[str, str]) -> int:
        """Pulls updated products from cloud and upserts into SQLite."""
        last_sync = self.db.get_setting("last_product_sync", "")
        params = {}
        if last_sync:
            params["updated_after"] = last_sync

        endpoints = [
            f"{base_url}/pos/products/sync",
            f"{base_url}/pos/products"
        ]

        for ep in endpoints:
            try:
                total_upserted = 0
                page = 1
                completed = False
                while page <= 200:
                    page_params = dict(params)
                    page_params.update({"page": page, "per_page": 500})
                    resp = requests.get(ep, headers=headers, params=page_params, timeout=30.0, verify=False)
                    if resp.status_code != 200:
                        break
                    data = resp.json()
                    products = []
                    has_more = False
                    if isinstance(data, list):
                        products = data
                    elif isinstance(data, dict):
                        products = data.get("products") or data.get("data") or []
                        has_more = bool(data.get("has_more"))
                    if products:
                        total_upserted += self.db.upsert_products(products)
                    should_continue = has_more or len(products) >= 500
                    if not should_continue:
                        completed = True
                        break
                    page += 1
                if page == 1 and not completed:
                    continue  # endpoint failed, try the next one
                if completed:
                    now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    self.db.set_setting("last_product_sync", now_str)
                return total_upserted
            except requests.RequestException as e:
                print(f"[SyncWorker] Product pull error at {ep}: {e}")
                continue
        return 0

    def lookup_remote_product(self, code_or_term: str) -> Optional[Dict[str, Any]]:
        """
        Instant on-demand product lookup directly against live backend.
        Used as immediate fallback when an un-cached QR code, barcode, or suffix is scanned/entered.
        Saves found product into SQLite and returns the product dict.
        """
        term = (code_or_term or "").strip()
        if not term:
            return None

        # Clean term if URL or AIM symbology
        if "product-image/" in term:
            term = term.rstrip("/").split("/")[-1]
        elif term.startswith("]Q") or term.startswith("]E") or term.startswith("]C"):
            term = term[3:]

        settings = self.db.get_all_settings()
        tenant = settings.get("tenant_subdomain", "https://jaffnagold.com")
        base_domain = settings.get("base_domain", "webxkey.lk")
        token = settings.get("api_token", "")
        terminal = settings.get("terminal_id", "POS-01")

        base_url = self.build_base_url(tenant, base_domain)
        headers = self.get_headers(token, terminal)

        endpoints = [
            f"{base_url}/pos/products/sync?search={term}&per_page=10",
        ]
        if "127.0.0.1" not in base_url and "localhost" not in base_url:
            endpoints.append(f"http://127.0.0.1:8000/api/v1/pos/products/sync?search={term}&per_page=10")

        for ep in endpoints:
            try:
                resp = requests.get(ep, headers=headers, timeout=1.2, verify=False)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                products = []
                if isinstance(data, list):
                    products = data
                elif isinstance(data, dict):
                    products = data.get("products") or data.get("data") or []
                if products:
                    self.db.upsert_products(products)
                    # Verify the queried term actually matches an upserted product
                    found = self.db.get_product_by_code(term)
                    if found:
                        return found
            except Exception as e:
                continue

        return None

    def pull_domain_sales(self, target_date: Optional[str] = None, limit: int = 50) -> Tuple[bool, int, float, str]:
        """
        Pulls today's (or specified date) sales from the live domain API and upserts into SQLite.
        Supports both dedicated POS endpoint (/api/v1/pos/invoices/today) and live fallback (/api/sales).
        Returns (success, count, total_amount, message).
        """
        settings = self.db.get_all_settings()
        tenant = settings.get("tenant_subdomain", "https://jaffnagold.com")
        base_domain = settings.get("base_domain", "webxkey.lk")
        token = settings.get("api_token", "")
        terminal = settings.get("terminal_id", "POS-01")

        base_url = self.build_base_url(tenant, base_domain)
        headers = self.get_headers(token, terminal)

        if not target_date:
            target_date = datetime.now().strftime("%Y-%m-%d")

        alt_base = base_url.replace("/api/v1", "/api") if "/api/v1" in base_url else base_url
        candidate_urls = [
            f"{base_url}/pos/invoices/today?date={target_date}&include_recent=1",
            f"{base_url}/pos/sales/today?date={target_date}&include_recent=1",
            f"{alt_base}/pos/invoices/today?date={target_date}&include_recent=1",
            f"{alt_base}/sales"
        ]

        def parse_iso(iso_str):
            if not iso_str:
                return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
                try:
                    import zoneinfo
                    local_dt = dt.astimezone(zoneinfo.ZoneInfo("Asia/Colombo"))
                    return local_dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    return dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                return str(iso_str).replace("T", " ").split(".")[0]

        total_upserted = 0
        total_amount = 0.0

        for ep in candidate_urls:
            try:
                resp = requests.get(ep, headers=headers, timeout=6.0, verify=False)
                if resp.status_code != 200:
                    continue

                data = resp.json()

                # Case A: Dedicated POS endpoint response {"invoices": [...]}
                if "invoices" in data:
                    invoices_list = data.get("invoices", [])
                    for inv in invoices_list:
                        self.db.upsert_synced_invoice(inv)
                        total_upserted += 1
                        total_amount += float(inv.get("grand_total", 0.0))
                    return True, total_upserted, total_amount, f"Synced {total_upserted} invoices from POS API"

                # Case B: Standard /api/sales response {"results": [...]}
                elif "results" in data:
                    raw_sales = data.get("results", [])
                    for s in raw_sales:
                        sdate = s.get("sale_date")
                        if target_date not in ["all", "recent", ""] and sdate != target_date:
                            continue

                        sid = s.get("id")
                        bill_no = s.get("invoice_number") or s.get("sale_id")
                        if bill_no and not bill_no.startswith("#") and not bill_no.startswith("SALE"):
                            bill_no = f"#{bill_no}"

                        cust_phone = ""
                        if s.get("customer") and isinstance(s["customer"], dict):
                            p = s["customer"].get("phone", "")
                            if p and p != "xxxxx":
                                cust_phone = p

                        # Check if line items are already cached in local DB
                        existing_inv = self.db.get_invoice_by_bill_no(bill_no)
                        cached_items = existing_inv.get("items", []) if existing_inv else []

                        items = cached_items
                        if not items and sid:
                            try:
                                det_resp = requests.get(f"{alt_base}/sales/{sid}", headers=headers, timeout=4.0, verify=False)
                                if det_resp.status_code == 200:
                                    det_items = det_resp.json().get("data", {}).get("items", [])
                                    for it in det_items:
                                        prod = it.get("product") or {}
                                        items.append({
                                            "product_id": prod.get("id") or it.get("id"),
                                            "product_name": it.get("product_name") or prod.get("name") or "Item",
                                            "sku": it.get("product_code") or prod.get("code") or "",
                                            "qty": float(it.get("quantity", 1)),
                                            "unit_price": float(it.get("unit_price", 0.0)),
                                            "line_total": float(it.get("total", 0.0)),
                                            "discount_percent": float(it.get("discount", 0.0))
                                        })
                            except Exception:
                                pass

                        pay_method = (s.get("payment_method") or "CASH").upper()
                        due_val = float(s.get("due_amount", 0.0) or 0.0)
                        if due_val > 0 or s.get("payment_status") in ["partial", "pending"] or pay_method == "CREDIT":
                            pay_method = "CREDIT"
                        elif pay_method in ["FULL", "PAID"]:
                            pay_method = "CASH"

                        gt = float(s.get("total_amount", 0.0))
                        paid_val = float(s.get("paid_amount", gt - due_val))
                        inv_record = {
                            "bill_no": bill_no,
                            "customer_name": s.get("customer_name") or "Walk-In",
                            "customer_phone": cust_phone,
                            "subtotal": float(s.get("subtotal", gt)),
                            "discount": float(s.get("discount_amount", 0.0)),
                            "tax": 0.0,
                            "grand_total": gt,
                            "paid_amount": paid_val,
                            "due_amount": due_val,
                            "payment_method": pay_method,
                            "items": items,
                            "created_at": parse_iso(s.get("created_at")),
                            "is_synced": 1,
                            "sms_sent": 1 if cust_phone else 0
                        }
                        self.db.upsert_synced_invoice(inv_record)
                        total_upserted += 1
                        total_amount += gt

                    return True, total_upserted, total_amount, f"Synced {total_upserted} bills from domain"
            except Exception as e:
                print(f"[SyncWorker] pull error at {ep}: {e}")
                continue

        return False, 0, 0.0, "Could not reach domain sales API"

    def run(self):
        """Worker thread main loop."""
        while self._is_running:
            settings = self.db.get_all_settings()
            tenant = settings.get("tenant_subdomain", "dbl")
            base_domain = settings.get("base_domain", "webxkey.lk")
            token = settings.get("api_token", "")
            terminal = settings.get("terminal_id", "POS-01")
            auto_sync = settings.get("auto_sync_enabled", "1") == "1"

            base_url = self.build_base_url(tenant, base_domain)
            headers = self.get_headers(token, terminal)

            # Check network heartbeat
            online = self.check_health(base_url, headers)
            self.is_online = online
            pending_count = self.db.get_pending_invoice_count()

            # If auto-sync is OFF, only sync if user explicitly triggered it
            should_sync = auto_sync or self._trigger_now or self._sync_products_requested or self._pull_sales_requested

            if online:
                # Push pending invoices
                if should_sync and pending_count > 0:
                    pushed_count, synced_bills = self.push_invoices_batch(base_url, headers, terminal)
                    pending_count = self.db.get_pending_invoice_count()
                    for bill in synced_bills:
                        self.invoice_pushed.emit(bill, True, "Synced to cloud")

                # Auto-sync product catalog if database has fewer than 50 items or if explicitly requested
                current_prod_count = self.db.get_product_count()
                if self._sync_products_requested or (auto_sync and current_prod_count < 50):
                    self._sync_products_requested = False
                    p_count = self.sync_product_catalog(base_url, headers)
                    if p_count > 0:
                        self.product_sync_completed.emit(p_count, f"Synced {p_count} products from cloud")

                # If sales sync was requested
                if self._pull_sales_requested:
                    self._pull_sales_requested = False
                    s_ok, s_count, s_tot, s_msg = self.pull_domain_sales()
                    self.sales_synced.emit(s_count, s_tot, s_msg)

                if auto_sync:
                    status_text = "ONLINE (Cloud Synced)"
                else:
                    status_text = "ONLINE (Auto-Sync: OFF)"
                self.status_changed.emit(True, pending_count, status_text)
            else:
                status_text = f"OFFLINE MODE ({pending_count} bills pending sync)"
                self.status_changed.emit(False, pending_count, status_text)

            # Sleep or wait for next immediate trigger
            self._mutex.lock()
            if self._is_running and not self._trigger_now:
                # Wait for interval or wake
                self._cond.wait(self._mutex, self.interval * 1000)
            self._trigger_now = False
            self._mutex.unlock()

    @staticmethod
    def test_connection_direct(tenant: str, base_domain: str, token: str, terminal: str) -> Dict[str, Any]:
        """Synchronous connection tester for Settings dialog."""
        worker = SyncWorker(None)
        base_url = worker.build_base_url(tenant, base_domain)
        headers = worker.get_headers(token, terminal)

        # 1. Ping
        health_ok = worker.check_health(base_url, headers)
        if not health_ok:
            return {
                "success": False,
                "message": f"Unable to reach server at {base_url}. Check connection or domain name."
            }

        # 2. Verify token / tenant endpoint
        verify_endpoints = [
            f"{base_url}/pos/settings/verify",
            f"{base_url}/pos/health",
            f"{base_url}/ping"
        ]
        for ep in verify_endpoints:
            try:
                res = requests.get(ep, headers=headers, timeout=5.0, verify=False)
                if res.status_code in [200, 204]:
                    return {
                        "success": True,
                        "base_url": base_url,
                        "message": f"Connection Successful! Connected to {base_url} (HTTP {res.status_code})"
                    }
                elif res.status_code in [401, 403]:
                    return {
                        "success": False,
                        "message": f"Server reached, but API Token was rejected (HTTP {res.status_code})."
                    }
            except Exception:
                continue

        return {
            "success": True,
            "base_url": base_url,
            "message": f"Server ping reached successfully at {base_url}!"
        }
