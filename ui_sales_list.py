"""
ui_sales_list.py - Today's Sales List & Receipt Reprint/Edit Dialogs for FastPOS.
Provides a comprehensive overview of all invoices generated today,
enabling cashiers to instantly reprint 80mm ESC/POS receipts, modify/edit past bills,
or void incorrect entries while maintaining stock integrity.
"""

from decimal import Decimal
import json
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox, QFrame, QPlainTextEdit, QApplication, QInputDialog,
    QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread
from PyQt6.QtGui import QFont, QColor, QKeyEvent

from database import DatabaseManager
from theme import get_theme_tokens
from sms_service import FastPOSSmsService, is_valid_phone, normalize_phone_number


def format_thermal_receipt(inv: Dict[str, Any], tenant_subdomain: str = "dbl", cashier_name: str = "Admin") -> str:
    """Formats an invoice into standard 80mm ESC/POS thermal receipt text (38 chars width)."""
    shop_name = "FASTPOS RETAIL TERMINAL"
    items = inv.get("items")
    if items is None:
        try:
            items = json.loads(inv.get("items_json", "[]"))
        except Exception:
            items = []

    created_at = inv.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    customer = inv.get("customer_name") or "Walk-In"
    bill_no = inv.get("bill_no", "N/A")
    payment = inv.get("payment_method", "CASH")

    lines = [
        "=" * 38,
        f"{shop_name:^38}",
        f"Tenant: {tenant_subdomain}.webxkey.lk",
        f"Bill No: {bill_no}",
        f"Date: {created_at}",
        f"Cashier: {cashier_name}",
        f"Customer: {customer}",
        "-" * 38,
        f"{'Item':<17}{'Qty':>4}{'Price':>8}{'Tot':>9}",
        "-" * 38
    ]

    for it in items:
        name = str(it.get("product_name", ""))[:17]
        qty = it.get("qty", 1)
        prc = float(it.get("unit_price", 0.0))
        tot = float(it.get("line_total", 0.0))
        disc_pct = float(it.get("discount_percent", 0.0))

        lines.append(f"{name:<17}{qty:>4}{prc:>8.2f}{tot:>9.2f}")
        if disc_pct > 0:
            lines.append(f"  ↳ Disc: {disc_pct:g}% applied")

    subtotal = float(inv.get("subtotal", 0.0))
    discount = float(inv.get("discount", 0.0))
    tax = float(inv.get("tax", 0.0))
    grand_total = float(inv.get("grand_total", 0.0))

    lines.extend([
        "-" * 38,
        f"{'Subtotal:':<24}Rs. {subtotal:>10.2f}",
    ])
    if discount > 0:
        lines.append(f"{'Discount Saved:':<24}Rs. {discount:>10.2f}")
    if tax > 0:
        lines.append(f"{'Tax:':<24}Rs. {tax:>10.2f}")

    lines.extend([
        f"{'GRAND TOTAL:':<24}Rs. {grand_total:>10.2f}",
        f"{'Amount Paid:':<24}Rs. {float(inv.get('paid_amount', grand_total - float(inv.get('due_amount', 0.0) or 0.0))):>10.2f}" if float(inv.get('due_amount', 0.0) or 0.0) > 0 else f"{'Payment (' + payment + '):':<24}Rs. {grand_total:>10.2f}",
        f"{'BALANCE DUE:':<24}Rs. {float(inv.get('due_amount', 0.0) or 0.0):>10.2f}" if float(inv.get('due_amount', 0.0) or 0.0) > 0 else "",
        f"{'Payment Status:':<24}{'CREDIT (DUE)':>14}" if float(inv.get('due_amount', 0.0) or 0.0) > 0 else "",
        "=" * 38,
        f"{'Thank you for shopping with us!':^38}",
        "=" * 38,
        "\n"
    ])
    return "\n".join([l for l in lines if l != ""])


