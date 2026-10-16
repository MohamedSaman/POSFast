"""
theme.py - Theme tokens, stylesheets, and dynamic theme switching for FastPOS Premium.
Supports both Sleek Dark Slate and Clean Modern Light themes.
"""

from typing import Dict, Any
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPalette, QColor, QFont


DARK_TOKENS = {
    "name": "dark",
    # Backgrounds
    "bg_app": "#1e242b",
    "bg_card": "#252d37",
    "bg_card_inner": "#1a202c",
    "bg_input": "#1e242b",
    "bg_input_focus": "#1b2530",
    "bg_dialog": "#1e242b",
    # Borders
    "border": "#343f4d",
    "border_subtle": "#2d3748",
    "border_focus": "#00e5ff",
    # Typography
    "text_primary": "#ffffff",
    "text_secondary": "#cbd5e1",
    "text_muted": "#94a3b8",
    "text_heading": "#00e5ff",
    # Accents & Actions
    "accent": "#00e5ff",
    "accent_hover": "#33ebff",
    "accent_bg": "#2b394a",
    "success": "#2ecc71",
    "success_hover": "#27ae60",
    "success_bg": "rgba(46, 204, 113, 0.2)",
    "warning": "#f39c12",
    "warning_bg": "rgba(243, 156, 18, 0.2)",
    "danger": "#ef4444",
    "danger_bg": "rgba(239, 68, 68, 0.2)",
    # Table Grid
    "table_bg": "#1e242b",
    "table_alt_bg": "#222933",
    "table_grid": "#2d3748",
    "table_header_bg": "#28323e",
    "table_header_fg": "#cbd5e1",
    "table_selected_bg": "#27374a",
    "table_selected_fg": "#ffffff",
    "table_focus_bg": "#233140",
    # Controls
    "scrollbar_bg": "#1e242b",
    "scrollbar_handle": "#374151",
    "scrollbar_hover": "#4b5563",
    "btn_default_bg": "#374151",
    "btn_default_fg": "#e2e8f0",
    "btn_default_hover": "#4b5563",
}

LIGHT_TOKENS = {
    "name": "light",
    # Backgrounds
    "bg_app": "#f1f5f9",          # Slate 100 soft background
    "bg_card": "#ffffff",         # Crisp pure white cards
    "bg_card_inner": "#f8fafc",   # Slate 50 inner containers
    "bg_input": "#ffffff",
    "bg_input_focus": "#f8fafc",
    "bg_dialog": "#f8fafc",
    # Borders
    "border": "#cbd5e1",         # Slate 300 clean borders
    "border_subtle": "#e2e8f0",  # Slate 200 subtle divider
    "border_focus": "#0284c7",   # Sky 600
    # Typography
    "text_primary": "#0f172a",   # Slate 900 high contrast
    "text_secondary": "#334155", # Slate 700
    "text_muted": "#64748b",     # Slate 500
    "text_heading": "#0284c7",   # Sky 600
    # Accents & Actions
    "accent": "#0284c7",         # Sky 600
    "accent_hover": "#0369a1",
    "accent_bg": "#e0f2fe",      # Sky 100
    "success": "#16a34a",        # Green 600
    "success_hover": "#15803d",
    "success_bg": "rgba(22, 163, 74, 0.15)",
    "warning": "#d97706",        # Amber 600
    "warning_bg": "rgba(217, 119, 6, 0.15)",
    "danger": "#dc2626",         # Red 600
    "danger_bg": "rgba(220, 38, 38, 0.15)",
    # Table Grid
    "table_bg": "#ffffff",
    "table_alt_bg": "#f8fafc",
    "table_grid": "#e2e8f0",
    "table_header_bg": "#f1f5f9",
    "table_header_fg": "#1e293b",
    "table_selected_bg": "#e0f2fe",
    "table_selected_fg": "#0369a1",
    "table_focus_bg": "#f0f9ff",
    # Controls
    "scrollbar_bg": "#f1f5f9",
    "scrollbar_handle": "#cbd5e1",
    "scrollbar_hover": "#94a3b8",
    "btn_default_bg": "#f1f5f9",
    "btn_default_fg": "#1e293b",
    "btn_default_hover": "#e2e8f0",
}


def get_theme_tokens(mode: str = "dark") -> Dict[str, str]:
    """Returns the color token dictionary for the specified theme with convenient aliases."""
    is_light = (mode or "").lower() == "light"
    base = LIGHT_TOKENS if is_light else DARK_TOKENS
    tokens = dict(base)
    # Convenience aliases across UI modules
    tokens["bg_main"] = tokens["bg_app"]
    tokens["text_main"] = tokens["text_primary"]
    tokens["input_bg"] = tokens["bg_input"]
    tokens["input_text"] = tokens["text_primary"]
    tokens["btn_secondary_bg"] = tokens["btn_default_bg"]
    tokens["btn_secondary_text"] = tokens["btn_default_fg"]
    tokens["btn_secondary_hover"] = tokens["btn_default_hover"]
    tokens["btn_primary_bg"] = tokens["accent"]
    tokens["btn_primary_text"] = "#ffffff" if is_light else "#000000"
    tokens["btn_primary_hover"] = tokens["accent_hover"]
    tokens["btn_success_bg"] = tokens["success"]
    tokens["btn_success_hover"] = tokens["success_hover"]
    tokens["table_row_alt"] = tokens["table_alt_bg"]
    tokens["table_header_text"] = tokens["table_header_fg"]
    return tokens


