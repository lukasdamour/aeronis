#!/usr/bin/env bash
# Builds desktop.py into a standalone executable with PyInstaller.
# Runs inside an isolated venv to avoid PyInstaller scanning the entire
# global pyenv environment (which causes the setuptools/None version bug
# and massively inflates the bundle with matplotlib, IPython, jedi...).
set -euo pipefail

cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"
VENV_DIR="$PROJECT_ROOT/.build-venv"

echo "=== Step 1/4: Creating isolated build venv ==="
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

echo "=== Step 2/4: Installing only required dependencies ==="
pip install --quiet --upgrade pip
pip install --quiet \
    pyinstaller \
    PySide6 \
    "flask>=3.0" \
    "flask-cors>=4.0" \
    "flasgger>=0.9"

# Install the project itself (core/ package) without dev extras
pip install --quiet -e "$PROJECT_ROOT" --no-deps

echo "=== Step 3/4: Building with PyInstaller ==="
rm -rf "$PROJECT_ROOT/build" \
       "$PROJECT_ROOT/dist" \
       "$PROJECT_ROOT/aeronis-desktop.spec"

pyinstaller --onedir --windowed \
    --name aeronis-desktop \
    --add-data "web:web" \
    --add-data "core:core" \
    --paths "$PROJECT_ROOT" \
    --paths "$PROJECT_ROOT/tiles-pipeline" \
    --hidden-import server \
    --hidden-import serve_tiles \
    --hidden-import flask \
    --hidden-import flask_cors \
    --hidden-import flasgger \
    --exclude-module matplotlib \
    --exclude-module numpy \
    --exclude-module IPython \
    --exclude-module jedi \
    --exclude-module pandas \
    --exclude-module scipy \
    --exclude-module PIL \
    --exclude-module pygame \
    desktop.py

echo "=== Step 4/4: Cleaning up build venv ==="
deactivate
rm -rf "$VENV_DIR"

echo ""
echo "Done. App folder: dist/aeronis-desktop/"
echo "To enable offline maps, drop your .mbtiles file at:"
echo "  dist/aeronis-desktop/tiles-pipeline/data/spain.mbtiles"