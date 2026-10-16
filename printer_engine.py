"""
printer_engine.py - Customizable thermal receipt engine for FastPOS.
Renders a Jinja2 HTML template (Qt rich-text subset) into a QTextDocument and prints it
silently to an OS printer via QPrinter (80mm / 58mm thermal, A4...) or exports a PDF.
Includes a Code128 barcode of the bill number drawn natively (no Pillow needed).
"""

import json
import math
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from jinja2 import Environment
from PyQt6.QtCore import QMarginsF, QSizeF, Qt, QRectF, QUrl
from PyQt6.QtGui import QImage, QPainter, QColor, QPageSize, QPageLayout, QTextDocument
from PyQt6.QtPrintSupport import QPrinter, QPrinterInfo

try:
    from barcode import Code128
except Exception:  # pragma: no cover
    Code128 = None

from database import get_app_data_dir
APP_DATA_DIR = get_app_data_dir()
RECEIPTS_DIR = os.path.join(APP_DATA_DIR, "receipts")

DEFAULT_BRANDING = {
    "shop_name": "JAFFNA GOLD COVERING",
    "shop_address": "237 KKS ROAD, JAFFNA",
    "shop_phone": "0761919650",
    "shop_hotline": "021 222 85 89",
    "footer_lines": "Thank You for Your Visit!\nReturn will be accepted within 3 days\nVisit Us Again",
}

DEFAULT_PRINT_SETTINGS = {
    "printer_name": "",
    "paper_width_mm": "72",
    "margin_mm": "2",
    "auto_print": "1",
    "receipt_template": "",
}