class ReprintReceiptDialog(QDialog):
    """Modal displaying formatted 80mm monospace thermal receipt with Print & Copy options."""

    def __init__(self, inv: Dict[str, Any], tenant: str = "dbl", cashier: str = "Admin", parent=None, theme_mode: str = "dark"):
        super().__init__(parent)
        self.inv = inv
        self.tenant = tenant
        self.cashier = cashier
        self.theme_mode = theme_mode
        self.receipt_text = format_thermal_receipt(inv, tenant, cashier)

        raw_no = str(inv.get('bill_no', '')).lstrip('#')
        self.setWindowTitle(f"Receipt Preview - #{raw_no}")
        self.setFixedSize(540, 680)
        self.setModal(True)
        self.init_ui()

    def init_ui(self):
        t = get_theme_tokens(self.theme_mode)
        self.setStyleSheet(f"QDialog {{ background-color: {t['bg_main']}; color: {t['text_main']}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        # Header Title
        title_box = QHBoxLayout()
        raw_no = str(self.inv.get('bill_no', '')).lstrip('#')
        lbl_title = QLabel(f"🖨️ Receipt #{raw_no}")
        lbl_title.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {t['accent']};")
        title_box.addWidget(lbl_title)
        title_box.addStretch()

        lbl_amt = QLabel(f"Rs. {float(self.inv.get('grand_total', 0.0)):.2f}")
        lbl_amt.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {t['success']};")
        title_box.addWidget(lbl_amt)
        layout.addLayout(title_box)

        # Receipt Monospace Text Area
        from PyQt6.QtWidgets import QTextBrowser
        from printer_engine import POSPrinterEngine
        self.engine = POSPrinterEngine(self.db_for_print())
        self.txt_receipt = QTextBrowser()
        self.txt_receipt.setStyleSheet(f"QTextBrowser {{ background-color: #ffffff; color: #000000; border: 1px solid {t['border']}; border-radius: 6px; }}")
        try:
            doc = self.engine.build_document(self.inv)
            doc.setTextWidth(360)
            self.txt_receipt.setDocument(doc)
            self._preview_doc = doc
        except Exception:
            self.txt_receipt.setPlainText(self.receipt_text)
        layout.addWidget(self.txt_receipt)

        # Bottom Action Buttons Bar
        btn_box = QHBoxLayout()
        btn_box.setSpacing(8)

        self.btn_copy = QPushButton("📋 Copy Text")
        self.btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy.setFixedHeight(40)
        self.btn_copy.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_copy.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['btn_secondary_bg']};
                color: {t['btn_secondary_text']};
                border: 1px solid {t['border']};
                border-radius: 6px;
                padding: 8px 6px;
                font-weight: 600;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {t['btn_secondary_hover']};
                color: {t['accent']};
            }}
        """)
        self.btn_copy.clicked.connect(self._copy_to_clipboard)
        btn_box.addWidget(self.btn_copy)

        self.btn_print = QPushButton("🖨️ Print Receipt")
        self.btn_print.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_print.setFixedHeight(40)
        self.btn_print.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_print.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['btn_success_bg']};
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 8px 6px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {t['btn_success_hover']};
            }}
        """)
        self.btn_print.clicked.connect(self._print_receipt)
        btn_box.addWidget(self.btn_print)

        self.btn_sms = QPushButton("📱 Send SMS")
        self.btn_sms.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sms.setFixedHeight(40)
        self.btn_sms.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_sms.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['accent']};
                color: #0f172a;
                border: none;
                border-radius: 6px;
                padding: 8px 6px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                opacity: 0.9;
            }}
        """)
        self.btn_sms.clicked.connect(self._send_sms)
        btn_box.addWidget(self.btn_sms)

        self.btn_close = QPushButton("✕ Close (Esc)")
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setFixedHeight(40)
        self.btn_close.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_close.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['btn_secondary_bg']};
                color: {t['btn_secondary_text']};
                border: 1px solid {t['border']};
                border-radius: 6px;
                padding: 8px 6px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {t['btn_secondary_hover']};
            }}
        """)
        self.btn_close.clicked.connect(self.accept)
        btn_box.addWidget(self.btn_close)

        layout.addLayout(btn_box)

    def _copy_to_clipboard(self):
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(self.receipt_text)
            self.btn_copy.setText("✓ Copied!")
            QTimer.singleShot(1500, lambda: self.btn_copy.setText("📋 Copy Text"))

    def db_for_print(self):
        return self._db if getattr(self, "_db", None) else DatabaseManager()

    def _print_receipt(self):
        ok, msg = self.engine.print_invoice(self.inv)
        if ok:
            QMessageBox.information(self, "Reprint Sent", f"Receipt for {self.inv.get('bill_no')}: {msg}")
        else:
            QMessageBox.warning(self, "Printer", msg)

    def _send_sms(self):
        phone = (self.inv.get("customer_phone") or "").strip()
        if not is_valid_phone(phone):
            new_phone, ok = QInputDialog.getText(
                self, "Send SMS Receipt", f"Enter Customer Mobile Number for Bill {self.inv.get('bill_no', '')}:",
                text=phone
            )
            if not ok or not new_phone.strip():
                return
            phone = new_phone.strip()
            self.inv["customer_phone"] = phone

        db = self.db_for_print()
        ok, msg = FastPOSSmsService.send_bill_invoice_sms(self.inv, db)
        if ok:
            self.inv["sms_sent"] = 1
            QMessageBox.information(self, "SMS Sent", f"Receipt SMS sent successfully to {phone}!\n\n{msg}")
        else:
            QMessageBox.warning(self, "SMS Failed", f"Could not send SMS: {msg}")


