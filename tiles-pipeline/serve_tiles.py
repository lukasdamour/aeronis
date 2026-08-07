#!/usr/bin/env python3
"""
Minimal local server to read a .mbtiles file and expose vector tiles
over HTTP in a format compatible with MapLibre GL JS.

No external dependencies: uses sqlite3 (stdlib) + http.server (stdlib).

Usage : python serve_tiles.py [chemin/vers/fichier.mbtiles] [port]
Default : ./data/spain.mbtiles on port 8765
"""

import sys
import os
import json
import sqlite3
import gzip
import io
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

DEFAULT_MBTILES_PATH = "./data/spain.mbtiles"
DEFAULT_PORT = 8765

# Kept as plain module globals (read by TileHandler on every request, not
# captured at import time) so both the CLI entry point below and
# run_tile_server() can set them before starting the server.
MBTILES_PATH = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MBTILES_PATH
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PORT

# The "Offline Maps" page lets the user pick, among several downloaded
# .mbtiles, which one should actually be served. That choice is written
# by core/offline_maps.py to this small JSON file rather than mutating
# MBTILES_PATH directly, since server.py (which handles that API) and
# this tile server can run as two separate processes (e.g. in Docker) --
# a shared file is the simplest thing that works in every deployment.
#
# Path resolution is duplicated from core/offline_maps.py's
# _state_dir() (not imported, to keep this file's stdlib-only, zero
# dependency design) -- both must agree on where downloads land,
# including inside the packaged desktop app, where the install
# directory itself may not be writable (see that module's docstring).
def _state_dir():
    if not getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(root, "Aeronis", "offline-maps")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Aeronis/offline-maps")
    root = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(root, "aeronis", "offline-maps")


ACTIVE_MAP_FILE = os.path.join(_state_dir(), "active_map.json")


def _current_mbtiles_path():
    """Path to serve right now: the user's active offline map if one was
    picked (and still exists on disk), otherwise the server's default."""
    try:
        with open(ACTIVE_MAP_FILE, "r", encoding="utf-8") as f:
            path = json.load(f).get("path")
        if path and os.path.isfile(path):
            return path
    except (FileNotFoundError, json.JSONDecodeError, KeyError, OSError):
        pass
    return MBTILES_PATH


def get_tile(conn, z, x, y):
    # MBTiles uses TMS schema (inverted y) unlike standard XYZ
    tms_y = (2 ** z - 1) - y
    cur = conn.execute(
        "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
        (z, x, tms_y)
    )
    row = cur.fetchone()
    return row[0] if row else None


def get_metadata(conn):
    cur = conn.execute("SELECT name, value FROM metadata")
    return dict(cur.fetchall())


class TileHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # disable default logs, too verbose

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")

    def do_GET(self):
        path = urlparse(self.path).path

        # TileJSON endpoint required by MapLibre to describe the source
        if path == "/tiles.json" or path == "/":
            import os
            mbtiles_path = _current_mbtiles_path()
            if not os.path.isfile(mbtiles_path):
                # No .mbtiles generated/mounted yet: fail cleanly so the
                # frontend's probeLocalTiles() falls back to online mode
                # instead of getting a reset connection.
                self.send_response(404)
                self._cors()
                self.end_headers()
                return

            try:
                conn = sqlite3.connect(mbtiles_path)
                meta = get_metadata(conn)
                conn.close()
            except sqlite3.DatabaseError:
                self.send_response(404)
                self._cors()
                self.end_headers()
                return

            import json
            tilejson = {
                "tilejson": "2.2.0",
                "name": meta.get("name", "offline-tiles"),
                "format": meta.get("format", "pbf"),
                "tiles": [f"http://127.0.0.1:{PORT}/tiles/{{z}}/{{x}}/{{y}}.pbf"],
                "minzoom": int(meta.get("minzoom", 0)),
                "maxzoom": int(meta.get("maxzoom", 14)),
                "bounds": [float(v) for v in meta.get("bounds", "-180,-85,180,85").split(",")],
                "vector_layers": json.loads(meta["json"])["vector_layers"] if "json" in meta else []
            }
            body = json.dumps(tilejson).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._cors()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # tile endpoint: /tiles/{z}/{x}/{y}.pbf
        if path.startswith("/tiles/"):
            try:
                parts = path[len("/tiles/"):].rsplit(".", 1)[0].split("/")
                z, x, y = int(parts[0]), int(parts[1]), int(parts[2])
            except (ValueError, IndexError):
                self.send_response(400)
                self.end_headers()
                return

            try:
                conn = sqlite3.connect(_current_mbtiles_path())
                data = get_tile(conn, z, x, y)
                conn.close()
            except sqlite3.DatabaseError:
                self.send_response(404)
                self._cors()
                self.end_headers()
                return

            if data is None:
                self.send_response(204)  # empty file, not an. error
                self._cors()
                self.end_headers()
                return

            # MBTiles tiles are usually gzipped
            self.send_response(200)
            self.send_header("Content-Type", "application/x-protobuf")
            self.send_header("Content-Encoding", "gzip")
            self._cors()
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        self.send_response(404)
        self.end_headers()


def run_tile_server(mbtiles_path=None, port=None, host=None):
    """
    Starts the tile HTTP server and blocks (serve_forever).

    Call this from a background thread when embedding the tile server
    in another process (see desktop.py) instead of running this file
    standalone. Existing CLI usage (`python serve_tiles.py path port`)
    and the Docker image both keep working unchanged.
    """
    global MBTILES_PATH, PORT
    if mbtiles_path is not None:
        MBTILES_PATH = mbtiles_path
    if port is not None:
        PORT = port
    host = host or os.environ.get("TILES_HOST", "127.0.0.1")

    print(f"Offline tile server started : http://{host}:{PORT}")
    print(f"Source : {MBTILES_PATH}")
    print(f"TileJSON : http://127.0.0.1:{PORT}/tiles.json")

    try:
        server = HTTPServer((host, PORT), TileHandler)
    except OSError as e:
        print(f"[tiles] could not bind {host}:{PORT} ({e}); offline tiles disabled for this session")
        return

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    print("Ctrl+C to stop.\n")
    run_tile_server()