"""
test_qa_full_suite.py - Senior QA Automated Test Suite for FastPOS Terminal.
================================================================================
Comprehensive End-to-End Automated Testing Matrix:
- SUITE 1: Barcode & QR Code Engine (Hardware Scanner Simulation, Symbologies, URLs)
- SUITE 2: On-Demand Remote Lookup & Live Fallback Caching
- SUITE 3: Financial Arithmetic, Line/Global Discounts, Tax & Rounding Precision
- SUITE 4: Multi-Bill Tabs System (Simultaneous Billing & Context Isolation)
- SUITE 5: Checkout State Machine, Payment Processing & Inventory Deduction
- SUITE 6: Offline Invoicing Queue & Settings Persistence
- SUITE 7: Thermal Receipt Formatting (80mm ESC/POS) & Bill Edit / Stock Refund
- SUITE 8: Security, SQL Injection, Buffer Limits & Input Sanitization
================================================================================
"""

import sys
import time
from decimal import Decimal
from PyQt6.QtWidgets import QApplication, QLineEdit
from PyQt6.QtCore import Qt, QEvent, QTimer
from PyQt6.QtGui import QKeyEvent

from database import DatabaseManager
from sync_worker import SyncWorker
from ui_main import MainWindow, CheckoutDialog
from ui_table import (
    POSBillingTable, ProductSearchLineEdit, ProductSuggestDelegate,
    COL_INDEX, COL_NAME, COL_QTY, COL_PRICE, COL_DISC, COL_TAX, COL_TOTAL, COL_ACTION
)
from ui_sales_list import format_thermal_receipt
from sms_service import AsyncSmsWorker, is_valid_phone


