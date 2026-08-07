#!/usr/bin/env python3
"""
Desktop shell for Aeronis, using PySide6 + QtWebEngine
instead of Tauri.

Unlike the Tauri version, there is no separate sidecar process: the
existing Flask app (server.py) runs in a background thread of this
SAME Python process, and this window just points a QWebEngineView at
it. web/ and server.py are reused completely unchanged.

Usage:
    pip install PySide6 --break-system-packages
    python desktop.py
"""

import os
import sys
import socket
import threading
import time

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtGui import QIcon

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# QtWebEngine's Chromium subprocess refuses to start as root unless its
# sandbox is explicitly disabled (this is a Chromium restriction, not a
# Qt bug) — relevant if this ever runs inside a root-owned container.
# Left untouched for a normal (non-root) desktop user, where the
# sandbox should stay on.
if hasattr(os, "geteuid") and os.geteuid() == 0:
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 5000
TILES_HOST = "127.0.0.1"
TILES_PORT = 8765
DEFAULT_MBTILES_PATH = os.path.join(BASE_DIR, "tiles-pipeline", "data", "spain.mbtiles")


def _wait_for_port(host, port, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def start_flask_server():
    sys.path.insert(0, BASE_DIR)
    import server as flask_server_module

    from werkzeug.serving import make_server

    httpd = make_server(SERVER_HOST, SERVER_PORT, flask_server_module.app)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    print(f"[server] started on http://{SERVER_HOST}:{SERVER_PORT}")
    return httpd


def start_tiles_server():
    try:
        tiles_dir = os.path.join(BASE_DIR, "tiles-pipeline")
        sys.path.insert(0, tiles_dir)
        import serve_tiles

        thread = threading.Thread(
            target=serve_tiles.run_tile_server,
            kwargs={
                "mbtiles_path": DEFAULT_MBTILES_PATH,
                "port": TILES_PORT,
                "host": TILES_HOST,
            },
            daemon=True,
        )
        thread.start()
    except Exception as e:
        print(f"[tiles] failed to start offline tile server: {e}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Aeronis")

        icon_path = os.path.join(BASE_DIR, "web", "img", "logo.jpeg")
        self.setWindowIcon(QIcon(icon_path))

        self.resize(1400, 900)
        self.setMinimumSize(1024, 700)

        self.view = QWebEngineView()
        self.view.setUrl(QUrl(f"http://{SERVER_HOST}:{SERVER_PORT}"))
        self.setCentralWidget(self.view)


def main():
    print("Starting Flask backend...")
    httpd = start_flask_server()

    if not _wait_for_port(SERVER_HOST, SERVER_PORT, timeout=10.0):
        print("[server] WARNING: did not become ready in time, opening window anyway")

    start_tiles_server()

    app = QApplication(sys.argv)
    icon_path = os.path.join(BASE_DIR, "web", "img", "logo.jpeg")
    app.setWindowIcon(QIcon(icon_path))
    
    window = MainWindow()
    window.show()

    exit_code = app.exec()

    httpd.shutdown()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()