# FastPOS Premium - Windows Executable (.EXE) & Deployment Guide

This guide explains how to convert **FastPOS** into a Windows `.exe` application, how to install it on your Windows PC, and how to distribute it to your clients.

---

## ⚡ Quickest Way: 1-Click Auto Installer (`INSTALL_FASTPOS.bat`)

A ready-to-distribute package is generated on your Mac at:
👉 **`/Users/admin/Desktop/FastPOS-Windows-Installer.zip`**

### What it does:
1. Extract `FastPOS-Windows-Installer.zip` on **ANY Windows PC**.
2. Double-click **`INSTALL_FASTPOS.bat`**.
3. **It does everything automatically:**
   - Detects if Python is installed; if not, **auto-downloads and installs Python 3.11**.
   - Installs required dependencies (`PyQt6`, `requests`, `jinja2`, `barcode`, etc.).
   - Builds **`FastPOS.exe`**.
   - Creates a **Desktop Shortcut** (`⚡ FastPOS Premium.lnk`) with the app icon.
   - Offers to launch FastPOS immediately!

---

## 🛠️ Alternative Build Options in the ZIP

Inside the extracted folder, you also have:
- **`build_windows.bat`**: Compiles an optimized folder build at `dist\FastPOS\FastPOS.exe`.
- **`build_single_exe.bat`**: Compiles into a single portable `dist\FastPOS.exe` file.
- **`RUN_PORTABLE.bat`**: Quick launcher that runs FastPOS directly without compilation.
- **`installer.iss`**: Inno Setup script that generates a standard Windows wizard setup (`FastPOS_Setup_v1.0.exe`).

---

## ☁️ Method 2: Automatic Cloud Build via GitHub Actions (No Windows PC Needed!)

If you host your code on **GitHub**, you don't even need a Windows computer to build the `.exe`!

1. Push your `POSFast` project to a GitHub repository.
2. The workflow file [`.github/workflows/build-windows.yml`](file:///.github/workflows/build-windows.yml) is already set up.
3. Every time you push (or click **Run Workflow** under GitHub's **Actions** tab), GitHub will:
   - Launch a virtual Microsoft Windows Server.
   - Install dependencies.
   - Compile `FastPOS.exe`.
   - Provide a direct download link under **Actions > Artifacts > FastPOS-Windows-Executable**!
4. You can download the `.exe` directly from your browser on your Mac and send it to your clients.

---

## 📦 How to Install and Run on a Windows PC

### 1. Launching FastPOS
- Double-click **`FastPOS.exe`**.
- It runs completely offline without requiring any terminal or Python installation on client machines!
- The local SQLite database (`pos_local.db`) and receipts directory are created automatically right next to `FastPOS.exe`.

### 2. Initial Setup (Press `[F12]` or Click Settings)
- **Domain URL**: Enter your live Laravel web URL (e.g. `https://yourdomain.com` or `http://192.168.1.100:8000`).
- **Tenant Subdomain**: Enter your branch / tenant code (e.g. `dbl` or `jaffna`).
- **Cashier Name**: Enter cashier / counter name.
- **Auto SMS Toggle**: Enable or disable automated SMS customer alerts.
- **Thermal Printer**: Select your installed Windows 80mm / 58mm thermal receipt printer (e.g. `POS-80`, `Xprinter`, `Epson TM-T88`).

---

## 🖨️ Windows Thermal Printer Tips

1. Connect your thermal receipt printer via USB or Network/Ethernet.
2. Install the printer's official Windows driver (e.g., Xprinter 80mm driver or generic text driver).
3. Open Windows **Settings > Bluetooth & Devices > Printers & Scanners** and verify the printer is listed and can print a Windows test page.
4. In FastPOS, open **Settings `[F12]` > Printer Configuration**:
   - FastPOS automatically detects all Windows printers installed on the PC.
   - Select your printer from the dropdown and set paper width (72mm or 80mm).
   - FastPOS will silently print thermal receipts with ESC/POS barcodes, logos, and custom headers!

---

## 🚀 Creating a Windows Setup Installer (`FastPOS_Setup.exe`)

If you want a professional installer with a desktop icon:
1. Install the free **Inno Setup** compiler: [https://jrsoftware.org/isdl.php](https://jrsoftware.org/isdl.php).
2. Right-click [`installer.iss`](file:///installer.iss) and select **Compile**.
3. It will generate `dist\FastPOS_Setup_v1.0.exe` which gives users a clean setup wizard (*Next > Next > Install*), creates a Desktop Shortcut, and adds FastPOS to the Windows Start Menu!
