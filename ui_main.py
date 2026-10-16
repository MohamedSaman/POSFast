"""
ui_main.py - Main POS Window & Layout for FastPOS Premium.
Features modern dark slate UI, top bar status badges, global search [F2],
sub-header with customer selector [F8], 72%/28% split layout, huge grand total display,
offline storage widget, checkout modal, bill hold/recall, and operator F-key footer bar.
"""

from decimal import Decimal
from datetime import datetime
from typing import Optional, Dict, Any, List
import json
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QFrame, QSplitter, QDialog, 
    QMessageBox, QListWidget, QListWidgetItem, QDialogButtonBox,
    QCheckBox, QGridLayout, QSizePolicy, QApplication, QScrollArea
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QEvent
from PyQt6.QtGui import QFont, QIcon, QKeyEvent, QColor

from database import DatabaseManager
from sync_worker import SyncWorker
from ui_table import POSBillingTable, COL_NAME, COL_QTY
from ui_settings import SettingsDialog
from ui_sales_list import SalesListDialog, ReprintReceiptDialog, format_thermal_receipt
from theme import get_theme_tokens, apply_theme_to_app
from sms_service import FastPOSSmsService, AsyncSmsWorker, is_valid_phone, normalize_phone_number


class CheckoutDialog(QDialog):
    """Payment & Print modal triggered by [F5] or Double-Enter on empty row."""
    def __init__(self, grand_total: Decimal, default_method: str = "CASH", theme_mode: str = "dark", parent=None, customer_name: str = "Walk-In", customer_phone: str = "", auto_sms_enabled: bool = True):
        super().__init__(parent)
        self.grand_total = grand_total
        self.payment_method = default_method
        self.paid_amount = grand_total
        self.due_amount = Decimal('0.00')
        self.change_amount = Decimal('0.00')
        self.theme_mode = theme_mode or "dark"
        self.theme = get_theme_tokens(self.theme_mode)
        self.customer_name = customer_name or "Walk-In"
        self.customer_phone = customer_phone or ""
        self.auto_sms_enabled = auto_sms_enabled
        self.send_sms = False

        self.setWindowTitle("Checkout & Payment (F5)")
        self.setFixedSize(520, 600)
        self.setModal(True)
        self.init_ui()

    def init_ui(self):
        t = get_theme_tokens(self.theme_mode)
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 22, 24, 22)

        # Header
        lbl_title = QLabel("💳 Finalize Bill & Print")
        lbl_title.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {t['text_heading']};")
        layout.addWidget(lbl_title)

        # Grand Total Card
        tot_card = QFrame()
        tot_card.setObjectName("checkoutTotCard")
        tot_card.setStyleSheet(f"""
            #checkoutTotCard {{
                background-color: {t['bg_card_inner']};
                border: 2px solid {t['success']};
                border-radius: 8px;
                padding: 12px;
            }}
            #checkoutTotCard QLabel {{
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }}
        """)
        tot_layout = QVBoxLayout(tot_card)
        tot_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl_tot_desc = QLabel("AMOUNT DUE")
        lbl_tot_desc.setStyleSheet(f"color: {t['text_muted']}; font-size: 13px; font-weight: bold;")
        self.lbl_grand_val = QLabel(f"Rs. {self.grand_total:.2f}")
        self.lbl_grand_val.setStyleSheet(f"color: {t['success']}; font-size: 36px; font-weight: bold; min-height: 44px;")
        tot_layout.addWidget(lbl_tot_desc, alignment=Qt.AlignmentFlag.AlignCenter)
        tot_layout.addWidget(self.lbl_grand_val, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(tot_card)

        # Customer Name & Phone Fields
        cust_row = QHBoxLayout()
        cust_row.setSpacing(10)

        cname_col = QVBoxLayout()
        cname_col.setSpacing(3)
        lbl_cn = QLabel("Customer Name:")
        lbl_cn.setStyleSheet(f"color: {t['text_muted']}; font-size: 11px; font-weight: bold;")
        self.txt_cust_name = QLineEdit(self.customer_name)
        self.txt_cust_name.setPlaceholderText("Walk-In")
        cname_col.addWidget(lbl_cn)
        cname_col.addWidget(self.txt_cust_name)

        cphone_col = QVBoxLayout()
        cphone_col.setSpacing(3)
        lbl_cp = QLabel("Mobile Number (SMS):")
        lbl_cp.setStyleSheet(f"color: {t['text_muted']}; font-size: 11px; font-weight: bold;")
        self.txt_cust_phone = QLineEdit(self.customer_phone)
        self.txt_cust_phone.setPlaceholderText("07XXXXXXXX")
        cphone_col.addWidget(lbl_cp)
        cphone_col.addWidget(self.txt_cust_phone)

        cust_row.addLayout(cname_col, 3)
        cust_row.addLayout(cphone_col, 2)
        layout.addLayout(cust_row)

        # Payment Method Selector
        method_layout = QHBoxLayout()
        self.btn_cash = QPushButton("💵 CASH")
        self.btn_card = QPushButton("💳 CARD")
        self.btn_transfer = QPushButton("🏦 TRANSFER")

        self.methods = ["CASH", "CARD", "TRANSFER"]
        self.method_buttons = [self.btn_cash, self.btn_card, self.btn_transfer]

        for b in self.method_buttons:
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedHeight(42)
            if self.theme_mode == "light":
                b.setStyleSheet("""
                    QPushButton {
                        background-color: #f1f5f9;
                        color: #1e293b;
                        border: 1px solid #cbd5e1;
                        border-radius: 6px;
                        font-weight: 600;
                        font-size: 13px;
                    }
                    QPushButton:focus {
                        border: 2px solid #0284c7;
                        background-color: #e2e8f0;
                    }
                    QPushButton:checked {
                        background-color: #0284c7;
                        color: #ffffff;
                        border: 2px solid #0284c7;
                        font-weight: bold;
                    }
                """)
            else:
                b.setStyleSheet("""
                    QPushButton {
                        background-color: #2d3748;
                        color: #e2e8f0;
                        border: 1px solid #4a5568;
                        border-radius: 6px;
                        font-weight: 600;
                        font-size: 13px;
                    }
                    QPushButton:focus {
                        border: 2px solid #00e5ff;
                        background-color: #374151;
                    }
                    QPushButton:checked {
                        background-color: #00e5ff;
                        color: #0f172a;
                        border: 2px solid #00e5ff;
                        font-weight: bold;
                    }
                """)
            b.setCheckable(True)
            b.installEventFilter(self)
            method_layout.addWidget(b)

        self.btn_cash.clicked.connect(lambda: self.set_method("CASH"))
        self.btn_card.clicked.connect(lambda: self.set_method("CARD"))
        self.btn_transfer.clicked.connect(lambda: self.set_method("TRANSFER"))

        layout.addLayout(method_layout)

        # Cash Tendered & Change Row
        form_layout = QGridLayout()

        lbl_paid = QLabel("Amount Tendered (Rs.):")
        lbl_paid.setStyleSheet(f"color: {t['text_primary']}; font-size: 14px; font-weight: 600;")
        self.txt_paid = QLineEdit(f"{self.grand_total:.2f}")
        self.txt_paid.setStyleSheet(f"""
            QLineEdit {{
                background-color: {t['bg_input']};
                color: {t['text_primary']};
                border: 2px solid {t['accent']};
                border-radius: 6px;
                padding: 8px;
                font-size: 18px;
                font-weight: bold;
            }}
        """)
        self.txt_paid.textChanged.connect(self.calculate_change)
        self.txt_paid.installEventFilter(self)
        self.txt_paid.returnPressed.connect(self.confirm_payment)
        form_layout.addWidget(lbl_paid, 0, 0)
        form_layout.addWidget(self.txt_paid, 0, 1)

        # Quick cash & credit buttons layout
        self.quick_layout = QHBoxLayout()
        form_layout.addLayout(self.quick_layout, 1, 1)

        # Change Due / Balance Due Display
        self.lbl_change_title = QLabel("Change Due (Rs.):")
        self.lbl_change_title.setStyleSheet(f"color: {t['text_primary']}; font-size: 14px; font-weight: 600;")
        self.lbl_change_val = QLabel("Rs. 0.00")
        self.lbl_change_val.setStyleSheet(f"color: {t['accent']}; font-size: 20px; font-weight: bold;")
        form_layout.addWidget(self.lbl_change_title, 2, 0)
        form_layout.addWidget(self.lbl_change_val, 2, 1)

        layout.addLayout(form_layout)

        # Print Receipt Checkbox
        self.chk_print = QCheckBox("Direct Thermal Print Receipt (ESC/POS 80mm)")
        self.chk_print.setChecked(True)
        self.chk_print.setStyleSheet(f"color: {t['text_secondary']}; font-size: 13px;")
        layout.addWidget(self.chk_print)

        # SMS Notification Checkbox
        self.chk_sms = QCheckBox("📱 Auto-Send SMS Bill to Customer Phone")
        is_phone_ok = is_valid_phone(self.customer_phone)
        self.chk_sms.setChecked(self.auto_sms_enabled and is_phone_ok)
        self.chk_sms.setStyleSheet(f"color: {t['text_primary']}; font-size: 13px; font-weight: 600;")
        layout.addWidget(self.chk_sms)

        def _on_phone_changed(text):
            if self.auto_sms_enabled:
                self.chk_sms.setChecked(is_valid_phone(text))
        self.txt_cust_phone.textChanged.connect(_on_phone_changed)

        layout.addStretch()

        # Action Buttons
        btn_box = QHBoxLayout()
        self.btn_cancel = QPushButton("Cancel (Esc)")
        self.btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['btn_default_bg']};
                color: {t['btn_default_fg']};
                padding: 10px 20px;
                border-radius: 6px;
                font-weight: 600;
                border: 1px solid {t['border']};
            }}
            QPushButton:hover {{
                background-color: {t['border']};
            }}
        """)
        self.btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(self.btn_cancel)

        self.btn_confirm = QPushButton("✓ PAY & PRINT [Enter]")
        self.btn_confirm.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_confirm.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['success']};
                color: #ffffff;
                padding: 12px 28px;
                border-radius: 6px;
                font-size: 15px;
                font-weight: bold;
                border: none;
            }}
            QPushButton:hover {{
                background-color: {t['success_hover']};
            }}
        """)
        self.btn_confirm.clicked.connect(self.confirm_payment)
        btn_box.addWidget(self.btn_confirm)

        layout.addLayout(btn_box)

        # Initialize method state and set initial focus directly on active payment method button
        self.set_method(self.payment_method)
        idx = self.methods.index(self.payment_method) if self.payment_method in self.methods else 0
        self.method_buttons[idx].setFocus()

    def showEvent(self, event):
        super().showEvent(event)
        idx = self.methods.index(self.payment_method) if self.payment_method in self.methods else 0
        QTimer.singleShot(10, lambda: self.method_buttons[idx].setFocus())

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()

            # When user is on payment method buttons
            if watched in self.method_buttons:
                if key in (Qt.Key.Key_Right, Qt.Key.Key_Tab):
                    cur_idx = self.methods.index(self.payment_method)
                    next_idx = (cur_idx + 1) % len(self.methods)
                    self.set_method(self.methods[next_idx])
                    self.method_buttons[next_idx].setFocus()
                    return True
                elif key in (Qt.Key.Key_Left, Qt.Key.Key_Backtab):
                    cur_idx = self.methods.index(self.payment_method)
                    prev_idx = (cur_idx - 1) % len(self.methods)
                    self.set_method(self.methods[prev_idx])
                    self.method_buttons[prev_idx].setFocus()
                    return True
                elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Down):
                    # Enter or Down Arrow confirms method and jumps to Amount Tendered
                    self.txt_paid.setFocus()
                    self.txt_paid.selectAll()
                    return True

            # When user is in Amount Tendered box
            elif watched == self.txt_paid:
                if key == Qt.Key.Key_Up:
                    # Up Arrow jumps back to Payment Methods
                    cur_idx = self.methods.index(self.payment_method)
                    self.method_buttons[cur_idx].setFocus()
                    return True
                elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    # Enter triggers Pay & Print
                    self.confirm_payment()
                    return True

        return super().eventFilter(watched, event)

    def _refresh_quick_buttons(self):
        if not hasattr(self, 'quick_layout'):
            return
        while self.quick_layout.count():
            item = self.quick_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        t = self.theme
        btn_style = f"""
            QPushButton {{
                background-color: {t['btn_default_bg']};
                color: {t['accent']};
                border: 1px solid {t['border']};
                border-radius: 4px;
                padding: 4px 6px;
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {t['border']};
            }}
        """
        exact_style = f"""
            QPushButton {{
                background-color: {t['btn_default_bg']};
                color: {t['success']};
                border: 1px solid {t['border']};
                border-radius: 4px;
                padding: 4px 6px;
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {t['border']};
            }}
        """
        zero_style = f"""
            QPushButton {{
                background-color: {t['btn_default_bg']};
                color: #ef4444;
                border: 1px solid {t['border']};
                border-radius: 4px;
                padding: 4px 6px;
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {t['border']};
            }}
        """

        # Exact button
        btn_exact = QPushButton("Exact")
        btn_exact.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_exact.setStyleSheet(exact_style)
        btn_exact.clicked.connect(lambda: self.set_quick_paid(float(self.grand_total)))
        self.quick_layout.addWidget(btn_exact)

        # Half (50%)
        half_val = round(float(self.grand_total) / 2.0, 2)
        btn_half = QPushButton("50%")
        btn_half.setToolTip(f"Pay half: Rs. {half_val:.2f}")
        btn_half.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_half.setStyleSheet(btn_style)
        btn_half.clicked.connect(lambda: self.set_quick_paid(half_val))
        self.quick_layout.addWidget(btn_half)

        # 0.00 (Due)
        btn_zero = QPushButton("Rs. 0 (Due)")
        btn_zero.setToolTip("Full balance due (Rs. 0 received)")
        btn_zero.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_zero.setStyleSheet(zero_style)
        btn_zero.clicked.connect(lambda: self.set_quick_paid(0.0))
        self.quick_layout.addWidget(btn_zero)

        # Standard round currency notes (up to 2 higher denominations)
        added = 0
        for amount in [100, 500, 1000, 2000, 5000]:
            if Decimal(str(amount)) >= self.grand_total and added < 2:
                qbtn = QPushButton(f"Rs. {amount}")
                qbtn.setCursor(Qt.CursorShape.PointingHandCursor)
                qbtn.setStyleSheet(btn_style)
                qbtn.clicked.connect(lambda _, val=amount: self.set_quick_paid(val))
                self.quick_layout.addWidget(qbtn)
                added += 1

    def set_method(self, method: str):
        self.payment_method = method
        self.btn_cash.setChecked(method == "CASH")
        self.btn_card.setChecked(method == "CARD")
        self.btn_transfer.setChecked(method == "TRANSFER")
        self._refresh_quick_buttons()
        self.calculate_change()

    def set_quick_paid(self, val: float):
        if hasattr(self, 'txt_paid'):
            self.txt_paid.setText(f"{val:.2f}")
            self.txt_paid.selectAll()

    def calculate_change(self):
        if not hasattr(self, 'txt_paid') or not hasattr(self, 'lbl_change_val') or not hasattr(self, 'lbl_change_title'):
            return
        t = self.theme
        try:
            paid_str = self.txt_paid.text().strip() or "0"
            tendered = Decimal(paid_str)
        except Exception:
            tendered = Decimal('0.00')

        if tendered < self.grand_total:
            # Auto Due: received money is less than amount to pay (e.g. charge 315, get 15 -> due 300)
            self.paid_amount = max(Decimal('0.00'), tendered)
            self.due_amount = self.grand_total - self.paid_amount
            self.change_amount = Decimal('0.00')
            self.lbl_change_title.setText("Balance Due (Rs.):")
            self.lbl_change_title.setStyleSheet("color: #ef4444; font-size: 14px; font-weight: bold;")
            self.lbl_change_val.setText(f"Rs. {self.due_amount:.2f}")
            self.lbl_change_val.setStyleSheet("color: #ef4444; font-size: 22px; font-weight: bold;")
        else:
            # Full or overpaid: change is due
            self.paid_amount = self.grand_total
            self.due_amount = Decimal('0.00')
            self.change_amount = tendered - self.grand_total
            self.lbl_change_title.setText("Change Due (Rs.):")
            self.lbl_change_title.setStyleSheet(f"color: {t['text_primary']}; font-size: 14px; font-weight: 600;")
            self.lbl_change_val.setText(f"Rs. {self.change_amount:.2f}")
            self.lbl_change_val.setStyleSheet(f"color: {t['accent']}; font-size: 20px; font-weight: bold;")

    def confirm_payment(self):
        self.calculate_change()
        cust_name = self.txt_cust_name.text().strip()
        if self.due_amount > 0:
            if not cust_name or cust_name.lower() in ("walk-in", "walk in", "walking"):
                QMessageBox.warning(
                    self, 
                    "Customer Name Required", 
                    f"There is a Balance Due of Rs. {self.due_amount:.2f}.\n\nPlease enter Customer Name (and Mobile Number) to track who owes this balance."
                )
                self.txt_cust_name.setFocus()
                self.txt_cust_name.selectAll()
                return

        self.customer_name = cust_name or "Walk-In"
        self.customer_phone = self.txt_cust_phone.text().strip()
        self.send_sms = self.chk_sms.isChecked() and is_valid_phone(self.customer_phone)
        self.accept()

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.reject()
            return

        if not self.txt_paid.hasFocus():
            if key in (Qt.Key.Key_Right, Qt.Key.Key_Tab):
                cur_idx = self.methods.index(self.payment_method)
                next_idx = (cur_idx + 1) % len(self.methods)
                self.set_method(self.methods[next_idx])
                self.method_buttons[next_idx].setFocus()
                return
            elif key in (Qt.Key.Key_Left, Qt.Key.Key_Backtab):
                cur_idx = self.methods.index(self.payment_method)
                prev_idx = (cur_idx - 1) % len(self.methods)
                self.set_method(self.methods[prev_idx])
                self.method_buttons[prev_idx].setFocus()
                return
            elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Down):
                self.txt_paid.setFocus()
                self.txt_paid.selectAll()
                return
        else:
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.confirm_payment()
                return
            elif key == Qt.Key.Key_Up:
                cur_idx = self.methods.index(self.payment_method)
                self.method_buttons[cur_idx].setFocus()
                return
        super().keyPressEvent(event)


