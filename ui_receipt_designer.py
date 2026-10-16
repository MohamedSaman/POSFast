"""
ui_receipt_designer.py - Receipt & Printer Designer dialog (opened from F12 Settings).
Branding fields, printer/paper setup, Jinja2 template editor with variable chips,
live preview and Test Print.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QPlainTextEdit,
    QTextBrowser, QComboBox, QSpinBox, QFormLayout, QCheckBox, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtPrintSupport import QPrinterInfo

from database import DatabaseManager
from printer_engine import POSPrinterEngine, DEFAULT_THERMAL_TEMPLATE

SAMPLE_INVOICE = {
    "bill_no": "#2026-0001", "created_at": "2026-10-15 20:13:00",
    "subtotal": 4575, "discount": 775, "tax": 0, "grand_total": 3800,
    "payment_method": "CASH", "customer_name": "Walk-In",
    "items": [{"product_name": "Sangku Pendon Chain", "qty": 1, "unit_price": 4575,
               "discount_percent": 15, "line_total": 3889}],
}

CHIPS = ["{{shop_name}}", "{{bill_no}}", "{{date}}", "{{time}}", "{{cashier}}",
         "{{grand_total}}", "{{payment_method}}", "{{paid_amount}}", "{{balance_amount}}",
         "{% for item in items %}", "{{item.name}}", "{% endfor %}"]

PRESETS = {"Thermal 80mm (72mm)": 72, "Thermal 58mm (48mm)": 48, "A4 (190mm)": 190, "Custom": None}


class ReceiptDesignerDialog(QDialog):
    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db
        self.engine = POSPrinterEngine(db)
        self.setWindowTitle("Receipt & Printer Designer")
        self.resize(1100, 700)
        self._build()
        self._load()
        self.txt_template.textChanged.connect(self._schedule_preview)
        self._refresh_preview()

    def _build(self):
        root = QHBoxLayout(self)

        left = QVBoxLayout()
        form = QFormLayout()
        self.f_name = QLineEdit(); self.f_addr = QLineEdit()
        self.f_phone = QLineEdit(); self.f_hot = QLineEdit()
        self.f_footer = QPlainTextEdit(); self.f_footer.setFixedHeight(70)
        form.addRow("Shop Name", self.f_name)
        form.addRow("Address", self.f_addr)
        form.addRow("Phone", self.f_phone)
        form.addRow("Hotline", self.f_hot)
        form.addRow("Footer lines", self.f_footer)

        self.cmb_printer = QComboBox()
        self.cmb_printer.addItem("(Auto: POS / default)", "")
        for p in QPrinterInfo.availablePrinters():
            self.cmb_printer.addItem(p.printerName(), p.printerName())
        form.addRow("Printer", self.cmb_printer)

        self.cmb_preset = QComboBox(); self.cmb_preset.addItems(list(PRESETS.keys()))
        self.cmb_preset.currentTextChanged.connect(self._on_preset)
        form.addRow("Paper", self.cmb_preset)
        self.sp_width = QSpinBox(); self.sp_width.setRange(30, 300); self.sp_width.setSuffix(" mm")
        self.sp_margin = QSpinBox(); self.sp_margin.setRange(0, 20); self.sp_margin.setSuffix(" mm")
        form.addRow("Printable width", self.sp_width)
        form.addRow("Margin", self.sp_margin)
        self.chk_auto = QCheckBox("Auto-print on checkout")
        form.addRow("", self.chk_auto)
        left.addLayout(form)

        left.addWidget(QLabel("Jinja2 Template (HTML)"))
        self.txt_template = QPlainTextEdit()
        self.txt_template.setStyleSheet("font-family: Menlo, monospace; font-size: 11px;")
        left.addWidget(self.txt_template, 1)

        chips = QHBoxLayout()
        for c in CHIPS[:6]:
            b = QPushButton(c); b.clicked.connect(lambda _, t=c: self.txt_template.insertPlainText(t))
            chips.addWidget(b)
        left.addLayout(chips)
        chips2 = QHBoxLayout()
        for c in CHIPS[6:]:
            b = QPushButton(c); b.clicked.connect(lambda _, t=c: self.txt_template.insertPlainText(t))
            chips2.addWidget(b)
        left.addLayout(chips2)

        btn_default = QPushButton("Reset to Default 80mm Template")
        btn_default.clicked.connect(lambda: self.txt_template.setPlainText(DEFAULT_THERMAL_TEMPLATE))
        left.addWidget(btn_default)
        root.addLayout(left, 3)

        right = QVBoxLayout()
        right.addWidget(QLabel("Live Receipt Preview"))
        self.preview = QTextBrowser()
        self.preview.setStyleSheet("QTextBrowser { background:#fff; }")
        right.addWidget(self.preview, 1)
        row = QHBoxLayout()
        b_test = QPushButton("🖨️ Test Print"); b_test.clicked.connect(self._test_print)
        b_save = QPushButton("Save"); b_save.clicked.connect(self._save)
        b_close = QPushButton("Close"); b_close.clicked.connect(self.reject)
        row.addWidget(b_test); row.addStretch(); row.addWidget(b_save); row.addWidget(b_close)
        right.addLayout(row)
        root.addLayout(right, 2)

        self._timer = QTimer(self); self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._refresh_preview)

    def _on_preset(self, text):
        w = PRESETS.get(text)
        if w:
            self.sp_width.setValue(w)

    def _load(self):
        cfg = self.engine.get_config()
        self.f_name.setText(cfg["shop_name"]); self.f_addr.setText(cfg["shop_address"])
        self.f_phone.setText(cfg["shop_phone"]); self.f_hot.setText(cfg["shop_hotline"])
        self.f_footer.setPlainText(cfg["footer_lines"])
        i = self.cmb_printer.findData(cfg["printer_name"])
        self.cmb_printer.setCurrentIndex(max(0, i))
        self.sp_width.setValue(int(float(cfg["paper_width_mm"])))
        self.sp_margin.setValue(int(float(cfg["margin_mm"])))
        self.chk_auto.setChecked(cfg["auto_print"] == "1")
        self.txt_template.setPlainText(cfg["receipt_template"] or DEFAULT_THERMAL_TEMPLATE)

    def _current_cfg(self):
        cfg = self.engine.get_config()
        cfg.update({
            "shop_name": self.f_name.text(), "shop_address": self.f_addr.text(),
            "shop_phone": self.f_phone.text(), "shop_hotline": self.f_hot.text(),
            "footer_lines": self.f_footer.toPlainText(),
            "printer_name": self.cmb_printer.currentData() or "",
            "paper_width_mm": str(self.sp_width.value()), "margin_mm": str(self.sp_margin.value()),
        })
        return cfg

    def _schedule_preview(self):
        self._timer.start(300)

    def _refresh_preview(self):
        try:
            doc = self.engine.build_document(SAMPLE_INVOICE, 3800, 0,
                                             template=self.txt_template.toPlainText(),
                                             cfg=self._current_cfg())
            doc.setTextWidth(self.sp_width.value() / 25.4 * 96)
            self._doc = doc
            self.preview.setDocument(doc)
        except Exception as e:
            self.preview.setPlainText(f"Template error: {e}")

    def _save(self):
        cfg = self._current_cfg()
        for k in ("shop_name", "shop_address", "shop_phone", "shop_hotline", "footer_lines",
                  "printer_name", "paper_width_mm", "margin_mm"):
            self.db.set_setting(k, cfg[k])
        self.db.set_setting("auto_print", "1" if self.chk_auto.isChecked() else "0")
        tpl = self.txt_template.toPlainText()
        self.db.set_setting("receipt_template", "" if tpl.strip() == DEFAULT_THERMAL_TEMPLATE.strip() else tpl)
        self.accept()

    def _test_print(self):
        self._save_silent()
        ok, msg = self.engine.print_invoice(SAMPLE_INVOICE, 3800, 0)
        (QMessageBox.information if ok else QMessageBox.warning)(self, "Test Print", msg)

    def _save_silent(self):
        cfg = self._current_cfg()
        for k in ("printer_name", "paper_width_mm", "margin_mm"):
            self.db.set_setting(k, cfg[k])