# NOTE: Qt rich text is used (pt font sizes scale with the printer DPI).
DEFAULT_THERMAL_TEMPLATE = """\
<div style="font-family:Helvetica, Arial, sans-serif; font-size:9pt; color:#000;">
<p align="center" style="margin:0;">
  <span style="font-size:15pt; font-weight:bold;">{{ shop_name }}</span><br>
  <span style="font-weight:bold;">{{ shop_address }}</span><br>
  {% if shop_phone %}<span style="font-weight:bold;">Tel: <u>{{ shop_phone }}</u></span><br>{% endif %}
  {% if shop_hotline %}<span style="font-weight:bold;">Hotline: <u>{{ shop_hotline }}</u></span>{% endif %}
</p>
<table width="100%" cellspacing="0" cellpadding="0"><tr><td style="border-top:1px dashed #000; font-size:3pt;">&nbsp;</td></tr></table>
<table width="100%" cellspacing="0" cellpadding="1" style="font-size:9pt;">
  <tr><td width="38%"><b>Receipt No</b></td><td>: {{ bill_no }}</td></tr>
  <tr><td><b>Date</b></td><td>: {{ date }}</td></tr>
  <tr><td><b>Time</b></td><td>: {{ time }}</td></tr>
  <tr><td><b>Cashier</b></td><td>: {{ cashier }}</td></tr>
</table>
<table width="100%" cellspacing="0" cellpadding="0"><tr><td style="border-top:1px dashed #000; font-size:3pt;">&nbsp;</td></tr></table>
<table width="100%" border="1" cellspacing="0" cellpadding="4" style="border-color:#000; border-collapse:collapse; font-size:9pt;">
  <tr>
    <td width="52%"><b>Item</b></td>
    <td width="14%" align="center"><b>Qty</b></td>
    <td align="right"><b>Sub Total</b></td>
  </tr>
  {% for item in items %}
  <tr>
    <td>
      <b>{{ item.sn }}. {{ item.name }}</b>
      {% if item.show_price %}<br><span style="font-size:7pt;"><b>Price: {{ item.price }}</b></span>{% endif %}
      {% if item.disc_amount_raw > 0 %}<br><span style="font-size:7pt;"><b>Disc: {{ item.disc_amount }} ({{ item.disc_pct }}%)</b></span>{% endif %}
      {% if item.note %}<br><span style="font-size:7pt;"><i><b>({{ item.note }})</b></i></span>{% endif %}
    </td>
    <td align="center">{{ item.qty }}</td>
    <td align="right"><b>{{ item.total }}</b></td>
  </tr>
  {% endfor %}
</table>
<table width="100%" cellspacing="0" cellpadding="0"><tr><td style="font-size:3pt;">&nbsp;</td></tr><tr><td style="border-top:1px dashed #000; font-size:3pt;">&nbsp;</td></tr></table>
<table width="100%" cellspacing="0" cellpadding="1" style="font-size:9pt;">
  <tr><td><b>Total Items</b></td><td align="right"><b>{{ total_items }}</b></td></tr>
  <tr><td><b>Sub Total</b></td><td align="right"><b>{{ subtotal }}</b></td></tr>
  {% if discount_raw > 0 %}<tr><td><b>Discount ({{ discount_pct }}%)</b></td><td align="right"><b>-{{ discount }}</b></td></tr>{% endif %}
  {% if tax_raw > 0 %}<tr><td><b>Tax</b></td><td align="right"><b>{{ tax }}</b></td></tr>{% endif %}
</table>
<table width="100%" cellspacing="0" cellpadding="2">
  <tr><td><span style="font-size:13pt; font-weight:bold;">TOTAL</span></td>
      <td align="right"><span style="font-size:13pt; font-weight:bold;">Rs. {{ grand_total }}</span></td></tr>
</table>
<table width="100%" cellspacing="0" cellpadding="1" style="font-size:9pt;">
  <tr><td><b>RECEIVED</b></td><td align="right"><b>{{ paid_amount }}</b></td></tr>
  {% if due_amount_raw > 0 %}
  <tr><td><span style="font-size:10pt; font-weight:bold;">BALANCE DUE</span></td><td align="right"><span style="font-size:10pt; font-weight:bold;">Rs. {{ due_amount }}</span></td></tr>
  {% else %}
  <tr><td><b>BALANCE</b></td><td align="right"><b>{{ balance_amount }}</b></td></tr>
  {% endif %}
</table>
<table width="100%" cellspacing="0" cellpadding="0"><tr><td style="font-size:3pt;">&nbsp;</td></tr><tr><td style="border-top:1px dashed #000; font-size:3pt;">&nbsp;</td></tr></table>
<table width="100%" cellspacing="0" cellpadding="2" style="font-size:9pt;">
  <tr><td width="45%"><b>Payment Method</b></td><td>: <b>{{ payment_method }}{% if due_amount_raw > 0 %} (DUE SALE){% endif %}</b></td></tr>
  {% if customer_name and customer_name != 'Walk-In' %}
  <tr><td width="45%"><b>Customer</b></td><td>: <b>{{ customer_name }}</b></td></tr>
  {% endif %}
</table>
<table width="100%" cellspacing="0" cellpadding="0"><tr><td style="border-top:1px dashed #000; font-size:3pt;">&nbsp;</td></tr></table>
{% if barcode_img %}
<p align="center" style="margin:4px 0 0 0;"><img src="barcode://bill" width="{{ barcode_w }}" height="{{ barcode_h }}"><br>
<span style="font-size:11pt; font-weight:bold;">{{ barcode_text }}</span></p>
{% endif %}
<p align="center" style="margin:4px 0 0 0; font-weight:bold;">
{% for line in footer_lines %}{{ line }}<br>{% endfor %}
</p>
<table width="100%" cellspacing="0" cellpadding="0">
  <tr><td style="border-top:1px solid #000; font-size:2pt;">&nbsp;</td></tr>
  <tr><td style="border-top:1px solid #000; font-size:2pt;">&nbsp;</td></tr>
</table>
</div>
"""

_env = Environment(autoescape=True)


def fmt_money(value: Any) -> str:
    """12,345 for whole numbers, 12,345.50 otherwise."""
    try:
        v = float(value)
    except Exception:
        return str(value)
    if abs(v - round(v)) < 0.005:
        return f"{int(round(v)):,}"
    return f"{v:,.2f}"


def fmt_qty(value: Any) -> str:
    try:
        v = float(value)
        return str(int(v)) if v == int(v) else f"{v:g}"
    except Exception:
        return str(value)


