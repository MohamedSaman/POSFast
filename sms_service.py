"""
sms_service.py - Customer SMS Invoice Notifications for FastPOS.
Integrates with remote Laravel POS API (/api/v1/pos/sms/send) with direct SMSlenz fallback.
Features phone normalization (+94 Sri Lanka standard), auto-formatting of bill summaries,
and background asynchronous dispatch for 0ms cashier latency.
"""

import re
import requests
import urllib3
from typing import Optional, Dict, Any, Tuple
from PyQt6.QtCore import QThread, pyqtSignal
from database import DatabaseManager

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def normalize_phone_number(phone: Optional[str]) -> str:
    """
    Normalizes Sri Lankan phone numbers to the +94XXXXXXXXX international format.
    Handles:
    - 0771234567 -> +94771234567
    - 771234567  -> +94771234567
    - 94771234567 -> +94771234567
    - +94771234567 -> +94771234567
    """
    if not phone:
        return ""
    raw = str(phone).strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""

    # +94 with 11 digits
    if raw.startswith("+94") and len(digits) == 11:
        return f"+{digits}"

    # 94 with 11 digits
    if digits.startswith("94") and len(digits) == 11:
        return f"+{digits}"

    # Local 0XXXXXXXXX (10 digits)
    if digits.startswith("0") and len(digits) == 10:
        return f"+94{digits[1:]}"

    # 9 digits without leading zero (e.g. 771234567)
    if len(digits) == 9 and digits[0] in "123456789":
        return f"+94{digits}"

    # Fallback
    return raw if raw.startswith("+") else f"+{digits}"


def is_valid_phone(phone: Optional[str]) -> bool:
    """Validates if phone has at least 9 numeric digits and is not a placeholder."""
    if not phone:
        return False
    norm = normalize_phone_number(phone)
    if not norm or "xxxxx" in norm.lower():
        return False
    digits = re.sub(r"\D", "", norm)
    return len(digits) >= 9


def format_bill_sms_message(inv: Dict[str, Any], shop_name: str = "Jaffna Gold") -> str:
    """
    Formats the SMS invoice notification matching the web store billing standard.
    """
    name = (inv.get("customer_name") or "Valued Customer").strip()
    if name.lower() in ["walk-in", "walking customer", "online customer", ""]:
        name = "Valued Customer"

    bill_no = inv.get("bill_no", "N/A")
    grand_total = float(inv.get("grand_total", 0.0))
    discount = float(inv.get("discount", 0.0))

    due_amount = float(inv.get("due_amount", 0.0) or 0.0)
    paid_amount = float(inv.get("paid_amount", grand_total - due_amount) if inv.get("paid_amount") is not None else grand_total - due_amount)

    if due_amount > 0:
        return (
            f"Dear {name}, thank you for your purchase at {shop_name}! "
            f"Bill #{bill_no}, Total: Rs.{grand_total:,.2f}, Paid: Rs.{paid_amount:,.2f}, "
            f"Balance Due: Rs.{due_amount:,.2f}. Visit us again!"
        )

    if discount > 0:
        return (
            f"Dear {name}, thank you for your purchase at {shop_name}! "
            f"Bill #{bill_no}, Total: Rs.{grand_total:,.2f} (Saved: Rs.{discount:,.2f}). "
            f"Visit us again!"
        )
    return (
        f"Dear {name}, thank you for your purchase at {shop_name}! "
        f"Bill #{bill_no}, Total: Rs.{grand_total:,.2f}. "
        f"Visit us again!"
    )


