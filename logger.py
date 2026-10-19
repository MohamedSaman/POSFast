"""
logger.py - Centralized logging utility for FastPOS Desktop Terminal.
Provides colorful, structured console output and persistent file logging to fastpos.log.
"""

import os
import sys
import logging
from datetime import datetime

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fastpos.log")

# ANSI terminal colors
COLOR_RESET = "\033[0m"
COLOR_CYAN = "\033[36m"
COLOR_GREEN = "\033[32m"
COLOR_YELLOW = "\033[33m"
COLOR_RED = "\033[31m"
COLOR_MAGENTA = "\033[35m"
COLOR_BOLD = "\033[1m"


def _format_time():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _append_to_file(level: str, tag: str, message: str):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{_format_time()}] [{level.upper()}] [{tag}] {message}\n")
    except Exception:
        pass


def log_step(step: str, details: str = "", tag: str = "FASTPOS-API"):
    """Logs a discrete workflow step (e.g. Connecting, Syncing, Pushing)."""
    t_str = _format_time()
    formatted = f"{COLOR_CYAN}{COLOR_BOLD}[{t_str}] [{tag}] 🚀 {step}{COLOR_RESET}"
    if details:
        formatted += f"\n   {COLOR_CYAN}↳ {details}{COLOR_RESET}"
    print(formatted, flush=True)
    _append_to_file("STEP", tag, f"{step} - {details}" if details else step)


def log_info(message: str, tag: str = "FASTPOS"):
    t_str = _format_time()
    print(f"[{t_str}] [{tag}] ℹ️  {message}", flush=True)
    _append_to_file("INFO", tag, message)


def log_success(message: str, tag: str = "FASTPOS-SYNC"):
    t_str = _format_time()
    print(f"{COLOR_GREEN}[{t_str}] [{tag}] ✓ {message}{COLOR_RESET}", flush=True)
    _append_to_file("SUCCESS", tag, message)


def log_warn(message: str, tag: str = "FASTPOS-WARN"):
    t_str = _format_time()
    print(f"{COLOR_YELLOW}[{t_str}] [{tag}] ⚠️  {message}{COLOR_RESET}", flush=True)
    _append_to_file("WARN", tag, message)


def log_error(message: str, exc: Exception = None, tag: str = "FASTPOS-ERROR"):
    t_str = _format_time()
    err_str = f"{message}"
    if exc:
        err_str += f" | Exception: {type(exc).__name__}: {str(exc)}"
    print(f"{COLOR_RED}{COLOR_BOLD}[{t_str}] [{tag}] ✕ {err_str}{COLOR_RESET}", flush=True)
    _append_to_file("ERROR", tag, err_str)
