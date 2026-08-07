# PyInstaller spec for the Aeronis desktop app.
#
# Builds a one-folder distribution (NOT --onefile): QtWebEngine ships
# its own Chromium subprocess and resource files, which onefile mode
# handles poorly (slow startup, fragile extraction). One-folder is the
# standard, reliable approach for QtWebEngine apps.
#
# Usage:
#   pip install -e . PySide6 pyinstaller --break-system-packages
#   python packaging/make_icons.py
#   pyinstaller desktop.spec
#
# Output: dist/Aeronis/ (run the executable inside it).
#
# This file is normally invoked by .github/workflows/desktop-build.yml,
# which builds it on Windows, macOS and Linux runners and attaches the
# results to GitHub Releases.

import sys
from pathlib import Path

block_cipher = None
ROOT = Path(".").resolve()

# server.py (root) and serve_tiles.py (tiles-pipeline/) are imported
# dynamically via sys.path manipulation in desktop.py, not as regular
# top-level imports next to the entry script — so PyInstaller's static
# analysis needs to be told where to look for them.
pathex = [str(ROOT), str(ROOT / "tiles-pipeline")]

hiddenimports = [
    "server",
    "serve_tiles",
    # QtWebEngine's own submodules aren't always picked up by static
    # analysis alone.
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebChannel",
    "PySide6.QtNetwork",
    "PySide6.QtPrintSupport",
]

# web/ is static frontend assets (HTML/CSS/JS/images/fonts) — not
# Python, so it must be copied in explicitly as data rather than
# picked up by import analysis.
datas = [
    (str(ROOT / "web"), "web"),
]

icon_file = None
if sys.platform == "win32":
    icon_candidate = ROOT / "packaging" / "icon.ico"
    if icon_candidate.exists():
        icon_file = str(icon_candidate)
elif sys.platform == "darwin":
    icon_candidate = ROOT / "packaging" / "icon.icns"
    if icon_candidate.exists():
        icon_file = str(icon_candidate)

a = Analysis(
    ["desktop.py"],
    pathex=pathex,
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Aeronis",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="Aeronis",
)

# macOS: also wrap the one-folder distribution as a proper .app bundle
# so it behaves like a native application (Finder double-click, Dock
# icon) rather than a loose folder with an executable inside.
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Aeronis.app",
        icon=icon_file,
        bundle_identifier="com.esiroi.aeronis",
        info_plist={
            "NSHighResolutionCapable": "True",
            "CFBundleShortVersionString": "0.3.0",
        },
    )
