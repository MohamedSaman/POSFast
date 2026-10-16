A **Jinja2 Template Engine** paired with **PyQt6’s `QPrinter` (for Thermal/A4)** and **Raw Text/ESC-P printing (for Dot Matrix)** allows you to use a single set of `{{variables}}` across all your `*.webxkey.lk` clients while customizing the exact layout, paper size, and printer behavior per shop.

---

## 1. How the Customizable Print Engine Works

```
[Finalized Bill in SQLite] + [Shop Details from *.webxkey.lk]
                         │
                         ▼
         [Jinja2 Variable Replacer Engine]
   (Injects {{shop_name}}, {{bill_no}}, {{items}}, etc.)
                         │
        ┌────────────────┴────────────────┐
        ▼                                 ▼
[Mode 1: HTML/CSS Engine]        [Mode 2: Raw Monospace Engine]
PyQt6 QTextDocument + QPrinter   Win32Print / Raw Socket (ESC/P)
- 58mm / 80mm Thermal Printer    - Dot Matrix (Epson LQ-310 / LX-310)
- A4 / A5 Laser & Inkjet         - Ultra-fast Draft Font (No lag)
- Supports Logos, Bold, Tables   - Exact tractor-feed page tear-off

```

### Why You Need Both Modes (Especially for Dot Matrix)

* **Thermal Printers (58mm / 80mm) & A4 Printers:** Work great with **HTML/CSS templates**. You can customize font sizes, borders, logos, and tables, and PyQt6 (`QPrinter`) renders them directly to the Windows printer driver.
* **Dot Matrix Printers (e.g., Epson LQ-310 / LX-310):** If you send HTML/graphics to a dot matrix printer, Windows prints it as an image—which is very slow, loud, and wears out the ribbon. Instead, Dot Matrix must use a **Plain Text Monospace Template** sent as `RAW` data directly to the printer so it uses its built-in hardware font and finishes printing in 2 seconds.

---

## 2. Universal Template Variables (`{{...}}`)

Your user (or your Laravel backend) can place any of these variables anywhere inside the template design:

| Category | Variable Tag | Description / Example Output |
| --- | --- | --- |
| **Shop / Client Info** *(Synced from `*.webxkey.lk`)* | `{{shop_name}}` | `JAFFNA GOLD HOUSE` or `DBL DISTRIBUTORS` |
|  | `{{shop_address}}` | `No. 45, Hospital Road, Jaffna` |
|  | `{{shop_phone}}` | `021-222-XXXX / 077-XXXXXXX` |
|  | `{{shop_brn}}` | `BRN / VAT Reg No: 114258900-7000` |
|  | `{{shop_logo}}` | Base64 or local path to client logo image |
|  | `{{footer_note}}` | `Goods once sold cannot be returned.` |
| **Bill Metadata** | `{{bill_no}}` | `OFF-2026-0894` |
|  | `{{date}}` | `15-Oct-2026` |
|  | `{{time}}` | `08:15 PM` |
|  | `{{cashier}}` | `Admin` |
|  | `{{customer_name}}` | `Walk-In Customer` |
|  | `{{payment_method}}` | `CASH` / `CARD` / `CREDIT` |
| **Item Loop** *(Repeats for every row)* | `{% for item in items %}` | Starts the product row loop |
|  | `{{item.sn}}` | `1`, `2`, `3` |
|  | `{{item.name}}` | `Apple Red (Local)` |
|  | `{{item.qty}}` | `2` |
|  | `{{item.price}}` | `150.00` |
|  | `{{item.disc}}` | `0.00` |
|  | `{{item.total}}` | `300.00` |
|  | `{% endfor %}` | Ends the product row loop |
| **Bill Totals** | `{{subtotal}}` | `1,250.00` |
|  | `{{discount}}` | `50.00` |
|  | `{{tax}}` | `0.00` |
|  | `{{grand_total}}` | `1,200.00` |
|  | `{{paid_amount}}` | `1,500.00` |
|  | `{{balance_amount}}` | `300.00` |
|  | `{{total_items}}` | `4` |

---

## 3. Customizable Page Setup & Printer Profiles

Inside your Python app’s **`F12 -> Printer & Page Setup`** tab, store these settings in the local SQLite `settings` table:

1. **Printer Device Name:** Dropdown listing all connected Windows/Linux printers (`QPrinterInfo.availablePrinters()`).
2. **Print Engine Mode:**
* `HTML_GDI` (For 58mm Thermal, 80mm Thermal, A4, A5)
* `RAW_DOT_MATRIX` (For Epson LQ/LX Dot Matrix printers)


