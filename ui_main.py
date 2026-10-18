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
    QCheckBox, QGridLayout, QSizePolicy, QApplication, QScrollArea,
    QTextEdit, QPlainTextEdit, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHeaderView
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
        self.original_grand_total = grand_total
        self.extra_discount = Decimal('0.00')
        self.grand_total = grand_total
        self.payment_mode = "single"  # "single" or "multiple"
        self.split_secondary_method = "online"  # "online" (Card) or "bank_transfer"
        self.split_payments = None
        self.payment_method = default_method if default_method != "MULTIPLE" else "CASH"
        self.paid_amount = grand_total
        self.due_amount = Decimal('0.00')
        self.change_amount = Decimal('0.00')
        self.theme_mode = theme_mode or "dark"
        self.theme = get_theme_tokens(self.theme_mode)
        self.customer_name = customer_name or "Walk-In"
        self.customer_phone = customer_phone or ""
        self.auto_sms_enabled = auto_sms_enabled
        self.send_sms = False
        self.cheque_no = ""
        self.bank_name = ""
        self.cheque_date = datetime.now().strftime("%Y-%m-%d")

        self.setWindowTitle("Checkout & Payment (F5)")
        self.resize(580, 780)
        self.setMinimumSize(560, 740)
        self.setModal(True)
        self.init_ui()

    def init_ui(self):
        t = get_theme_tokens(self.theme_mode)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 16, 20, 16)

        # Header
        lbl_title = QLabel("💳 Finalize Bill & Print")
        lbl_title.setStyleSheet(f"font-size: 17px; font-weight: bold; color: {t['text_heading']};")
        layout.addWidget(lbl_title)

        # Grand Total Card
        tot_card = QFrame()
        tot_card.setObjectName("checkoutTotCard")
        tot_card.setStyleSheet(f"""
            #checkoutTotCard {{
                background-color: {t['bg_card_inner']};
                border: 2px solid {t['success']};
                border-radius: 8px;
                padding: 8px 12px;
            }}
            #checkoutTotCard QLabel {{
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }}
        """)
        tot_layout = QVBoxLayout(tot_card)
        tot_layout.setContentsMargins(4, 4, 4, 4)
        tot_layout.setSpacing(2)
        tot_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_tot_desc = QLabel("AMOUNT DUE")
        self.lbl_tot_desc.setStyleSheet(f"color: {t['text_muted']}; font-size: 11px; font-weight: bold; letter-spacing: 0.5px;")
        self.lbl_grand_val = QLabel(f"Rs. {self.grand_total:.2f}")
        self.lbl_grand_val.setStyleSheet(f"color: {t['success']}; font-size: 32px; font-weight: bold;")
        tot_layout.addWidget(self.lbl_tot_desc, alignment=Qt.AlignmentFlag.AlignCenter)
        tot_layout.addWidget(self.lbl_grand_val, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(tot_card)

        # Global Bill Discount & Round-Off Card
        disc_card = QFrame()
        disc_card.setObjectName("checkoutDiscCard")
        disc_card.setStyleSheet(f"""
            #checkoutDiscCard {{
                background-color: {t['bg_card_inner']};
                border: 1px solid {t['border']};
                border-radius: 8px;
                padding: 4px 10px;
            }}
            #checkoutDiscCard QLabel {{
                background: transparent;
                border: none;
            }}
        """)
        disc_layout = QHBoxLayout(disc_card)
        disc_layout.setContentsMargins(6, 4, 6, 4)
        disc_layout.setSpacing(8)

        lbl_disc = QLabel("🏷️ Discount / Round-off:")
        lbl_disc.setStyleSheet(f"color: {t['text_primary']}; font-size: 12px; font-weight: bold;")
        disc_layout.addWidget(lbl_disc)

        self.txt_discount = QLineEdit("0.00")
        self.txt_discount.setPlaceholderText("0.00")
        self.txt_discount.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.txt_discount.setFixedWidth(95)
        self.txt_discount.setFixedHeight(30)
        self.txt_discount.setStyleSheet(f"""
            QLineEdit {{
                background-color: {t['bg_input']};
                color: {t['accent']};
                border: 1.5px solid {t['accent']};
                border-radius: 5px;
                padding: 2px 6px;
                font-size: 14px;
                font-weight: bold;
            }}
            QLineEdit:focus {{
                border: 1.5px solid {t['accent']};
                background-color: {t['bg_card']};
            }}
        """)
        self.txt_discount.textChanged.connect(self._on_discount_changed)
        self.txt_discount.installEventFilter(self)
        disc_layout.addWidget(self.txt_discount)

        # Quick round helper buttons
        self.btn_round_none = QPushButton("Rs. 0")
        self.btn_round_none.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_round_none.setFixedHeight(28)
        self.btn_round_none.setToolTip("Clear extra discount (0.00)")
        self.btn_round_none.clicked.connect(lambda: self.set_quick_discount(Decimal('0.00')))

        self.btn_round_50 = QPushButton("Round 50")
        self.btn_round_50.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_round_50.setFixedHeight(28)
        self.btn_round_50.setToolTip("Round down to nearest 50")
        self.btn_round_50.clicked.connect(lambda: self.round_down_to(Decimal('50.00')))

        self.btn_round_100 = QPushButton("Round 100")
        self.btn_round_100.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_round_100.setFixedHeight(28)
        self.btn_round_100.setToolTip("Round down to nearest 100 (e.g. 3250 -> 3200)")
        self.btn_round_100.clicked.connect(lambda: self.round_down_to(Decimal('100.00')))

        for rb in (self.btn_round_none, self.btn_round_50, self.btn_round_100):
            rb.setStyleSheet(f"""
                QPushButton {{
                    background-color: {t['btn_default_bg']};
                    color: {t['text_secondary']};
                    border: 1px solid {t['border']};
                    border-radius: 4px;
                    padding: 3px 8px;
                    font-size: 11px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background-color: {t['border']};
                    color: {t['text_primary']};
                }}
            """)
            disc_layout.addWidget(rb)

        layout.addWidget(disc_card)

        # Customer Name & Phone Fields
        cust_row = QHBoxLayout()
        cust_row.setSpacing(10)

        cname_col = QVBoxLayout()
        cname_col.setSpacing(2)
        lbl_cn = QLabel("Customer Name:")
        lbl_cn.setStyleSheet(f"color: {t['text_muted']}; font-size: 11px; font-weight: bold;")
        self.txt_cust_name = QLineEdit(self.customer_name)
        self.txt_cust_name.setPlaceholderText("Walk-In")
        self.txt_cust_name.setFixedHeight(32)
        self.txt_cust_name.setStyleSheet(f"QLineEdit {{ background-color: {t['bg_input']}; color: {t['text_primary']}; border: 1px solid {t['border']}; border-radius: 5px; padding: 4px 8px; font-size: 12px; }}")
        cname_col.addWidget(lbl_cn)
        cname_col.addWidget(self.txt_cust_name)

        cphone_col = QVBoxLayout()
        cphone_col.setSpacing(2)
        lbl_cp = QLabel("Mobile Number (SMS):")
        lbl_cp.setStyleSheet(f"color: {t['text_muted']}; font-size: 11px; font-weight: bold;")
        self.txt_cust_phone = QLineEdit(self.customer_phone)
        self.txt_cust_phone.setPlaceholderText("07XXXXXXXX")
        self.txt_cust_phone.setFixedHeight(32)
        self.txt_cust_phone.setStyleSheet(f"QLineEdit {{ background-color: {t['bg_input']}; color: {t['text_primary']}; border: 1px solid {t['border']}; border-radius: 5px; padding: 4px 8px; font-size: 12px; }}")
        cphone_col.addWidget(lbl_cp)
        cphone_col.addWidget(self.txt_cust_phone)

        cust_row.addLayout(cname_col, 3)
        cust_row.addLayout(cphone_col, 2)
        layout.addLayout(cust_row)

        # Payment Mode Toggle Bar (Single vs Multi Payment)
        mode_box = QFrame()
        mode_box.setObjectName("checkoutModeBox")
        mode_box.setStyleSheet(f"""
            #checkoutModeBox {{
                background-color: {t['bg_card_inner']};
                border: 1px solid {t['border']};
                border-radius: 8px;
                padding: 2px;
            }}
            #checkoutModeBox QPushButton {{
                border: none;
                border-radius: 6px;
            }}
        """)
        mode_layout = QHBoxLayout(mode_box)
        mode_layout.setContentsMargins(3, 3, 3, 3)
        mode_layout.setSpacing(6)

        self.btn_mode_single = QPushButton("💵 Single Payment")
        self.btn_mode_single.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mode_single.setFixedHeight(34)
        self.btn_mode_single.clicked.connect(lambda: self.set_payment_mode("single"))

        self.btn_mode_multi = QPushButton("🔀 Multi Payment (Split)")
        self.btn_mode_multi.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mode_multi.setFixedHeight(34)
        self.btn_mode_multi.clicked.connect(lambda: self.set_payment_mode("multiple"))

        mode_layout.addWidget(self.btn_mode_single)
        mode_layout.addWidget(self.btn_mode_multi)
        layout.addWidget(mode_box)

        # --- Container 1: Single Payment ---
        self.container_single = QWidget()
        single_vbox = QVBoxLayout(self.container_single)
        single_vbox.setContentsMargins(0, 0, 0, 0)
        single_vbox.setSpacing(10)

        # Payment Method Selector
        method_layout = QHBoxLayout()
        self.btn_cash = QPushButton("💵 CASH")
        self.btn_card = QPushButton("💳 CARD")
        self.btn_transfer = QPushButton("🏦 TRANSFER")
        self.btn_cheque = QPushButton("📜 CHEQUE")

        self.methods = ["CASH", "CARD", "TRANSFER", "CHEQUE"]
        self.method_buttons = [self.btn_cash, self.btn_card, self.btn_transfer, self.btn_cheque]

        for b in self.method_buttons:
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedHeight(40)
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
        self.btn_cheque.clicked.connect(lambda: self.set_method("CHEQUE"))

        single_vbox.addLayout(method_layout)

        # Cash Tendered & Change Row
        form_layout = QGridLayout()

        lbl_paid = QLabel("Amount Tendered (Rs.):")
        lbl_paid.setStyleSheet(f"color: {t['text_primary']}; font-size: 13px; font-weight: 600;")
        self.txt_paid = QLineEdit(f"{self.grand_total:.2f}")
        self.txt_paid.setFixedHeight(36)
        self.txt_paid.setStyleSheet(f"""
            QLineEdit {{
                background-color: {t['bg_input']};
                color: {t['text_primary']};
                border: 2px solid {t['accent']};
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 16px;
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
        self.lbl_change_title.setStyleSheet(f"color: {t['text_primary']}; font-size: 13px; font-weight: 600;")
        self.lbl_change_val = QLabel("Rs. 0.00")
        self.lbl_change_val.setStyleSheet(f"color: {t['accent']}; font-size: 18px; font-weight: bold;")
        form_layout.addWidget(self.lbl_change_title, 2, 0)
        form_layout.addWidget(self.lbl_change_val, 2, 1)

        single_vbox.addLayout(form_layout)

        # Cheque Details Form Card (visible only when CHEQUE method selected)
        self.cheque_frame = QFrame()
        self.cheque_frame.setObjectName("checkoutChequeCard")
        self.cheque_frame.setStyleSheet(f"""
            #checkoutChequeCard {{
                background-color: {t['bg_card_inner']};
                border: 1.5px solid #f59e0b;
                border-radius: 8px;
                padding: 6px 12px;
            }}
            #checkoutChequeCard QLabel {{
                background: transparent;
                border: none;
                font-size: 11px;
                font-weight: 600;
                color: {t['text_primary']};
            }}
        """)
        ch_layout = QGridLayout(self.cheque_frame)
        ch_layout.setContentsMargins(6, 6, 6, 6)
        ch_layout.setSpacing(6)

        lbl_chq_title = QLabel("📜 CHEQUE PAYMENT DETAILS")
        lbl_chq_title.setStyleSheet("color: #f59e0b; font-size: 11px; font-weight: bold; letter-spacing: 0.5px;")
        ch_layout.addWidget(lbl_chq_title, 0, 0, 1, 2)

        lbl_cno = QLabel("Cheque Number:")
        self.txt_cheque_no = QLineEdit()
        self.txt_cheque_no.setPlaceholderText("e.g. 123456")
        self.txt_cheque_no.setFixedHeight(30)
        self.txt_cheque_no.setStyleSheet(f"background-color: {t['bg_input']}; color: {t['text_primary']}; border: 1px solid {t['border']}; border-radius: 5px; padding: 2px 6px;")
        self.txt_cheque_no.installEventFilter(self)
        ch_layout.addWidget(lbl_cno, 1, 0)
        ch_layout.addWidget(self.txt_cheque_no, 1, 1)

        lbl_cbank = QLabel("Bank Name:")
        self.txt_bank_name = QLineEdit()
        self.txt_bank_name.setPlaceholderText("e.g. Commercial Bank, BOC, Sampath")
        self.txt_bank_name.setFixedHeight(30)
        self.txt_bank_name.setStyleSheet(f"background-color: {t['bg_input']}; color: {t['text_primary']}; border: 1px solid {t['border']}; border-radius: 5px; padding: 2px 6px;")
        self.txt_bank_name.installEventFilter(self)
        ch_layout.addWidget(lbl_cbank, 2, 0)
        ch_layout.addWidget(self.txt_bank_name, 2, 1)

        lbl_cdate = QLabel("Cheque Date:")
        self.txt_cheque_date = QLineEdit(datetime.now().strftime("%Y-%m-%d"))
        self.txt_cheque_date.setPlaceholderText("YYYY-MM-DD")
        self.txt_cheque_date.setFixedHeight(30)
        self.txt_cheque_date.setStyleSheet(f"background-color: {t['bg_input']}; color: {t['text_primary']}; border: 1px solid {t['border']}; border-radius: 5px; padding: 2px 6px;")
        self.txt_cheque_date.installEventFilter(self)
        ch_layout.addWidget(lbl_cdate, 3, 0)
        ch_layout.addWidget(self.txt_cheque_date, 3, 1)

        self.cheque_frame.setVisible(False)
        single_vbox.addWidget(self.cheque_frame)
        layout.addWidget(self.container_single)

        # --- Container 2: Multi Payment (Split) ---
        self.container_multi = QWidget()
        multi_vbox = QVBoxLayout(self.container_multi)
        multi_vbox.setContentsMargins(0, 0, 0, 0)
        multi_vbox.setSpacing(8)

        # Card 1: Primary Method (Cash)
        cash_card = QFrame()
        cash_card.setObjectName("multiCashCard")
        cash_card.setStyleSheet(f"""
            #multiCashCard {{
                background-color: {t['bg_card_inner']};
                border: 1px solid {t['border']};
                border-radius: 8px;
                padding: 8px 12px;
            }}
            #multiCashCard QLabel {{
                background: transparent;
                border: none;
                padding: 0px;
            }}
        """)
        cc_layout = QVBoxLayout(cash_card)
        cc_layout.setContentsMargins(4, 4, 4, 4)
        cc_layout.setSpacing(6)

        ch_hdr = QHBoxLayout()
        lbl_p_title = QLabel("1. PRIMARY METHOD: CASH")
        lbl_p_title.setStyleSheet(f"color: {t['text_muted']}; font-size: 11px; font-weight: bold; letter-spacing: 0.5px;")
        ch_hdr.addWidget(lbl_p_title)
        ch_hdr.addStretch()

        q_exact = QPushButton("Exact")
        q_exact.setCursor(Qt.CursorShape.PointingHandCursor)
        q_exact.setFixedHeight(24)
        q_exact.setStyleSheet(f"background-color: {t['btn_default_bg']}; color: {t['success']}; border: 1px solid {t['border']}; border-radius: 4px; padding: 1px 8px; font-weight: bold; font-size: 11px;")
        q_exact.clicked.connect(self._set_multi_cash_exact)

        q_half = QPushButton("50%")
        q_half.setCursor(Qt.CursorShape.PointingHandCursor)
        q_half.setFixedHeight(24)
        q_half.setStyleSheet(f"background-color: {t['btn_default_bg']}; color: {t['accent']}; border: 1px solid {t['border']}; border-radius: 4px; padding: 1px 8px; font-weight: bold; font-size: 11px;")
        q_half.clicked.connect(self._set_multi_cash_half)

        q_zero = QPushButton("Rs. 0")
        q_zero.setCursor(Qt.CursorShape.PointingHandCursor)
        q_zero.setFixedHeight(24)
        q_zero.setStyleSheet(f"background-color: {t['btn_default_bg']}; color: #ef4444; border: 1px solid {t['border']}; border-radius: 4px; padding: 1px 8px; font-weight: bold; font-size: 11px;")
        q_zero.clicked.connect(self._set_multi_cash_zero)

        ch_hdr.addWidget(q_exact)
        ch_hdr.addWidget(q_half)
        ch_hdr.addWidget(q_zero)
        cc_layout.addLayout(ch_hdr)

        cin_row = QHBoxLayout()
        lbl_mc = QLabel("Cash Received:")
        lbl_mc.setStyleSheet(f"color: {t['text_primary']}; font-size: 13px; font-weight: 600;")
        lbl_mc.setFixedWidth(110)
        self.txt_multi_cash = QLineEdit(f"{self.grand_total:.2f}")
        self.txt_multi_cash.setFixedHeight(36)
        self.txt_multi_cash.setStyleSheet(f"""
            QLineEdit {{
                background-color: {t['bg_input']};
                color: {t['text_primary']};
                border: 2px solid {t['accent']};
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 16px;
                font-weight: bold;
            }}
        """)
        self.txt_multi_cash.textChanged.connect(self.calculate_multi_change)
        self.txt_multi_cash.installEventFilter(self)

        cin_row.addWidget(lbl_mc)
        cin_row.addWidget(self.txt_multi_cash, 1)
        cc_layout.addLayout(cin_row)
        multi_vbox.addWidget(cash_card)

        # Card 2: Secondary Method (Card / Bank Transfer)
        sec_card = QFrame()
        sec_card.setObjectName("multiSecCard")
        sec_card.setStyleSheet(f"""
            #multiSecCard {{
                background-color: {t['bg_card_inner']};
                border: 1px solid {t['border']};
                border-radius: 8px;
                padding: 8px 12px;
            }}
            #multiSecCard QLabel {{
                background: transparent;
                border: none;
                padding: 0px;
            }}
        """)
        sc_layout = QVBoxLayout(sec_card)
        sc_layout.setContentsMargins(4, 4, 4, 4)
        sc_layout.setSpacing(6)

        sec_hdr = QHBoxLayout()
        lbl_s_title = QLabel("2. SECONDARY METHOD:")
        lbl_s_title.setStyleSheet(f"color: {t['text_muted']}; font-size: 11px; font-weight: bold; letter-spacing: 0.5px;")
        sec_hdr.addWidget(lbl_s_title)
        sec_hdr.addStretch()

        self.btn_sec_card = QPushButton("💳 Card Pay")
        self.btn_sec_card.setCheckable(True)
        self.btn_sec_card.setFixedHeight(26)
        self.btn_sec_card.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sec_card.clicked.connect(lambda: self.set_multi_sec_method("online"))

        self.btn_sec_transfer = QPushButton("🏦 Bank Transfer")
        self.btn_sec_transfer.setCheckable(True)
        self.btn_sec_transfer.setFixedHeight(26)
        self.btn_sec_transfer.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sec_transfer.clicked.connect(lambda: self.set_multi_sec_method("bank_transfer"))

        sec_hdr.addWidget(self.btn_sec_card)
        sec_hdr.addWidget(self.btn_sec_transfer)
        sc_layout.addLayout(sec_hdr)

        sin_row = QHBoxLayout()
        lbl_ms = QLabel("Sec. Amount:")
        lbl_ms.setStyleSheet(f"color: {t['text_primary']}; font-size: 13px; font-weight: 600;")
        lbl_ms.setFixedWidth(110)
        self.txt_multi_sec = QLineEdit("0.00")
        self.txt_multi_sec.setFixedHeight(36)
        self.txt_multi_sec.setStyleSheet(f"""
            QLineEdit {{
                background-color: {t['bg_input']};
                color: {t['text_primary']};
                border: 2px solid {t['border']};
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 16px;
                font-weight: bold;
            }}
            QLineEdit:focus {{
                border: 2px solid {t['accent']};
            }}
        """)
        self.txt_multi_sec.textChanged.connect(self.calculate_multi_change)
        self.txt_multi_sec.installEventFilter(self)

        self.btn_fill_bal = QPushButton("⚡ Fill Balance")
        self.btn_fill_bal.setToolTip("Auto-fill remaining balance to reach Grand Total")
        self.btn_fill_bal.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_fill_bal.setFixedHeight(36)
        self.btn_fill_bal.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['accent']};
                color: #ffffff;
                font-weight: bold;
                font-size: 12px;
                border-radius: 6px;
                padding: 0px 14px;
                border: none;
            }}
            QPushButton:hover {{
                opacity: 0.9;
            }}
        """)
        self.btn_fill_bal.clicked.connect(self.fill_multi_balance)

        sin_row.addWidget(lbl_ms)
        sin_row.addWidget(self.txt_multi_sec, 1)
        sin_row.addWidget(self.btn_fill_bal)
        sc_layout.addLayout(sin_row)

        ref_row = QHBoxLayout()
        lbl_ref = QLabel("Ref / Slip #:")
        lbl_ref.setStyleSheet(f"color: {t['text_secondary']}; font-size: 12px; font-weight: 600;")
        lbl_ref.setFixedWidth(110)
        self.txt_multi_ref = QLineEdit("")
        self.txt_multi_ref.setPlaceholderText("Approval code / Bank slip reference (optional)")
        self.txt_multi_ref.setFixedHeight(30)
        self.txt_multi_ref.setStyleSheet(f"""
            QLineEdit {{
                background-color: {t['bg_input']};
                color: {t['text_primary']};
                border: 1px solid {t['border']};
                border-radius: 5px;
                padding: 3px 6px;
                font-size: 12px;
            }}
        """)
        self.txt_multi_ref.returnPressed.connect(self.confirm_payment)
        ref_row.addWidget(lbl_ref)
        ref_row.addWidget(self.txt_multi_ref, 1)
        sc_layout.addLayout(ref_row)

        multi_vbox.addWidget(sec_card)

        # Card 3: Multi Payment Summary (2 Columns)
        summ_card = QFrame()
        summ_card.setObjectName("multiSummaryCard")
        summ_card.setStyleSheet(f"""
            #multiSummaryCard {{
                background-color: {t['bg_card_inner']};
                border: 1px solid {t['border']};
                border-radius: 8px;
                padding: 6px 12px;
            }}
            #multiSummaryCard QLabel {{
                background: transparent;
                border: none;
                padding: 0px;
            }}
        """)
        sm_layout = QHBoxLayout(summ_card)
        sm_layout.setContentsMargins(6, 4, 6, 4)

        col1 = QVBoxLayout()
        col1.setSpacing(2)
        lbl_t1 = QLabel("TOTAL TENDERED")
        lbl_t1.setStyleSheet(f"color: {t['text_muted']}; font-size: 10px; font-weight: bold; letter-spacing: 0.5px;")
        self.lbl_multi_total_val = QLabel(f"Rs. {self.grand_total:.2f}")
        self.lbl_multi_total_val.setStyleSheet(f"color: {t['text_primary']}; font-size: 16px; font-weight: bold;")
        col1.addWidget(lbl_t1)
        col1.addWidget(self.lbl_multi_total_val)
        sm_layout.addLayout(col1, 1)

        col2 = QVBoxLayout()
        col2.setSpacing(2)
        self.lbl_multi_status_title = QLabel("BALANCE TO RETURN")
        self.lbl_multi_status_title.setStyleSheet(f"color: {t['text_muted']}; font-size: 10px; font-weight: bold; letter-spacing: 0.5px;")
        self.lbl_multi_status_val = QLabel("Rs. 0.00")
        self.lbl_multi_status_val.setStyleSheet(f"color: {t['accent']}; font-size: 18px; font-weight: bold;")
        col2.addWidget(self.lbl_multi_status_title)
        col2.addWidget(self.lbl_multi_status_val)
        sm_layout.addLayout(col2, 1)

        multi_vbox.addWidget(summ_card)
        layout.addWidget(self.container_multi)

        # Print Receipt Checkbox
        self.chk_print = QCheckBox("Direct Thermal Print Receipt (ESC/POS 80mm)")
        self.chk_print.setChecked(True)
        self.chk_print.setStyleSheet(f"color: {t['text_secondary']}; font-size: 12px;")
        layout.addWidget(self.chk_print)

        # SMS Notification Checkbox
        self.chk_sms = QCheckBox("📱 Auto-Send SMS Bill to Customer Phone")
        is_phone_ok = is_valid_phone(self.customer_phone)
        self.chk_sms.setChecked(self.auto_sms_enabled and is_phone_ok)
        self.chk_sms.setStyleSheet(f"color: {t['text_primary']}; font-size: 12px; font-weight: 600;")
        layout.addWidget(self.chk_sms)

        def _on_phone_changed(text):
            if self.auto_sms_enabled:
                self.chk_sms.setChecked(is_valid_phone(text))
        self.txt_cust_phone.textChanged.connect(_on_phone_changed)

        # Action Buttons
        btn_box = QHBoxLayout()
        self.btn_cancel = QPushButton("Cancel (Esc)")
        self.btn_cancel.setFixedHeight(40)
        self.btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['btn_default_bg']};
                color: {t['text_primary']};
                padding: 8px 18px;
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

        self.btn_confirm = QPushButton("✓ PAY && PRINT [Enter]")
        self.btn_confirm.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_confirm.setFixedHeight(40)
        self.btn_confirm.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['success']};
                color: #ffffff;
                padding: 8px 24px;
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

        # Initialize mode & method state
        self.set_multi_sec_method(self.split_secondary_method)
        self.set_payment_mode("single")
        self.set_method(self.payment_method)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(15, self._focus_discount)

    def _focus_discount(self):
        if hasattr(self, 'txt_discount'):
            self.txt_discount.setFocus()
            self.txt_discount.selectAll()

    def _on_discount_changed(self):
        val_str = self.txt_discount.text().strip()
        try:
            extra = Decimal(val_str) if val_str else Decimal('0.00')
        except Exception:
            extra = Decimal('0.00')

        if extra < 0:
            extra = Decimal('0.00')
        if extra > self.original_grand_total:
            extra = self.original_grand_total

        self.extra_discount = extra
        self.grand_total = self.original_grand_total - self.extra_discount
        self.lbl_grand_val.setText(f"Rs. {self.grand_total:.2f}")

        if self.extra_discount > 0:
            self.lbl_tot_desc.setText(f"AMOUNT DUE (Orig: Rs. {self.original_grand_total:.2f} - Disc: Rs. {self.extra_discount:.2f})")
        else:
            self.lbl_tot_desc.setText("AMOUNT DUE")

        # Update default amount tendered to match new grand total
        self.txt_paid.setText(f"{self.grand_total:.2f}")
        if hasattr(self, 'txt_multi_cash'):
            self.txt_multi_cash.setText(f"{self.grand_total:.2f}")
        if hasattr(self, 'txt_multi_sec'):
            self.txt_multi_sec.setText("0.00")
        self._refresh_quick_buttons()
        if self.payment_mode == "single":
            self.calculate_change()
        else:
            self.calculate_multi_change()

    def set_quick_discount(self, disc_amt: Decimal):
        disc_amt = max(Decimal('0.00'), min(disc_amt, self.original_grand_total))
        self.txt_discount.setText(f"{disc_amt:.2f}")
        self.txt_discount.selectAll()
        self.txt_discount.setFocus()

    def round_down_to(self, step: Decimal):
        if step <= 0 or self.original_grand_total <= 0:
            return
        rounded_total = (self.original_grand_total // step) * step
        diff = self.original_grand_total - rounded_total
        self.set_quick_discount(diff)

    def set_payment_mode(self, mode: str):
        self.payment_mode = mode
        is_single = (mode == "single")
        self.btn_mode_single.setChecked(is_single)
        self.btn_mode_multi.setChecked(not is_single)

        t = self.theme
        checked_style = f"""
            QPushButton {{
                background-color: {t['accent']};
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
                border: none;
                border-radius: 6px;
            }}
        """
        unchecked_style = f"""
            QPushButton {{
                background-color: transparent;
                color: {t['text_secondary']};
                font-weight: 600;
                font-size: 13px;
                border: none;
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background-color: {t['btn_default_bg']};
                color: {t['text_primary']};
            }}
        """
        self.btn_mode_single.setStyleSheet(checked_style if is_single else unchecked_style)
        self.btn_mode_multi.setStyleSheet(unchecked_style if is_single else checked_style)

        self.container_single.setVisible(is_single)
        self.container_multi.setVisible(not is_single)

        if is_single:
            self.calculate_change()
        else:
            self.calculate_multi_change()

    def set_multi_sec_method(self, method: str):
        self.split_secondary_method = method
        is_card = (method == "online")
        self.btn_sec_card.setChecked(is_card)
        self.btn_sec_transfer.setChecked(not is_card)
        t = self.theme
        active_style = f"""
            QPushButton {{
                background-color: {t['accent']};
                color: #ffffff;
                border: 1px solid {t['accent']};
                border-radius: 5px;
                font-weight: bold;
                font-size: 11px;
                padding: 2px 10px;
            }}
        """
        inactive_style = f"""
            QPushButton {{
                background-color: {t['btn_default_bg']};
                color: {t['text_secondary']};
                border: 1px solid {t['border']};
                border-radius: 5px;
                font-weight: 600;
                font-size: 11px;
                padding: 2px 10px;
            }}
            QPushButton:hover {{
                background-color: {t['border']};
                color: {t['text_primary']};
            }}
        """
        self.btn_sec_card.setStyleSheet(active_style if is_card else inactive_style)
        self.btn_sec_transfer.setStyleSheet(inactive_style if is_card else active_style)
        if is_card:
            self.txt_multi_ref.setPlaceholderText("Card Approval Code / Transaction Ref (optional)")
        else:
            self.txt_multi_ref.setPlaceholderText("Bank Name / Slip No. / Transfer Ref (optional)")

    def fill_multi_balance(self):
        try:
            cash_str = self.txt_multi_cash.text().strip() or "0"
            cash_val = Decimal(cash_str)
        except Exception:
            cash_val = Decimal('0.00')
        bal = max(Decimal('0.00'), self.grand_total - cash_val)
        self.txt_multi_sec.setText(f"{bal:.2f}")
        self.txt_multi_sec.selectAll()
        self.txt_multi_sec.setFocus()
        self.calculate_multi_change()

    def _set_multi_cash_exact(self):
        self.txt_multi_cash.setText(f"{self.grand_total:.2f}")
        self.txt_multi_sec.setText("0.00")
        self.calculate_multi_change()

    def _set_multi_cash_half(self):
        half_val = round(float(self.grand_total) / 2.0, 2)
        self.txt_multi_cash.setText(f"{half_val:.2f}")
        rem = round(float(self.grand_total) - half_val, 2)
        self.txt_multi_sec.setText(f"{rem:.2f}")
        self.calculate_multi_change()

    def _set_multi_cash_zero(self):
        self.txt_multi_cash.setText("0.00")
        self.txt_multi_sec.setText(f"{self.grand_total:.2f}")
        self.calculate_multi_change()

    def calculate_multi_change(self):
        if not hasattr(self, 'txt_multi_cash') or not hasattr(self, 'txt_multi_sec'):
            return
        t = self.theme
        try:
            c_str = self.txt_multi_cash.text().strip() or "0"
            cash_val = Decimal(c_str)
        except Exception:
            cash_val = Decimal('0.00')

        try:
            s_str = self.txt_multi_sec.text().strip() or "0"
            sec_val = Decimal(s_str)
        except Exception:
            sec_val = Decimal('0.00')

        total_rec = cash_val + sec_val

        if total_rec < self.grand_total:
            self.paid_amount = max(Decimal('0.00'), total_rec)
            self.due_amount = self.grand_total - self.paid_amount
            self.change_amount = Decimal('0.00')
            self.lbl_multi_status_title.setText("BALANCE DUE")
            self.lbl_multi_status_title.setStyleSheet("color: #ef4444; font-size: 10px; font-weight: bold; letter-spacing: 0.5px;")
            self.lbl_multi_status_val.setText(f"Rs. {self.due_amount:.2f}")
            self.lbl_multi_status_val.setStyleSheet("color: #ef4444; font-size: 18px; font-weight: bold;")
        else:
            self.paid_amount = self.grand_total
            self.due_amount = Decimal('0.00')
            self.change_amount = total_rec - self.grand_total
            self.lbl_multi_status_title.setText("BALANCE TO RETURN")
            self.lbl_multi_status_title.setStyleSheet(f"color: {t['text_muted']}; font-size: 10px; font-weight: bold; letter-spacing: 0.5px;")
            self.lbl_multi_status_val.setText(f"Rs. {self.change_amount:.2f}")
            self.lbl_multi_status_val.setStyleSheet(f"color: {t['accent']}; font-size: 18px; font-weight: bold;")

        self.lbl_multi_total_val.setText(f"Rs. {total_rec:.2f}")

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()

            # When user is on Global Discount field
            if hasattr(self, 'txt_discount') and watched == self.txt_discount:
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Down, Qt.Key.Key_Tab):
                    if self.payment_mode == "single":
                        cur_idx = self.methods.index(self.payment_method) if self.payment_method in self.methods else 0
                        self.method_buttons[cur_idx].setFocus()
                    else:
                        self.txt_multi_cash.setFocus()
                        self.txt_multi_cash.selectAll()
                    return True

            # When user is on payment method buttons
            elif watched in self.method_buttons:
                if key == Qt.Key.Key_Up:
                    # Up Arrow jumps back to Discount field
                    if hasattr(self, 'txt_discount'):
                        self.txt_discount.setFocus()
                        self.txt_discount.selectAll()
                    return True
                elif key in (Qt.Key.Key_Right, Qt.Key.Key_Tab):
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
                    cur_idx = self.methods.index(self.payment_method) if self.payment_method in self.methods else 0
                    self.method_buttons[cur_idx].setFocus()
                    return True
                elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    # Enter triggers Pay & Print
                    self.confirm_payment()
                    return True

            # When user is on Multi Cash input
            elif hasattr(self, 'txt_multi_cash') and watched == self.txt_multi_cash:
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Down):
                    self.txt_multi_sec.setFocus()
                    self.txt_multi_sec.selectAll()
                    return True
                elif key == Qt.Key.Key_Up:
                    if hasattr(self, 'txt_discount'):
                        self.txt_discount.setFocus()
                        self.txt_discount.selectAll()
                    return True

            # When user is on Multi Sec input
            elif hasattr(self, 'txt_multi_sec') and watched == self.txt_multi_sec:
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self.confirm_payment()
                    return True
                elif key == Qt.Key.Key_Up:
                    self.txt_multi_cash.setFocus()
                    self.txt_multi_cash.selectAll()
                    return True

            # When user is on Cheque fields
            elif hasattr(self, 'txt_cheque_no') and watched == self.txt_cheque_no:
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Down):
                    self.txt_bank_name.setFocus()
                    self.txt_bank_name.selectAll()
                    return True
                elif key == Qt.Key.Key_Up:
                    self.txt_paid.setFocus()
                    self.txt_paid.selectAll()
                    return True
            elif hasattr(self, 'txt_bank_name') and watched == self.txt_bank_name:
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Down):
                    self.txt_cheque_date.setFocus()
                    self.txt_cheque_date.selectAll()
                    return True
                elif key == Qt.Key.Key_Up:
                    self.txt_cheque_no.setFocus()
                    self.txt_cheque_no.selectAll()
                    return True
            elif hasattr(self, 'txt_cheque_date') and watched == self.txt_cheque_date:
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self.confirm_payment()
                    return True
                elif key == Qt.Key.Key_Up:
                    self.txt_bank_name.setFocus()
                    self.txt_bank_name.selectAll()
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
        self.btn_cheque.setChecked(method == "CHEQUE")
        if hasattr(self, 'cheque_frame'):
            self.cheque_frame.setVisible(method == "CHEQUE")
            if method == "CHEQUE":
                self.txt_cheque_no.setFocus()
                self.txt_cheque_no.selectAll()
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
        if self.payment_mode == "multiple":
            self.calculate_multi_change()
            try:
                cash_val = Decimal(self.txt_multi_cash.text().strip() or "0")
            except Exception:
                cash_val = Decimal('0.00')
            try:
                sec_val = Decimal(self.txt_multi_sec.text().strip() or "0")
            except Exception:
                sec_val = Decimal('0.00')

            self.payment_method = "MULTIPLE"
            self.split_payments = {
                "cash": float(cash_val),
                "secondary_method": self.split_secondary_method,
                "secondary_amount": float(sec_val),
                "secondary_ref": self.txt_multi_ref.text().strip()
            }
        else:
            self.calculate_change()
            self.split_payments = None

        if self.payment_method == "CHEQUE":
            ch_no = self.txt_cheque_no.text().strip()
            if not ch_no:
                QMessageBox.warning(
                    self,
                    "Cheque Number Required",
                    "Please enter the Cheque Number before completing payment."
                )
                self.txt_cheque_no.setFocus()
                return
            self.cheque_no = ch_no
            self.bank_name = self.txt_bank_name.text().strip()
            self.cheque_date = self.txt_cheque_date.text().strip() or datetime.now().strftime("%Y-%m-%d")
        else:
            self.cheque_no = ""
            self.bank_name = ""
            self.cheque_date = ""

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

        if hasattr(self, 'txt_discount') and self.txt_discount.hasFocus():
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Down):
                if self.payment_mode == "single":
                    cur_idx = self.methods.index(self.payment_method) if self.payment_method in self.methods else 0
                    self.method_buttons[cur_idx].setFocus()
                else:
                    self.txt_multi_cash.setFocus()
                    self.txt_multi_cash.selectAll()
                return
        elif not self.txt_paid.hasFocus() and (not hasattr(self, 'txt_multi_cash') or not self.txt_multi_cash.hasFocus()) and (not hasattr(self, 'txt_multi_sec') or not self.txt_multi_sec.hasFocus()):
            if key == Qt.Key.Key_Up:
                if hasattr(self, 'txt_discount'):
                    self.txt_discount.setFocus()
                    self.txt_discount.selectAll()
                return
            elif key in (Qt.Key.Key_Right, Qt.Key.Key_Tab) and self.payment_mode == "single":
                cur_idx = self.methods.index(self.payment_method)
                next_idx = (cur_idx + 1) % len(self.methods)
                self.set_method(self.methods[next_idx])
                self.method_buttons[next_idx].setFocus()
                return
            elif key in (Qt.Key.Key_Left, Qt.Key.Key_Backtab) and self.payment_mode == "single":
                cur_idx = self.methods.index(self.payment_method)
                prev_idx = (cur_idx - 1) % len(self.methods)
                self.set_method(self.methods[prev_idx])
                self.method_buttons[prev_idx].setFocus()
                return
            elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Down):
                if self.payment_mode == "single":
                    self.txt_paid.setFocus()
                    self.txt_paid.selectAll()
                else:
                    self.txt_multi_cash.setFocus()
                    self.txt_multi_cash.selectAll()
                return
        else:
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.confirm_payment()
                return
            elif key == Qt.Key.Key_Up:
                if self.payment_mode == "single":
                    cur_idx = self.methods.index(self.payment_method) if self.payment_method in self.methods else 0
                    self.method_buttons[cur_idx].setFocus()
                else:
                    if hasattr(self, 'txt_discount'):
                        self.txt_discount.setFocus()
                        self.txt_discount.selectAll()
                return
        super().keyPressEvent(event)