class FastPOSSmsService:
    """Service to dispatch customer bill SMS notifications."""

    @staticmethod
    def send_sms(phone: str, message: str, db: DatabaseManager) -> Tuple[bool, str]:
        """
        Sends an SMS message.
        First tries the connected Laravel API endpoint (/api/v1/pos/sms/send).
        If offline or unconfigured, falls back to direct SMSlenz gateway.
        """
        norm_phone = normalize_phone_number(phone)
        if not is_valid_phone(norm_phone):
            return False, "Invalid customer phone number."

        # 1. Try sending via remote Laravel API
        tenant = db.get_setting("tenant_subdomain", "http://127.0.0.1:8000")
        base_domain = db.get_setting("base_domain", "webxkey.lk")
        token = db.get_setting("api_token", "")
        terminal = db.get_setting("terminal_id", "POS-01")

        # Resolve base URL
        if tenant.startswith("http://") or tenant.startswith("https://"):
            clean = tenant.rstrip("/")
            api_base = clean if "/api" in clean else f"{clean}/api/v1"
        elif "127.0.0.1" in tenant or "localhost" in tenant:
            host = tenant if tenant.startswith("http") else f"http://{tenant}"
            api_base = f"{host.rstrip('/')}/api/v1"
        elif "." in tenant:
            api_base = f"https://{tenant}/api/v1"
        else:
            api_base = f"https://{tenant}.{base_domain}/api/v1"

        endpoint = f"{api_base}/pos/sms/send"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Terminal-ID": terminal
        }
        if token.strip():
            headers["Authorization"] = f"Bearer {token.strip()}"

        try:
            resp = requests.post(
                endpoint,
                json={"phone": norm_phone, "message": message},
                headers=headers,
                timeout=5.0,
                verify=False
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success" or (isinstance(data.get("data"), dict) and data["data"].get("success")):
                    return True, f"SMS sent via Laravel API to {norm_phone}"
        except Exception:
            # Backend not reachable; continue to direct SMS gateway fallback
            pass

        # 2. Fallback: Direct SMSlenz gateway
        gateway_url = db.get_setting("sms_send_url", "https://smslenz.lk/api/send-sms")
        api_key = db.get_setting("sms_api_key", "9b60385e-e599-49f3-a30b-fee08a8aa52a")
        user_id = db.get_setting("sms_user_id", "1644")
        sender_id = db.get_setting("sms_sender_id", "Sportynix")

        if gateway_url and api_key and user_id:
            try:
                # SMSlenz expects clean 947XXXXXXXX without '+'
                clean_contact = norm_phone.lstrip("+")
                form_data = {
                    "user_id": user_id,
                    "api_key": api_key,
                    "sender_id": sender_id,
                    "contact": clean_contact,
                    "message": message,
                }
                resp = requests.post(gateway_url, data=form_data, timeout=6.0, verify=False)
                if resp.status_code == 200:
                    res_json = resp.json()
                    if res_json.get("success"):
                        return True, f"SMS sent via SMSlenz to {norm_phone}"
                    return False, res_json.get("message", "Gateway returned failure.")
            except Exception as e:
                return False, f"SMS gateway error: {str(e)}"

        return False, "Could not reach server or SMS gateway."

    @staticmethod
    def send_bill_invoice_sms(inv: Dict[str, Any], db: DatabaseManager) -> Tuple[bool, str]:
        """
        Formats and sends an invoice receipt SMS to the customer if phone is recorded
        and Auto-SMS is enabled.
        """
        # Check setting
        enabled = db.get_setting("auto_sms_enabled", "1") == "1"
        if not enabled:
            return False, "Auto SMS is turned OFF in system settings."

        phone = inv.get("customer_phone")
        if not is_valid_phone(phone):
            return False, "No valid phone number for customer."

        shop_name = db.get_setting("shop_name", "Jaffna Gold")
        message = format_bill_sms_message(inv, shop_name)
        ok, msg = FastPOSSmsService.send_sms(phone, message, db)

        if ok:
            bill_no = inv.get("bill_no")
            if bill_no:
                db.mark_invoice_sms_sent(bill_no)

        return ok, msg


class AsyncSmsWorker(QThread):
    """Background worker thread to dispatch SMS without blocking PyQt UI."""
    finished = pyqtSignal(bool, str)

    def __init__(self, inv_or_phone, message_or_db, db=None):
        super().__init__()
        if isinstance(inv_or_phone, dict):
            self.inv = inv_or_phone
            self.db = message_or_db
            self.phone = None
            self.message = None
        else:
            self.inv = None
            self.phone = inv_or_phone
            self.message = message_or_db
            self.db = db

    def run(self):
        if self.inv is not None:
            ok, msg = FastPOSSmsService.send_bill_invoice_sms(self.inv, self.db)
        else:
            ok, msg = FastPOSSmsService.send_sms(self.phone, self.message, self.db)
        self.finished.emit(ok, msg)
