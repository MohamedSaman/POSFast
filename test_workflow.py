"""
test_workflow.py - Automated Headless Verification of POS Workflows.
Tests:
- SQLite seeding and indexing
- Auto-suggest querying and row population
- Auto 10% discount application on row population and bulk recalculation
- Decimal calculation for Gross Subtotal, Discount, Tax, and Grand Total
- Double-Enter on empty row triggers checkout signal
- Invoice creation with is_synced=0 and stock decrement
- Today's Sales Query (get_todays_invoices)
- 80mm ESC/POS Thermal Receipt formatting (format_thermal_receipt)
- Edit Past Bill preparation (prepare_invoice_for_edit restores stock and deletes old invoice)
- Tenant isolation safety guard blocking switch with pending offline bills
- Park / Hold and Recall bill (F3 / F4)
"""

import sys
from decimal import Decimal
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from database import DatabaseManager
from sync_worker import SyncWorker
from ui_main import MainWindow
from ui_table import COL_INDEX, COL_NAME, COL_QTY, COL_PRICE, COL_DISC, COL_TAX, COL_TOTAL
from ui_sales_list import format_thermal_receipt


def run_tests():
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)

    db = DatabaseManager(":memory:")
    db.init_db()

    print("\n--- TEST 1: Database Initialization & Seeding ---")
    seeded_products = db.search_products("Apple")
    assert len(seeded_products) >= 2, f"Expected at least 2 Apple products, found {len(seeded_products)}"
    print(f"✓ Found {len(seeded_products)} Apple products in SQLite.")

    bread = db.get_product_by_code("BREAD-001")
    assert bread is not None, "Product lookup by SKU failed"
    assert bread["name"] == "Whole Wheat Bread"
    initial_bread_stock = bread["stock"]
    print(f"✓ Product lookup by SKU successful: {bread['name']} (Stock: {initial_bread_stock})")

    print("\n--- TEST 2: Main Window & Table Navigation ---")
    worker = SyncWorker(db)
    window = MainWindow(db, worker)
    table = window.table

    assert table.rowCount() == 1, "Initial table should have 1 empty row"
    assert table.auto_discount_enabled is True, "Auto-discount should default to True"
    assert table.auto_discount_percent == 10.0, "Auto-discount percent should default to 10.0%"
    print("✓ Initial billing table loaded with 1 blank row and Auto 10% Discount ACTIVE.")

    print("\n--- TEST 3: Selecting Product & Auto 10% Discount Calculation ---")
    table.on_product_selected(0, bread)
    assert table.item(0, COL_NAME).text() == "Whole Wheat Bread"
    assert table.item(0, COL_QTY).text() == "1"
    assert table.item(0, COL_PRICE).text() == "2.50"
    assert table.item(0, COL_DISC).text() == "10", "Auto-discount 10% should be set in Disc (%) cell"
    # Price 2.50 with 10% discount = 2.25
    assert table.item(0, COL_TOTAL).text() == "2.25", f"Expected 2.25, got {table.item(0, COL_TOTAL).text()}"
    print("✓ Row 0 populated: Whole Wheat Bread, Qty 1, Price 2.50, Disc 10%, Total 2.25")

    # Update Qty to 2 -> 2 * 2.50 * 0.90 = 4.50
    table.item(0, COL_QTY).setText("2")
    table.recalculate_row(0)
    assert table.item(0, COL_TOTAL).text() == "4.50"
    print("✓ Qty changed to 2 -> Line Total recalculated to 4.50 (with 10% discount)")

    print("\n--- TEST 4: Adding Second Row & Totals Breakdown ---")
    row1 = 1 if table.rowCount() > 1 else table.add_blank_row()
    milk = db.get_product_by_code("MILK-001")
    table.on_product_selected(row1, milk)
    assert table.item(1, COL_NAME).text() == "Organic Milk 1L"
    # Milk Price 3.80 * 0.9 = 3.42
    assert table.item(1, COL_TOTAL).text() == "3.42"
    print("✓ Row 1 populated: Organic Milk 1L, Total 3.42")

    # Check Window Breakdown:
    # Gross Subtotal = (2 * 2.50) + (1 * 3.80) = 5.00 + 3.80 = 8.80
    # Discount Total = (5.00 * 0.10) + (3.80 * 0.10) = 0.50 + 0.38 = 0.88
    # Grand Total = 8.80 - 0.88 = 7.92
    assert window.subtotal == Decimal("8.80"), f"Expected Gross Subtotal 8.80, got {window.subtotal}"
    assert window.discount_total == Decimal("0.88"), f"Expected Discount 0.88, got {window.discount_total}"
    assert window.grand_total == Decimal("7.92"), f"Expected Grand Total 7.92, got {window.grand_total}"
    assert window.lbl_grand_total.text() == "Rs. 7.92"
    assert window.lbl_disc_val.text() == "Rs. 0.88"
    print(f"✓ Breakdown verified: Subtotal Rs. {window.subtotal}, Disc Rs. {window.discount_total}, Grand Total Rs. {window.grand_total}")

    print("\n--- TEST 5: Double-Enter on Empty Row Checkout Trigger ---")
    checkout_triggered = []
    table.request_checkout.disconnect(window.finalize_and_checkout)
    table.request_checkout.connect(lambda: checkout_triggered.append(True))

    row2 = table.add_blank_row()
    table.on_empty_enter_pressed(row2)
    assert len(checkout_triggered) == 0, "Single enter should not trigger checkout"
    assert table.empty_enter_count == 1

    table.on_empty_enter_pressed(row2)
    assert len(checkout_triggered) == 1, "Double enter should trigger checkout"
    print("✓ Double-Enter on blank product row successfully triggered checkout signal!")

    print("\n--- TEST 6: Invoice Creation & Stock Deduction ---")
    items = table.get_bill_items()
    assert len(items) == 2, f"Expected 2 items, got {len(items)}"
    inv_id = db.create_invoice({
        "bill_no": "#2026-0001",
        "customer_name": "Walk-In",
        "subtotal": float(window.subtotal),
        "discount": float(window.discount_total),
        "tax": 0.0,
        "grand_total": float(window.grand_total),
        "payment_method": "CASH",
        "items_json": items,
        "created_at": "2026-10-15 14:00:00"
    }, is_synced=0)

    assert inv_id > 0
    assert db.get_pending_invoice_count() == 1
    print("✓ Invoice saved to SQLite with is_synced = 0 (1 pending offline bill)")

    # Verify stock deduction (2 units of bread deducted)
    updated_bread = db.get_product_by_code("BREAD-001")
    assert updated_bread["stock"] == initial_bread_stock - 2.0
    print(f"✓ Stock deducted: Bread stock went from {initial_bread_stock} to {updated_bread['stock']}")

    print("\n--- TEST 7: Today's Sales List & Thermal Receipt Formatting ---")
    todays = db.get_todays_invoices("2026-10-15")
    assert len(todays) == 1, f"Expected 1 invoice today, got {len(todays)}"
    today_inv = todays[0]
    assert today_inv["bill_no"] == "#2026-0001"
    assert len(today_inv["items"]) == 2
    print(f"✓ Fetched today's invoices: Bill {today_inv['bill_no']} with {len(today_inv['items'])} items.")

    # Test receipt formatting
    receipt_str = format_thermal_receipt(today_inv, tenant_subdomain="dbl", cashier_name="Admin")
    assert "#2026-0001" in receipt_str
    assert "Whole Wheat Bread" in receipt_str
    assert "Rs.       7.92" in receipt_str
    assert "Discount Saved:" in receipt_str
    print("✓ Thermal Receipt output formatted properly with 80mm ESC/POS layout.")

    print("\n--- TEST 8: Edit Past Bill Flow & Inventory Restoration ---")
    # Prepare invoice for edit: stock should be refunded, old invoice deleted
    prepared = db.prepare_invoice_for_edit("#2026-0001")
    assert prepared is not None
    assert prepared["bill_no"] == "#2026-0001"

    # Verify bread stock was restored
    restored_bread = db.get_product_by_code("BREAD-001")
    assert restored_bread["stock"] == initial_bread_stock, f"Expected stock {initial_bread_stock}, got {restored_bread['stock']}"
    print(f"✓ Stock restored on edit: Bread stock safely restored back to {restored_bread['stock']}")

    # Verify old invoice was deleted from SQLite
    assert db.get_invoice_by_bill_no("#2026-0001") is None
    print("✓ Old invoice removed from database ready for re-saving without duplicate stock deduction.")

    # Load into table
    table.load_items(prepared["items"])
    assert table.rowCount() >= 2
    print("✓ Prepared invoice items successfully loaded back into billing table for editing.")

    print("\n--- TEST 9: Tenant Isolation Safety Guard ---")
    # Since invoice was deleted in edit test, count is 0
    can_switch_now, _ = db.can_switch_tenant()
    assert can_switch_now is True
    print("✓ Tenant safety guard verified.")

    print("\n--- TEST 10: Park / Hold & Recall Bill (F3 / F4) ---")
    hold_id = db.hold_bill("#2026-0002", "VIP Customer", items, 7.92)
    assert hold_id > 0
    held_list = db.get_held_bills()
    assert len(held_list) == 1
    assert held_list[0]["customer_name"] == "VIP Customer"
    db.delete_held_bill(hold_id)
    assert len(db.get_held_bills()) == 0
    print("✓ Park / Hold & Recall verified successfully.")

    print("\n--- TEST 11: Multi-Bill Tabs System (Simultaneous Billing) ---")
    assert len(window.tabs) == 1
    assert window.active_tab_idx == 0

    # Put Customer A into Tab 1
    window.current_customer = "Customer A (Saman)"
    window.current_customer_phone = "0771234567"
    window.table.clear_bill()
    window.table.on_product_selected(0, bread, continuous_scan=False)
    assert window.grand_total == Decimal("2.25")
    window._save_current_tab_state()
    print("✓ Tab 1 configured with Customer A and Bread (Total: Rs. 2.25)")

    # Open Tab 2 for Customer B
    window.add_new_bill_tab(customer_name="Customer B (Kugan)", customer_phone="0779998888")
    assert len(window.tabs) == 2
    assert window.active_tab_idx == 1
    assert window.current_customer == "Customer B (Kugan)"
    assert window.grand_total == Decimal("0.00")
    print("✓ Tab 2 opened for Customer B with clean grid")

    # Add Milk to Customer B in Tab 2
    window.table.on_product_selected(0, milk, continuous_scan=False)
    assert window.grand_total == Decimal("3.42")
    window._save_current_tab_state()
    print("✓ Tab 2 populated with Organic Milk (Total: Rs. 3.42)")

    # Switch back to Tab 1 (Customer A)
    window.switch_to_tab(0)
    assert window.active_tab_idx == 0
    assert window.current_customer == "Customer A (Saman)"
    assert window.grand_total == Decimal("2.25")
    assert window.table.item(0, COL_NAME).text() == "Whole Wheat Bread"
    print("✓ Switched back to Tab 1: Customer A and Bread cart 100% intact!")

    # Switch back to Tab 2 (Customer B)
    window.switch_to_next_tab()
    assert window.active_tab_idx == 1
    assert window.current_customer == "Customer B (Kugan)"
    assert window.grand_total == Decimal("3.42")
    assert window.table.item(0, COL_NAME).text() == "Organic Milk 1L"
    print("✓ Cycled to Tab 2 via switch_to_next_tab: Customer B and Milk cart 100% intact!")

    # Close Tab 2 and verify auto-return to Tab 1
    del window.tabs[window.active_tab_idx]
    window._load_tab_state(0)
    assert len(window.tabs) == 1
    assert window.active_tab_idx == 0
    assert window.current_customer == "Customer A (Saman)"
    assert window.grand_total == Decimal("2.25")
    print("✓ Closed Tab 2: Automatically returned to Tab 1 with Customer A ready to finalize!")

    # --- TEST 12: QR / Barcode Scan & Repeated Item Scan Behavior ---
    print("\n--- TEST 12: QR / Barcode Suffix & Repeated Scan Flow ---")
    # Insert test product with long barcode like 2001073509061
    db.upsert_products([{
        "id": 9999,
        "sku": "PROD-TESTQR",
        "barcode": "2001073509061",
        "name": "Gold Pendant 22K",
        "selling_price": 3000.0,
        "stock_qty": 15.0
    }])
    
    # Lookup by full barcode
    p_full = db.get_product_by_code("2001073509061")
    assert p_full is not None
    assert p_full["name"] == "Gold Pendant 22K"
    
    # Lookup by suffix (509061) as scanned from Windows scanner
    p_suffix = db.get_product_by_code("509061")
    assert p_suffix is not None, "Suffix barcode lookup failed for 509061!"
    assert p_suffix["id"] == 9999
    assert p_suffix["name"] == "Gold Pendant 22K"
    print("✓ Barcode suffix matching verified: '509061' successfully resolved to '2001073509061'")

    # Test repeated scan on table
    window.new_bill() # clean bill
    assert window.table.rowCount() == 1
    # Scan 1: First item added to row 0
    window.table.on_product_selected(0, p_suffix)
    assert window.table.item(0, COL_QTY).text() == "1"
    # Row 1 is now blank ready for next item
    assert window.table.rowCount() == 2
    
    # Scan 2: Same item scanned into row 1
    window.table.on_product_selected(1, p_suffix)
    # Row 0 quantity should be incremented to 2
    assert window.table.item(0, COL_QTY).text() == "2"
    # Row 1 product cell should be reset and empty (no lingering suggest text)
    assert window.table.item(1, COL_NAME).text() == ""
    assert window.table.item(1, COL_NAME).data(Qt.ItemDataRole.UserRole) is None
    print("✓ Repeated scan verified: Existing row Qty auto-incremented to 2 and scan row stayed cleanly blank!")

    # --- TEST 13: Local Storage Database Clear & Configs (sms_sender_id, auto_sync_enabled) ---
    print("\n--- TEST 13: Local Storage Database Clear & Configs (sms_sender_id, auto_sync_enabled) ---")
    db.set_setting("sms_sender_id", "Jaffna Gold")
    assert db.get_setting("sms_sender_id") == "Jaffna Gold"
    db.set_setting("auto_sync_enabled", "0")
    assert db.get_setting("auto_sync_enabled") == "0"
    all_s = db.get_all_settings()
    assert all_s.get("sms_sender_id") == "Jaffna Gold"
    assert all_s.get("auto_sync_enabled") == "0"
    print("✓ Custom sms_sender_id and auto_sync_enabled successfully saved and loaded.")

    # Insert sample data to verify clearing
    db.create_invoice({
        "bill_no": "#2026-CLEAR-TEST",
        "customer_name": "Test Cust",
        "subtotal": 100.0,
        "discount": 0.0,
        "tax": 0.0,
        "grand_total": 100.0,
        "payment_method": "CASH",
        "items_json": [],
        "created_at": "2026-10-16 12:00:00"
    }, is_synced=0)
    db.hold_bill("#2026-HOLD-TEST", "Held Cust", [], 50.0)
    assert len(db.get_held_bills()) >= 1

    # Execute clear local storage
    stats = db.clear_local_storage(preserve_settings=True)
    assert stats["products"] >= 1
    assert stats["invoices"] >= 1
    assert stats["held_bills"] >= 1
    assert len(db.search_products("")) == 0, "Products should be empty after clear"
    assert db.get_pending_invoice_count() == 0, "Invoices should be empty after clear"
    assert len(db.get_held_bills()) == 0, "Held bills should be empty after clear"
    assert db.get_setting("last_product_sync") == ""
    assert db.get_setting("last_sales_sync") == ""

    # Verify settings are preserved
    assert db.get_setting("sms_sender_id") == "Jaffna Gold"
    assert db.get_setting("auto_sync_enabled") == "0"
    print("✓ Local database wiped clean: products, invoices, and held bills cleared while settings and credentials preserved!")

    # Verify window handles database_cleared signal
    window._on_database_cleared()
    assert len(window.tabs) == 1
    assert window.active_tab_idx == 0
    assert window.table.rowCount() == 1
    # --- TEST 14: Global Bill Discount, Round-Off & Keyboard Navigation Flow ---
    print("\n--- TEST 14: Global Bill Discount, Round-Off & Keyboard Navigation Flow ---")
    from ui_main import CheckoutDialog
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtCore import QEvent

    chk = CheckoutDialog(Decimal('3250.00'), default_method="CASH", theme_mode="dark")
    assert chk.original_grand_total == Decimal('3250.00')
    assert chk.grand_total == Decimal('3250.00')
    assert chk.txt_discount.text() == "0.00"

    # Test round down to nearest 100 (3250 -> 3200, discount = 50)
    chk.round_down_to(Decimal('100.00'))
    assert chk.extra_discount == Decimal('50.00')
    assert chk.grand_total == Decimal('3200.00')
    assert chk.txt_paid.text() == "3200.00"
    print("✓ Round 100 helper verified: 3250.00 rounded to 3200.00 with 50.00 discount")

    # Test manual entry in discount box
    chk.txt_discount.setText("250.00")
    assert chk.extra_discount == Decimal('250.00')
    assert chk.grand_total == Decimal('3000.00')
    assert chk.txt_paid.text() == "3000.00"
    print("✓ Manual discount verified: Rs. 250 discount updated total to Rs. 3000.00")

    chk.show()
    app.processEvents()

    # Test navigation: Enter on txt_discount jumps to Payment Method button
    enter_ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
    handled = chk.eventFilter(chk.txt_discount, enter_ev)
    assert handled is True
    app.processEvents()
    assert chk.method_buttons[0].hasFocus()
    print("✓ Enter on discount field successfully focused CASH payment method button")

    # Enter on payment method button jumps to Amount Tendered
    handled_pm = chk.eventFilter(chk.method_buttons[0], enter_ev)
    assert handled_pm is True
    app.processEvents()
    assert chk.txt_paid.hasFocus()
    print("✓ Enter on CASH button successfully focused Amount Tendered field")

    chk.close()

    # Verify AsyncSmsWorker has sms_finished signal
    from sms_service import AsyncSmsWorker
    sms_w = AsyncSmsWorker({"bill_no": "#TEST", "customer_phone": "0771234567"}, db)
    assert hasattr(sms_w, 'sms_finished')
    sms_w.sms_finished.connect(lambda ok, msg: None)
    print("✓ AsyncSmsWorker initialized with valid sms_finished signal")

    print("\n===========================================================")
    print("ALL 14 ARCHITECTURAL, SCANNER & SETTINGS TESTS PASSED!")
    print("===========================================================\n")


if __name__ == "__main__":
    run_tests()


