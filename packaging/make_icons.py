#!/usr/bin/env python3
"""
Generate Windows (.ico) and macOS (.icns) app icons from the square
logo used elsewhere in the app (web/img/logo.jpeg).

Run once locally, or automatically as a step in the desktop build
workflow (.github/workflows/desktop-build.yml) before invoking
PyInstaller, since PyInstaller needs a platform-native icon format,
not a plain .jpeg.

Usage:
    pip install Pillow --break-system-packages
    python packaging/make_icons.py
"""

import os
from PIL import Image

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_LOGO = os.path.join(BASE_DIR, "web", "img", "logo.jpeg")
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
ICNS_SIZES = [16, 32, 64, 128, 256, 512, 1024]
PNG_SIZE = 256


def main():
    if not os.path.isfile(SOURCE_LOGO):
        raise SystemExit(f"Source logo not found: {SOURCE_LOGO}")

    img = Image.open(SOURCE_LOGO).convert("RGBA")

    ico_path = os.path.join(OUT_DIR, "icon.ico")
    img.save(ico_path, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    print(f"wrote {ico_path}")

    icns_path = os.path.join(OUT_DIR, "icon.icns")
    img.save(icns_path, format="ICNS", sizes=[(s, s) for s in ICNS_SIZES])
    print(f"wrote {icns_path}")

    png_path = os.path.join(OUT_DIR, "icon.png")
    img.resize((PNG_SIZE, PNG_SIZE)).save(png_path, format="PNG")
    print(f"wrote {png_path}")


if __name__ == "__main__":
    main()