class RecallBillsDialog(QDialog):
    """Lists parked bills for cashier recall (F4)."""
    bill_recalled = pyqtSignal(dict)

    def __init__(self, db: DatabaseManager, theme_mode: str = "dark", parent=None):
        super().__init__(parent)
        self.db = db
        self.theme_mode = theme_mode or "dark"
        self.setWindowTitle("Recall Parked Bills (F4)")
        self.setFixedSize(560, 430)
        self.setModal(True)
        self.init_ui()

    def init_ui(self):
        t = get_theme_tokens(self.theme_mode)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        lbl = QLabel("Parked / Held Bills Waiting for Recall:")
        lbl.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {t['text_heading']};")
        layout.addWidget(lbl)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background-color: {t['bg_card']};
                border: 1px solid {t['border']};
                border-radius: 6px;
                color: {t['text_primary']};
                font-size: 13px;
                padding: 6px;
            }}
            QListWidget::item {{
                padding: 10px;
                border-bottom: 1px solid {t['border_subtle']};
                border-radius: 4px;
            }}
            QListWidget::item:selected {{
                background-color: {t['accent']};
                color: {'#0f172a' if self.theme_mode == 'dark' else '#ffffff'};
                font-weight: bold;
            }}
        """)
        layout.addWidget(self.list_widget)

        self.load_bills()

        btn_box = QHBoxLayout()
        self.btn_recall = QPushButton("Restore Bill to Grid")
        self.btn_recall.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['success']};
                color: white;
                font-weight: bold;
                padding: 8px 18px;
                border-radius: 6px;
                border: none;
            }}
            QPushButton:hover {{
                background-color: {t['success_hover']};
            }}
        """)
        self.btn_recall.clicked.connect(self.do_recall)
        btn_box.addWidget(self.btn_recall)

        self.btn_delete = QPushButton("Delete Held Bill")
        self.btn_delete.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['danger']};
                color: white;
                font-weight: bold;
                padding: 8px 18px;
                border-radius: 6px;
                border: none;
            }}
        """)
        self.btn_delete.clicked.connect(self.do_delete)
        btn_box.addWidget(self.btn_delete)

        self.btn_close = QPushButton("Close")
        self.btn_close.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['btn_default_bg']};
                color: {t['btn_default_fg']};
                padding: 8px 18px;
                border-radius: 6px;
                border: 1px solid {t['border']};
            }}
        """)
        self.btn_close.clicked.connect(self.reject)
        btn_box.addWidget(self.btn_close)

        layout.addLayout(btn_box)

    def load_bills(self):
        self.list_widget.clear()
        bills = self.db.get_held_bills()
        if not bills:
            item = QListWidgetItem("No parked bills found.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list_widget.addItem(item)
            return

        for b in bills:
            item_count = len(b.get("items", []))
            text = f"Bill {b['bill_no']} | Customer: {b.get('customer_name', 'Walk-In')} | {item_count} items | Rs. {b['grand_total']:.2f} ({b['created_at']})"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, b)
            self.list_widget.addItem(item)

    def do_recall(self):
        curr = self.list_widget.currentItem()
        if not curr:
            return
        data = curr.data(Qt.ItemDataRole.UserRole)
        if data:
            self.db.delete_held_bill(data["id"])
            self.bill_recalled.emit(data)
            self.accept()

    def do_delete(self):
        curr = self.list_widget.currentItem()
        if not curr:
            return
        data = curr.data(Qt.ItemDataRole.UserRole)
        if data:
            self.db.delete_held_bill(data["id"])
            self.load_bills()


