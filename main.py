"""
main.py - Application Entry Point & Dark Slate Theme Stylesheet for FastPOS.
Integrates SQLite, the background synchronization engine, and the PyQt6 billing UI.
"""

import sys
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPalette, QColor

from database import DatabaseManager
from sync_worker import SyncWorker
from ui_main import MainWindow
from theme import apply_theme_to_app, generate_stylesheet, get_theme_tokens


def main():
    # Set High DPI scaling attributes
    if hasattr(Qt.ApplicationAttribute, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt.ApplicationAttribute, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("FastPOS Premium")
    app.setApplicationDisplayName("FastPOS Premium")

    # Set native clean system font across OS
    if sys.platform == "win32":
        app_font = QFont("Segoe UI", 10)
    elif sys.platform == "darwin":
        app_font = QFont(".AppleSystemUIFont", 13)
    else:
        app_font = QFont("Segoe UI", 10)
    app_font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(app_font)

    # Set Window / Application Icon
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
    if os.path.exists(icon_path):
        from PyQt6.QtGui import QIcon
        app.setWindowIcon(QIcon(icon_path))

    # 1. Initialize Database & Seed sample data
    db = DatabaseManager()

    # Log startup configuration
    from logger import log_step, log_info, log_success, LOG_FILE
    tenant = db.get_setting("tenant_subdomain", "https://jaffnagold.com")
    token = db.get_setting("api_token", "")
    cashier = db.get_setting("cashier_name", "Admin")
    terminal = db.get_setting("terminal_id", "POS-01")
    pending = db.get_pending_invoice_count()

    log_step(
        "FastPOS Desktop Terminal Starting", 
        f"Server: {tenant} | Terminal: {terminal} | Cashier: {cashier} | Token: {'[Configured]' if token else '[None]'}"
    )
    log_info(f"Persistent activity log file: {LOG_FILE}")
    if pending > 0:
        log_info(f"Found {pending} offline bill(s) pending sync in SQLite cache.")

    # 2. Load and apply saved Theme (Dark or Light)
    current_theme = db.get_setting("theme", "dark")
    apply_theme_to_app(app, current_theme)

    # 3. Initialize Background Sync Worker (15s interval)
    sync_worker = SyncWorker(db, interval_seconds=15)
    sync_worker.start()

    # 4. Create Main POS Window with initial theme
    main_window = MainWindow(db, sync_worker, initial_theme=current_theme)
    main_window.show()

    # Clean thread exit on app close
    def on_app_exit():
        print("[FastPOS] Shutting down sync worker thread...")
        sync_worker.stop()

    app.aboutToQuit.connect(on_app_exit)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