def make_barcode_image(text: str, bar_height: int = 70, module_px: int = 3) -> Optional[QImage]:
    """Draws a Code128 barcode as a QImage (no Pillow dependency)."""
    if not text or Code128 is None:
        return None
    try:
        modules = Code128(str(text)).build()[0]  # string of '1'/'0'
    except Exception:
        return None
    quiet = 10 * module_px
    width = len(modules) * module_px + quiet * 2
    img = QImage(width, bar_height, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("black"))
    for i, ch in enumerate(modules):
        if ch == "1":
            p.drawRect(quiet + i * module_px, 0, module_px, bar_height)
    p.end()
    return img


class POSPrinterEngine:
    def __init__(self, db):
        self.db = db

    # ---------- settings ----------
    def get_config(self) -> Dict[str, str]:
        cfg = {}
        cfg.update(DEFAULT_BRANDING)
        cfg.update(DEFAULT_PRINT_SETTINGS)
        stored = self.db.get_all_settings()
        for k in list(cfg.keys()):
            if k in stored and stored[k] is not None and stored[k] != "":
                cfg[k] = stored[k]
        return cfg

    def get_template(self) -> str:
        return self.get_config().get("receipt_template") or DEFAULT_THERMAL_TEMPLATE

    # ---------- context ----------
    def build_context(self, inv: Dict[str, Any], paid: Any = None, change: Any = None,
                      cfg: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        cfg = cfg or self.get_config()
        items = inv.get("items")
        if items is None:
            try:
                items = json.loads(inv.get("items_json") or "[]")
            except Exception:
                items = []

        created = str(inv.get("created_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        try:
            dt = datetime.fromisoformat(created.replace("T", " ")[:19])
        except Exception:
            dt = datetime.now()

        rows: List[Dict[str, Any]] = []
        total_qty = 0.0
        for i, it in enumerate(items, 1):
            qty = float(it.get("qty", 1) or 0)
            price = float(it.get("unit_price", 0) or 0)
            disc_pct = float(it.get("discount_percent", 0) or 0)
            disc_amt = qty * price * disc_pct / 100.0
            total_qty += qty
            rows.append({
                "sn": i,
                "name": str(it.get("product_name", "")).upper(),
                "sku": it.get("sku", ""),
                "qty": fmt_qty(qty),
                "price": fmt_money(price),
                "show_price": True,
                "disc_pct": f"{disc_pct:g}",
                "disc_amount": fmt_money(round(disc_amt)),
                "disc_amount_raw": disc_amt,
                "note": it.get("note", ""),
                "total": fmt_money(it.get("line_total", qty * price - disc_amt)),
            })

        subtotal = float(inv.get("subtotal", 0) or 0)
        discount = float(inv.get("discount", 0) or 0)
        tax = float(inv.get("tax", 0) or 0)
        grand = float(inv.get("grand_total", 0) or 0)
        disc_pct_total = (discount / subtotal * 100.0) if subtotal else 0.0
        due_raw = float(inv.get("due_amount", 0.0) or 0.0)
        if paid is not None:
            paid_f = float(paid)
        elif "paid_amount" in inv and inv["paid_amount"] is not None:
            paid_f = float(inv["paid_amount"])
        else:
            paid_f = max(0.0, grand - due_raw)

        if due_raw <= 0 and paid is not None and float(paid) < grand and inv.get("payment_method") == "CREDIT":
            due_raw = max(0.0, grand - paid_f)

        change_f = float(change) if change is not None else max(0.0, paid_f - grand)

        bill_no = str(inv.get("bill_no", ""))
        bill_digits = bill_no.lstrip("#").replace("-", "")
        barcode_text = bill_digits or bill_no

        footer = [l.strip() for l in (cfg.get("footer_lines") or "").splitlines() if l.strip()]
        return {
            "shop_name": cfg["shop_name"], "shop_address": cfg["shop_address"],
            "shop_phone": cfg["shop_phone"], "shop_hotline": cfg["shop_hotline"],
            "shop_logo": "", "footer_lines": footer, "footer_note": " ".join(footer),
            "bill_no": bill_no, "date": dt.strftime("%d-%m-%Y"), "time": dt.strftime("%I:%M %p"),
            "cashier": self.db.get_setting("cashier_name", "Admin"),
            "customer_name": inv.get("customer_name") or "Walk-In",
            "payment_method": inv.get("payment_method", "CASH"),
            "items": rows, "total_items": fmt_qty(total_qty),
            "subtotal": fmt_money(subtotal),
            "discount": fmt_money(discount), "discount_raw": discount,
            "discount_pct": f"{disc_pct_total:.1f}".rstrip("0").rstrip("."),
            "tax": fmt_money(tax), "tax_raw": tax,
            "grand_total": fmt_money(grand),
            "paid_amount": fmt_money(paid_f), "balance_amount": fmt_money(change_f),
            "due_amount": fmt_money(due_raw), "due_amount_raw": due_raw,
            "barcode_img": True, "barcode_text": barcode_text,
            "barcode_w": 200, "barcode_h": 44,
        }

    # ---------- rendering ----------
    def render_html(self, context: Dict[str, Any], template: Optional[str] = None) -> str:
        tpl = _env.from_string(template or self.get_template())
        return tpl.render(**context)

    def build_document(self, inv: Dict[str, Any], paid: Any = None, change: Any = None,
                       template: Optional[str] = None,
                       cfg: Optional[Dict[str, str]] = None) -> QTextDocument:
        ctx = self.build_context(inv, paid, change, cfg)
        html = self.render_html(ctx, template)
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        img = make_barcode_image(ctx["barcode_text"])
        if img is not None:
            doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl("barcode://bill"), img)
        doc.setHtml(html)
        return doc

    # ---------- printing ----------
    def resolve_printer_name(self, wanted: str = "") -> str:
        names = [p.printerName() for p in QPrinterInfo.availablePrinters()]
        if wanted and wanted in names:
            return wanted
        for n in names:
            if "pos" in n.lower() or "thermal" in n.lower():
                return n
        d = QPrinterInfo.defaultPrinter()
        return d.printerName() if not d.isNull() else ""

    def _paint(self, doc: QTextDocument, printer: QPrinter, width_mm: float, margin_mm: float) -> None:
        dpi = printer.resolution()
        doc.documentLayout().setPaintDevice(printer)
        doc.setTextWidth(width_mm / 25.4 * dpi)
        height_mm = doc.size().height() / dpi * 25.4 + 6
        printer.setPageSize(QPageSize(QSizeF(width_mm + 2 * margin_mm, height_mm + 2 * margin_mm),
                                      QPageSize.Unit.Millimeter, "Receipt"))
        printer.setPageMargins(QMarginsF(margin_mm, margin_mm, margin_mm, margin_mm),
                               QPageLayout.Unit.Millimeter)
        doc.setTextWidth(printer.pageLayout().paintRectPixels(dpi).width())
        painter = QPainter(printer)
        doc.drawContents(painter)
        painter.end()

    def export_pdf(self, inv: Dict[str, Any], path: str, paid: Any = None, change: Any = None,
                   template: Optional[str] = None) -> str:
        cfg = self.get_config()
        doc = self.build_document(inv, paid, change, template, cfg)
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(path)
        self._paint(doc, printer, float(cfg["paper_width_mm"]), float(cfg["margin_mm"]))
        return path

    def print_invoice(self, inv: Dict[str, Any], paid: Any = None, change: Any = None,
                      template: Optional[str] = None) -> Tuple[bool, str]:
        """Prints silently to the configured printer; falls back to a PDF in ./receipts."""
        cfg = self.get_config()
        try:
            name = self.resolve_printer_name(cfg.get("printer_name", ""))
            if not name:
                raise RuntimeError("No printer available")
            doc = self.build_document(inv, paid, change, template, cfg)
            printer = QPrinter(QPrinterInfo.printerInfo(name), QPrinter.PrinterMode.HighResolution)
            self._paint(doc, printer, float(cfg["paper_width_mm"]), float(cfg["margin_mm"]))
            return True, f"Printed to {name}"
        except Exception as e:
            try:
                os.makedirs(RECEIPTS_DIR, exist_ok=True)
                safe = str(inv.get("bill_no", "bill")).replace("#", "").replace("/", "-")
                path = os.path.join(RECEIPTS_DIR, f"{safe}.pdf")
                self.export_pdf(inv, path, paid, change, template)
                return False, f"Printer error ({e}). Saved PDF: {path}"
            except Exception as e2:
                return False, f"Print failed: {e} / {e2}"