class LiveSalesSyncWorker(QThread):
    sync_finished = pyqtSignal(bool, int, float, str)

    def __init__(self, db: DatabaseManager, target_date: str = "", parent=None):
        super().__init__(parent)
        self.db = db
        self.target_date = target_date or datetime.now().strftime("%Y-%m-%d")

    def run(self):
        try:
            from sync_worker import SyncWorker
            worker = SyncWorker(self.db)
            ok, count, total_amt, msg = worker.pull_domain_sales(target_date=self.target_date)
            self.sync_finished.emit(ok, count, total_amt, msg)
        except Exception as e:
            self.sync_finished.emit(False, 0, 0.0, str(e))


class SalesListDialog(QDialog):
    """
    Dialog listing all bills generated today and synced from the live domain.
    Allows cashiers to:
    - View live synced sales from the domain (jaffnagold.com)
    - Filter by Today, Yesterday, or All Recent live bills
    - Search & filter by Bill #, Customer, Phone
    - Reprint 80mm receipts [Enter]
    - Edit / Modify past bill
    - Send / Resend SMS bill notifications
    - Void past bill
    """
    edit_bill_requested = pyqtSignal(dict) # Emitted when cashier chooses to edit a past bill

    def __init__(self, db: DatabaseManager, tenant: str = "dbl", cashier: str = "Admin", parent=None, theme_mode: str = "dark"):
        super().__init__(parent)
        self.db = db
        self.tenant = tenant
        self.cashier = cashier
        self.theme_mode = theme_mode
        self.current_date_filter = datetime.now().strftime("%Y-%m-%d")
        self.all_invoices: List[Dict[str, Any]] = []
        self.filtered_invoices: List[Dict[str, Any]] = []
        self.sync_worker_thread: Optional[LiveSalesSyncWorker] = None
        self.sort_column = 0 # Default column: 0 (Bill #)
        self.sort_order = Qt.SortOrder.DescendingOrder # Default: Descending (highest / newest bill first)
        self.base_headers = ["Bill #", "Time", "Customer", "Phone", "Items", "Subtotal", "Discount", "Grand Total", "Payment", "SMS", "Cloud Sync"]

        self.setWindowTitle("Today's Sales & Receipts (F6) - Live Domain Sync")
        self.setMinimumSize(1200, 640)
        self.resize(1260, 700)
        self.setModal(True)
        self.init_ui()
        self.load_data(fetch_live=True)

    def init_ui(self):
        t = get_theme_tokens(self.theme_mode)
        self.setStyleSheet(f"QDialog {{ background-color: {t['bg_main']}; color: {t['text_main']}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        # 1. Header Card
        header_card = QFrame()
        header_card.setObjectName("salesHeaderCard")
        header_card.setStyleSheet(f"""
            #salesHeaderCard {{
                background-color: {t['bg_card']};
                border: 1px solid {t['border']};
                border-radius: 8px;
                padding: 12px 16px;
            }}
            #salesHeaderCard QLabel {{
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }}
        """)
        h_layout = QHBoxLayout(header_card)
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.setSpacing(12)

        left_info = QVBoxLayout()
        lbl_title = QLabel("📋 Today's Sales Receipts (Domain Live Sync)")
        lbl_title.setStyleSheet(f"font-size: 17px; font-weight: bold; color: {t['accent']};")
        self.lbl_stats = QLabel("Loading today's bills...")
        self.lbl_stats.setStyleSheet(f"font-size: 13px; color: {t['text_muted']};")
        self.lbl_sync_indicator = QLabel("🔄 Connecting to live domain...")
        self.lbl_sync_indicator.setStyleSheet("font-size: 12px; color: #38bdf8; font-weight: 600;")
        left_info.addWidget(lbl_title)
        left_info.addWidget(self.lbl_stats)
        left_info.addWidget(self.lbl_sync_indicator)
        h_layout.addLayout(left_info)

        h_layout.addStretch()

        # Date Filter Buttons Group
        date_box = QHBoxLayout()
        date_box.setSpacing(6)
        
        self.btn_date_today = QPushButton("📅 Today")
        self.btn_date_today.setCheckable(True)
        self.btn_date_today.setChecked(True)
        self.btn_date_today.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_date_today.clicked.connect(lambda: self._set_date_filter("today"))
        
        self.btn_date_yesterday = QPushButton("⏪ Yesterday")
        self.btn_date_yesterday.setCheckable(True)
        self.btn_date_yesterday.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_date_yesterday.clicked.connect(lambda: self._set_date_filter("yesterday"))
        
        self.btn_date_all = QPushButton("🌐 All Recent (50)")
        self.btn_date_all.setCheckable(True)
        self.btn_date_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_date_all.clicked.connect(lambda: self._set_date_filter("all"))
        
        self.date_buttons = [self.btn_date_today, self.btn_date_yesterday, self.btn_date_all]
        self._update_date_button_styles()

        date_box.addWidget(self.btn_date_today)
        date_box.addWidget(self.btn_date_yesterday)
        date_box.addWidget(self.btn_date_all)
        h_layout.addLayout(date_box)

        # Search Filter Box
        self.txt_filter = QLineEdit()
        self.txt_filter.setPlaceholderText("🔍 Filter by Bill #, Customer, Phone...")
        self.txt_filter.setFixedWidth(240)
        self.txt_filter.setStyleSheet(f"""
            QLineEdit {{
                background-color: {t['input_bg']};
                color: {t['input_text']};
                border: 1px solid {t['border']};
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border-color: {t['border_focus']};
            }}
        """)
        self.txt_filter.textChanged.connect(self._apply_filter)
        h_layout.addWidget(self.txt_filter)

        # Sort Order Toggle Button (Ascending / Descending)
        self.btn_sort = QPushButton("⬇ Bill # (Desc)")
        self.btn_sort.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sort.setToolTip("Toggle Order: Descending (Newest first) or Ascending (Oldest first). You can also click any column header.")
        self.btn_sort.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['btn_secondary_bg']};
                color: {t['accent']};
                border: 1px solid {t['border']};
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {t['btn_secondary_hover']};
                color: #ffffff;
            }}
        """)
        self.btn_sort.clicked.connect(self._toggle_sort_order)
        h_layout.addWidget(self.btn_sort)

        self.btn_refresh = QPushButton("🔄 Refresh & Sync")
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['btn_secondary_bg']};
                color: {t['btn_secondary_text']};
                border: 1px solid {t['border']};
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {t['btn_secondary_hover']};
            }}
        """)
        self.btn_refresh.clicked.connect(lambda: self.load_data(fetch_live=True))
        h_layout.addWidget(self.btn_refresh)

        layout.addWidget(header_card)

        # 2. Invoices Table
        self.table = QTableWidget(0, 11)
        self.table.setHorizontalHeaderLabels(self.base_headers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {t['bg_card']};
                alternate-background-color: {t['table_row_alt']};
                border: 1px solid {t['border']};
                border-radius: 8px;
                color: {t['text_main']};
                font-size: 13px;
                gridline-color: {t['table_grid']};
            }}
            QTableWidget::item {{
                padding: 6px 8px;
                border-bottom: 1px solid {t['border']};
            }}
            QTableWidget::item:selected {{
                background-color: {t['accent']};
                color: #ffffff;
            }}
            QHeaderView::section {{
                background-color: {t['table_header_bg']};
                color: {t['table_header_text']};
                font-weight: 700;
                font-size: 12px;
                padding: 8px 6px;
                border: none;
                border-bottom: 2px solid {t['border']};
                border-right: 1px solid {t['border']};
            }}
            QHeaderView::section:hover {{
                background-color: {t['btn_secondary_hover']};
                color: {t['accent']};
            }}
        """)

        header = self.table.horizontalHeader()
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.sectionClicked.connect(self._on_header_section_clicked)

        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed) # Bill #
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed) # Time
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch) # Customer
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed) # Phone
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed) # Items
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed) # Subtotal
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed) # Discount
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed) # Grand Total
        header.setSectionResizeMode(8, QHeaderView.ResizeMode.Fixed) # Payment
        header.setSectionResizeMode(9, QHeaderView.ResizeMode.Fixed) # SMS
        header.setSectionResizeMode(10, QHeaderView.ResizeMode.Fixed) # Sync

        self.table.setColumnWidth(0, 115) # Bill #
        self.table.setColumnWidth(1, 80)  # Time
        # Column 2: Customer (Stretch)
        self.table.setColumnWidth(3, 105) # Phone
        self.table.setColumnWidth(4, 70)  # Items
        self.table.setColumnWidth(5, 120) # Subtotal
        self.table.setColumnWidth(6, 115) # Discount
        self.table.setColumnWidth(7, 125) # Grand Total
        self.table.setColumnWidth(8, 105) # Payment
        self.table.setColumnWidth(9, 75)  # SMS
        self.table.setColumnWidth(10, 95) # Sync

        self.table.doubleClicked.connect(self._reprint_selected)
        layout.addWidget(self.table)

        # 3. Action Buttons Bar
        action_bar = QHBoxLayout()
        action_bar.setSpacing(12)

        self.btn_reprint = QPushButton("🖨️ Reprint Receipt [Enter]")
        self.btn_reprint.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reprint.setFixedHeight(40)
        self.btn_reprint.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['btn_success_bg']};
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 8px 18px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {t['btn_success_hover']};
            }}
        """)
        self.btn_reprint.clicked.connect(self._reprint_selected)
        action_bar.addWidget(self.btn_reprint)

        self.btn_sms = QPushButton("📱 Send / Resend SMS")
        self.btn_sms.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sms.setFixedHeight(40)
        self.btn_sms.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['accent']};
                color: #0f172a;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                opacity: 0.9;
            }}
        """)
        self.btn_sms.clicked.connect(self._send_sms_selected)
        action_bar.addWidget(self.btn_sms)

        self.btn_edit = QPushButton("✏️ Edit / Modify Bill")
        self.btn_edit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_edit.setFixedHeight(40)
        self.btn_edit.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['btn_primary_bg']};
                color: {t['btn_primary_text']};
                border: none;
                border-radius: 6px;
                padding: 8px 18px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {t['btn_primary_hover']};
            }}
        """)
        self.btn_edit.clicked.connect(self._edit_selected)
        action_bar.addWidget(self.btn_edit)

        self.btn_void = QPushButton("🗑️ Void Bill")
        self.btn_void.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_void.setFixedHeight(40)
        self.btn_void.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['btn_secondary_bg']};
                color: {t['danger']};
                border: 1px solid {t['border']};
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: rgba(231, 76, 60, 0.2);
                border-color: {t['danger']};
            }}
        """)
        self.btn_void.clicked.connect(self._void_selected)
        action_bar.addWidget(self.btn_void)

        action_bar.addStretch()

        self.btn_close = QPushButton("Close (Esc)")
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setFixedHeight(40)
        self.btn_close.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['btn_secondary_bg']};
                color: {t['btn_secondary_text']};
                border: 1px solid {t['border']};
                border-radius: 6px;
                padding: 8px 18px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {t['btn_secondary_hover']};
            }}
        """)
        self.btn_close.clicked.connect(self.reject)
        action_bar.addWidget(self.btn_close)

        layout.addLayout(action_bar)
        self._update_header_labels()
        self._update_sort_button_text()

    def _set_date_filter(self, mode: str):
        today = datetime.now()
        if mode == "today":
            self.current_date_filter = today.strftime("%Y-%m-%d")
        elif mode == "yesterday":
            self.current_date_filter = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        elif mode == "all":
            self.current_date_filter = "all"

        self._update_date_button_styles()
        self.load_data(fetch_live=True)

    def _update_date_button_styles(self):
        t = get_theme_tokens(self.theme_mode)
        today_str = datetime.now().strftime("%Y-%m-%d")
        yest_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        active_btn = self.btn_date_today
        if self.current_date_filter == yest_str:
            active_btn = self.btn_date_yesterday
        elif self.current_date_filter in ["all", "recent"]:
            active_btn = self.btn_date_all

        for b in getattr(self, "date_buttons", []):
            is_active = (b == active_btn)
            b.setChecked(is_active)
            if is_active:
                b.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {t['accent']};
                        color: {'#0f172a' if self.theme_mode == 'dark' else '#ffffff'};
                        border: 1px solid {t['accent']};
                        border-radius: 6px;
                        padding: 6px 12px;
                        font-weight: bold;
                        font-size: 12px;
                    }}
                """)
            else:
                b.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {t['btn_secondary_bg']};
                        color: {t['btn_secondary_text']};
                        border: 1px solid {t['border']};
                        border-radius: 6px;
                        padding: 6px 12px;
                        font-weight: 600;
                        font-size: 12px;
                    }}
                    QPushButton:hover {{
                        background-color: {t['btn_secondary_hover']};
                    }}
                """)

    def load_data(self, fetch_live: bool = True):
        """Fetches all invoices for selected date filter from SQLite, then initiates live domain sync."""
        self.all_invoices = self.db.get_todays_invoices(self.current_date_filter)
        self._apply_filter(self.txt_filter.text())

        if not fetch_live:
            return

        tenant = self.db.get_setting("tenant_subdomain", "jaffnagold.com")
        clean_host = tenant.replace("https://", "").replace("http://", "").rstrip("/")
        self.lbl_sync_indicator.setText(f"🔄 Syncing live sales from domain ({clean_host})...")
        self.lbl_sync_indicator.setStyleSheet("font-size: 12px; color: #38bdf8; font-weight: 600;")
        self.btn_refresh.setEnabled(False)

        self.sync_worker_thread = LiveSalesSyncWorker(self.db, target_date=self.current_date_filter, parent=self)
        self.sync_worker_thread.sync_finished.connect(self._on_live_sync_finished)
        self.sync_worker_thread.start()

    def _on_live_sync_finished(self, ok: bool, count: int, total_amt: float, msg: str):
        self.btn_refresh.setEnabled(True)
        tenant = self.db.get_setting("tenant_subdomain", "jaffnagold.com")
        clean_host = tenant.replace("https://", "").replace("http://", "").rstrip("/")
        if ok:
            self.lbl_sync_indicator.setText(f"🟢 Domain Live Connected: {count} bills synced ({clean_host})")
            self.lbl_sync_indicator.setStyleSheet("font-size: 12px; color: #2ecc71; font-weight: 600;")
        else:
            self.lbl_sync_indicator.setText(f"⚠️ Offline / Cached Mode ({msg})")
            self.lbl_sync_indicator.setStyleSheet("font-size: 12px; color: #f39c12; font-weight: 600;")

        # Reload SQLite invoices with newly synced bills
        self.all_invoices = self.db.get_todays_invoices(self.current_date_filter)
        self._apply_filter(self.txt_filter.text())

    @staticmethod
    def _extract_bill_seq(bill_no: Any) -> int:
        """Extracts the numeric sequence from a bill number (e.g. #10625 -> 10625)."""
        nums = re.findall(r"\d+", str(bill_no or ""))
        return int(nums[-1]) if nums else 0

    def _get_sort_key(self, inv: Dict[str, Any], column: int):
        if column == 0:  # Bill #
            return self._extract_bill_seq(inv.get("bill_no", ""))
        elif column == 1:  # Time
            return str(inv.get("created_at", ""))
        elif column == 2:  # Customer
            return str(inv.get("customer_name") or "").lower()
        elif column == 3:  # Phone
            return str(inv.get("customer_phone") or "")
        elif column == 4:  # Items count
            items = inv.get("items", [])
            return len(items) if isinstance(items, list) else 0
        elif column == 5:  # Subtotal
            try:
                return float(inv.get("subtotal", 0.0) or 0.0)
            except Exception:
                return 0.0
        elif column == 6:  # Discount
            try:
                return float(inv.get("discount", 0.0) or 0.0)
            except Exception:
                return 0.0
        elif column == 7:  # Grand Total
            try:
                return float(inv.get("grand_total", 0.0) or 0.0)
            except Exception:
                return 0.0
        elif column == 8:  # Payment method
            return str(inv.get("payment_method", "")).lower()
        elif column == 9:  # SMS status
            return int(inv.get("sms_sent", 0) or 0)
        elif column == 10:  # Sync status
            return int(inv.get("is_synced", 0) or 0)
        return self._extract_bill_seq(inv.get("bill_no", ""))

    def _sort_invoices(self, invoices: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        reverse = (self.sort_order == Qt.SortOrder.DescendingOrder)
        return sorted(invoices, key=lambda inv: self._get_sort_key(inv, self.sort_column), reverse=reverse)

    def _update_header_labels(self):
        for i, title in enumerate(self.base_headers):
            if i == self.sort_column:
                arrow = " ⬇" if self.sort_order == Qt.SortOrder.DescendingOrder else " ⬆"
                item = QTableWidgetItem(f"{title}{arrow}")
            else:
                item = QTableWidgetItem(title)
            self.table.setHorizontalHeaderItem(i, item)
        self.table.horizontalHeader().setSortIndicator(self.sort_column, self.sort_order)

    def _update_sort_button_text(self):
        col_names = {
            0: "Bill #", 1: "Time", 2: "Customer", 3: "Phone", 4: "Items",
            5: "Subtotal", 6: "Discount", 7: "Total", 8: "Payment", 9: "SMS", 10: "Sync"
        }
        col_name = col_names.get(self.sort_column, "Bill #")
        if self.sort_order == Qt.SortOrder.DescendingOrder:
            self.btn_sort.setText(f"⬇ {col_name} (Desc)")
            self.btn_sort.setToolTip(f"Currently sorted by {col_name} Descending (Newest / Highest first). Click to switch to Ascending.")
        else:
            self.btn_sort.setText(f"⬆ {col_name} (Asc)")
            self.btn_sort.setToolTip(f"Currently sorted by {col_name} Ascending (Oldest / Lowest first). Click to switch to Descending.")

    def _on_header_section_clicked(self, logical_index: int):
        """Called when cashier clicks any column header to toggle / change sort order."""
        if self.sort_column == logical_index:
            # Toggle between Descending and Ascending
            if self.sort_order == Qt.SortOrder.DescendingOrder:
                self.sort_order = Qt.SortOrder.AscendingOrder
            else:
                self.sort_order = Qt.SortOrder.DescendingOrder
        else:
            # Switch to new column
            self.sort_column = logical_index
            if logical_index in (0, 1, 4, 5, 6, 7):
                self.sort_order = Qt.SortOrder.DescendingOrder
            else:
                self.sort_order = Qt.SortOrder.AscendingOrder

        self._update_header_labels()
        self._update_sort_button_text()
        self.filtered_invoices = self._sort_invoices(self.filtered_invoices)
        self._render_table()

    def _toggle_sort_order(self):
        """Called when cashier clicks the sort button in toolbar."""
        if self.sort_order == Qt.SortOrder.DescendingOrder:
            self.sort_order = Qt.SortOrder.AscendingOrder
        else:
            self.sort_order = Qt.SortOrder.DescendingOrder

        self._update_header_labels()
        self._update_sort_button_text()
        self.filtered_invoices = self._sort_invoices(self.filtered_invoices)
        self._render_table()

    def _apply_filter(self, query: str = ""):
        q = query.strip().lower()
        if not q:
            self.filtered_invoices = list(self.all_invoices)
        else:
            self.filtered_invoices = [
                inv for inv in self.all_invoices
                if q in inv.get("bill_no", "").lower()
                or q in (inv.get("customer_name") or "").lower()
                or q in (inv.get("customer_phone") or "").lower()
                or q in inv.get("payment_method", "").lower()
            ]

        self.filtered_invoices = self._sort_invoices(self.filtered_invoices)
        self._render_table()

    def _render_table(self):
        # Save selected bill_no to restore selection after re-rendering
        selected_bill_no = None
        cur_row = self.table.currentRow()
        if cur_row >= 0:
            cur_item = self.table.item(cur_row, 0)
            if cur_item:
                inv_data = cur_item.data(Qt.ItemDataRole.UserRole)
                if isinstance(inv_data, dict):
                    selected_bill_no = inv_data.get("bill_no")

        self.table.setRowCount(0)
        total_rev = Decimal("0.00")

        for inv in self.filtered_invoices:
            row = self.table.rowCount()
            self.table.insertRow(row)

            # 0: Bill #
            item_no = QTableWidgetItem(inv.get("bill_no", ""))
            item_no.setData(Qt.ItemDataRole.UserRole, inv)
            item_no.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_no.setForeground(QColor("#00e5ff"))
            font = item_no.font()
            font.setBold(True)
            item_no.setFont(font)
            self.table.setItem(row, 0, item_no)

            # 1: Time
            created = inv.get("created_at", "")
            time_str = created.split(" ")[1] if " " in created else created
            item_time = QTableWidgetItem(time_str)
            item_time.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 1, item_time)

            # 2: Customer
            cust = inv.get("customer_name") or "Walk-In"
            item_cust = QTableWidgetItem(cust)
            self.table.setItem(row, 2, item_cust)

            # 3: Phone
            phone = inv.get("customer_phone") or ""
            item_phone = QTableWidgetItem(phone if phone else "—")
            item_phone.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if phone:
                item_phone.setForeground(QColor("#38bdf8"))
            else:
                item_phone.setForeground(QColor("#64748b"))
            self.table.setItem(row, 3, item_phone)

            # 4: Items count
            items = inv.get("items", [])
            item_items = QTableWidgetItem(f"{len(items)} items")
            item_items.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 4, item_items)

            # 5: Subtotal
            sub = float(inv.get("subtotal", 0.0))
            item_sub = QTableWidgetItem(f"Rs. {sub:.2f}")
            item_sub.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 5, item_sub)

            # 6: Discount
            disc = float(inv.get("discount", 0.0))
            item_disc = QTableWidgetItem(f"Rs. {disc:.2f}" if disc > 0 else "-")
            item_disc.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if disc > 0:
                item_disc.setForeground(QColor("#f39c12"))
            self.table.setItem(row, 6, item_disc)

            # 7: Grand Total
            gt = float(inv.get("grand_total", 0.0))
            total_rev += Decimal(str(gt))
            item_gt = QTableWidgetItem(f"Rs. {gt:.2f}")
            item_gt.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item_gt.setForeground(QColor("#2ecc71"))
            gt_font = item_gt.font()
            gt_font.setBold(True)
            item_gt.setFont(gt_font)
            self.table.setItem(row, 7, item_gt)

            # 8: Payment
            pm = inv.get("payment_method", "CASH")
            due = float(inv.get("due_amount", 0.0) or 0.0)
            if due > 0:
                pm_text = f"{pm} (Due: Rs. {due:.2f})"
                item_pm = QTableWidgetItem(pm_text)
                item_pm.setForeground(QColor("#f59e0b"))
            else:
                item_pm = QTableWidgetItem(pm)
            item_pm.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 8, item_pm)

            # 9: SMS status
            sms_sent = inv.get("sms_sent", 0) == 1
            if sms_sent:
                sms_text = "📱 Sent"
                sms_color = "#2ecc71"
            elif phone:
                sms_text = "💬 Pending"
                sms_color = "#f39c12"
            else:
                sms_text = "—"
                sms_color = "#64748b"
            item_sms = QTableWidgetItem(sms_text)
            item_sms.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_sms.setForeground(QColor(sms_color))
            self.table.setItem(row, 9, item_sms)

            # 10: Sync status
            synced = inv.get("is_synced", 0) == 1
            sync_text = "🟢 Synced" if synced else "⏳ Pending"
            item_sync = QTableWidgetItem(sync_text)
            item_sync.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_sync.setForeground(QColor("#2ecc71" if synced else "#f39c12"))
            self.table.setItem(row, 10, item_sync)

            self.table.setRowHeight(row, 38)

        count = len(self.filtered_invoices)
        today_str = datetime.now().strftime("%Y-%m-%d")
        if self.current_date_filter == today_str:
            scope_name = "Today"
        elif self.current_date_filter in ["all", "recent"]:
            scope_name = "All Recent"
        elif self.current_date_filter == (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"):
            scope_name = "Yesterday"
        else:
            scope_name = self.current_date_filter

        self.lbl_stats.setText(f"Total Bills ({scope_name}): <b>{count}</b> | Total Revenue: <b style='color:#2ecc71;'>Rs. {total_rev:,.2f}</b>")

        restored = False
        if selected_bill_no:
            for r in range(self.table.rowCount()):
                it = self.table.item(r, 0)
                if it:
                    d = it.data(Qt.ItemDataRole.UserRole)
                    if isinstance(d, dict) and d.get("bill_no") == selected_bill_no:
                        self.table.selectRow(r)
                        restored = True
                        break
        if not restored and self.table.rowCount() > 0:
            self.table.selectRow(0)

    def _get_selected_invoice(self) -> Optional[Dict[str, Any]]:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Select Bill", "Please select a bill from the list first.")
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _send_sms_selected(self):
        inv = self._get_selected_invoice()
        if not inv:
            return
        phone = (inv.get("customer_phone") or "").strip()
        if not is_valid_phone(phone):
            new_phone, ok = QInputDialog.getText(
                self, "Send SMS Bill Receipt", f"Enter Customer Mobile Number for Bill {inv.get('bill_no', '')}:",
                text=phone
            )
            if not ok or not new_phone.strip():
                return
            phone = new_phone.strip()
            inv["customer_phone"] = phone

        ok, msg = FastPOSSmsService.send_bill_invoice_sms(inv, self.db)
        if ok:
            inv["sms_sent"] = 1
            self._render_table()
            QMessageBox.information(self, "SMS Sent", f"Receipt SMS sent successfully to {phone}!\n\n{msg}")
        else:
            QMessageBox.warning(self, "SMS Failed", f"Could not send SMS: {msg}")

    def _reprint_selected(self):
        inv = self._get_selected_invoice()
        if not inv:
            return
        dlg = ReprintReceiptDialog(inv, self.tenant, self.cashier, self, theme_mode=self.theme_mode)
        dlg.exec()

    def _edit_selected(self):
        inv = self._get_selected_invoice()
        if not inv:
            return

        bill_no = inv.get("bill_no", "")
        res = QMessageBox.question(
            self,
            "Edit Past Bill",
            f"Are you sure you want to load Bill {bill_no} back into the billing table for editing?\n\n"
            f"• Stock deductions for this bill will be safely credited back.\n"
            f"• You can adjust items, quantities, or discounts and re-finalize [F5].\n\n"
            f"Proceed with editing?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if res == QMessageBox.StandardButton.Yes:
            # Revert stock and prepare for edit in DB
            prepared = self.db.prepare_invoice_for_edit(bill_no)
            if prepared:
                self.edit_bill_requested.emit(prepared)
                self.accept()
            else:
                QMessageBox.critical(self, "Error", f"Failed to prepare Bill {bill_no} for editing.")

    def _void_selected(self):
        inv = self._get_selected_invoice()
        if not inv:
            return

        bill_no = inv.get("bill_no", "")
        res = QMessageBox.warning(
            self,
            "Void Past Bill",
            f"Are you sure you want to completely VOID Bill {bill_no}?\n\n"
            f"• This will restore product stock back to inventory.\n"
            f"• The invoice will be permanently removed from today's list.\n\n"
            f"Confirm Voiding?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if res == QMessageBox.StandardButton.Yes:
            # Prepare for edit deletes it and restores stock
            self.db.prepare_invoice_for_edit(bill_no)
            QMessageBox.information(self, "Bill Voided", f"Bill {bill_no} was voided and stock restored.")
            self.load_data()

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._reprint_selected()
            return
        super().keyPressEvent(event)