class StaffSelectDialog(QDialog):
    """
    Dialog allowing cashier to search and pick their active user account.
    Displays synced users from API (admin, shop-staff, delivery man).
    """
    def __init__(self, db: DatabaseManager, sync_worker=None, theme_mode: str = "dark", parent=None):
        super().__init__(parent)
        self.db = db
        self.sync_worker = sync_worker
        self.theme_mode = theme_mode or "dark"
        self.selected_user = None
        self.all_users = []
        self.filtered_users = []

        self.setWindowTitle("Select Active Cashier / Staff (Ctrl+U)")
        self.setMinimumSize(560, 480)
        self.resize(580, 520)
        self.setModal(True)
        self.init_ui()
        self.load_users()

    def init_ui(self):
        t = get_theme_tokens(self.theme_mode)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Header
        h_box = QHBoxLayout()
        lbl_title = QLabel("👤 Select Active Cashier / Staff User")
        lbl_title.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {t['text_heading']};")
        h_box.addWidget(lbl_title)
        h_box.addStretch()

        self.btn_sync_api = QPushButton("🔄 Sync Users from API")
        self.btn_sync_api.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sync_api.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['btn_default_bg']};
                color: {t['accent']};
                border: 1px solid {t['border']};
                border-radius: 5px;
                padding: 4px 10px;
                font-weight: 600;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {t['border']};
            }}
        """)
        self.btn_sync_api.clicked.connect(self._sync_users_now)
        h_box.addWidget(self.btn_sync_api)
        layout.addLayout(h_box)

        lbl_desc = QLabel("Bills and sales will be attributed to the selected user on the system.")
        lbl_desc.setStyleSheet(f"color: {t['text_muted']}; font-size: 11px;")
        layout.addWidget(lbl_desc)

        # Search Bar
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("🔍 Search staff by name, role (admin, shop-staff, delivery man), or email...")
        self.txt_search.setFixedHeight(34)
        self.txt_search.setStyleSheet(f"""
            QLineEdit {{
                background-color: {t['bg_input']};
                color: {t['text_primary']};
                border: 1px solid {t['border']};
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border-color: {t['accent']};
            }}
        """)
        self.txt_search.textChanged.connect(self._apply_filter)
        layout.addWidget(self.txt_search)

        # Users Table
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["ID", "Name", "Role", "Email"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {t['bg_card']};
                alternate-background-color: {t['bg_card_inner']};
                border: 1px solid {t['border']};
                border-radius: 6px;
                color: {t['text_primary']};
                font-size: 12px;
            }}
            QTableWidget::item:selected {{
                background-color: {t['accent']};
                color: #ffffff;
            }}
            QHeaderView::section {{
                background-color: {t['table_header_bg']};
                color: {t['table_header_text']};
                font-weight: bold;
                padding: 6px;
                border: none;
                border-bottom: 1px solid {t['border']};
            }}
        """)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 50)
        self.table.setColumnWidth(2, 120)
        self.table.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.table)

        # Status / Feedback label
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet(f"color: {t['text_muted']}; font-size: 11px;")
        layout.addWidget(self.lbl_status)

        # Buttons
        btn_box = QHBoxLayout()
        self.btn_cancel = QPushButton("Cancel (Esc)")
        self.btn_cancel.setFixedHeight(36)
        self.btn_cancel.setStyleSheet(f"background-color: {t['btn_default_bg']}; color: {t['text_primary']}; border: 1px solid {t['border']}; border-radius: 6px; padding: 6px 14px;")
        self.btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(self.btn_cancel)

        btn_box.addStretch()

        self.btn_select = QPushButton("✓ Select & Activate User [Enter]")
        self.btn_select.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_select.setFixedHeight(36)
        self.btn_select.setStyleSheet(f"background-color: {t['success']}; color: #ffffff; font-weight: bold; border-radius: 6px; padding: 6px 20px; border: none;")
        self.btn_select.clicked.connect(self._confirm_selection)
        btn_box.addWidget(self.btn_select)
        layout.addLayout(btn_box)

    def load_users(self):
        self.all_users = self.db.get_all_users()
        if not self.all_users and self.sync_worker and self.sync_worker.is_online:
            self._sync_users_now()
            self.all_users = self.db.get_all_users()
        self._apply_filter(self.txt_search.text())

    def _apply_filter(self, query: str = ""):
        q = query.strip().lower()
        if not q:
            self.filtered_users = list(self.all_users)
        else:
            self.filtered_users = [
                u for u in self.all_users
                if q in str(u.get("name", "")).lower()
                or q in str(u.get("role", "")).lower()
                or q in str(u.get("email", "")).lower()
                or q in str(u.get("id", ""))
            ]
        self._render_table()

    def _render_table(self):
        self.table.setRowCount(0)
        active_u = self.db.get_active_cashier_user()
        active_id = active_u.get("id")

        for u in self.filtered_users:
            r = self.table.rowCount()
            self.table.insertRow(r)

            # Col 0: ID
            it_id = QTableWidgetItem(str(u.get("id", "")))
            it_id.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            it_id.setData(Qt.ItemDataRole.UserRole, u)
            self.table.setItem(r, 0, it_id)

            # Col 1: Name
            uname = u.get("name", "")
            is_active = (u.get("id") == active_id)
            name_text = f"★ {uname} (Active)" if is_active else uname
            it_name = QTableWidgetItem(name_text)
            f = it_name.font()
            f.setBold(True)
            it_name.setFont(f)
            self.table.setItem(r, 1, it_name)

            # Col 2: Role
            role = str(u.get("role", "staff")).replace("_", "-")
            it_role = QTableWidgetItem(role)
            it_role.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if "admin" in role.lower():
                it_role.setForeground(QColor("#a855f7"))
            elif "delivery" in role.lower():
                it_role.setForeground(QColor("#f59e0b"))
            else:
                it_role.setForeground(QColor("#38bdf8"))
            self.table.setItem(r, 2, it_role)

            # Col 3: Email
            it_email = QTableWidgetItem(u.get("email") or "—")
            self.table.setItem(r, 3, it_email)

            if is_active:
                self.table.selectRow(r)

        if self.table.rowCount() > 0 and self.table.currentRow() < 0:
            self.table.selectRow(0)

    def _sync_users_now(self):
        settings = self.db.get_all_settings()
        tenant = settings.get("tenant_subdomain", "dbl")
        base_domain = settings.get("base_domain", "webxkey.lk")
        token = settings.get("api_token", "")
        terminal = settings.get("terminal_id", "POS-01")

        if self.sync_worker:
            base_url = self.sync_worker.build_base_url(tenant, base_domain)
            headers = self.sync_worker.get_headers(token, terminal)
            count = self.sync_worker.sync_users(base_url, headers)
            self.lbl_status.setText(f"✓ Synced {count} staff users from API ({base_url})")
            self.all_users = self.db.get_all_users()
            self._apply_filter(self.txt_search.text())
        else:
            self.lbl_status.setText("⚠️ Sync worker unavailable.")

    def _confirm_selection(self):
        cur_row = self.table.currentRow()
        if cur_row < 0:
            QMessageBox.warning(self, "Select Cashier", "Please select a staff member from the list.")
            return
        it = self.table.item(cur_row, 0)
        if it:
            u = it.data(Qt.ItemDataRole.UserRole)
            if u:
                self.selected_user = u
                self.db.set_active_cashier_user(u["id"], u["name"], u.get("role", "staff"))
                self.accept()

    def _on_item_double_clicked(self, item):
        self._confirm_selection()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._confirm_selection()
            return
        elif event.key() == Qt.Key.Key_Escape:
            self.reject()
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

        # Global Barcode / QR Scanner Buffer
        self._scan_buffer = ""
        self._scan_timer = QTimer(self)
        self._scan_timer.setSingleShot(True)
        self._scan_timer.setInterval(250)
        self._scan_timer.timeout.connect(self._clear_scan_buffer)

    def _clear_scan_buffer(self):
        self._scan_buffer = ""

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

        if hasattr(self, 'btn_cashier'):
            self.btn_cashier.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {t['text_heading']};
                    font-weight: bold;
                    font-size: 13px;
                    border: 1px dashed {t['border']};
                    border-radius: 6px;
                    padding: 4px 10px;
                }}
                QPushButton:hover {{
                    background-color: {t['btn_default_bg']};
                    border-color: {t['accent']};
                }}
            """)

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

        # Cashier Selector [Ctrl+U]
        t = get_theme_tokens(self.current_theme)
        active_u = self.db.get_active_cashier_user()
        self.current_cashier_id = active_u.get("id", 1)
        self.current_cashier_name = active_u.get("name") or self.db.get_setting("cashier_name", "Admin")
        self.current_cashier_role = active_u.get("role", "admin")
        self.btn_cashier = QPushButton(f"👤 {self.current_cashier_name} [{self.current_cashier_role}] (Ctrl+U)")
        self.lbl_cashier = self.btn_cashier
        self.btn_cashier.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cashier.setToolTip("Click or press [Ctrl+U] to switch active Cashier / Staff user")
        self.btn_cashier.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {t['text_heading']};
                font-weight: bold;
                font-size: 13px;
                border: 1px dashed {t['border']};
                border-radius: 6px;
                padding: 4px 10px;
            }}
            QPushButton:hover {{
                background-color: {t['btn_default_bg']};
                border-color: {t['accent']};
            }}
        """)
        self.btn_cashier.clicked.connect(self.prompt_cashier_select)
        layout.addWidget(self.btn_cashier)

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

    def close_bill_tab(self, index: int, force: bool = False):
        """Closes a bill tab. Offers to Hold/Park the bill if items are present."""
        if not (0 <= index < len(self.tabs)):
            return

        if len(self.tabs) <= 1:
            if not force and self.table.has_valid_items():
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
        if not force and tab_to_close.items and len(tab_to_close.items) > 0:
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
            self.sync_worker.users_synced.connect(self.on_users_synced)

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

    def on_users_synced(self, count: int, message: str):
        self.show_status_bar_message(f"Staff Sync: {message}")
        active_u = self.db.get_active_cashier_user()
        self.current_cashier_id = active_u.get("id", 1)
        self.current_cashier_name = active_u.get("name", "Admin")
        self.current_cashier_role = active_u.get("role", "staff")
        if hasattr(self, 'btn_cashier'):
            self.btn_cashier.setText(f"👤 {self.current_cashier_name} [{self.current_cashier_role}] (Ctrl+U)")

    def trigger_manual_sync(self):
        if self.sync_worker:
            self.sync_worker.request_immediate_sync(sync_products=True, sync_users=True)
            self.show_status_bar_message("Sync triggered for products and users...")

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
        methods = ["CASH", "CARD", "TRANSFER", "CHEQUE"]
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

    # --- Cashier / Staff Selection [Ctrl+U] ---
    def prompt_cashier_select(self):
        """Opens staff selector to switch the active cashier and attribute sales."""
        dlg = StaffSelectDialog(self.db, sync_worker=self.sync_worker, theme_mode=self.current_theme, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_user:
            u = dlg.selected_user
            self.current_cashier_id = u["id"]
            self.current_cashier_name = u["name"]
            self.current_cashier_role = u.get("role", "staff")
            if hasattr(self, 'btn_cashier'):
                self.btn_cashier.setText(f"👤 {u['name']} [{self.current_cashier_role}] (Ctrl+U)")
            self.show_status_bar_message(f"👤 Active Cashier set to: {u['name']} ({self.current_cashier_role})")

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

            extra_disc = getattr(checkout_dlg, 'extra_discount', Decimal('0.00'))
            final_total_discount = getattr(self, 'discount_total', Decimal('0.00')) + extra_disc
            final_grand_total = getattr(checkout_dlg, 'grand_total', self.grand_total)
            active_u = self.db.get_active_cashier_user()
            user_id = active_u.get("id") or getattr(self, "current_cashier_id", 1)
            cashier_name = active_u.get("name") or getattr(self, "current_cashier_name", "Admin")
            cheque_no = getattr(checkout_dlg, 'cheque_no', '')
            bank_name = getattr(checkout_dlg, 'bank_name', '')
            cheque_date = getattr(checkout_dlg, 'cheque_date', '')

            invoice_record = {
                "bill_no": self.current_bill_no,
                "customer_name": self.current_customer,
                "customer_phone": self.current_customer_phone,
                "subtotal": float(self.subtotal),
                "discount": float(final_total_discount),
                "tax": float(self.tax_total),
                "grand_total": float(final_grand_total),
                "paid_amount": float(checkout_dlg.paid_amount),
                "due_amount": float(checkout_dlg.due_amount),
                "payment_method": checkout_dlg.payment_method,
                "split_payments": checkout_dlg.split_payments,
                "items": items,
                "items_json": items,
                "created_at": now_str,
                "sms_sent": 0,
                "user_id": user_id,
                "cashier_name": cashier_name,
                "cheque_no": cheque_no,
                "bank_name": bank_name,
                "cheque_date": cheque_date
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

            self.show_status_bar_message(f"Bill {self.current_bill_no} finalized! (Rs. {final_grand_total:.2f})")

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
        dlg.database_cleared.connect(self._on_database_cleared)
        dlg.exec()

    def _on_settings_saved(self):
        cashier = self.db.get_setting("cashier_name", "Admin")
        role = self.db.get_setting("cashier_role", "admin")
        self.current_cashier_name = cashier
        self.current_cashier_role = role
        if hasattr(self, 'btn_cashier') and self.btn_cashier:
            self.btn_cashier.setText(f"👤 {cashier} [{role}] (Ctrl+U)")
        self.show_status_bar_message("Settings saved.")

    def _on_database_cleared(self):
        self.next_tab_counter = 1
        self.current_bill_no = self.db.get_next_bill_number()
        self.current_customer = "Walk-In"
        self.current_customer_phone = ""
        self.tabs = [
            BillTab(
                tab_id=self.next_tab_counter,
                bill_no=self.current_bill_no,
                customer_name=self.current_customer,
                customer_phone=self.current_customer_phone,
                payment_method="Cash"
            )
        ]
        self.active_tab_idx = 0
        self.table.clear_bill()
        self._load_tab_state(0)
        self.show_status_bar_message("Local database wiped clean. Press [F10] to re-sync all live products.")

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
            "• <b>[Ctrl+U]:</b> Switch Active Cashier / Staff User<br>"
            "• <b>[F9]:</b> Toggle Payment Method (Cash / Card / Transfer / Cheque)<br>"
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

        # Multi-Bill Tab Hotkeys: Ctrl+T, Ctrl+W, Ctrl+U, Ctrl+Tab, Ctrl+Shift+Tab
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_T:
                self.add_new_bill_tab()
                return
            elif key == Qt.Key.Key_W:
                self.close_bill_tab(self.active_tab_idx)
                return
            elif key == Qt.Key.Key_U:
                self.prompt_cashier_select()
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

        # Global USB / Wireless Barcode & QR Scanner Capture
        focus_w = self.focusWidget()
        is_editing_text = isinstance(focus_w, (QLineEdit, QTextEdit, QPlainTextEdit))

        if not is_editing_text:
            text = event.text()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                scanned = self._scan_buffer.strip()
                self._scan_buffer = ""
                if scanned:
                    prod = self.db.get_product_by_code(scanned)
                    if not prod and hasattr(self, 'sync_worker') and self.sync_worker:
                        prod = self.sync_worker.lookup_remote_product(scanned)
                    if prod:
                        cur_row = self.table.rowCount() - 1
                        if cur_row < 0:
                            cur_row = self.table.add_blank_row()
                        name_item = self.table.item(cur_row, COL_NAME)
                        if name_item and name_item.text().strip():
                            cur_row = self.table.add_blank_row()
                        self.table.on_product_selected(cur_row, prod)
                        return
                    else:
                        self.show_status_bar_message(f"✕ Product not found for scanned code: '{scanned}' (Press F10 to sync)")
                        return
            elif text and text.isprintable():
                self._scan_buffer += text
                self._scan_timer.start()

        super().keyPressEvent(event)