def generate_stylesheet(mode: str = "dark") -> str:
    """Generates the comprehensive PyQt6 QSS stylesheet for the application."""
    t = get_theme_tokens(mode)
    
    return f"""
/* Global Reset & Base */
QWidget {{
    background-color: {t['bg_app']};
    color: {t['text_primary']};
    font-family: -apple-system, "SF Pro Text", "Helvetica Neue", "Segoe UI", Arial, sans-serif;
    font-size: 13px;
    selection-background-color: {t['accent']};
    selection-color: {'#0f172a' if mode == 'dark' else '#ffffff'};
}}

QMainWindow {{
    background-color: {t['bg_app']};
}}

/* Reset labels so they do not inherit borders/padding from cards */
QLabel {{
    background-color: transparent;
    border: none;
    padding: 0px;
    margin: 0px;
    color: {t['text_primary']};
}}

/* Status Bar */
QStatusBar {{
    background-color: {t['bg_card']};
    color: {t['text_muted']};
    border-top: 1px solid {t['border']};
    font-size: 12px;
    padding: 2px 8px;
}}

/* Billing Grid & Tables */
QTableWidget {{
    background-color: {t['table_bg']};
    alternate-background-color: {t['table_alt_bg']};
    gridline-color: {t['table_grid']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    outline: none;
    color: {t['text_primary']};
}}

QTableWidget::item {{
    padding: 4px 6px;
    border-bottom: 1px solid {t['border_subtle']};
    color: {t['text_primary']};
}}

QTableWidget::item:focus {{
    border: 2px solid {t['border_focus']};
    background-color: {t['table_focus_bg']};
}}

QTableWidget::item:selected {{
    background-color: {t['table_selected_bg']};
    color: {t['table_selected_fg']};
}}

/* Table Headers */
QHeaderView::section {{
    background-color: {t['table_header_bg']};
    color: {t['table_header_fg']};
    font-weight: 700;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 8px 6px;
    border: none;
    border-bottom: 2px solid {t['border']};
    border-right: 1px solid {t['border_subtle']};
}}

/* Input Fields */
QLineEdit {{
    background-color: {t['bg_input']};
    color: {t['text_primary']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 13px;
}}

QLineEdit:focus {{
    border: 2px solid {t['border_focus']};
    background-color: {t['bg_input_focus']};
}}

/* Buttons */
QPushButton {{
    border: 1px solid {t['border']};
    background-color: {t['btn_default_bg']};
    color: {t['btn_default_fg']};
    border-radius: 6px;
    padding: 8px 14px;
    font-weight: 600;
}}

QPushButton:hover {{
    background-color: {t['btn_default_hover']};
}}

/* ScrollBars */
QScrollBar:vertical {{
    border: none;
    background: {t['scrollbar_bg']};
    width: 8px;
    margin: 0px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical {{
    background: {t['scrollbar_handle']};
    min-height: 20px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical:hover {{
    background: {t['scrollbar_hover']};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    border: none;
    background: {t['scrollbar_bg']};
    height: 8px;
    margin: 0px;
    border-radius: 4px;
}}

QScrollBar::handle:horizontal {{
    background: {t['scrollbar_handle']};
    min-width: 20px;
    border-radius: 4px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {t['scrollbar_hover']};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* Dialogs */
QDialog {{
    background-color: {t['bg_dialog']};
    color: {t['text_primary']};
}}

/* List Widgets (e.g. Parked Bills, Suggestion Dropdowns) */
QListWidget {{
    background-color: {t['bg_card']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    color: {t['text_primary']};
    font-size: 13px;
    padding: 6px;
}}

QListWidget::item {{
    padding: 8px 12px;
    border-bottom: 1px solid {t['border_subtle']};
    border-radius: 4px;
    color: {t['text_primary']};
}}

QListWidget::item:selected {{
    background-color: {t['accent']};
    color: {'#0f172a' if mode == 'dark' else '#ffffff'};
    font-weight: bold;
}}

/* Message Boxes */
QMessageBox {{
    background-color: {t['bg_card']};
    color: {t['text_primary']};
}}

QMessageBox QLabel {{
    color: {t['text_primary']};
    font-size: 13px;
}}

QMessageBox QPushButton {{
    background-color: {t['btn_default_bg']};
    color: {t['btn_default_fg']};
    border: 1px solid {t['border']};
    padding: 6px 16px;
    border-radius: 4px;
    min-width: 70px;
}}

QMessageBox QPushButton:hover {{
    background-color: {t['btn_default_hover']};
}}
"""


def apply_theme_to_app(app: QApplication, mode: str = "dark"):
    """Applies the theme stylesheet and palette to the QApplication instance."""
    stylesheet = generate_stylesheet(mode)
    app.setStyleSheet(stylesheet)