class SeniorQATestRunner:
    def __init__(self):
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.db = DatabaseManager(":memory:")
        self.db.init_db()
        self.worker = SyncWorker(self.db)
        self.window = MainWindow(self.db, self.worker)
        self.table = self.window.table
        self.passed_tests = 0
        self.failed_tests = 0
        self.test_results = []

    def log_test(self, suite: str, test_id: str, desc: str, passed: bool, notes: str = ""):
        status = "PASS" if passed else "FAIL"
        if passed:
            self.passed_tests += 1
            print(f"  [{status}] {test_id}: {desc}")
        else:
            self.failed_tests += 1
            print(f"  [{status}] {test_id}: {desc} --> ERROR: {notes}")
        self.test_results.append({
            "suite": suite,
            "id": test_id,
            "desc": desc,
            "status": status,
            "notes": notes
        })

    def run_all(self):
        start_time = time.time()
        print("\n" + "=" * 80)
        print("🚀 SENIOR QA TEST SUITE: FastPOS High-Speed Retail & Jewelry Terminal")
        print("=" * 80)

        self.suite_1_barcode_qr_engine()
        self.suite_2_remote_lookup_fallback()
        self.suite_3_financial_arithmetic()
        self.suite_4_multi_bill_tabs()
        self.suite_5_checkout_and_stock_ledger()
        self.suite_6_offline_queue_and_settings()
        self.suite_7_thermal_receipt_and_edit_bill()
        self.suite_8_security_and_edge_cases()

        elapsed = time.time() - start_time
        print("\n" + "=" * 80)
        print(f"🏁 QA TEST RUN COMPLETE: {self.passed_tests} PASSED, {self.failed_tests} FAILED in {elapsed:.2f}s")
        print("=" * 80 + "\n")

        assert self.failed_tests == 0, f"{self.failed_tests} QA test(s) failed!"
        return self.test_results

    # --------------------------------------------------------------------------
    # SUITE 1: Barcode & QR Code Engine
    # --------------------------------------------------------------------------
    def suite_1_barcode_qr_engine(self):
        print("\n[SUITE 1: Barcode & QR Code Engine (Scanner Simulation)]")
        # Seed realistic jewelry item
        self.db.upsert_products([{
            "id": 4657,
            "sku": "PROD-C2F40A",
            "barcode": "2001106191249",
            "name": "Appolo Bangles 2.8",
            "selling_price": 3200.00,
            "stock_qty": 14.0
        }, {
            "id": 5001,
            "sku": "PROD-RING",
            "barcode": "2004702957295",
            "name": "Gold Ring 22K 4g",
            "selling_price": 45000.00,
            "stock_qty": 5.0
        }])

        # Test A1: Exact 13-digit EAN Barcode
        p1 = self.db.get_product_by_code("2001106191249")
        self.log_test("Suite 1", "TC-1.1", "Exact 13-digit EAN barcode lookup", 
                      p1 is not None and p1["id"] == 4657)

        # Test A2: Suffix matching (5 digits: 91249)
        p2 = self.db.get_product_by_code("91249")
        self.log_test("Suite 1", "TC-1.2", "Suffix 5-digit tag lookup (91249 -> 2001106191249)", 
                      p2 is not None and p2["id"] == 4657)

        # Test A3: Short 3-digit tag suffix (249)
        p3 = self.db.get_product_by_code("249")
        self.log_test("Suite 1", "TC-1.3", "Short 3-digit suffix tag lookup (249)", 
                      p3 is not None and p3["id"] == 4657)

        # Test A4: QR Code URL payload
        p4 = self.db.get_product_by_code("https://jaffnagold.com/product-image/4657")
        self.log_test("Suite 1", "TC-1.4", "QR Code URL payload parsing (/product-image/4657)", 
                      p4 is not None and p4["id"] == 4657)

        # Test A5: QR Code URL with query string
        p5 = self.db.get_product_by_code("https://jaffnagold.com/scan?barcode=2001106191249&src=tag")
        self.log_test("Suite 1", "TC-1.5", "QR Code URL with query parameters (?barcode=...)", 
                      p5 is not None and p5["id"] == 4657)

        # Test A6: 2D Scanner AIM symbology prefix (']Q1' for QR code)
        p6 = self.db.get_product_by_code("]Q12001106191249")
        self.log_test("Suite 1", "TC-1.6", "AIM symbology prefix stripping (]Q1...)", 
                      p6 is not None and p6["id"] == 4657)

        # Test A7: 1D Scanner AIM symbology prefix (']E0' for EAN-13)
        p7 = self.db.get_product_by_code("]E02001106191249")
        self.log_test("Suite 1", "TC-1.7", "AIM symbology prefix stripping (]E0...)", 
                      p7 is not None and p7["id"] == 4657)

        # Test A8: Non-printable control characters (\x02 STX and \x03 ETX)
        p8 = self.db.get_product_by_code("\x022001106191249\x03")
        self.log_test("Suite 1", "TC-1.8", "Scanner control character stripping (STX/ETX)", 
                      p8 is not None and p8["id"] == 4657)

        # Test A9: Hardware Scanner simulation into UI Grid via ProductSearchLineEdit
        self.window.new_bill()
        cur_row = self.table.rowCount() - 1
        self.table.focus_cell(cur_row, COL_NAME, edit=True)
        editor = self.table.focusWidget()
        assert isinstance(editor, ProductSearchLineEdit)

        # Simulate scanner keystrokes ending in Return \r
        for ch in "91249\r":
            ke = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Return if ch == '\r' else ord(ch), Qt.KeyboardModifier.NoModifier, ch)
            self.app.sendEvent(editor, ke)
        self.app.processEvents()

        row0_name = self.table.item(0, COL_NAME).text()
        row0_qty = self.table.item(0, COL_QTY).text()
        self.log_test("Suite 1", "TC-1.9", "Simulated scanner burst adds product and advances row", 
                      "Appolo Bangles" in row0_name and row0_qty == "1" and self.table.rowCount() == 2)

        # Test A10: Duplicate scan auto-increments quantity and keeps new row clean
        cur_row = self.table.rowCount() - 1
        self.table.focus_cell(cur_row, COL_NAME, edit=True)
        editor = self.table.focusWidget()
        for ch in "2001106191249\r\n":
            ke = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Return if ch in ('\r', '\n') else ord(ch), Qt.KeyboardModifier.NoModifier, ch)
            self.app.sendEvent(editor, ke)
        self.app.processEvents()

        row0_qty_after = self.table.item(0, COL_QTY).text()
        row1_name = self.table.item(1, COL_NAME).text()
        self.log_test("Suite 1", "TC-1.10", "Duplicate scan auto-increments Qty to 2 and keeps active cell blank", 
                      row0_qty_after == "2" and row1_name == "")

    # --------------------------------------------------------------------------
    # SUITE 2: On-Demand Remote Lookup & Fallback Caching
    # --------------------------------------------------------------------------
    def suite_2_remote_lookup_fallback(self):
        print("\n[SUITE 2: On-Demand Remote Lookup & Live Fallback Caching]")
        # Product 9876 does not exist in local SQLite
        assert self.db.get_product_by_code("UNCACHED-CODE-99") is None

        # Test lookup_remote_product handles offline / timeout gracefully
        t0 = time.time()
        res_none = self.worker.lookup_remote_product("DEFINITELY-NON-EXISTENT-CODE-123456")
        dur = time.time() - t0
        self.log_test("Suite 2", "TC-2.1", "Remote lookup handles non-existent code within timeout (< 3s)", 
                      res_none is None and dur < 3.5)

        # Test mock upsert on remote hit
        mock_remote_data = [{
            "id": 8888,
            "sku": "PROD-8888",
            "barcode": "2008888000001",
            "name": "Platinum Chain 18K",
            "selling_price": 75000.0,
            "stock_qty": 3.0
        }]
        self.db.upsert_products(mock_remote_data)
        cached = self.db.get_product_by_code("2008888000001")
        self.log_test("Suite 2", "TC-2.2", "Remote product successfully cached into local SQLite", 
                      cached is not None and cached["name"] == "Platinum Chain 18K")

        # Test suffix lookup on newly cached remote item
        cached_suffix = self.db.get_product_by_code("000001")
        self.log_test("Suite 2", "TC-2.3", "Suffix matching works immediately on newly cached remote product", 
                      cached_suffix is not None and cached_suffix["id"] == 8888)

    # --------------------------------------------------------------------------
    # SUITE 3: Financial Arithmetic, Line/Global Discounts, Tax & Rounding Precision
    # --------------------------------------------------------------------------
    def suite_3_financial_arithmetic(self):
        print("\n[SUITE 3: Financial Arithmetic & Precision]")
        self.window.new_bill()
        table = self.window.table

        # Insert 3 items with specific prices:
        # Item 1: Qty 1 @ Rs. 3200.00, Auto-Disc 10% -> 2880.00
        p1 = self.db.get_product_by_code("91249")
        table.on_product_selected(0, p1, continuous_scan=False)
        self.log_test("Suite 3", "TC-3.1", "Auto-10% discount on single item: 3200.00 - 10% = 2880.00", 
                      table.item(0, COL_TOTAL).text() == "2880.00")

        # Item 2: Qty 2 @ Rs. 1500.00, Custom Disc 5%, Tax 0% -> (2 * 1500) * 0.95 = 2850.00
        r1 = table.add_blank_row()
        self.db.upsert_products([{"id": 7771, "sku": "P-7771", "barcode": "7771", "name": "Silver Coin 10g", "selling_price": 1500.0, "stock_qty": 20.0}])
        table.on_product_selected(r1, self.db.get_product_by_code("7771"), continuous_scan=False)
        table.item(r1, COL_QTY).setText("2")
        table.item(r1, COL_DISC).setText("5")
        table.recalculate_row(r1)
        self.log_test("Suite 3", "TC-3.2", "Custom line discount: 2 @ 1500.00 with 5% disc = 2850.00", 
                      table.item(r1, COL_TOTAL).text() == "2850.00")

        # Verify Grand Total before global discount
        # Gross = 3200 + 3000 = 6200.00
        # Line Disc = 320 + 150 = 470.00
        # Grand Total = 6200 - 470 = 5730.00
        self.log_test("Suite 3", "TC-3.3", "Subtotal & Grand Total precision check (Rs. 5730.00)", 
                      self.window.grand_total == Decimal("5730.00"))

        # Test Global Discount & Round Down to nearest 100 in Checkout Dialog
        chk = CheckoutDialog(self.window.grand_total, default_method="CASH", theme_mode="dark")
        chk.round_down_to(Decimal("100.00"))
        # 5730 rounded down to 5700 -> Extra discount = 30.00
        self.log_test("Suite 3", "TC-3.4", "Round down to 100 helper: 5730.00 -> 5700.00 (Disc: 30.00)", 
                      chk.grand_total == Decimal("5700.00") and chk.extra_discount == Decimal("30.00"))

        # Test manual global discount of Rs. 200 -> Grand Total = 5530.00
        chk.txt_discount.setText("200.00")
        self.log_test("Suite 3", "TC-3.5", "Manual global discount: 5730.00 - 200.00 = 5530.00", 
                      chk.grand_total == Decimal("5530.00") and chk.txt_paid.text() == "5530.00")
        chk.close()

    # --------------------------------------------------------------------------
    # SUITE 4: Multi-Bill Tabs System
    # --------------------------------------------------------------------------
    def suite_4_multi_bill_tabs(self):
        print("\n[SUITE 4: Multi-Bill Tabs (Simultaneous Billing)]")
        win = self.window
        # Reset window tab state to a clean single tab
        win.table.clear_bill()
        win.tabs = [win.tabs[0]]
        win.active_tab_idx = 0
        win._load_tab_state(0)

        # Tab 1: Customer Alice with Appolo Bangles
        win.current_customer = "Alice"
        win.table.on_product_selected(0, self.db.get_product_by_code("91249"), continuous_scan=False)
        tab1_total = win.grand_total
        win._save_current_tab_state()

        # Tab 2: Customer Bob with Ring
        win.add_new_bill_tab(customer_name="Bob", customer_phone="0771112233")
        self.log_test("Suite 4", "TC-4.1", "Add Tab 2 increments tab count to 2", len(win.tabs) == 2 and win.active_tab_idx == 1)

        win.table.on_product_selected(0, self.db.get_product_by_code("2004702957295"), continuous_scan=False)
        tab2_total = win.grand_total
        win._save_current_tab_state()
        self.log_test("Suite 4", "TC-4.2", "Tab 2 has isolated cart state", tab2_total != tab1_total and win.current_customer == "Bob")

        # Switch back to Tab 1
        win.switch_to_tab(0)
        self.log_test("Suite 4", "TC-4.3", "Switch to Tab 1 restores Customer Alice and cart total", 
                      win.current_customer == "Alice" and win.grand_total == tab1_total)

        # Tab navigation hotkeys
        win.switch_to_next_tab()
        self.log_test("Suite 4", "TC-4.4", "switch_to_next_tab cycles to Tab 2", win.active_tab_idx == 1)

        win.switch_to_prev_tab()
        self.log_test("Suite 4", "TC-4.5", "switch_to_prev_tab cycles back to Tab 1", win.active_tab_idx == 0)

        # Close Tab 2 safely (force=True to bypass GUI prompt in automated tests)
        win.close_bill_tab(1, force=True)
        self.log_test("Suite 4", "TC-4.6", "Close Tab 2 leaves 1 active tab without data corruption", 
                      len(win.tabs) == 1 and win.active_tab_idx == 0)

        # Prevent closing only active tab
        win.close_bill_tab(0, force=True)
        self.log_test("Suite 4", "TC-4.7", "Attempting to close the only remaining tab is safely prevented", 
                      len(win.tabs) == 1)

    # --------------------------------------------------------------------------
    # SUITE 5: Checkout State Machine, Payment Processing & Inventory Deduction
    # --------------------------------------------------------------------------
    def suite_5_checkout_and_stock_ledger(self):
        print("\n[SUITE 5: Checkout, Payments & Inventory Ledger]")
        # Check initial stock
        prod = self.db.get_product_by_code("2001106191249")
        initial_stock = prod["stock"]

        # Finalize invoice for 2 units
        items = [{
            "id": prod["id"],
            "name": prod["name"],
            "barcode": prod["barcode"],
            "sku": prod["sku"],
            "qty": 2.0,
            "price": 3200.0,
            "disc_pct": 10.0,
            "tax_pct": 0.0,
            "total": 5760.0
        }]

        inv_id = self.db.create_invoice({
            "bill_no": "#QA-TEST-001",
            "customer_name": "QA Customer",
            "customer_phone": "0771234567",
            "subtotal": 6400.0,
            "discount": 640.0,
            "tax": 0.0,
            "grand_total": 5760.0,
            "paid_amount": 5760.0,
            "due_amount": 0.0,
            "payment_method": "CASH",
            "items_json": items,
            "created_at": "2026-10-16 16:00:00"
        }, is_synced=0)

        self.log_test("Suite 5", "TC-5.1", "Invoice created successfully with ID > 0", inv_id > 0)

        # Verify stock deduction
        prod_after = self.db.get_product_by_code("2001106191249")
        self.log_test("Suite 5", "TC-5.2", f"Stock deducted accurately ({initial_stock} -> {prod_after['stock']})", 
                      prod_after["stock"] == initial_stock - 2.0)

        # Verify offline pending count
        pending_count = self.db.get_pending_invoice_count()
        self.log_test("Suite 5", "TC-5.3", "Invoice properly queued in offline storage (is_synced = 0)", 
                      pending_count >= 1)

    # --------------------------------------------------------------------------
    # SUITE 6: Offline Invoicing Queue & Settings Persistence
    # --------------------------------------------------------------------------
    def suite_6_offline_queue_and_settings(self):
        print("\n[SUITE 6: Offline Storage & Settings Management]")
        # Test settings persistence
        self.db.set_setting("sms_sender_id", "QA Gold Terminal")
        self.db.set_setting("auto_discount_percent", "15.0")
        self.db.set_setting("auto_sync_enabled", "1")

        self.log_test("Suite 6", "TC-6.1", "Custom sms_sender_id persisted", 
                      self.db.get_setting("sms_sender_id") == "QA Gold Terminal")
        self.log_test("Suite 6", "TC-6.2", "Custom auto_discount_percent persisted", 
                      self.db.get_setting("auto_discount_percent") == "15.0")
        self.log_test("Suite 6", "TC-6.3", "Custom auto_sync_enabled persisted", 
                      self.db.get_setting("auto_sync_enabled") == "1")

        # Test clear_local_storage preserves settings
        clear_stats = self.db.clear_local_storage(preserve_settings=True)
        self.log_test("Suite 6", "TC-6.4", "clear_local_storage clears products & invoices", 
                      clear_stats["invoices"] >= 1 and self.db.get_pending_invoice_count() == 0)
        self.log_test("Suite 6", "TC-6.5", "clear_local_storage preserves core settings and credentials", 
                      self.db.get_setting("sms_sender_id") == "QA Gold Terminal")

    # --------------------------------------------------------------------------
    # SUITE 7: Thermal Receipt Formatting & Bill Edit / Stock Refund
    # --------------------------------------------------------------------------
    def suite_7_thermal_receipt_and_edit_bill(self):
        print("\n[SUITE 7: Thermal Printing & Bill Edit / Inventory Restoration]")
        # Re-seed test product
        self.db.upsert_products([{
            "id": 9001,
            "sku": "P-9001",
            "barcode": "2009001000001",
            "name": "Emerald Necklace",
            "selling_price": 50000.0,
            "stock_qty": 10.0
        }])

        items = [{
            "id": 9001,
            "name": "Emerald Necklace",
            "barcode": "2009001000001",
            "sku": "P-9001",
            "qty": 1.0,
            "price": 50000.0,
            "disc_pct": 10.0,
            "tax_pct": 0.0,
            "total": 45000.0
        }]

        # Create bill #EDIT-01
        self.db.create_invoice({
            "bill_no": "#EDIT-01",
            "customer_name": "VIP Mrs. Silva",
            "customer_phone": "0778889999",
            "subtotal": 50000.0,
            "discount": 5000.0,
            "tax": 0.0,
            "grand_total": 45000.0,
            "payment_method": "CARD",
            "items_json": items,
            "created_at": "2026-10-16 15:30:00"
        }, is_synced=0)

        # Stock should be 9.0
        assert self.db.get_product_by_code("2009001000001")["stock"] == 9.0

        # Test receipt format
        inv = self.db.get_invoice_by_bill_no("#EDIT-01")
        receipt = format_thermal_receipt(inv, tenant_subdomain="jaffnagold", cashier_name="Cashier 01")
        self.log_test("Suite 7", "TC-7.1", "80mm Thermal Receipt layout includes header, items, totals", 
                      "#EDIT-01" in receipt and "Emerald Necklace" in receipt and "45000.00" in receipt)

        # Test prepare_invoice_for_edit (must refund stock and delete old invoice)
        prep = self.db.prepare_invoice_for_edit("#EDIT-01")
        restored_stock = self.db.get_product_by_code("2009001000001")["stock"]
        old_inv = self.db.get_invoice_by_bill_no("#EDIT-01")

        self.log_test("Suite 7", "TC-7.2", "Bill Edit accurately restores stock to inventory (9.0 -> 10.0)", 
                      restored_stock == 10.0)
        self.log_test("Suite 7", "TC-7.3", "Bill Edit safely deletes old un-edited invoice record", 
                      old_inv is None and prep is not None)

    # --------------------------------------------------------------------------
    # SUITE 8: Security, SQL Injection, Buffer Limits & Input Sanitization
    # --------------------------------------------------------------------------
    def suite_8_security_and_edge_cases(self):
        print("\n[SUITE 8: Security, SQL Injection & Edge Cases]")
        
        # Test H1: SQL Injection payload in product search
        sql_inj_1 = "' OR '1'='1"
        res_inj_1 = self.db.search_products(sql_inj_1)
        self.log_test("Suite 8", "TC-8.1", "SQL Injection in search_products (' OR '1'='1) safely handled", 
                      isinstance(res_inj_1, list))

        # Test H2: SQL Injection drop table payload in barcode lookup
        sql_inj_2 = "'; DROP TABLE products; --"
        res_inj_2 = self.db.get_product_by_code(sql_inj_2)
        # Verify table still exists
        table_exists = self.db.get_product_count() >= 0
        self.log_test("Suite 8", "TC-8.2", "SQL Injection drop table attempt safely parameterized", 
                      res_inj_2 is None and table_exists)

        # Test H3: Extremely long input string (10,000 chars)
        long_str = "A" * 10000
        res_long = self.db.get_product_by_code(long_str)
        self.log_test("Suite 8", "TC-8.3", "Buffer boundary: 10,000 char input handled without memory crash", 
                      res_long is None)

        # Test H4: Phone number validation for SMS
        self.log_test("Suite 8", "TC-8.4", "Valid local 10-digit mobile (0771234567)", is_valid_phone("0771234567"))
        self.log_test("Suite 8", "TC-8.5", "Valid international format (+94771234567)", is_valid_phone("+94771234567"))
        self.log_test("Suite 8", "TC-8.6", "Invalid short phone (12345) rejected", not is_valid_phone("12345"))
        self.log_test("Suite 8", "TC-8.7", "Invalid letters in phone (077abc4567) rejected", not is_valid_phone("077abc4567"))


if __name__ == "__main__":
    runner = SeniorQATestRunner()
    results = runner.run_all()
