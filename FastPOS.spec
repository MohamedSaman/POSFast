# -*- mode: python ; coding: utf-8 -*-
import os

datas_list = [('icon.png', '.')]
if os.path.exists('pos_default.db'):
    datas_list.append(('pos_default.db', '.'))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas_list,
    hiddenimports=['PyQt6', 'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets', 'PyQt6.QtPrintSupport', 'jinja2', 'requests', 'barcode', 'barcode.codex', 'sqlite3'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

icon_path = 'icon.ico' if os.path.exists('icon.ico') else 'icon.png'

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FastPOS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FastPOS',
)
app = BUNDLE(
    coll,
    name='FastPOS.app',
    icon='icon.png',
    bundle_identifier=None,
)