3. **Paper Size Preset (or Custom `Width mm` x `Height mm`):**
* **Thermal 80mm:** Width `72mm` printable area, Height `Dynamic (Auto-fit)`
* **Thermal 58mm:** Width `48mm` printable area, Height `Dynamic (Auto-fit)`
* **Dot Matrix Half-Invoice (9.5" x 5.5"):** Width `215mm`, Height `140mm` (or `80 columns` width, `33 lines` per page)
* **A4 Full Page:** `210mm x 297mm`


4. **Margins:** `Top`, `Bottom`, `Left`, `Right` (in `mm`).
5. **Auto-Print on Double Enter:** Toggle `ON / OFF` (Prints immediately when cashier presses `Enter` twice on an empty row).

---

## 4. Customizable Template Examples (Using the Same Variables)

### Template A: 80mm Thermal Receipt (HTML Mode)

Each client can edit this HTML inside the app or on `*.webxkey.lk`:

```html
<div style="font-family: 'Courier New', monospace; width: 100%; font-size: 12px;">
  <div style="text-align: center;">
    <h2 style="margin: 0;">{{shop_name}}</h2>
    <div>{{shop_address}}</div>
    <div>Tel: {{shop_phone}}</div>
    <hr style="border-top: 1px dashed #000;">
  </div>

  <div>
    <b>Bill No:</b> {{bill_no}} <span style="float:right;">{{date}} {{time}}</span><br>
    <b>Customer:</b> {{customer_name}} <span style="float:right;">Cashier: {{cashier}}</span>
  </div>
  <hr style="border-top: 1px dashed #000;">

  <table style="width: 100%; font-size: 12px; border-collapse: collapse;">
    <thead>
      <tr style="border-bottom: 1px dashed #000; text-align: left;">
        <th>Item</th>
        <th style="text-align: center;">Qty</th>
        <th style="text-align: right;">Price</th>
        <th style="text-align: right;">Total</th>
      </tr>
    </thead>
    <tbody>
      {% for item in items %}
      <tr>
        <td colspan="4" style="padding-top: 4px;"><b>{{item.sn}}. {{item.name}}</b></td>
      </tr>
      <tr>
        <td></td>
        <td style="text-align: center;">{{item.qty}}</td>
        <td style="text-align: right;">{{item.price}}</td>
        <td style="text-align: right;">{{item.total}}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>

  <hr style="border-top: 1px dashed #000;">
  <div style="text-align: right; font-size: 13px;">
    Subtotal: {{subtotal}}<br>
    Discount: -{{discount}}<br>
    <b style="font-size: 16px;">GRAND TOTAL: {{grand_total}}</b><br>
    Paid ({{payment_method}}): {{paid_amount}} | Balance: {{balance_amount}}
  </div>
  <hr style="border-top: 1px dashed #000;">
  <div style="text-align: center; font-size: 11px;">
    {{footer_note}}<br>
    <b>System by WebXKey.lk</b>
  </div>
</div>

```

### Template B: Dot Matrix Printer 80-Column (Raw Text Mode)

Using Jinja2 string alignment filters (`ljust`, `rjust`), the exact same variables format cleanly for Dot Matrix continuous paper:

```text
{{ shop_name.center(76) }}
{{ shop_address.center(76) }}
{{ ("Tel: " ~ shop_phone).center(76) }}
============================================================================
Invoice No : {{ bill_no.ljust(25) }} Date : {{ date }} {{ time }}
Customer   : {{ customer_name.ljust(25) }} Mode : {{ payment_method }}
----------------------------------------------------------------------------
S.N  Product Description                  Qty       Price          Total
----------------------------------------------------------------------------
{% for item in items -%}
{{ item.sn|string|ljust(4) }} {{ item.name[:34].ljust(35) }} {{ item.qty|string|rjust(5) }} {{ item.price|rjust(11) }} {{ item.total|rjust(14) }}
{% endfor -%}
----------------------------------------------------------------------------
Total Items: {{ total_items|string|ljust(28) }}      SUBTOTAL : {{ subtotal|rjust(14) }}
                                               DISCOUNT : {{ discount|rjust(14) }}
                                            GRAND TOTAL : {{ grand_total|rjust(14) }}
============================================================================
{{ footer_note.center(76) }}


```

*(Note: The `` at the bottom is the ASCII Form Feed character `\x0c`, which tells the Dot Matrix printer to automatically roll the tractor paper to the exact tear-off line!)*

---

## 5. Syncing Client Details & Templates from `*.webxkey.lk`

To avoid configuring every terminal manually, expand your Laravel `/api/v1/pos/settings` endpoint on `dbl.webxkey.lk`, `jaffnagold.webxkey.lk`, and `rnz.webxkey.lk` to return the client's branding and default template:

