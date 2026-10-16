"""
ui_settings.py - Multi-Tenant Settings Dialog (F12) for FastPOS.
Configures dynamic tenant subdomains (*.webxkey.lk), local dev endpoints (127.0.0.1:8000),
API Bearer tokens, terminal identification, theme switching (Dark & Light), and live connection testing.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QMessageBox, QFrame, QGridLayout, QProgressBar, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from database import DatabaseManager
from sync_worker import SyncWorker
from theme import get_theme_tokens, apply_theme_to_app
from sms_service import FastPOSSmsService, is_valid_phone, normalize_phone_number


class TestConnectionWorker(QThread):
    finished = pyqtSignal(dict)

    def __init__(self, tenant: str, base_domain: str, token: str, terminal: str):
        super().__init__()
        self.tenant = tenant
        self.base_domain = base_domain
        self.token = token
        self.terminal = terminal

    def run(self):
        result = SyncWorker.test_connection_direct(
            self.tenant, self.base_domain, self.token, self.terminal
        )
        self.finished.emit(result)


class SettingsDialog(QDialog):
    settings_saved = pyqtSignal()
    theme_changed = pyqtSignal(str)

    def __init__(self, db: DatabaseManager, sync_worker: SyncWorker = None, parent=None, theme_mode: str = "dark"):
        super().__init__(parent)
        self.db = db
        self.sync_worker = sync_worker
        self.current_theme = theme_mode or self.db.get_setting("theme", "dark")
        self.auto_sms_enabled = "1"
        self.setWindowTitle("System & Multi-Tenant Settings (F12)")
        self.setFixedSize(620, 740)
        self.setModal(True)
        self.init_ui()
        self.load_settings()
        self.apply_theme(self.current_theme)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 22, 24, 22)

        # Header Title
        self.title_label = QLabel("⚙️ Multi-Tenant Cloud API & System Configuration")
        self.title_label.setObjectName("dialogTitle")
        self.title_label.setStyleSheet("font-size: 17px; font-weight: bold; color: #00e5ff;")
        layout.addWidget(self.title_label)

        self.desc_label = QLabel("Configure your Laravel backend connection, cashier ID, and theme appearance.")
        self.desc_label.setStyleSheet("color: #a0aec0; font-size: 12px;")
        layout.addWidget(self.desc_label)

        # Form Container Frame
        self.form_frame = QFrame()
        self.form_frame.setObjectName("settingsFormCard")
        form_layout = QGridLayout(self.form_frame)
        form_layout.setSpacing(10)
        form_layout.setContentsMargins(14, 14, 14, 14)

        # 0. Theme Mode Switcher
        self.lbl_theme = QLabel("Theme Mode:")
        self.lbl_theme.setStyleSheet("font-weight: 600;")
        
        theme_box = QHBoxLayout()
        theme_box.setSpacing(8)
        self.btn_theme_dark = QPushButton("🌙 Dark Mode")
        self.btn_theme_dark.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_theme_dark.setFixedHeight(34)
        self.btn_theme_dark.clicked.connect(lambda: self.switch_theme("dark"))

        self.btn_theme_light = QPushButton("☀️ Light Mode")
        self.btn_theme_light.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_theme_light.setFixedHeight(34)
        self.btn_theme_light.clicked.connect(lambda: self.switch_theme("light"))

        theme_box.addWidget(self.btn_theme_dark)
        theme_box.addWidget(self.btn_theme_light)
        theme_box.addStretch()

        form_layout.addWidget(self.lbl_theme, 0, 0)
        form_layout.addLayout(theme_box, 0, 1)

        # 1. Tenant Subdomain / Server URL
        self.lbl_tenant = QLabel("Server URL:")
        self.lbl_tenant.setStyleSheet("font-weight: 600;")
        
        url_box = QVBoxLayout()
        url_box.setSpacing(4)

        self.txt_tenant = QLineEdit()
        self.txt_tenant.setPlaceholderText("e.g. http://127.0.0.1:8000  or  https://jaffnagold.webxkey.lk")
        self.txt_tenant.textChanged.connect(self.update_url_preview)
        url_box.addWidget(self.txt_tenant)

        # 1-Click Local Dev Helper Button
        local_row = QHBoxLayout()
        self.btn_use_local = QPushButton("⚡ Use Local Laravel (http://127.0.0.1:8000)")
        self.btn_use_local.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_use_local.setFixedHeight(28)
        self.btn_use_local.setToolTip("Click to autofill local Laravel artisan serve URL")
        self.btn_use_local.clicked.connect(self.set_local_server_url)
        local_row.addWidget(self.btn_use_local)
        local_row.addStretch()
        url_box.addLayout(local_row)

        form_layout.addWidget(self.lbl_tenant, 1, 0)
        form_layout.addLayout(url_box, 1, 1)

        # Base Domain (hidden internal fallback)
        self.txt_base = QLineEdit("webxkey.lk")
        self.txt_base.hide()
        self.txt_base.textChanged.connect(self.update_url_preview)

        # Dynamic URL Preview
        self.lbl_preview = QLabel("API Base URL:")
        self.lbl_preview.setStyleSheet("color: #a0aec0; font-size: 11px;")
        self.lbl_url_preview = QLabel()
        self.lbl_url_preview.setStyleSheet("color: #00e5ff; font-family: monospace; font-size: 11px;")
        form_layout.addWidget(self.lbl_preview, 2, 0)
        form_layout.addWidget(self.lbl_url_preview, 2, 1)

        # 3. API Bearer Token
        self.lbl_token = QLabel("API Token / Key:")
        self.lbl_token.setStyleSheet("font-weight: 600;")
        token_box = QHBoxLayout()
        self.txt_token = QLineEdit()
        self.txt_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_token.setPlaceholderText("Laravel Sanctum API Bearer Token (optional for local)")
        self.btn_toggle_token = QPushButton("👁")
        self.btn_toggle_token.setFixedWidth(40)
        self.btn_toggle_token.setFixedHeight(34)
        self.btn_toggle_token.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_token.clicked.connect(self.toggle_token_visibility)
        token_box.addWidget(self.txt_token)
        token_box.addWidget(self.btn_toggle_token)
        form_layout.addWidget(self.lbl_token, 3, 0)
        form_layout.addLayout(token_box, 3, 1)

        # 4. Terminal ID
        self.lbl_terminal = QLabel("Terminal / Counter ID:")
        self.lbl_terminal.setStyleSheet("font-weight: 600;")
        self.txt_terminal = QLineEdit()
        self.txt_terminal.setPlaceholderText("e.g. POS-01, COUNTER-A")
        form_layout.addWidget(self.lbl_terminal, 4, 0)
        form_layout.addWidget(self.txt_terminal, 4, 1)

        # 5. Cashier Name
        self.lbl_cashier = QLabel("Default Cashier:")
        self.lbl_cashier.setStyleSheet("font-weight: 600;")
        self.txt_cashier = QLineEdit()
        self.txt_cashier.setPlaceholderText("e.g. Admin, John, Saman")
        form_layout.addWidget(self.lbl_cashier, 5, 0)
        form_layout.addWidget(self.txt_cashier, 5, 1)

        # 6. Auto-Send Customer SMS
        self.lbl_sms_toggle = QLabel("Auto SMS Receipts:")
        self.lbl_sms_toggle.setStyleSheet("font-weight: 600;")
        
        sms_btn_box = QHBoxLayout()
        sms_btn_box.setSpacing(8)
        self.btn_sms_on = QPushButton("🟢 Enabled (ON)")
        self.btn_sms_on.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sms_on.setFixedHeight(34)
        self.btn_sms_on.clicked.connect(lambda: self.set_sms_enabled("1"))

        self.btn_sms_off = QPushButton("⚪ Disabled (OFF)")
        self.btn_sms_off.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sms_off.setFixedHeight(34)
        self.btn_sms_off.clicked.connect(lambda: self.set_sms_enabled("0"))

        sms_btn_box.addWidget(self.btn_sms_on)
        sms_btn_box.addWidget(self.btn_sms_off)
        sms_btn_box.addStretch()

        form_layout.addWidget(self.lbl_sms_toggle, 6, 0)
        form_layout.addLayout(sms_btn_box, 6, 1)

        # 7. SMS Quick Test Tool
        self.lbl_sms_test = QLabel("Test SMS Gateway:")
        self.lbl_sms_test.setStyleSheet("font-weight: 600;")
        
        test_sms_box = QHBoxLayout()
        test_sms_box.setSpacing(8)
        self.txt_test_phone = QLineEdit()
        self.txt_test_phone.setPlaceholderText("Test phone (e.g. 0771234567)")
        
        self.btn_send_test_sms = QPushButton("📨 Send Test")
        self.btn_send_test_sms.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_send_test_sms.setFixedHeight(34)
        self.btn_send_test_sms.clicked.connect(self.send_test_sms)

        test_sms_box.addWidget(self.txt_test_phone)
        test_sms_box.addWidget(self.btn_send_test_sms)

        form_layout.addWidget(self.lbl_sms_test, 7, 0)
        form_layout.addLayout(test_sms_box, 7, 1)

        layout.addWidget(self.form_frame)

        # Test Connection Progress Bar & Status
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.lbl_test_status = QLabel("")
        self.lbl_test_status.setStyleSheet("font-size: 12px; font-weight: 500;")
        self.lbl_test_status.setWordWrap(True)
        layout.addWidget(self.lbl_test_status)

        # Test Button
        self.btn_test = QPushButton("⚡ Test Connection & Sync Products Now")
        self.btn_test.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_test.clicked.connect(self.run_connection_test)
        layout.addWidget(self.btn_test)

        self.btn_designer = QPushButton("🖨️ Receipt & Printer Designer...")
        self.btn_designer.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_designer.clicked.connect(self.open_designer)
        layout.addWidget(self.btn_designer)

        layout.addStretch()

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_save = QPushButton("Save Settings")
        self.btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save.clicked.connect(self.save_settings)
        btn_layout.addWidget(self.btn_save)

        layout.addLayout(btn_layout)

    def set_local_server_url(self):
        self.txt_tenant.setText("http://127.0.0.1:8000")
        self.lbl_test_status.setText("💡 Selected local Laravel development server: http://127.0.0.1:8000")
        t = get_theme_tokens(self.current_theme)
        self.lbl_test_status.setStyleSheet(f"color: {t['accent']}; font-size: 12px;")

    def switch_theme(self, mode: str):
        self.current_theme = mode
        self.db.set_setting("theme", mode)
        app = QApplication.instance()
        if app:
            apply_theme_to_app(app, mode)
        self.apply_theme(mode)
        self.theme_changed.emit(mode)

    def apply_theme(self, mode: str):
        t = get_theme_tokens(mode)
        self.current_theme = mode

        # Dialog Title & Description
        self.title_label.setStyleSheet(f"font-size: 17px; font-weight: bold; color: {t['text_heading']};")
        self.desc_label.setStyleSheet(f"color: {t['text_muted']}; font-size: 12px;")

        # Form Card Container
        self.form_frame.setStyleSheet(f"""
            #settingsFormCard {{
                background-color: {t['bg_card']};
                border: 1px solid {t['border']};
                border-radius: 8px;
            }}
            #settingsFormCard QLabel {{
                background-color: transparent;
                border: none;
                color: {t['text_primary']};
            }}
        """)

        # Theme Buttons
        if mode == "dark":
            self.btn_theme_dark.setStyleSheet("""
                QPushButton {
                    background-color: #00e5ff;
                    color: #0f172a;
                    border: 1px solid #00e5ff;
                    border-radius: 6px;
                    padding: 6px 16px;
                    font-weight: bold;
                }
            """)
            self.btn_theme_light.setStyleSheet("""
                QPushButton {
                    background-color: #252d37;
                    color: #cbd5e1;
                    border: 1px solid #343f4d;
                    border-radius: 6px;
                    padding: 6px 16px;
                    font-weight: 500;
                }
                QPushButton:hover {
                    background-color: #374151;
                    color: #ffffff;
                }
            """)
        else:
            self.btn_theme_dark.setStyleSheet("""
                QPushButton {
                    background-color: #f1f5f9;
                    color: #334155;
                    border: 1px solid #cbd5e1;
                    border-radius: 6px;
                    padding: 6px 16px;
                    font-weight: 500;
                }
                QPushButton:hover {
                    background-color: #e2e8f0;
                    color: #0f172a;
                }
            """)
            self.btn_theme_light.setStyleSheet("""
                QPushButton {
                    background-color: #0284c7;
                    color: #ffffff;
                    border: 1px solid #0284c7;
                    border-radius: 6px;
                    padding: 6px 16px;
                    font-weight: bold;
                }
            """)

        # Local Helper Button
        self.btn_use_local.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['accent_bg']};
                color: {t['accent']};
                border: 1px solid {t['accent']};
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {t['accent']};
                color: {'#0f172a' if mode == 'dark' else '#ffffff'};
            }}
        """)

        self.btn_toggle_token.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['btn_default_bg']};
                color: {t['btn_default_fg']};
                border: 1px solid {t['border']};
                border-radius: 6px;
            }}
        """)

        self.lbl_preview.setStyleSheet(f"color: {t['text_muted']}; font-size: 11px;")
        self.lbl_url_preview.setStyleSheet(f"color: {t['accent']}; font-family: monospace; font-size: 11px; font-weight: bold;")

        # Test Button
        self.btn_test.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['accent_bg']};
                color: {t['accent']};
                border: 1px solid {t['accent']};
                border-radius: 6px;
                padding: 10px;
                font-weight: 600;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {t['accent']};
                color: {'#0f172a' if mode == 'dark' else '#ffffff'};
            }}
        """)

        self.btn_designer.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['btn_default_bg']};
                color: {t['text_primary']};
                border: 1px solid {t['border']};
                border-radius: 6px;
                padding: 8px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {t['border']};
            }}
        """)

        self.btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['btn_default_bg']};
                color: {t['btn_default_fg']};
                border: 1px solid {t['border']};
                border-radius: 6px;
                padding: 8px 20px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {t['border']};
            }}
        """)

        self.btn_save.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['success']};
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 8px 26px;
                font-weight: bold;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {t['success_hover']};
            }}
        """)
        self.update_sms_button_styles()

    def set_sms_enabled(self, val: str):
        self.auto_sms_enabled = str(val)
        self.update_sms_button_styles()

    def update_sms_button_styles(self):
        t = get_theme_tokens(self.current_theme)
        is_on = getattr(self, "auto_sms_enabled", "1") == "1"
        if is_on:
            self.btn_sms_on.setStyleSheet(f"""
                QPushButton {{
                    background-color: {t['success']};
                    color: #ffffff;
                    border: 2px solid {t['success']};
                    border-radius: 6px;
                    padding: 6px 16px;
                    font-weight: bold;
                    font-size: 12px;
                }}
            """)
            self.btn_sms_off.setStyleSheet(f"""
                QPushButton {{
                    background-color: {t['btn_default_bg']};
                    color: {t['text_muted']};
                    border: 1px solid {t['border']};
                    border-radius: 6px;
                    padding: 6px 16px;
                    font-size: 12px;
                }}
                QPushButton:hover {{
                    background-color: {t['border']};
                }}
            """)
        else:
            self.btn_sms_on.setStyleSheet(f"""
                QPushButton {{
                    background-color: {t['btn_default_bg']};
                    color: {t['text_muted']};
                    border: 1px solid {t['border']};
                    border-radius: 6px;
                    padding: 6px 16px;
                    font-size: 12px;
                }}
                QPushButton:hover {{
                    background-color: {t['border']};
                }}
            """)
            self.btn_sms_off.setStyleSheet(f"""
                QPushButton {{
                    background-color: {t['danger']};
                    color: #ffffff;
                    border: 2px solid {t['danger']};
                    border-radius: 6px;
                    padding: 6px 16px;
                    font-weight: bold;
                    font-size: 12px;
                }}
            """)

        self.btn_send_test_sms.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['btn_default_bg']};
                color: {t['accent']};
                border: 1px solid {t['border']};
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {t['accent']};
                color: {'#0f172a' if self.current_theme == 'dark' else '#ffffff'};
            }}
        """)

    def send_test_sms(self):
        phone = self.txt_test_phone.text().strip()
        if not phone:
            QMessageBox.warning(self, "Test SMS", "Please enter a recipient phone number first.")
            return
        if not is_valid_phone(phone):
            QMessageBox.warning(self, "Invalid Phone", "Please enter a valid phone number (e.g. 0771234567).")
            return

        t = get_theme_tokens(self.current_theme)
        self.btn_send_test_sms.setEnabled(False)
        self.lbl_test_status.setText("Sending test SMS...")
        self.lbl_test_status.setStyleSheet(f"color: {t['warning']}; font-size: 12px;")

        norm_phone = normalize_phone_number(phone)
        test_msg = "Hello from FastPOS Terminal! Customer invoice SMS notification test is working successfully."
        ok, msg = FastPOSSmsService.send_sms(norm_phone, test_msg, self.db)
        self.btn_send_test_sms.setEnabled(True)

        if ok:
            self.lbl_test_status.setText(f"✓ {msg}")
            self.lbl_test_status.setStyleSheet(f"color: {t['success']}; font-size: 12px; font-weight: bold;")
        else:
            self.lbl_test_status.setText(f"✕ {msg}")
            self.lbl_test_status.setStyleSheet(f"color: {t['danger']}; font-size: 12px; font-weight: bold;")

    def load_settings(self):
        settings = self.db.get_all_settings()
        self.original_tenant = settings.get("tenant_subdomain", "http://127.0.0.1:8000")
        self.txt_tenant.setText(self.original_tenant)
        self.txt_base.setText("webxkey.lk")
        self.txt_token.setText(settings.get("api_token", ""))
        self.txt_terminal.setText(settings.get("terminal_id", "POS-01"))
        self.txt_cashier.setText(settings.get("cashier_name", "Admin"))
        self.auto_sms_enabled = settings.get("auto_sms_enabled", "1")
        self.set_sms_enabled(self.auto_sms_enabled)
        self.update_url_preview()

    def update_url_preview(self):
        tenant = self.txt_tenant.text().strip() or "127.0.0.1:8000"
        base = self.txt_base.text().strip() or "webxkey.lk"
        if tenant.startswith("http://") or tenant.startswith("https://"):
            url = f"{tenant.rstrip('/')}/api/v1"
        elif "127.0.0.1" in base or "localhost" in base:
            host = base if base.startswith("http") else f"http://{base}"
            url = f"{host.rstrip('/')}/api/v1"
        elif "127.0.0.1" in tenant or "localhost" in tenant:
            host = tenant if tenant.startswith("http") else f"http://{tenant}"
            url = f"{host.rstrip('/')}/api/v1"
        elif "." in tenant:
            url = f"https://{tenant}/api/v1"
        else:
            url = f"https://{tenant}.{base}/api/v1"
        self.lbl_url_preview.setText(url)

    def open_designer(self):
        from ui_receipt_designer import ReceiptDesignerDialog
        ReceiptDesignerDialog(self.db, self).exec()

    def toggle_token_visibility(self):
        if self.txt_token.echoMode() == QLineEdit.EchoMode.Password:
            self.txt_token.setEchoMode(QLineEdit.EchoMode.Normal)
            self.btn_toggle_token.setText("🔒")
        else:
            self.txt_token.setEchoMode(QLineEdit.EchoMode.Password)
            self.btn_toggle_token.setText("👁")

    def run_connection_test(self):
        tenant = self.txt_tenant.text().strip()
        base = self.txt_base.text().strip()
        token = self.txt_token.text().strip()
        terminal = self.txt_terminal.text().strip() or "POS-01"

        if not tenant:
            QMessageBox.warning(self, "Validation", "Please specify a tenant subdomain or server URL first.")
            return

        t = get_theme_tokens(self.current_theme)
        self.btn_test.setEnabled(False)
        self.progress_bar.show()
        self.lbl_test_status.setText("Connecting to remote server...")
        self.lbl_test_status.setStyleSheet(f"color: {t['warning']}; font-size: 12px;")

        self.test_worker = TestConnectionWorker(tenant, base, token, terminal)
        self.test_worker.finished.connect(self.on_test_finished)
        self.test_worker.start()

    def on_test_finished(self, result: dict):
        self.btn_test.setEnabled(True)
        self.progress_bar.hide()
        t = get_theme_tokens(self.current_theme)
        if result.get("success"):
            self.lbl_test_status.setText(f"✓ {result.get('message')}")
            self.lbl_test_status.setStyleSheet(f"color: {t['success']}; font-size: 12px; font-weight: bold;")
            if self.sync_worker:
                self.sync_worker.request_immediate_sync(sync_products=True)
        else:
            msg = result.get('message', 'Failed to reach server.')
            # Provide helpful hint if domain resolution failed
            if "jaffnagold.com" in self.txt_tenant.text() or "Could not resolve" in msg:
                msg += "\n💡 Tip: Your Laravel server is running locally on http://127.0.0.1:8000. Click 'Use Local Laravel' above!"
            self.lbl_test_status.setText(f"✕ {msg}")
            self.lbl_test_status.setStyleSheet(f"color: {t['danger']}; font-size: 12px; font-weight: bold;")

    def save_settings(self):
        new_tenant = self.txt_tenant.text().strip()
        if not new_tenant:
            QMessageBox.warning(self, "Validation", "Server URL cannot be empty.")
            return

        # Safety Guard: Tenant Isolation Check
        if hasattr(self, 'original_tenant') and new_tenant != self.original_tenant:
            can_switch, pending_count = self.db.can_switch_tenant()
            if not can_switch:
                QMessageBox.critical(
                    self,
                    "Tenant Switch Blocked!",
                    f"There are {pending_count} pending offline bills queued for '{self.original_tenant}'.\n\n"
                    "Switching tenants now would cause sales data to be pushed to the wrong client system or lost.\n"
                    "Please connect online and synchronize all offline bills before switching tenants."
                )
                return

        # Persist settings
        self.db.set_setting("tenant_subdomain", new_tenant)
        self.db.set_setting("base_domain", self.txt_base.text().strip() or "webxkey.lk")
        self.db.set_setting("api_token", self.txt_token.text().strip())
        self.db.set_setting("terminal_id", self.txt_terminal.text().strip() or "POS-01")
        self.db.set_setting("cashier_name", self.txt_cashier.text().strip() or "Admin")
        self.db.set_setting("theme", self.current_theme)
        self.db.set_setting("auto_sms_enabled", getattr(self, "auto_sms_enabled", "1"))

        if self.sync_worker:
            self.sync_worker.request_immediate_sync(sync_products=True)

        self.settings_saved.emit()
        self.accept()
