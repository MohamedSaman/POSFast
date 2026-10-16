"""
ui_table.py - High-Speed POS Billing Table & Keyboard Workflow.
Implements custom QTableWidget, QStyledItemDelegate with instant SQLite auto-suggest popup,
strict Enter/Double-Enter state machine, Decimal precision, and F7 row voiding.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Dict, Any, List
from PyQt6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QStyledItemDelegate, QLineEdit,
    QListWidget, QListWidgetItem, QWidget, QHBoxLayout, QPushButton,
    QHeaderView, QAbstractItemView, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QEvent, QRect, QTimer, QObject
from PyQt6.QtGui import QColor, QFont, QPainter, QKeyEvent, QBrush, QPen

from database import DatabaseManager


# Column Definitions
COL_INDEX = 0
COL_NAME = 1
COL_QTY = 2
COL_PRICE = 3
COL_DISC = 4
COL_TAX = 5
COL_TOTAL = 6
COL_ACTION = 7
TOTAL_COLUMNS = 8


def calculate_line_total(qty: float, price: float, disc_pct: float = 0.0, tax_pct: float = 0.0) -> Decimal:
    """Calculates row total with strict Decimal precision."""
    try:
        d_qty = Decimal(str(qty))
        d_price = Decimal(str(price))
        d_disc = Decimal(str(disc_pct))
        d_tax = Decimal(str(tax_pct))

        discount_factor = Decimal('1') - (d_disc / Decimal('100'))
        tax_factor = Decimal('1') + (d_tax / Decimal('100'))

        total = d_qty * d_price * discount_factor * tax_factor
        return total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal('0.00')


class SuggestPopup(QListWidget):
    """Floating auto-suggest popup positioned directly beneath the active editing cell."""
    item_chosen = pyqtSignal(dict)

    def __init__(self, theme_mode: str = "dark", parent=None):
        super().__init__(parent)
        self.theme_mode = theme_mode
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.apply_theme(theme_mode)
        self.itemClicked.connect(self._on_item_clicked)

    def apply_theme(self, mode: str = "dark"):
        self.theme_mode = mode
        if mode == "light":
            self.setStyleSheet("""
                QListWidget {
                    background-color: #ffffff;
                    border: 1px solid #0284c7;
                    border-radius: 6px;
                    color: #0f172a;
                    font-family: -apple-system, "SF Pro Text", "Helvetica Neue", "Segoe UI", Arial, sans-serif;
                    font-size: 13px;
                    padding: 4px;
                }
                QListWidget::item {
                    padding: 8px 12px;
                    border-radius: 4px;
                    margin-bottom: 2px;
                    color: #0f172a;
                }
                QListWidget::item:selected {
                    background-color: #0284c7;
                    color: #ffffff;
                    font-weight: bold;
                }
                QListWidget::item:hover:!selected {
                    background-color: #f1f5f9;
                }
            """)
        else:
            self.setStyleSheet("""
                QListWidget {
                    background-color: #1a202c;
                    border: 1px solid #00e5ff;
                    border-radius: 6px;
                    color: #e2e8f0;
                    font-family: -apple-system, "SF Pro Text", "Helvetica Neue", "Segoe UI", Arial, sans-serif;
                    font-size: 13px;
                    padding: 4px;
                }
                QListWidget::item {
                    padding: 8px 12px;
                    border-radius: 4px;
                    margin-bottom: 2px;
                    color: #e2e8f0;
                }
                QListWidget::item:selected {
                    background-color: #00e5ff;
                    color: #0f172a;
                    font-weight: bold;
                }
                QListWidget::item:hover:!selected {
                    background-color: #2d3748;
                }
            """)

    def _on_item_clicked(self, item: QListWidgetItem):
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            self.item_chosen.emit(data)

    def choose_current(self):
        item = self.currentItem()
        if item:
            self._on_item_clicked(item)


class ProductSearchLineEdit(QLineEdit):
    """Custom editor with live auto-suggest dropdown and keyboard navigation."""
    product_selected = pyqtSignal(dict)
    empty_enter_pressed = pyqtSignal()
    single_enter_confirmed = pyqtSignal(str)

    def __init__(self, db: DatabaseManager, theme_mode: str = "dark", parent=None):
        super().__init__(parent)
        self.db = db
        self.theme_mode = theme_mode
        self.popup = SuggestPopup(theme_mode=theme_mode)
        self.popup.item_chosen.connect(self._apply_product)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(75)  # 75ms debounce so rapid barcode scans do not flash popup
        self._search_timer.timeout.connect(self._do_search)
        self.textChanged.connect(self._on_text_changed)
        self.apply_theme(theme_mode)

    def apply_theme(self, mode: str = "dark"):
        self.theme_mode = mode
        if hasattr(self, 'popup') and self.popup:
            self.popup.apply_theme(mode)
        if mode == "light":
            self.setStyleSheet("""
                QLineEdit {
                    background-color: #ffffff;
                    color: #0f172a;
                    border: 2px solid #0284c7;
                    border-radius: 4px;
                    padding: 4px 8px;
                    font-size: 14px;
                }
            """)
        else:
            self.setStyleSheet("""
                QLineEdit {
                    background-color: #1e242b;
                    color: #ffffff;
                    border: 2px solid #00e5ff;
                    border-radius: 4px;
                    padding: 4px 8px;
                    font-size: 14px;
                }
            """)

    def _on_text_changed(self, text: str):
        query = text.strip()
        if not query:
            self._search_timer.stop()
            self.popup.hide()
            return
        self._search_timer.start()

    def _do_search(self):
        query = self.text().strip()
        if not query:
            self.popup.hide()
            return

        matches = self.db.search_products(query, limit=6)
        if not matches:
            self.popup.hide()
            return

        self.popup.clear()
        for p in matches:
            stock_disp = int(p['stock']) if p['stock'].is_integer() else f"{p['stock']:.1f}"
            sku_disp = f" - [{p['sku']}]" if p.get('sku') else ""
            item_text = f"{p['name']}{sku_disp} - (Rs. {p['price']:.2f}) [{stock_disp} left]"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, p)
            self.popup.addItem(item)

        self.popup.setCurrentRow(0)
        self._position_popup()
        self.popup.show()

    def _position_popup(self):
        global_pos = self.mapToGlobal(QPoint(0, self.height() + 2))
        popup_width = max(self.width(), 380)
        self.popup.setFixedWidth(popup_width)
        item_count = min(self.popup.count(), 6)
        self.popup.setFixedHeight(max(40, item_count * 38 + 12))
        self.popup.move(global_pos)

    def _apply_product(self, product: dict):
        self._search_timer.stop()
        self.popup.hide()
        self.popup.clear()
        self.blockSignals(True)
        self.setText(product["name"])
        self.blockSignals(False)
        self.product_selected.emit(product)

    def _resolve_and_commit(self):
        """Resolves current scanned or typed text immediately."""
        self._search_timer.stop()
        had_popup = self.popup.isVisible() and self.popup.count() > 0
        popup_product = None
        if had_popup:
            top_item = self.popup.currentItem() or self.popup.item(0)
            if top_item:
                popup_product = top_item.data(Qt.ItemDataRole.UserRole)
        self.popup.hide()

        current_text = self.text().strip()
        if not current_text:
            self.empty_enter_pressed.emit()
            return

        # 1. If suggestion popup was showing and had a match, select it instantly (0ms delay)!
        if popup_product:
            self._apply_product(popup_product)
            return

        # 2. Local database lookup (exact barcode, SKU, ID, suffix, prefix)
        found = self.db.get_product_by_code(current_text)
        if found:
            self._apply_product(found)
            return

        # 3. Remote lookup fallback ONLY for barcode/QR/digits if not found locally
        is_code_like = any(c.isdigit() for c in current_text) or "product-image" in current_text or current_text.startswith("]")
        if not found and is_code_like:
            table = self.parent()
            while table and not hasattr(table, 'lookup_remote_product'):
                table = table.parent()
            if table and hasattr(table, 'lookup_remote_product'):
                found = table.lookup_remote_product(current_text)
            if found:
                self._apply_product(found)
                return

        # 4. Custom item name or unresolved code fallback
        self.single_enter_confirmed.emit(current_text)

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()

        if self.popup.isVisible():
            if key == Qt.Key.Key_Down:
                cur = self.popup.currentRow()
                if cur < self.popup.count() - 1:
                    self.popup.setCurrentRow(cur + 1)
                return
            elif key == Qt.Key.Key_Up:
                cur = self.popup.currentRow()
                if cur > 0:
                    self.popup.setCurrentRow(cur - 1)
                return
            elif key == Qt.Key.Key_Escape:
                self._search_timer.stop()
                self.popup.hide()
                return

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._resolve_and_commit()
            return

        super().keyPressEvent(event)

    def hideEvent(self, event):
        try:
            if hasattr(self, '_search_timer'):
                self._search_timer.stop()
            if self.popup:
                self.popup.hide()
        except (RuntimeError, SystemError, Exception):
            pass
        try:
            super().hideEvent(event)
        except (RuntimeError, SystemError, Exception):
            pass


class ProductSuggestDelegate(QStyledItemDelegate):
    """Delegate for Column 1 (Product Name) handling live auto-suggest & watermark."""

    def __init__(self, db: DatabaseManager, table: 'POSBillingTable', parent=None):
        super().__init__(parent)
        self.db = db
        self.table = table

    def eventFilter(self, editor: QObject, event: QEvent) -> bool:
        if isinstance(editor, ProductSearchLineEdit) and event.type() == QEvent.Type.KeyPress:
            key_event = event
            if key_event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                editor._resolve_and_commit()
                return True
            elif key_event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up) and editor.popup.isVisible():
                editor.keyPressEvent(key_event)
                return True
        return super().eventFilter(editor, event)

    def createEditor(self, parent: QWidget, option, index) -> QWidget:
        if index.column() == COL_NAME:
            mode = getattr(self.table, 'theme_mode', 'dark')
            editor = ProductSearchLineEdit(self.db, theme_mode=mode, parent=parent)
            editor.product_selected.connect(
                lambda prod: self.table.on_product_selected(index.row(), prod)
            )
            editor.empty_enter_pressed.connect(
                lambda: self.table.on_empty_enter_pressed(index.row())
            )
            editor.single_enter_confirmed.connect(
                lambda text: self.table.on_single_enter_confirmed(index.row(), text)
            )
            return editor
        return super().createEditor(parent, option, index)

    def setEditorData(self, editor: QWidget, index):
        if isinstance(editor, ProductSearchLineEdit):
            editor.setText(index.data() or "")
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor: QWidget, model, index):
        if isinstance(editor, ProductSearchLineEdit):
            model.setData(index, editor.text())
        else:
            super().setModelData(editor, model, index)

    def paint(self, painter: QPainter, option, index):
        # Draw watermark hint on empty rows
        if index.column() == COL_NAME:
            text = index.data() or ""
            if not text.strip() and index.row() == self.table.rowCount() - 1:
                painter.save()
                painter.setFont(QFont("Helvetica Neue", 11, QFont.Weight.Normal))
                mode = getattr(self.table, 'theme_mode', 'dark')
                painter.setPen(QColor("#64748b" if mode == "dark" else "#94a3b8"))
                rect = option.rect.adjusted(12, 0, -8, 0)
                painter.drawText(
                    rect, 
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    "⏎ Leave blank and press ENTER twice to checkout / finalize bill"
                )
                painter.restore()
                return

        super().paint(painter, option, index)


class POSBillingTable(QTableWidget):
    """Custom High-Performance Billing Grid with strict keyboard navigation."""
    totals_changed = pyqtSignal(Decimal, Decimal, Decimal, Decimal) # subtotal, discount, tax, grand_total
    request_checkout = pyqtSignal()
    status_message = pyqtSignal(str)

    def __init__(self, db: DatabaseManager, theme_mode: str = "dark", parent=None):
        super().__init__(0, TOTAL_COLUMNS, parent)
        self.db = db
        self.theme_mode = theme_mode
        self.empty_enter_count = 0

    def apply_theme(self, mode: str = "dark"):
        self.theme_mode = mode
        self.viewport().update()

        # Auto Discount 10% defaults loaded from DB settings
        try:
            self.auto_discount_enabled = self.db.get_setting("auto_discount_enabled", "1") == "1"
            self.auto_discount_percent = float(self.db.get_setting("auto_discount_percent", "10.0"))
        except Exception:
            self.auto_discount_enabled = True
            self.auto_discount_percent = 10.0

        self._setup_table_ui()
        self.setItemDelegateForColumn(COL_NAME, ProductSuggestDelegate(self.db, self, self))
        self.cellChanged.connect(self._on_cell_changed)

    def _setup_table_ui(self):
        headers = ["#", "Product Name", "Qty", "Price", "Disc (%)", "Tax (%)", "Total", "Action"]
        self.setHorizontalHeaderLabels(headers)

        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked | 
            QAbstractItemView.EditTrigger.SelectedClicked |
            QAbstractItemView.EditTrigger.EditKeyPressed |
            QAbstractItemView.EditTrigger.AnyKeyPressed
        )

        header = self.horizontalHeader()
        header.setSectionResizeMode(COL_INDEX, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_QTY, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(COL_PRICE, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(COL_DISC, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(COL_TAX, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(COL_TOTAL, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(COL_ACTION, QHeaderView.ResizeMode.Fixed)

        self.setColumnWidth(COL_INDEX, 50)
        self.setColumnWidth(COL_QTY, 80)
        self.setColumnWidth(COL_PRICE, 100)
        self.setColumnWidth(COL_DISC, 85)
        self.setColumnWidth(COL_TAX, 85)
        self.setColumnWidth(COL_TOTAL, 110)
        self.setColumnWidth(COL_ACTION, 60)

        self.verticalHeader().setVisible(False)
        self.setShowGrid(True)
        self.setAlternatingRowColors(True)

    def add_blank_row(self) -> int:
        """Appends a new empty row ready for cashier input."""
        row = self.rowCount()
        self.blockSignals(True)
        self.insertRow(row)

        # Col 0: Index
        idx_item = QTableWidgetItem(str(row + 1))
        idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        idx_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.setItem(row, COL_INDEX, idx_item)

        # Col 1: Product Name
        name_item = QTableWidgetItem("")
        name_item.setData(Qt.ItemDataRole.UserRole, None) # will store product dict
        self.setItem(row, COL_NAME, name_item)

        # Col 2: Qty
        qty_item = QTableWidgetItem("")
        qty_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setItem(row, COL_QTY, qty_item)

        # Col 3: Price
        price_item = QTableWidgetItem("")
        price_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setItem(row, COL_PRICE, price_item)

        # Col 4: Disc (%)
        disc_val = str(int(self.auto_discount_percent)) if self.auto_discount_enabled else "0"
        disc_item = QTableWidgetItem(disc_val)
        disc_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setItem(row, COL_DISC, disc_item)

        # Col 5: Tax (%)
        tax_item = QTableWidgetItem("0")
        tax_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setItem(row, COL_TAX, tax_item)

        # Col 6: Total (Read-only)
        total_item = QTableWidgetItem("0.00")
        total_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        total_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.setItem(row, COL_TOTAL, total_item)

        # Col 7: Delete Action Button
        btn_del = QPushButton("🗑")
        btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_del.setToolTip("Delete Row (F7)")
        btn_del.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #e74c3c;
                font-size: 14px;
                border: none;
                padding: 4px;
            }
            QPushButton:hover {
                color: #ff6b6b;
                background-color: rgba(231, 76, 60, 0.15);
                border-radius: 4px;
            }
        """)
        btn_del.clicked.connect(lambda _, r=row: self.delete_row(r))
        self.setCellWidget(row, COL_ACTION, btn_del)

        self.setRowHeight(row, 44)
        self.blockSignals(False)
        return row

    def find_product_row(self, product: dict) -> Optional[int]:
        """Finds row index if product already exists in current bill."""
        p_id = product.get("id")
        p_barcode = product.get("barcode")
        p_sku = product.get("sku")
        p_name = product.get("name", "").strip().lower()

        for r in range(self.rowCount()):
            name_item = self.item(r, COL_NAME)
            if not name_item or not name_item.text().strip():
                continue
            item_prod = name_item.data(Qt.ItemDataRole.UserRole)
            if isinstance(item_prod, dict):
                if p_id and item_prod.get("id") == p_id:
                    return r
                if p_barcode and item_prod.get("barcode") == p_barcode:
                    return r
                if p_sku and item_prod.get("sku") == p_sku:
                    return r
            if name_item.text().strip().lower() == p_name:
                return r
        return None

    def on_product_selected(self, row: int, product: dict, continuous_scan: bool = True):
        """Called when product is picked from suggest popup or exact barcode."""
        self.empty_enter_count = 0

        # Check if product is already in an earlier row
        existing_row = self.find_product_row(product)
        if existing_row is not None and existing_row != row:
            qty_item = self.item(existing_row, COL_QTY)
            curr_qty = float(qty_item.text().strip() or "1") if qty_item else 1.0
            new_qty = curr_qty + 1.0
            if qty_item:
                qty_item.setText(str(int(new_qty) if new_qty.is_integer() else f"{new_qty:.1f}"))
            self.recalculate_row(existing_row)
            self.status_message.emit(f"✓ Scanned {product['name']} (Qty: {new_qty:g})")

            # Reset the current row so no partial/suggest text lingers
            self.blockSignals(True)
            name_item = self.item(row, COL_NAME)
            if name_item:
                name_item.setText("")
                name_item.setData(Qt.ItemDataRole.UserRole, None)
            self.blockSignals(False)

            # Ensure any open editor popup is hidden and cleared
            editor = self.focusWidget()
            if isinstance(editor, ProductSearchLineEdit):
                editor.popup.hide()
                editor.popup.clear()
                editor.blockSignals(True)
                editor.clear()
                editor.blockSignals(False)

            # Re-focus the current row cleanly ready for next scan without showing suggest popup
            QTimer.singleShot(25, lambda: self.focus_cell(row, COL_NAME, edit=True))
            return

        self.blockSignals(True)

        # Store product metadata
        name_item = self.item(row, COL_NAME)
        if name_item:
            name_item.setText(product["name"])
            name_item.setData(Qt.ItemDataRole.UserRole, product)

        # Qty default 1
        qty_item = self.item(row, COL_QTY)
        if qty_item:
            qty_item.setText("1")

        # Price
        price = float(product.get("price", 0.0))
        price_item = self.item(row, COL_PRICE)
        if price_item:
            price_item.setText(f"{price:.2f}")

        # Disc (%) - Default 10% if auto-discount is active
        disc_item = self.item(row, COL_DISC)
        if disc_item and (not disc_item.text().strip() or disc_item.text().strip() == "0"):
            if self.auto_discount_enabled:
                disc_item.setText(str(int(self.auto_discount_percent)))

        # Tax
        tax_pct = float(product.get("tax_percent", 0.0))
        tax_item = self.item(row, COL_TAX)
        if tax_item:
            tax_item.setText(f"{tax_pct:.1f}" if tax_pct else "0")

        self.blockSignals(False)
        self.recalculate_row(row)

        tot_item = self.item(row, COL_TOTAL)
        tot_disp = tot_item.text() if tot_item else "0.00"
        self.status_message.emit(f"✓ Added {product['name']} (Rs. {tot_disp})")

        # Continuous Scan Flow: auto-add next row and focus its product cell ready for next scan
        if continuous_scan:
            if row == self.rowCount() - 1:
                next_row = self.add_blank_row()
            else:
                next_row = row + 1
            QTimer.singleShot(10, lambda: self.focus_cell(next_row, COL_NAME, edit=True))
        else:
            QTimer.singleShot(10, lambda: self.focus_cell(row, COL_QTY, edit=True, select_all=True))

    def lookup_remote_product(self, term: str) -> Optional[dict]:
        """Queries the live cloud backend on demand when an un-cached code is scanned."""
        try:
            win = self.window()
            worker = getattr(win, 'sync_worker', None)
            if worker and hasattr(worker, 'lookup_remote_product'):
                return worker.lookup_remote_product(term)
        except Exception as e:
            print(f"[POSBillingTable] Remote lookup error: {e}")
        return None

    def on_single_enter_confirmed(self, row: int, typed_text: str = ""):
        """Cashier pressed Enter on Product Name with custom text or unresolved code."""
        self.empty_enter_count = 0
        name_item = self.item(row, COL_NAME)
        typed = typed_text.strip() if typed_text else (name_item.text().strip() if name_item else "")

        # Try resolving code via database (exact, suffix, prefix)
        found = self.db.get_product_by_code(typed) if typed else None
        is_code_like = any(c.isdigit() for c in typed) or "product-image" in typed or typed.startswith("]")
        if not found and typed and is_code_like:
            found = self.lookup_remote_product(typed)
        if found:
            self.on_product_selected(row, found)
            return

        # Barcode / SKU-like text that matched no product: reject and clear cell
        if typed and any(c.isdigit() for c in typed) and len(typed) >= 3:
            self.blockSignals(True)
            if name_item:
                name_item.setText("")
                name_item.setData(Qt.ItemDataRole.UserRole, None)
            self.blockSignals(False)

            editor = self.focusWidget()
            if isinstance(editor, QLineEdit):
                editor.blockSignals(True)
                editor.clear()
                editor.blockSignals(False)

            self.status_message.emit(f"✕ Product not found for code: '{typed}' (Press F10 to sync catalog)")
            QTimer.singleShot(20, lambda: self.focus_cell(row, COL_NAME, edit=True))
            return

        # Plain custom text item entered manually by cashier
        if name_item and typed:
            name_item.setText(typed)
        qty_item = self.item(row, COL_QTY)
        if qty_item and not qty_item.text().strip():
            qty_item.setText("1")
        self.recalculate_row(row)
        if row == self.rowCount() - 1:
            next_row = self.add_blank_row()
        else:
            next_row = row + 1
        QTimer.singleShot(10, lambda: self.focus_cell(next_row, COL_NAME, edit=True))

    def on_empty_enter_pressed(self, row: int):
        """Cashier pressed Enter on an empty product cell."""
        self.empty_enter_count += 1
        if self.empty_enter_count >= 2:
            self.empty_enter_count = 0
            if self.has_valid_items():
                self.request_checkout.emit()
            else:
                self.status_message.emit("Cannot checkout: Please add at least 1 item to the bill.")
        else:
            self.status_message.emit("Press ENTER once more to checkout / finalize bill.")

    def recalculate_row(self, row: int):
        """Recalculate line total for the specified row."""
        try:
            qty_text = self.item(row, COL_QTY).text() if self.item(row, COL_QTY) else "0"
            price_text = self.item(row, COL_PRICE).text() if self.item(row, COL_PRICE) else "0"
            disc_text = self.item(row, COL_DISC).text() if self.item(row, COL_DISC) else "0"
            tax_text = self.item(row, COL_TAX).text() if self.item(row, COL_TAX) else "0"

            qty = float(qty_text) if qty_text.strip() else 0.0
            price = float(price_text) if price_text.strip() else 0.0
            disc = float(disc_text) if disc_text.strip() else 0.0
            tax = float(tax_text) if tax_text.strip() else 0.0

            line_tot = calculate_line_total(qty, price, disc, tax)

            total_item = self.item(row, COL_TOTAL)
            if total_item:
                total_item.setText(f"{line_tot:.2f}")

        except Exception as e:
            print(f"[POSBillingTable] Recalculate row error: {e}")

        self.recalculate_grand_totals()

    def recalculate_grand_totals(self):
        """Calculates grand total, gross subtotal, discount, and tax across all rows."""
        gross_subtotal = Decimal('0.00')
        total_discount = Decimal('0.00')
        tax_total = Decimal('0.00')
        grand_total = Decimal('0.00')

        for r in range(self.rowCount()):
            name_item = self.item(r, COL_NAME)
            if not name_item or not name_item.text().strip():
                continue

            try:
                qty = Decimal(self.item(r, COL_QTY).text().strip() or "0")
                price = Decimal(self.item(r, COL_PRICE).text().strip() or "0")
                disc = Decimal(self.item(r, COL_DISC).text().strip() or "0")
                tax_pct = Decimal(self.item(r, COL_TAX).text().strip() or "0")

                gross = qty * price
                disc_amt = gross * (disc / Decimal('100'))
                base = gross - disc_amt
                tax_amount = base * (tax_pct / Decimal('100'))
                line_total = (base + tax_amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

                gross_subtotal += gross
                total_discount += disc_amt
                tax_total += tax_amount
                grand_total += line_total
            except Exception:
                continue

        gross_subtotal = gross_subtotal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        total_discount = total_discount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        tax_total = tax_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        grand_total = grand_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        self.totals_changed.emit(gross_subtotal, total_discount, tax_total, grand_total)

    def _on_cell_changed(self, row: int, col: int):
        if col in (COL_QTY, COL_PRICE, COL_DISC, COL_TAX):
            self.recalculate_row(row)

    def focus_cell(self, row: int, col: int, edit: bool = False, select_all: bool = False):
        """Safely moves focus to cell and optionally triggers inline editing."""
        if 0 <= row < self.rowCount() and 0 <= col < TOTAL_COLUMNS:
            self.setCurrentCell(row, col)
            if edit:
                self.edit(self.model().index(row, col))
                editor = self.focusWidget()
                if isinstance(editor, QLineEdit) and select_all:
                    editor.selectAll()

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        cur_row = self.currentRow()
        cur_col = self.currentColumn()

        # F7: Delete Row
        if key == Qt.Key.Key_F7:
            if cur_row >= 0:
                self.delete_row(cur_row)
            return

        # ENTER / RETURN navigation workflow
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if cur_col == COL_QTY:
                # Confirm Qty -> Move to Price (Col 3)
                self.recalculate_row(cur_row)
                QTimer.singleShot(10, lambda: self.focus_cell(cur_row, COL_PRICE, edit=True, select_all=True))
                return

            elif cur_col == COL_PRICE:
                # Confirm Price -> Calculate row total, append new empty row if needed, focus next Col 1
                self.recalculate_row(cur_row)
                if cur_row == self.rowCount() - 1:
                    next_row = self.add_blank_row()
                else:
                    next_row = cur_row + 1
                QTimer.singleShot(10, lambda: self.focus_cell(next_row, COL_NAME, edit=True))
                return

            elif cur_col in (COL_DISC, COL_TAX):
                self.recalculate_row(cur_row)
                if cur_row == self.rowCount() - 1:
                    next_row = self.add_blank_row()
                else:
                    next_row = cur_row + 1
                QTimer.singleShot(10, lambda: self.focus_cell(next_row, COL_NAME, edit=True))
                return

        super().keyPressEvent(event)

    def delete_row(self, row: int):
        """Removes a row and re-indexes remaining rows."""
        if 0 <= row < self.rowCount():
            self.removeRow(row)
            # Re-index
            for r in range(self.rowCount()):
                idx_item = self.item(r, COL_INDEX)
                if idx_item:
                    idx_item.setText(str(r + 1))
                # Update delete button callback
                w = self.cellWidget(r, COL_ACTION)
                if isinstance(w, QPushButton):
                    w.clicked.disconnect()
                    w.clicked.connect(lambda _, curr=r: self.delete_row(curr))

            self.recalculate_grand_totals()

            # Ensure at least one empty row exists
            if self.rowCount() == 0:
                self.add_blank_row()
                self.focus_cell(0, COL_NAME, edit=True)
            else:
                next_focus_row = min(row, self.rowCount() - 1)
                self.focus_cell(next_focus_row, COL_NAME, edit=True)

    def has_valid_items(self) -> bool:
        """Checks if the bill contains at least 1 valid line item."""
        for r in range(self.rowCount()):
            name_item = self.item(r, COL_NAME)
            qty_item = self.item(r, COL_QTY)
            if name_item and name_item.text().strip():
                try:
                    qty = float(qty_item.text().strip() if qty_item else "0")
                    if qty > 0:
                        return True
                except ValueError:
                    continue
        return False

    def get_bill_items(self) -> List[Dict[str, Any]]:
        """Extracts all line items into standard JSON payload format."""
        items = []
        for r in range(self.rowCount()):
            name_item = self.item(r, COL_NAME)
            if not name_item or not name_item.text().strip():
                continue

            product = name_item.data(Qt.ItemDataRole.UserRole) or {}
            qty = float(self.item(r, COL_QTY).text().strip() or "1")
            price = float(self.item(r, COL_PRICE).text().strip() or "0")
            disc = float(self.item(r, COL_DISC).text().strip() or "0")
            tax = float(self.item(r, COL_TAX).text().strip() or "0")
            tot = float(self.item(r, COL_TOTAL).text().strip() or "0")

            items.append({
                "product_id": product.get("id"),
                "product_remote_id": product.get("id"),
                "sku": product.get("sku", ""),
                "barcode": product.get("barcode", ""),
                "product_name": name_item.text().strip(),
                "qty": qty,
                "unit_price": price,
                "discount_percent": disc,
                "tax_percent": tax,
                "line_total": tot
            })
        return items

    def clear_bill(self):
        """Clears all rows and resets table with a single empty row."""
        self.setRowCount(0)
        self.empty_enter_count = 0
        self.add_blank_row()
        self.focus_cell(0, COL_NAME, edit=True)
        self.recalculate_grand_totals()

    def load_items(self, items: List[Dict[str, Any]]):
        """Restores items (e.g. from Recall held bill)."""
        self.setRowCount(0)
        for item in items:
            row = self.add_blank_row()
            name_item = self.item(row, COL_NAME)
            if name_item:
                name_item.setText(item.get("product_name", ""))
                name_item.setData(Qt.ItemDataRole.UserRole, {
                    "id": item.get("product_id") or item.get("product_remote_id"),
                    "sku": item.get("sku", ""),
                    "barcode": item.get("barcode", ""),
                    "name": item.get("product_name", ""),
                    "price": item.get("unit_price", 0.0),
                    "tax_percent": item.get("tax_percent", 0.0)
                })

            self.item(row, COL_QTY).setText(str(item.get("qty", 1)))
            self.item(row, COL_PRICE).setText(f"{item.get('unit_price', 0.0):.2f}")
            self.item(row, COL_DISC).setText(str(item.get("discount_percent", 0)))
            self.item(row, COL_TAX).setText(str(item.get("tax_percent", 0)))
            self.recalculate_row(row)

        self.add_blank_row()
        self.focus_cell(self.rowCount() - 1, COL_NAME, edit=True)

    def toggle_auto_discount(self) -> bool:
        """Toggles 10% auto-discount mode on or off and updates rows."""
        self.auto_discount_enabled = not self.auto_discount_enabled
        try:
            self.db.set_setting("auto_discount_enabled", "1" if self.auto_discount_enabled else "0")
        except Exception:
            pass
        if self.auto_discount_enabled:
            self.apply_bulk_discount(self.auto_discount_percent)
        else:
            self.apply_bulk_discount(0.0)
        return self.auto_discount_enabled

    def apply_bulk_discount(self, percent: float):
        """Applies a discount percentage across all existing items in the billing table."""
        self.blockSignals(True)
        for r in range(self.rowCount()):
            name_item = self.item(r, COL_NAME)
            if name_item and name_item.text().strip():
                disc_item = self.item(r, COL_DISC)
                if disc_item:
                    disc_item.setText(f"{percent:g}")
                self.recalculate_row(r)
        self.blockSignals(False)
        self.recalculate_grand_totals()