```json
{
  "shop_name": "RNZ ENTERPRISES",
  "shop_address": "Main Street, Jaffna",
  "shop_phone": "021-2223344",
  "shop_brn": "PV-0029182",
  "footer_note": "Thank you for shopping with RNZ!",
  "default_printer_mode": "RAW_DOT_MATRIX",
  "paper_width_mm": 215,
  "paper_height_mm": 140,
  "custom_template": "..."
}

```

* When the Python app connects to `rnz.webxkey.lk`, it downloads these details into SQLite.
* If the shop needs a local tweak (e.g., PC #1 has an 80mm Thermal printer, while PC #2 at the wholesale counter has an Epson LQ-310 Dot Matrix printer), the technician can override the template and paper size locally inside **`F12 -> Print Designer`**.

---

## 6. Prompt to Give Your Coding Agent (Copy & Paste)

Paste this follow-up prompt into your coding agent to build the customizable print engine and template designer:

```text
Now add a customizable Multi-Printer Bill Printing Engine and Live Template Designer to this POS application.

### 1. INSTALL DEPENDENCIES
Use `Jinja2` for template variable rendering and `PyQt6.QtPrintSupport` (`QPrinter`, `QPrintPreviewDialog`) for HTML/GDI printing, plus `win32print` (on Windows) or raw file/socket printing for Dot Matrix printers.

### 2. CREATE `printer_engine.py`
Build a `POSPrinterEngine` class that supports two modes configurable per terminal:
- **Mode 1: `HTML_GDI` (For 58mm Thermal, 80mm Thermal, A4, A5)**
  - Renders a Jinja2 HTML template using `QTextDocument`.
  - Configures `QPrinter` with custom page size (`width_mm`, `height_mm`) and custom margins (`top`, `bottom`, `left`, `right`) stored in SQLite `settings`.
  - Sends directly to the selected OS printer name without showing a dialog during normal checkout.
- **Mode 2: `RAW_DOT_MATRIX` (For Epson LQ-310 / LX-310 Dot Matrix)**
  - Renders a Jinja2 plain-text monospace template (supporting `.ljust()`, `.rjust()`, `.center()` filters).
  - Sends raw bytes (including ESC/P initialization `\x1b\x40` and Form Feed `\x0c` at the end) directly to the printer queue via `win32print.WritePrinter` (with cross-platform fallback) for instant hardware-font printing.

### 3. UNIVERSAL TEMPLATE VARIABLES
Pass this dictionary context into Jinja2 for every bill:
- Shop variables (loaded from SQLite `settings`, synced from `https://{tenant}.webxkey.lk/api/v1/pos/settings`): `shop_name`, `shop_address`, `shop_phone`, `shop_brn`, `footer_note`, `shop_logo`.
- Bill variables: `bill_no`, `date`, `time`, `cashier`, `customer_name`, `payment_method`, `subtotal`, `discount`, `tax`, `grand_total`, `paid_amount`, `balance_amount`, `total_items`.
- Line items array `items`: `sn`, `name`, `sku`, `qty`, `price`, `disc`, `tax`, `total`.

### 4. UPGRADE `ui_settings.py` (`F12` Settings Dialog)
Add a **"Print & Layout Designer"** tab inside the `F12` Settings window with:
1. **Shop Branding Fields**: Editable fields for `shop_name`, `shop_address`, `shop_phone`, `footer_note` (with a button to "Pull Branding from `*.webxkey.lk`").
2. **Printer & Page Setup**:
   - OS Printer Dropdown (`QPrinterInfo.availablePrinters()`)
   - Print Mode selector: `HTML (Thermal 58mm/80mm & A4)` vs `RAW Text (Dot Matrix)`
   - Preset Selector: `Thermal 80mm`, `Thermal 58mm`, `Dot Matrix Half-Page (215x140mm)`, `A4 (210x297mm)`, or `Custom Size`
   - Numeric spinboxes for `Width (mm)`, `Height (mm)`, and `Margins (mm)`
3. **Custom Template Editor & Live Preview**:
   - Left side: A code editor (`QPlainTextEdit`) showing the active Jinja2 template, plus clickable chips to insert variables like `{{shop_name}}`, `{{bill_no}}`, `{{grand_total}}`.
   - "Load Default 80mm Thermal Template" and "Load Default Dot Matrix Template" buttons.
   - Right side: A **Live Bill Preview** panel (`QTextBrowser`) that renders the current template in real-time using sample dummy bill data as I type, plus a **"Test Print"** button.

### 5. HOOK INTO DOUBLE-ENTER CHECKOUT
When the user triggers checkout (via pressing `Enter` twice on an empty Product Name cell or pressing `F5`), save the invoice to SQLite, immediately trigger `POSPrinterEngine.print_invoice(invoice_data)`, and reset the billing grid for the next customer.

```