class BillTab:
    """Represents an active multi-bill tab session for concurrent billing."""
    def __init__(self, tab_id: int, bill_no: str, customer_name: str = "Walk-In", customer_phone: str = "", payment_method: str = "CASH"):
        self.tab_id = tab_id
        self.bill_no = bill_no
        self.customer_name = customer_name
        self.customer_phone = customer_phone
        self.payment_method = payment_method
        self.items: List[Dict[str, Any]] = []
        self.subtotal = Decimal('0.00')
        self.discount_total = Decimal('0.00')
        self.tax_total = Decimal('0.00')
        self.grand_total = Decimal('0.00')
        self.auto_discount_enabled = True


class BillTabWidget(QFrame):
    """Visual tab pill representing an open bill."""
    def __init__(self, index: int, tab: BillTab, is_active: bool, theme_tokens: dict, on_click, on_close, can_close: bool = True):
        super().__init__()
        self.index = index
        self.tab = tab
        self.is_active = is_active
        self.theme_tokens = theme_tokens
        self.on_click = on_click
        self.on_close = on_close
        self.can_close = can_close
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.init_ui()

    def init_ui(self):
        t = self.theme_tokens
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(6)

        # Tab Icon
        icon_str = "🟢" if self.is_active else "🧾"
        lbl_icon = QLabel(icon_str)
        lbl_icon.setStyleSheet("background: transparent; border: none; font-size: 11px;")
        layout.addWidget(lbl_icon)

        # Text label
        cust = self.tab.customer_name if self.tab.customer_name else "Walk-In"
        if len(cust) > 13:
            cust = cust[:11] + ".."

        tot_text = f"Rs. {self.tab.grand_total:.2f}" if self.tab.grand_total > 0 else "Empty"
        item_cnt = len(self.tab.items)
        cnt_text = f" ({item_cnt})" if item_cnt > 0 else ""

        self.lbl_text = QLabel(f"<b>Bill {self.index + 1}:</b> {cust} • {tot_text}{cnt_text}")
        self.lbl_text.setStyleSheet("background: transparent; border: none; font-size: 12px;")
        layout.addWidget(self.lbl_text)

        # Close button
        if self.can_close:
            self.btn_close = QPushButton("✕")
            self.btn_close.setFixedSize(18, 18)
            self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_close.setToolTip(f"Close Bill {self.index + 1} Tab")
            self.btn_close.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {t['text_muted']};
                    border: none;
                    border-radius: 9px;
                    font-size: 11px;
                    font-weight: bold;
                    padding: 0px;
                }}
                QPushButton:hover {{
                    background-color: {t['danger_bg']};
                    color: {t['danger']};
                }}
            """)
            self.btn_close.clicked.connect(lambda: self.on_close(self.index))
            layout.addWidget(self.btn_close)

        # Styling
        obj_name = f"tabPill_{self.index}"
        self.setObjectName(obj_name)
        mode = t.get("name", "dark")
        if self.is_active:
            bg_color = t['accent_bg'] if mode == 'dark' else '#e0f2fe'
            border_color = t['accent'] if mode == 'dark' else '#0284c7'
            text_color = t['accent'] if mode == 'dark' else '#0369a1'
            self.setStyleSheet(f"""
                #{obj_name} {{
                    background-color: {bg_color};
                    border: 2px solid {border_color};
                    border-radius: 6px;
                }}
                #{obj_name} QLabel {{
                    color: {text_color};
                    background: transparent;
                    border: none;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                #{obj_name} {{
                    background-color: {t['bg_card']};
                    border: 1px solid {t['border']};
                    border-radius: 6px;
                }}
                #{obj_name}:hover {{
                    background-color: {t['border_subtle']};
                    border-color: {t['accent']};
                }}
                #{obj_name} QLabel {{
                    color: {t['text_secondary']};
                    background: transparent;
                    border: none;
                }}
            """)

    def update_summary(self, tab: BillTab):
        self.tab = tab
        cust = tab.customer_name if tab.customer_name else "Walk-In"
        if len(cust) > 13:
            cust = cust[:11] + ".."
        tot_text = f"Rs. {tab.grand_total:.2f}" if tab.grand_total > 0 else "Empty"
        item_cnt = len(tab.items)
        cnt_text = f" ({item_cnt})" if item_cnt > 0 else ""
        self.lbl_text.setText(f"<b>Bill {self.index + 1}:</b> {cust} • {tot_text}{cnt_text}")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if hasattr(self, 'btn_close') and self.btn_close.geometry().contains(event.pos()):
                super().mousePressEvent(event)
                return
            self.on_click(self.index)
        super().mousePressEvent(event)


class MainWindow(QMainWindow):
    """Main Point-of-Sale Billing Terminal Window with Multi-Bill Tabs support."""

    def __init__(self, db: DatabaseManager, sync_worker: SyncWorker, initial_theme: str = "dark"):
        super().__init__()
        self.db = db
        self.sync_worker = sync_worker
        self.current_theme = initial_theme or self.db.get_setting("theme", "dark")
        self._is_online = False
        self._pending_count = 0
        self.footer_buttons = []

        self.current_bill_no = self.db.get_next_bill_number()
        self.current_customer = "Walk-In"
        self.current_customer_phone = ""
        self.current_payment_method = "CASH"
        self.subtotal = Decimal('0.00')
        self.discount_total = Decimal('0.00')
        self.tax_total = Decimal('0.00')
        self.grand_total = Decimal('0.00')

        # Multi-Bill Tabs state
        self.tabs: List[BillTab] = []
        self.active_tab_idx: int = 0
        self.next_tab_counter: int = 1
        self.tab_widgets: List[BillTabWidget] = []

        initial_tab = BillTab(
            tab_id=self.next_tab_counter,
            bill_no=self.current_bill_no,
            customer_name=self.current_customer,
            customer_phone=self.current_customer_phone,
            payment_method=self.current_payment_method
        )
        self.tabs.append(initial_tab)

        self.setWindowTitle("FastPOS Premium - Multi-Tenant Offline Point of Sale")
        self.setMinimumSize(1280, 800)
        self.init_ui()
        self.setup_clock_timer()
        self.setup_sync_connections()

    def _update_customer_button(self):
        if not hasattr(self, "btn_customer"):
            return
        if getattr(self, "current_customer_phone", ""):
            self.btn_customer.setText(f"Customer: {self.current_customer} ({self.current_customer_phone}) (F8)")
        else:
            self.btn_customer.setText(f"Customer: {self.current_customer} (F8)")

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(14, 12, 14, 12)
        main_layout.setSpacing(10)

        # 1. Top Bar
        main_layout.addWidget(self._create_top_bar())

        # 2. Sub-Header
        main_layout.addWidget(self._create_sub_header())

        # 2.5 Multi-Bill Tabs Bar
        main_layout.addWidget(self._create_bill_tabs_bar())

        # 3. Center Area (Splitter 72% / 28%)
        center_widget = self._create_center_area()
        main_layout.addWidget(center_widget, stretch=1)

        # 4. Operator Quick Keys Footer Bar
        main_layout.addWidget(self._create_footer_bar())

        # Apply initial theme tokens across widgets
        self.apply_theme(self.current_theme)

        # Initialize billing table with one empty row if not already populated
        if self.table.rowCount() == 0:
            self.table.add_blank_row()
        QTimer.singleShot(100, lambda: self.table.focus_cell(0, COL_NAME, edit=True))
        self._render_bill_tabs()

    def toggle_theme(self):
        """Switches between Dark and Light mode instantly."""
        new_theme = "light" if self.current_theme == "dark" else "dark"
        self.apply_theme(new_theme)
        self.db.set_setting("theme", new_theme)
        mode_text = "Light Mode ☀️" if new_theme == "light" else "Dark Mode 🌙"
        self.show_status_bar_message(f"Switched theme to {mode_text}")

    def apply_theme(self, mode: str):
        """Applies comprehensive Dark or Light theme across all UI components."""
        self.current_theme = mode
        t = get_theme_tokens(mode)
        app = QApplication.instance()
        if app:
            apply_theme_to_app(app, mode)

        if hasattr(self, 'table') and self.table:
            self.table.apply_theme(mode)

        # Theme Toggle button style & label
        if hasattr(self, 'btn_theme_toggle'):
            if mode == "dark":
                self.btn_theme_toggle.setText("☀️ Light Mode")
                self.btn_theme_toggle.setToolTip("Switch to Clean Light Theme")
                self.btn_theme_toggle.setStyleSheet("""
                    QPushButton {
                        background-color: #2b394a;
                        color: #ffd166;
                        border: 1px solid #ffd166;
                        border-radius: 6px;
                        padding: 4px 12px;
                        font-weight: bold;
                        font-size: 12px;
                    }
                    QPushButton:hover {
                        background-color: #ffd166;
                        color: #1e242b;
                    }
                """)
            else:
                self.btn_theme_toggle.setText("🌙 Dark Mode")
                self.btn_theme_toggle.setToolTip("Switch to Sleek Dark Slate Theme")
                self.btn_theme_toggle.setStyleSheet("""
                    QPushButton {
                        background-color: #1e293b;
                        color: #38bdf8;
                        border: 1px solid #0284c7;
                        border-radius: 6px;
                        padding: 4px 12px;
                        font-weight: bold;
                        font-size: 12px;
                    }
                    QPushButton:hover {
                        background-color: #0284c7;
                        color: #ffffff;
                    }
                """)

        # Top Bar
        if hasattr(self, 'top_bar'):
            self.top_bar.setStyleSheet(f"""
                #topBar {{
                    background-color: {t['bg_card']};
                    border: 1px solid {t['border']};
                    border-radius: 8px;
                    padding: 6px 14px;
                }}
                #topBar QLabel {{
                    background: transparent;
                    border: none;
                }}
            """)

        if hasattr(self, 'lbl_logo'):
            self.lbl_logo.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {t['text_primary']};")

        if hasattr(self, 'txt_global_search'):
            self.txt_global_search.setStyleSheet(f"""
                QLineEdit {{
                    background-color: {t['bg_input']};
                    color: {t['text_primary']};
                    border: 1px solid {t['border']};
                    border-radius: 6px;
                    padding: 6px 10px;
                    font-size: 13px;
                }}
                QLineEdit:focus {{
                    border: 1px solid {t['border_focus']};
                }}
            """)

        # Sub Header
        if hasattr(self, 'sub_header'):
            self.sub_header.setStyleSheet(f"""
                #subHeader {{
                    background-color: {t['bg_card']};
                    border: 1px solid {t['border']};
                    border-radius: 8px;
                    padding: 6px 14px;
                }}
                #subHeader QLabel {{
                    background: transparent;
                    border: none;
                }}
            """)

        if hasattr(self, 'lbl_bill_no'):
            self.lbl_bill_no.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {t['accent']};")

        if hasattr(self, 'lbl_datetime'):
            self.lbl_datetime.setStyleSheet(f"font-size: 13px; color: {t['text_secondary']};")

        if hasattr(self, 'lbl_cashier'):
            self.lbl_cashier.setStyleSheet(f"font-size: 13px; color: {t['text_secondary']};")

        if hasattr(self, 'btn_customer'):
            self.btn_customer.setStyleSheet(f"""
                QPushButton {{
                    background-color: {t['btn_default_bg']};
                    color: {t['btn_default_fg']};
                    border: 1px solid {t['border']};
                    border-radius: 6px;
                    padding: 6px 12px;
                    font-size: 13px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    border-color: {t['accent']};
                    color: {t['accent']};
                }}
            """)

        # Left Panel Card
        if hasattr(self, 'left_panel'):
            self.left_panel.setStyleSheet(f"""
                #leftPanelCard {{
                    background-color: {t['bg_card']};
                    border: 1px solid {t['border']};
                    border-radius: 8px;
                }}
                #leftPanelCard QLabel {{
                    background: transparent;
                    border: none;
                }}
            """)

        if hasattr(self, 'lbl_table_header'):
            self.lbl_table_header.setStyleSheet(f"color: {t['text_muted']}; font-size: 13px; font-weight: bold;")

        if hasattr(self, 'lbl_table_hint'):
            self.lbl_table_hint.setStyleSheet(f"color: {t['text_muted']}; font-size: 11px; font-style: italic;")

        # Total Card
        if hasattr(self, 'total_card'):
            self.total_card.setStyleSheet(f"""
                #totalCard {{
                    background-color: {t['bg_card']};
                    border: 1px solid {t['border']};
                    border-radius: 8px;
                    padding: 14px;
                }}
                #totalCard QLabel {{
                    background: transparent;
                    border: none;
                }}
            """)

        if hasattr(self, 'lbl_gt_title'):
            self.lbl_gt_title.setStyleSheet(f"color: {t['text_muted']}; font-size: 13px; font-weight: bold;")

        if hasattr(self, 'lbl_grand_total'):
            self.lbl_grand_total.setStyleSheet(f"""
                font-size: 44px;
                font-weight: bold;
                color: {t['success']};
                min-height: 54px;
                background: transparent;
                border: none;
            """)

        if hasattr(self, 'sep_line'):
            self.sep_line.setStyleSheet(f"color: {t['border']};")

        if hasattr(self, 'lbl_sub'):
            self.lbl_sub.setStyleSheet(f"color: {t['text_secondary']}; font-size: 14px;")
        if hasattr(self, 'lbl_subtotal_val'):
            self.lbl_subtotal_val.setStyleSheet(f"color: {t['text_primary']}; font-size: 14px; font-weight: bold;")

        if hasattr(self, 'lbl_disc'):
            self.lbl_disc.setStyleSheet(f"color: {t['text_secondary']}; font-size: 14px;")
        if hasattr(self, 'lbl_disc_val'):
            self.lbl_disc_val.setStyleSheet(f"color: {t['warning']}; font-size: 14px; font-weight: bold;")

        if hasattr(self, 'lbl_tax'):
            self.lbl_tax.setStyleSheet(f"color: {t['text_secondary']}; font-size: 14px;")
        if hasattr(self, 'lbl_tax_val'):
            self.lbl_tax_val.setStyleSheet(f"color: {t['text_primary']}; font-size: 14px; font-weight: bold;")

        if hasattr(self, 'btn_pay_toggle'):
            self.btn_pay_toggle.setStyleSheet(f"""
                QPushButton {{
                    background-color: {t['accent_bg']};
                    color: {t['accent']};
                    border: 1px solid {t['accent']};
                    border-radius: 6px;
                    padding: 10px;
                    font-size: 14px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {t['accent']};
                    color: {'#0f172a' if mode == 'dark' else '#ffffff'};
                }}
            """)

        # Storage Card
        if hasattr(self, 'storage_card'):
            self.storage_card.setStyleSheet(f"""
                #storageCard {{
                    background-color: {t['bg_card']};
                    border: 1px solid {t['border']};
                    border-radius: 8px;
                    padding: 14px;
                }}
                #storageCard QLabel {{
                    background: transparent;
                    border: none;
                }}
            """)

        if hasattr(self, 'lbl_sc_title'):
            self.lbl_sc_title.setStyleSheet(f"color: {t['text_muted']}; font-size: 12px; font-weight: bold;")

        if hasattr(self, 'lbl_pending_bills'):
            self.lbl_pending_bills.setStyleSheet(f"color: {t['text_primary']}; font-size: 16px; font-weight: bold;")

        if hasattr(self, 'lbl_sync_state'):
            self.lbl_sync_state.setStyleSheet(f"color: {t['text_muted']}; font-size: 13px;")

        if hasattr(self, 'btn_manual_sync'):
            self.btn_manual_sync.setStyleSheet(f"""
                QPushButton {{
                    background-color: {t['btn_default_bg']};
                    color: {t['accent']};
                    border: 1px solid {t['border']};
                    border-radius: 4px;
                    padding: 4px 10px;
                    font-size: 12px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {t['border']};
                }}
            """)

        # Multi-Bill Tabs Bar
        if hasattr(self, 'tabs_bar'):
            self.tabs_bar.setStyleSheet(f"""
                #billTabsBar {{
                    background-color: {t['bg_card']};
                    border: 1px solid {t['border']};
                    border-radius: 8px;
                    padding: 3px 6px;
                }}
            """)
        if hasattr(self, 'lbl_tabs_title'):
            self.lbl_tabs_title.setStyleSheet(f"color: {t['text_heading']}; font-size: 13px; font-weight: bold; background: transparent; border: none;")

        if hasattr(self, 'btn_new_tab'):
            self.btn_new_tab.setStyleSheet(f"""
                QPushButton {{
                    background-color: {t['accent_bg']};
                    color: {t['accent']};
                    border: 1px solid {t['accent']};
                    border-radius: 6px;
                    padding: 4px 12px;
                    font-size: 12px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {t['accent']};
                    color: {'#0f172a' if mode == 'dark' else '#ffffff'};
                }}
            """)

        # Footer Bar
        if hasattr(self, 'footer_bar'):
            self.footer_bar.setStyleSheet(f"""
                #footerBar {{
                    background-color: {t['bg_card']};
                    border: 1px solid {t['border']};
                    border-radius: 8px;
                    padding: 6px 10px;
                }}
            """)

        # Footer Buttons
        if hasattr(self, 'footer_buttons'):
            for btn, text in self.footer_buttons:
                if "[F5]" in text:
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            background-color: {t['success']};
                            color: #ffffff;
                            border: 2px solid {t['success']};
                            border-radius: 6px;
                            font-size: 14px;
                            font-weight: bold;
                        }}
                        QPushButton:hover {{
                            background-color: {t['success_hover']};
                        }}
                    """)
                elif "[F3]" in text:
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            background-color: {t['accent_bg']};
                            color: {t['accent']};
                            border: 1px solid {t['accent']};
                            border-radius: 6px;
                            font-size: 13px;
                            font-weight: bold;
                        }}
                        QPushButton:hover {{
                            background-color: {t['accent']};
                            color: {'#0f172a' if mode == 'dark' else '#ffffff'};
                        }}
                    """)
                elif "[F6]" in text:
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            background-color: #2563eb;
                            color: #ffffff;
                            border: 1px solid #1d4ed8;
                            border-radius: 6px;
                            font-size: 13px;
                            font-weight: bold;
                        }}
                        QPushButton:hover {{
                            background-color: #1d4ed8;
                        }}
                    """)
                elif "[F12]" in text:
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            background-color: {t['btn_default_bg']};
                            color: {t['accent']};
                            border: 1px solid {t['border']};
                            border-radius: 6px;
                            font-size: 13px;
                            font-weight: 600;
                        }}
                        QPushButton:hover {{
                            background-color: {t['border']};
                        }}
                    """)
                else:
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            background-color: {t['btn_default_bg']};
                            color: {t['btn_default_fg']};
                            border: 1px solid {t['border']};
                            border-radius: 6px;
                            font-size: 13px;
                            font-weight: 600;
                        }}
                        QPushButton:hover {{
                            background-color: {t['border']};
                        }}
                    """)

        self._update_auto_disc_button_style()
        self._refresh_status_badge()
        self._render_bill_tabs()

    # --- Top Bar ---
    def _create_top_bar(self) -> QWidget:
        self.top_bar = QFrame()
        self.top_bar.setObjectName("topBar")
        layout = QHBoxLayout(self.top_bar)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(16)

        # Logo / App Title
        self.lbl_logo = QLabel("🚀 FastPOS Premium")
        self.lbl_logo.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(self.lbl_logo)

        layout.addStretch()

        # Online / Offline Status Badge
        self.lbl_status_badge = QLabel("⚠️ OFFLINE MODE (Checking...)")
        self.lbl_status_badge.setObjectName("statusBadge")
        layout.addWidget(self.lbl_status_badge)

        layout.addStretch()

        # Theme Switcher Button
        self.btn_theme_toggle = QPushButton("☀️ Light Mode")
        self.btn_theme_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_theme_toggle.setFixedHeight(34)
        self.btn_theme_toggle.clicked.connect(self.toggle_theme)
        layout.addWidget(self.btn_theme_toggle)

        # Global Barcode / Product Search Box [F2]
        search_box = QHBoxLayout()
        search_box.setSpacing(6)
        lbl_search_icon = QLabel("🔍")

        self.txt_global_search = QLineEdit()
        self.txt_global_search.setPlaceholderText("[F2] Search Products / Scan Barcode...")
        self.txt_global_search.setFixedWidth(280)
        self.txt_global_search.returnPressed.connect(self._on_global_search_enter)

        search_box.addWidget(lbl_search_icon)
        search_box.addWidget(self.txt_global_search)
        layout.addLayout(search_box)

        return self.top_bar

    # --- Sub-Header ---
    def _create_sub_header(self) -> QWidget:
        self.sub_header = QFrame()
        self.sub_header.setObjectName("subHeader")
        layout = QHBoxLayout(self.sub_header)
        layout.setContentsMargins(14, 6, 14, 6)
        layout.setSpacing(24)

        # Bill Number
        self.lbl_bill_no = QLabel(f"Bill {self.current_bill_no}")
        layout.addWidget(self.lbl_bill_no)

        # Live Date & Time
        self.lbl_datetime = QLabel(datetime.now().strftime("Date: %d-%b-%Y  %H:%M:%S"))
        layout.addWidget(self.lbl_datetime)

        # Cashier Name
        cashier = self.db.get_setting("cashier_name", "Admin")
        self.lbl_cashier = QLabel(f"Cashier: {cashier}")
        layout.addWidget(self.lbl_cashier)

        layout.addStretch()

        # Customer Selector [F8]
        self.btn_customer = QPushButton(f"Customer: {self.current_customer} (F8)")
        self.btn_customer.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_customer.clicked.connect(self.prompt_customer)
        layout.addWidget(self.btn_customer)

        return self.sub_header

    # --- Multi-Bill Tabs System ---
    def _create_bill_tabs_bar(self) -> QWidget:
        self.tabs_bar = QFrame()
        self.tabs_bar.setObjectName("billTabsBar")
        layout = QHBoxLayout(self.tabs_bar)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(8)

        # Title
        self.lbl_tabs_title = QLabel("📑 Active Bills:")
        self.lbl_tabs_title.setObjectName("lblTabsTitle")
        self.lbl_tabs_title.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(self.lbl_tabs_title)

        # Container for tab pills
        self.tabs_inner_widget = QWidget()
        self.tabs_inner_widget.setObjectName("tabsInnerWidget")
        self.tabs_inner_widget.setStyleSheet("background: transparent; border: none;")
        self.tabs_layout = QHBoxLayout(self.tabs_inner_widget)
        self.tabs_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs_layout.setSpacing(8)
        self.tabs_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.tabs_inner_widget, stretch=1)

        # [➕ New Bill Tab (F3)]
        self.btn_new_tab = QPushButton("➕ New Bill (F3)")
        self.btn_new_tab.setObjectName("btnNewBillTab")
        self.btn_new_tab.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_new_tab.setFixedHeight(34)
        self.btn_new_tab.setToolTip("Open new bill tab to serve another customer concurrently (Hotkey: F3 / Ctrl+T)")
        self.btn_new_tab.clicked.connect(lambda: self.add_new_bill_tab())
        layout.addWidget(self.btn_new_tab)

        # [⏸️ Parked Bills (F4)]
        self.btn_quick_recall = QPushButton("⏸️ Parked (F4)")
        self.btn_quick_recall.setObjectName("btnQuickRecall")
        self.btn_quick_recall.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_quick_recall.setFixedHeight(34)
        self.btn_quick_recall.setToolTip("View & recall parked / held bills (Hotkey: F4)")
        self.btn_quick_recall.clicked.connect(self.recall_parked_bill)
        layout.addWidget(self.btn_quick_recall)

        return self.tabs_bar

    def _render_bill_tabs(self):
        """Re-renders all tab pills in the horizontal bar."""
        if not hasattr(self, 'tabs_layout'):
            return

        t = get_theme_tokens(self.current_theme)

        # Clear existing tab widgets safely
        self.tab_widgets = []
        while self.tabs_layout.count():
            item = self.tabs_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        can_close = len(self.tabs) > 1
        for i, tab in enumerate(self.tabs):
            is_active = (i == self.active_tab_idx)
            w = BillTabWidget(
                index=i,
                tab=tab,
                is_active=is_active,
                theme_tokens=t,
                on_click=self.switch_to_tab,
                on_close=self.close_bill_tab,
                can_close=can_close
            )
            self.tabs_layout.addWidget(w)
            self.tab_widgets.append(w)

        self.tabs_layout.addStretch()

        # Update Parked count badge
        if hasattr(self, 'btn_quick_recall'):
            try:
                held = self.db.get_held_bills()
                held_cnt = len(held)
                if held_cnt > 0:
                    self.btn_quick_recall.setText(f"⏸️ {held_cnt} Parked (F4)")
                    self.btn_quick_recall.setStyleSheet(f"""
                        QPushButton {{
                            background-color: {t['warning_bg']};
                            color: {t['warning']};
                            border: 1px solid {t['warning']};
                            border-radius: 6px;
                            font-weight: bold;
                            padding: 4px 12px;
                            font-size: 12px;
                        }}
                        QPushButton:hover {{
                            background-color: {t['warning']};
                            color: #000000;
                        }}
                    """)
                else:
                    self.btn_quick_recall.setText("⏸️ Parked (F4)")
                    self.btn_quick_recall.setStyleSheet(f"""
                        QPushButton {{
                            background-color: {t['btn_default_bg']};
                            color: {t['btn_default_fg']};
                            border: 1px solid {t['border']};
                            border-radius: 6px;
                            font-weight: 600;
                            padding: 4px 12px;
                            font-size: 12px;
                        }}
                        QPushButton:hover {{
                            background-color: {t['border']};
                        }}
                    """)
            except Exception:
                pass

    def _update_tab_summary_labels(self):
        """Updates text of the active tab without re-creating all widgets."""
        if hasattr(self, 'tab_widgets') and 0 <= self.active_tab_idx < len(self.tab_widgets):
            self.tab_widgets[self.active_tab_idx].update_summary(self.tabs[self.active_tab_idx])

    def _save_current_tab_state(self):
        """Saves current table items and metadata into active tab session."""
        if not hasattr(self, 'tabs') or not (0 <= self.active_tab_idx < len(self.tabs)):
            return
        tab = self.tabs[self.active_tab_idx]
        tab.bill_no = self.current_bill_no
        tab.customer_name = self.current_customer
        tab.customer_phone = self.current_customer_phone
        tab.payment_method = self.current_payment_method
        tab.subtotal = self.subtotal
        tab.discount_total = self.discount_total
        tab.tax_total = self.tax_total
        tab.grand_total = self.grand_total
        tab.auto_discount_enabled = getattr(self.table, 'auto_discount_enabled', True)
        tab.items = self.table.get_bill_items()

    def _load_tab_state(self, index: int):
        """Loads tab session state into UI controls and billing table."""
        if not hasattr(self, 'tabs') or not (0 <= index < len(self.tabs)):
            return
        self.active_tab_idx = index
        tab = self.tabs[index]
        self.current_bill_no = tab.bill_no
        self.lbl_bill_no.setText(f"Bill {self.current_bill_no}")
        self.current_customer = tab.customer_name
        self.current_customer_phone = tab.customer_phone
        self._update_customer_button()
        self.current_payment_method = tab.payment_method
        if hasattr(self, 'btn_pay_toggle'):
            self.btn_pay_toggle.setText(f"Payment: {self.current_payment_method} (F9)")

        self.table.auto_discount_enabled = tab.auto_discount_enabled
        self._update_auto_disc_button_style()

        if tab.items:
            self.table.load_items(tab.items)
        else:
            self.table.clear_bill()

        self._render_bill_tabs()

    def switch_to_tab(self, index: int):
        """Switches active view to target tab."""
        if index == self.active_tab_idx or not (0 <= index < len(self.tabs)):
            return
        self._save_current_tab_state()
        self._load_tab_state(index)
        self.show_status_bar_message(f"Switched to Bill Tab #{index + 1}: {self.current_customer} ({self.current_bill_no})")

    def switch_to_next_tab(self):
        """Cycles forward to the next open bill tab."""
        if len(self.tabs) <= 1:
            return
        next_idx = (self.active_tab_idx + 1) % len(self.tabs)
        self.switch_to_tab(next_idx)

    def switch_to_prev_tab(self):
        """Cycles backward to the previous open bill tab."""
        if len(self.tabs) <= 1:
            return
        prev_idx = (self.active_tab_idx - 1) % len(self.tabs)
        self.switch_to_tab(prev_idx)

    def add_new_bill_tab(self, bill_no: Optional[str] = None, customer_name: str = "Walk-In", customer_phone: str = "", items: Optional[list] = None):
        """Opens a new bill tab, allowing multiple customers to be billed simultaneously."""
        if len(self.tabs) >= 8:
            QMessageBox.warning(self, "Tabs Limit", "Maximum of 8 simultaneous bills can be open. Please finalize or close an existing tab.")
            return

        self._save_current_tab_state()

        self.next_tab_counter += 1
        new_bill_no = bill_no or self.db.get_next_bill_number()
        new_tab = BillTab(
            tab_id=self.next_tab_counter,
            bill_no=new_bill_no,
            customer_name=customer_name,
            customer_phone=customer_phone,
            payment_method="CASH"
        )
        if items:
            new_tab.items = items

        self.tabs.append(new_tab)
        new_idx = len(self.tabs) - 1
        self._load_tab_state(new_idx)
        self.show_status_bar_message(f"Opened New Bill Tab #{new_idx + 1} ({new_bill_no})")

    def close_bill_tab(self, index: int):
        """Closes a bill tab. Offers to Hold/Park the bill if items are present."""
        if not (0 <= index < len(self.tabs)):
            return

        if len(self.tabs) <= 1:
            if self.table.has_valid_items():
                reply = QMessageBox.question(
                    self, "Clear Bill", "Hold this bill before clearing?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel
                )
                if reply == QMessageBox.StandardButton.Cancel:
                    return
                elif reply == QMessageBox.StandardButton.Yes:
                    self.hold_current_bill()
                    return
            self.table.clear_bill()
            self.current_bill_no = self.db.get_next_bill_number()
            self.lbl_bill_no.setText(f"Bill {self.current_bill_no}")
            self.current_customer = "Walk-In"
            self.current_customer_phone = ""
            self._update_customer_button()
            self._save_current_tab_state()
            self._render_bill_tabs()
            return

        if index == self.active_tab_idx:
            self._save_current_tab_state()

        tab_to_close = self.tabs[index]
        if tab_to_close.items and len(tab_to_close.items) > 0:
            reply = QMessageBox.question(
                self, "Close Bill Tab",
                f"Bill Tab #{index + 1} ({tab_to_close.customer_name}) has {len(tab_to_close.items)} items.\n\n"
                "Would you like to Park / Hold this bill before closing?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return
            elif reply == QMessageBox.StandardButton.Yes:
                self.db.hold_bill(
                    tab_to_close.bill_no,
                    tab_to_close.customer_name,
                    tab_to_close.items,
                    float(tab_to_close.grand_total),
                    customer_phone=tab_to_close.customer_phone
                )
                self.show_status_bar_message(f"Bill {tab_to_close.bill_no} parked successfully.")

        del self.tabs[index]

        if index < self.active_tab_idx:
            new_idx = self.active_tab_idx - 1
        else:
            new_idx = min(self.active_tab_idx, len(self.tabs) - 1)

        self._load_tab_state(new_idx)

    # --- Center Area (Billing Table 72% + Summary Sidebar 28%) ---
    def _create_center_area(self) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Left 72%: Billing Table
        self.left_panel = QFrame()
        self.left_panel.setObjectName("leftPanelCard")
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(12, 10, 12, 10)
        left_layout.setSpacing(8)

        # Header bar above table with Auto-Discount Toggle
        table_hdr_box = QHBoxLayout()
        self.lbl_table_header = QLabel("ITEMS IN CURRENT BILL")
        table_hdr_box.addWidget(self.lbl_table_header)
        table_hdr_box.addStretch()

        self.table = POSBillingTable(self.db, theme_mode=self.current_theme, parent=self)
        self.table.totals_changed.connect(self.update_totals_display)
        self.table.request_checkout.connect(self.finalize_and_checkout)
        self.table.status_message.connect(self.show_status_bar_message)

        self.btn_auto_disc = QPushButton("⚡ Auto 10% Disc [ON]")
        self.btn_auto_disc.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_auto_disc.setToolTip("Click to toggle automatic 10% discount on sales")
        self.btn_auto_disc.clicked.connect(self._on_toggle_auto_discount)
        table_hdr_box.addWidget(self.btn_auto_disc)
        left_layout.addLayout(table_hdr_box)

        left_layout.addWidget(self.table)

        # Footer Hint under Table
        self.lbl_table_hint = QLabel("*[Enter] Navigates cells • [F7] Void Row • [F5] Checkout*")
        left_layout.addWidget(self.lbl_table_hint)

        layout.addWidget(self.left_panel, stretch=72)

        # Right 28%: Grand Total, Summary & Offline Storage
        right_panel = QVBoxLayout()
        right_panel.setSpacing(12)

        # 1. Top Card: Grand Total & Breakdown
        self.total_card = QFrame()
        self.total_card.setObjectName("totalCard")
        tc_layout = QVBoxLayout(self.total_card)
        tc_layout.setSpacing(10)

        self.lbl_gt_title = QLabel("GRAND TOTAL")
        self.lbl_gt_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tc_layout.addWidget(self.lbl_gt_title)

        self.lbl_grand_total = QLabel("Rs. 0.00")
        self.lbl_grand_total.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tc_layout.addWidget(self.lbl_grand_total)

        # Breakdown table lines
        self.sep_line = QFrame()
        self.sep_line.setFrameShape(QFrame.Shape.HLine)
        tc_layout.addWidget(self.sep_line)

        # Subtotal
        sub_box = QHBoxLayout()
        self.lbl_sub = QLabel("Subtotal:")
        self.lbl_subtotal_val = QLabel("Rs. 0.00")
        sub_box.addWidget(self.lbl_sub)
        sub_box.addStretch()
        sub_box.addWidget(self.lbl_subtotal_val)
        tc_layout.addLayout(sub_box)

        # Discount
        disc_box = QHBoxLayout()
        self.lbl_disc = QLabel("Discount:")
        self.lbl_disc_val = QLabel("Rs. 0.00")
        disc_box.addWidget(self.lbl_disc)
        disc_box.addStretch()
        disc_box.addWidget(self.lbl_disc_val)
        tc_layout.addLayout(disc_box)

        # Tax
        tax_box = QHBoxLayout()
        self.lbl_tax = QLabel("Tax/VAT:")
        self.lbl_tax_val = QLabel("Rs. 0.00")
        tax_box.addWidget(self.lbl_tax)
        tax_box.addStretch()
        tax_box.addWidget(self.lbl_tax_val)
        tc_layout.addLayout(tax_box)

        tc_layout.addSpacing(6)

        # Payment Method Toggle Button
        self.btn_pay_toggle = QPushButton(f"Payment: {self.current_payment_method} (F9)")
        self.btn_pay_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pay_toggle.clicked.connect(self.toggle_payment_method)
        tc_layout.addWidget(self.btn_pay_toggle)

        right_panel.addWidget(self.total_card)

        # 2. Bottom Card: Offline Storage Status
        self.storage_card = QFrame()
        self.storage_card.setObjectName("storageCard")
        sc_layout = QVBoxLayout(self.storage_card)
        sc_layout.setSpacing(8)

        self.lbl_sc_title = QLabel("OFFLINE STORAGE")
        sc_layout.addWidget(self.lbl_sc_title)

        self.lbl_pending_bills = QLabel("0 Offline Bills Pending")
        sc_layout.addWidget(self.lbl_pending_bills)

        sync_status_box = QHBoxLayout()
        self.lbl_sync_state = QLabel("Status: Checking... 🔄")
        sync_status_box.addWidget(self.lbl_sync_state)
        sync_status_box.addStretch()

        self.btn_manual_sync = QPushButton("Sync [F10]")
        self.btn_manual_sync.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_manual_sync.clicked.connect(self.trigger_manual_sync)
        sync_status_box.addWidget(self.btn_manual_sync)

        sc_layout.addLayout(sync_status_box)

        right_panel.addWidget(self.storage_card)
        right_panel.addStretch()

        layout.addLayout(right_panel, stretch=28)
        return container

    def _update_auto_disc_button_style(self):
        if not hasattr(self, 'btn_auto_disc'):
            return
        t = get_theme_tokens(self.current_theme)
        is_on = getattr(self.table, 'auto_discount_enabled', True)
        if is_on:
            self.btn_auto_disc.setText("⚡ Auto 10% Disc [ON]")
            self.btn_auto_disc.setStyleSheet(f"""
                QPushButton {{
                    background-color: {t['success_bg']};
                    color: {t['success']};
                    border: 1px solid {t['success']};
                    border-radius: 14px;
                    padding: 3px 10px;
                    font-size: 11px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {t['success']};
                    color: #ffffff;
                }}
            """)
        else:
            self.btn_auto_disc.setText("⚡ Auto 10% Disc [OFF]")
            self.btn_auto_disc.setStyleSheet(f"""
                QPushButton {{
                    background-color: {t['btn_default_bg']};
                    color: {t['text_muted']};
                    border: 1px solid {t['border']};
                    border-radius: 14px;
                    padding: 3px 10px;
                    font-size: 11px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {t['border']};
                    color: {t['text_primary']};
                }}
            """)

    def _on_toggle_auto_discount(self):
        is_on = self.table.toggle_auto_discount()
        self._update_auto_disc_button_style()
        status = "ENABLED (10% applied)" if is_on else "DISABLED (0% applied)"
        self.show_status_bar_message(f"Auto-Discount is now {status}.")

    # --- Bottom Footer Bar ---
    def _create_footer_bar(self) -> QWidget:
        self.footer_bar = QFrame()
        self.footer_bar.setObjectName("footerBar")
        layout = QHBoxLayout(self.footer_bar)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(10)

        # Buttons configuration
        btn_specs = [
            ("[F1] Help", self.show_help),
            ("[F3] New Bill Tab", self.new_bill),
            ("[F4] Hold/Recall", self.show_hold_recall_menu),
            ("[F5] PAY & PRINT 🖨️", self.finalize_and_checkout),
            ("[F6] Sales List 📋", self.open_sales_list),
            ("[F7] Void Row", self.void_current_row),
            ("[F12] Settings", self.open_settings),
        ]

        self.footer_buttons = []
        for text, handler in btn_specs:
            btn = QPushButton(text)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(42)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(handler)
            self.footer_buttons.append((btn, text))
            layout.addWidget(btn)

        return self.footer_bar

    # --- Live Clocks & Timers ---
    def setup_clock_timer(self):
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._update_clock)
        self.clock_timer.start(1000)

    def _update_clock(self):
        self.lbl_datetime.setText(datetime.now().strftime("Date: %d-%b-%Y  %H:%M:%S"))

    # --- Sync Worker Signal Connections ---
    def setup_sync_connections(self):
        if self.sync_worker:
            self.sync_worker.status_changed.connect(self.on_sync_status_changed)
            self.sync_worker.product_sync_completed.connect(self.on_product_sync_completed)

        # Initial check of pending count
        count = self.db.get_pending_invoice_count()
        self.update_pending_storage_display(count, is_online=False)

    def _refresh_status_badge(self):
        if not hasattr(self, 'lbl_status_badge'):
            return
        t = get_theme_tokens(self.current_theme)
        if getattr(self, '_is_online', False):
            self.lbl_status_badge.setText("🟢 ONLINE (Cloud Synced)")
            self.lbl_status_badge.setStyleSheet(f"""
                QLabel#statusBadge {{
                    background-color: {t['success_bg']};
                    color: {t['success']};
                    border: 1px solid {t['success']};
                    border-radius: 16px;
                    padding: 5px 14px;
                    font-size: 13px;
                    font-weight: bold;
                }}
            """)
        else:
            pending = getattr(self, '_pending_count', 0)
            self.lbl_status_badge.setText(f"⚠️ OFFLINE MODE ({pending} bills pending sync)")
            self.lbl_status_badge.setStyleSheet(f"""
                QLabel#statusBadge {{
                    background-color: {t['warning_bg']};
                    color: {t['warning']};
                    border: 1px solid {t['warning']};
                    border-radius: 16px;
                    padding: 5px 14px;
                    font-size: 13px;
                    font-weight: bold;
                }}
            """)

    def on_sync_status_changed(self, is_online: bool, pending_count: int, message: str):
        self._is_online = is_online
        self._pending_count = pending_count
        self.update_pending_storage_display(pending_count, is_online)
        self._refresh_status_badge()
        if is_online:
            self.lbl_sync_state.setText("Status: Connected 🟢")
        else:
            self.lbl_sync_state.setText("Status: Reconnecting... 🔄")

    def update_pending_storage_display(self, count: int, is_online: bool):
        self.lbl_pending_bills.setText(f"{count} Offline Bills Pending")

    def on_product_sync_completed(self, count: int, message: str):
        self.show_status_bar_message(f"Catalog Sync: {message}")

    def trigger_manual_sync(self):
        if self.sync_worker:
            self.sync_worker.request_immediate_sync(sync_products=True)
            self.show_status_bar_message("Sync triggered...")

    # --- Totals Calculation ---
    def update_totals_display(self, subtotal: Decimal, discount: Decimal, tax: Decimal, grand_total: Decimal):
        self.subtotal = subtotal
        self.discount_total = discount
        self.tax_total = tax
        self.grand_total = grand_total

        self.lbl_grand_total.setText(f"Rs. {grand_total:.2f}")
        self.lbl_subtotal_val.setText(f"Rs. {subtotal:.2f}")
        self.lbl_tax_val.setText(f"Rs. {tax:.2f}")
        self.lbl_disc_val.setText(f"Rs. {discount:.2f}")

        # Keep active tab in sync
        if hasattr(self, 'tabs') and 0 <= self.active_tab_idx < len(self.tabs):
            tab = self.tabs[self.active_tab_idx]
            tab.subtotal = subtotal
            tab.discount_total = discount
            tab.tax_total = tax
            tab.grand_total = grand_total
            tab.items = self.table.get_bill_items()
            self._update_tab_summary_labels()

    # --- Payment Toggle ---
    def toggle_payment_method(self):
        methods = ["CASH", "CARD", "TRANSFER"]
        idx = methods.index(self.current_payment_method) if self.current_payment_method in methods else 0
        self.current_payment_method = methods[(idx + 1) % len(methods)]
        self.btn_pay_toggle.setText(f"Payment: {self.current_payment_method} (F9)")
        if hasattr(self, 'tabs') and 0 <= self.active_tab_idx < len(self.tabs):
            self.tabs[self.active_tab_idx].payment_method = self.current_payment_method

    # --- Global Search [F2] ---
    def _on_global_search_enter(self):
        query = self.txt_global_search.text().strip()
        if not query:
            return

        prod = self.db.get_product_by_code(query)
        if not prod:
            results = self.db.search_products(query, limit=1)
            if results:
                prod = results[0]

        if prod:
            # Add to current empty row or create new row
            cur_row = self.table.rowCount() - 1
            if cur_row < 0:
                cur_row = self.table.add_blank_row()

            # If current row already has item, add a new one
            name_item = self.table.item(cur_row, COL_NAME)
            if name_item and name_item.text().strip():
                cur_row = self.table.add_blank_row()

            self.table.on_product_selected(cur_row, prod)
            self.txt_global_search.clear()
            QTimer.singleShot(30, self.txt_global_search.setFocus)
        else:
            self.show_status_bar_message(f"Product not found for: '{query}'")

    # --- Customer Prompt [F8] ---
    def prompt_customer(self):
        t = get_theme_tokens(self.current_theme)
        dialog = QDialog(self)
        dialog.setWindowTitle("Select / Add Customer (F8)")
        dialog.setFixedSize(420, 250)
        d_layout = QVBoxLayout(dialog)
        d_layout.setContentsMargins(22, 20, 22, 20)
        d_layout.setSpacing(12)

        lbl = QLabel("👤 Customer Details & SMS Notification")
        lbl.setStyleSheet(f"color: {t['text_heading']}; font-size: 15px; font-weight: bold;")
        d_layout.addWidget(lbl)

        form_l = QGridLayout()
        form_l.setSpacing(10)

        lbl_name = QLabel("Customer Name:")
        lbl_name.setStyleSheet(f"color: {t['text_primary']}; font-size: 12px; font-weight: 600;")
        init_name = self.current_customer if self.current_customer != "Walk-In" else ""
        txt_name = QLineEdit(init_name)
        txt_name.setPlaceholderText("Customer Name (or blank for Walk-In)")
        txt_name.setStyleSheet(f"background-color: {t['bg_input']}; color: {t['text_primary']}; padding: 8px; border: 1px solid {t['border']}; border-radius: 6px;")

        lbl_phone = QLabel("Mobile Number:")
        lbl_phone.setStyleSheet(f"color: {t['text_primary']}; font-size: 12px; font-weight: 600;")
        txt_phone = QLineEdit(getattr(self, "current_customer_phone", ""))
        txt_phone.setPlaceholderText("07XXXXXXXX (for auto SMS bill)")
        txt_phone.setStyleSheet(f"background-color: {t['bg_input']}; color: {t['text_primary']}; padding: 8px; border: 1px solid {t['border']}; border-radius: 6px;")

        form_l.addWidget(lbl_name, 0, 0)
        form_l.addWidget(txt_name, 0, 1)
        form_l.addWidget(lbl_phone, 1, 0)
        form_l.addWidget(txt_phone, 1, 1)
        d_layout.addLayout(form_l)

        lbl_hint = QLabel("💡 When mobile number is entered, customer receives automated SMS bill on checkout.")
        lbl_hint.setStyleSheet(f"color: {t['text_muted']}; font-size: 11px;")
        lbl_hint.setWordWrap(True)
        d_layout.addWidget(lbl_hint)

        bbox = QHBoxLayout()
        btn_walk = QPushButton("Walk-In")
        btn_walk.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_walk.setStyleSheet(f"background-color: {t['btn_default_bg']}; color: {t['btn_default_fg']}; border: 1px solid {t['border']}; border-radius: 6px; padding: 6px 14px;")
        btn_walk.clicked.connect(lambda: (txt_name.setText("Walk-In"), txt_phone.setText(""), dialog.accept()))

        btn_ok = QPushButton("Save Customer")
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.setStyleSheet(f"background-color: {t['success']}; color: white; font-weight: bold; padding: 6px 18px; border-radius: 6px; border: none;")
        btn_ok.clicked.connect(dialog.accept)

        bbox.addWidget(btn_walk)
        bbox.addStretch()
        bbox.addWidget(btn_ok)
        d_layout.addLayout(bbox)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            cname = txt_name.text().strip() or "Walk-In"
            cphone = txt_phone.text().strip()
            self.current_customer = cname
            self.current_customer_phone = cphone
            self._update_customer_button()
            if hasattr(self, 'tabs') and 0 <= self.active_tab_idx < len(self.tabs):
                self.tabs[self.active_tab_idx].customer_name = cname
                self.tabs[self.active_tab_idx].customer_phone = cphone
                self._update_tab_summary_labels()

    # --- Bill Management Actions ---
    def new_bill(self):
        """Starts a clean bill or opens a new tab if current bill has items."""
        if self.table.has_valid_items():
            self.add_new_bill_tab()
        else:
            self.show_status_bar_message(f"Current Bill #{self.active_tab_idx + 1} ({self.current_bill_no}) is ready.")

    def void_bill(self):
        """Void entire bill with confirmation [F6]."""
        if not self.table.has_valid_items():
            return
        res = QMessageBox.warning(
            self, "Void Bill (F6)", "Are you sure you want to void and clear the entire bill?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if res == QMessageBox.StandardButton.Yes:
            self.table.clear_bill()
            self.show_status_bar_message("Bill voided.")

    def void_current_row(self):
        """Deletes focused row [F7]."""
        cur = self.table.currentRow()
        if cur >= 0:
            self.table.delete_row(cur)

    def show_hold_recall_menu(self):
        """Menu dialog to either Hold current bill [F3] or Recall a parked bill [F4]."""
        t = get_theme_tokens(self.current_theme)
        dialog = QDialog(self)
        dialog.setWindowTitle("Hold / Recall Bill (F4)")
        dialog.setFixedSize(380, 210)
        d_layout = QVBoxLayout(dialog)
        d_layout.setContentsMargins(20, 20, 20, 20)
        d_layout.setSpacing(14)

        lbl = QLabel("Choose Action:")
        lbl.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {t['text_heading']};")
        d_layout.addWidget(lbl)

        btn_hold = QPushButton("📥 Hold Current Bill (Park Bill)")
        btn_hold.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_hold.setStyleSheet(f"background-color: {t['btn_default_bg']}; color: {t['btn_default_fg']}; padding: 10px; border-radius: 6px; font-weight: 600; border: 1px solid {t['border']};")
        btn_hold.clicked.connect(lambda: (dialog.accept(), self.hold_current_bill()))
        d_layout.addWidget(btn_hold)

        btn_recall = QPushButton("📤 Recall Parked Bill...")
        btn_recall.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_recall.setStyleSheet(f"background-color: {t['success']}; color: #ffffff; padding: 10px; border-radius: 6px; font-weight: bold; border: none;")
        btn_recall.clicked.connect(lambda: (dialog.accept(), self.recall_parked_bill()))
        d_layout.addWidget(btn_recall)

        dialog.exec()

    def hold_current_bill(self):
        """Parks active bill and closes tab (or clears if only 1 tab)."""
        if not self.table.has_valid_items():
            QMessageBox.warning(self, "Hold Bill", "No items in current bill to hold.")
            return

        items = self.table.get_bill_items()
        self.db.hold_bill(self.current_bill_no, self.current_customer, items, float(self.grand_total), customer_phone=self.current_customer_phone)
        self.show_status_bar_message(f"Bill {self.current_bill_no} parked successfully.")

        if len(self.tabs) > 1:
            del self.tabs[self.active_tab_idx]
            new_idx = min(self.active_tab_idx, len(self.tabs) - 1)
            self._load_tab_state(new_idx)
        else:
            self.current_bill_no = self.db.get_next_bill_number()
            self.lbl_bill_no.setText(f"Bill {self.current_bill_no}")
            self.current_customer = "Walk-In"
            self.current_customer_phone = ""
            self._update_customer_button()
            self.table.clear_bill()
            self._save_current_tab_state()
            self._render_bill_tabs()

    def recall_parked_bill(self):
        """Opens Recall dialog."""
        dialog = RecallBillsDialog(self.db, theme_mode=self.current_theme, parent=self)
        dialog.bill_recalled.connect(self._restore_held_bill)
        dialog.exec()

    def _restore_held_bill(self, bill_data: dict):
        """Restores a parked bill into a new tab (or current if empty)."""
        if self.table.has_valid_items():
            self.add_new_bill_tab(
                bill_no=bill_data.get("bill_no"),
                customer_name=bill_data.get("customer_name") or "Walk-In",
                customer_phone=bill_data.get("customer_phone") or "",
                items=bill_data.get("items", [])
            )
        else:
            self.current_bill_no = bill_data.get("bill_no") or self.current_bill_no
            self.lbl_bill_no.setText(f"Bill {self.current_bill_no}")
            self.current_customer = bill_data.get("customer_name") or "Walk-In"
            self.current_customer_phone = bill_data.get("customer_phone") or ""
            self._update_customer_button()
            self.table.load_items(bill_data.get("items", []))
            self._save_current_tab_state()
            self._render_bill_tabs()
        self.show_status_bar_message(f"Restored parked bill {self.current_bill_no}.")

    # --- Checkout Flow [F5] / Double-Enter ---
    def finalize_and_checkout(self):
        """Triggers the Checkout dialog and prints/saves bill."""
        if not self.table.has_valid_items():
            QMessageBox.warning(self, "Empty Bill", "Please add at least one product before checking out.")
            return

        auto_sms_enabled = (self.db.get_setting("auto_sms_enabled", "1") == "1")
        checkout_dlg = CheckoutDialog(
            self.grand_total, 
            default_method=self.current_payment_method, 
            theme_mode=self.current_theme,
            parent=self,
            customer_name=self.current_customer,
            customer_phone=self.current_customer_phone,
            auto_sms_enabled=auto_sms_enabled
        )
        if checkout_dlg.exec() == QDialog.DialogCode.Accepted:
            self.current_customer = checkout_dlg.customer_name
            self.current_customer_phone = checkout_dlg.customer_phone

            items = self.table.get_bill_items()
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Determine online sync status
            is_online = self.sync_worker.is_online if self.sync_worker else False
            initial_synced = 0 # Saved locally first; worker will push if online

            invoice_record = {
                "bill_no": self.current_bill_no,
                "customer_name": self.current_customer,
                "customer_phone": self.current_customer_phone,
                "subtotal": float(self.subtotal),
                "discount": float(self.discount_total),
                "tax": float(self.tax_total),
                "grand_total": float(self.grand_total),
                "paid_amount": float(checkout_dlg.paid_amount),
                "due_amount": float(checkout_dlg.due_amount),
                "payment_method": checkout_dlg.payment_method,
                "items_json": items,
                "created_at": now_str,
                "sms_sent": 0
            }

            # Save in SQLite (0ms UI lag)
            self.db.create_invoice(invoice_record, is_synced=initial_synced)

            # Direct Print Receipt (simulated ESC/POS format)
            if checkout_dlg.chk_print.isChecked():
                self.print_thermal_receipt(invoice_record, checkout_dlg.paid_amount, checkout_dlg.change_amount)

            # Non-blocking Background SMS Dispatch
            if checkout_dlg.send_sms and self.current_customer_phone:
                self.sms_worker = AsyncSmsWorker(invoice_record, self.db)
                self.sms_worker.sms_finished.connect(
                    lambda ok, msg: self.show_status_bar_message(("📱 " if ok else "⚠️ ") + msg)
                )
                self.sms_worker.start()

            # Wake sync worker immediately
            if self.sync_worker:
                self.sync_worker.request_immediate_sync()

            # Refresh pending count
            pending = self.db.get_pending_invoice_count()
            self.update_pending_storage_display(pending, is_online)

            self.show_status_bar_message(f"Bill {self.current_bill_no} finalized! (Rs. {self.grand_total:.2f})")

            # Advance to next new bill or switch to remaining tab
            if len(self.tabs) > 1:
                fin_bill = self.current_bill_no
                del self.tabs[self.active_tab_idx]
                new_idx = min(self.active_tab_idx, len(self.tabs) - 1)
                self._load_tab_state(new_idx)
                self.show_status_bar_message(f"Bill {fin_bill} finalized! Switched to Tab #{new_idx + 1}: {self.current_customer} ({self.current_bill_no})")
            else:
                self.current_bill_no = self.db.get_next_bill_number()
                self.lbl_bill_no.setText(f"Bill {self.current_bill_no}")
                self.current_customer = "Walk-In"
                self.current_customer_phone = ""
                self._update_customer_button()
                self.table.clear_bill()
                self._save_current_tab_state()
                self._render_bill_tabs()

    def print_thermal_receipt(self, inv: dict, paid: Optional[Decimal] = None, change: Optional[Decimal] = None):
        """Formats and outputs standard 80mm ESC/POS thermal receipt string."""
        from printer_engine import POSPrinterEngine
        ok, msg = POSPrinterEngine(self.db).print_invoice(inv, paid, change)
        self.show_status_bar_message(("🖨️ " if ok else "⚠️ ") + msg)
        if not ok:
            print(f"[Printer] {msg}")
        return
        tenant = self.db.get_setting("tenant_subdomain", "dbl")
        cashier = self.db.get_setting("cashier_name", "Admin")
        receipt_text = format_thermal_receipt(inv, tenant, cashier)
        print(f"\n[THERMAL RECEIPT OUTPUT - ESC/POS 80mm]\n{receipt_text}")

    # --- Today's Sales List [F6] ---
    def open_sales_list(self):
        """Opens Today's Sales List modal (F6) for receipt reprinting and bill editing."""
        tenant = self.db.get_setting("tenant_subdomain", "dbl")
        cashier = self.db.get_setting("cashier_name", "Admin")
        dlg = SalesListDialog(self.db, tenant=tenant, cashier=cashier, parent=self, theme_mode=self.current_theme)
        dlg.edit_bill_requested.connect(self._on_edit_past_bill)
        dlg.exec()

    def _on_edit_past_bill(self, bill_data: dict):
        """Loads a past bill back into the billing table for cashier modification."""
        if self.table.has_valid_items():
            self.add_new_bill_tab(
                bill_no=bill_data.get("bill_no"),
                customer_name=bill_data.get("customer_name") or "Walk-In",
                customer_phone=bill_data.get("customer_phone") or "",
                items=bill_data.get("items", [])
            )
            self.lbl_bill_no.setText(f"Bill {self.current_bill_no} (EDITING)")
            self.current_payment_method = bill_data.get("payment_method") or "CASH"
            if hasattr(self, 'btn_pay_toggle'):
                self.btn_pay_toggle.setText(f"Payment: {self.current_payment_method} (F9)")
        else:
            self.current_bill_no = bill_data.get("bill_no") or self.current_bill_no
            self.lbl_bill_no.setText(f"Bill {self.current_bill_no} (EDITING)")
            self.current_customer = bill_data.get("customer_name") or "Walk-In"
            self.current_customer_phone = bill_data.get("customer_phone") or ""
            self._update_customer_button()
            self.current_payment_method = bill_data.get("payment_method") or "CASH"
            if hasattr(self, 'btn_pay_toggle'):
                self.btn_pay_toggle.setText(f"Payment: {self.current_payment_method} (F9)")
            self.table.load_items(bill_data.get("items", []))
            self._save_current_tab_state()
            self._render_bill_tabs()

        self.show_status_bar_message(f"Loaded Bill {self.current_bill_no} for editing. Press [F5] when done to re-finalize.")

    # --- Settings Dialog [F12] ---
    def open_settings(self):
        dlg = SettingsDialog(self.db, self.sync_worker, parent=self, theme_mode=self.current_theme)
        dlg.theme_changed.connect(self.apply_theme)
        dlg.settings_saved.connect(self._on_settings_saved)
        dlg.exec()

    def _on_settings_saved(self):
        cashier = self.db.get_setting("cashier_name", "Admin")
        self.lbl_cashier.setText(f"Cashier: {cashier}")
        self.show_status_bar_message("Settings saved.")

    # --- Help Dialog [F1] ---
    def show_help(self):
        msg = (
            "🚀 <b>FastPOS Premium Keyboard Shortcuts:</b><br><br>"
            "• <b>[Enter] on Product Name:</b> Select product, jump to Qty.<br>"
            "• <b>Double [Enter] on Empty Name:</b> Instantly Checkout / Finalize bill.<br>"
            "• <b>[Enter] on Qty:</b> Confirm quantity, jump to Price.<br>"
            "• <b>[Enter] on Price:</b> Calculate total, add new row, jump to next item.<br>"
            "• <b>[F1]:</b> Help dialog<br>"
            "• <b>[F2]:</b> Global barcode / product search bar<br>"
            "• <b>[F3] / [Ctrl+T]:</b> Open New Bill Tab (Multi-Customer Billing)<br>"
            "• <b>[Ctrl+Tab]:</b> Switch between open Bill Tabs<br>"
            "• <b>[Ctrl+W]:</b> Close active Bill Tab<br>"
            "• <b>[F4]:</b> Hold / Recall parked bill<br>"
            "• <b>[F5]:</b> Quick Pay & Print<br>"
            "• <b>[F6]:</b> Today's Sales List (Reprint Receipt & Edit Bill)<br>"
            "• <b>[F7]:</b> Delete / Void focused row<br>"
            "• <b>[F8]:</b> Select / Change Customer<br>"
            "• <b>[F9]:</b> Toggle Payment Method (Cash/Card/Transfer)<br>"
            "• <b>[F10]:</b> Manual Cloud Sync<br>"
            "• <b>[F12]:</b> System & Multi-Tenant Settings<br>"
        )
        QMessageBox.information(self, "FastPOS Keyboard Guide", msg)

    def show_status_bar_message(self, message: str):
        self.statusBar().showMessage(message, 4000)

    # --- Global Hotkeys Overriding ---
    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        modifiers = event.modifiers()

        # Multi-Bill Tab Hotkeys: Ctrl+T, Ctrl+W, Ctrl+Tab, Ctrl+Shift+Tab
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_T:
                self.add_new_bill_tab()
                return
            elif key == Qt.Key.Key_W:
                self.close_bill_tab(self.active_tab_idx)
                return
            elif key == Qt.Key.Key_Tab:
                if modifiers & Qt.KeyboardModifier.ShiftModifier:
                    self.switch_to_prev_tab()
                else:
                    self.switch_to_next_tab()
                return
            elif key == Qt.Key.Key_PageDown:
                self.switch_to_next_tab()
                return
            elif key == Qt.Key.Key_PageUp:
                self.switch_to_prev_tab()
                return

        if key == Qt.Key.Key_F1:
            self.show_help()
            return
        elif key == Qt.Key.Key_F2:
            self.txt_global_search.setFocus()
            self.txt_global_search.selectAll()
            return
        elif key == Qt.Key.Key_F3:
            self.new_bill()
            return
        elif key == Qt.Key.Key_F4:
            self.recall_parked_bill()
            return
        elif key == Qt.Key.Key_F5:
            self.finalize_and_checkout()
            return
        elif key == Qt.Key.Key_F6:
            self.open_sales_list()
            return
        elif key == Qt.Key.Key_F7:
            self.void_current_row()
            return
        elif key == Qt.Key.Key_F8:
            self.prompt_customer()
            return
        elif key == Qt.Key.Key_F9:
            self.toggle_payment_method()
            return
        elif key == Qt.Key.Key_F10:
            self.trigger_manual_sync()
            return
        elif key == Qt.Key.Key_F12:
            self.open_settings()
            return

        super().keyPressEvent(event)
