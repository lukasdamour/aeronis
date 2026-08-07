"""
Backend support for the "Offline Maps" page.

Runs the same two-step pipeline as tiles-pipeline/build_offline_map.sh
(Geofabrik OSM extract -> Planetiler) but as plain Python rather than a
shelled-out bash script, so it also works:
  - on Windows, which has no bash by default
  - inside the packaged desktop app (PyInstaller), where the install
    directory (Program Files, a read-only AppImage, a macOS .app
    bundle) usually isn't writable -- downloaded data goes to a
    per-user app-data directory instead (see _state_dir()).

build_offline_map.sh itself is untouched and still works for manual,
from-a-checkout use (see tiles-pipeline/README-style comments in the
script) -- this module doesn't call it, it reimplements the same two
steps directly so the packaged app doesn't depend on it being present.

Only requirement at runtime: a JRE (`java` on PATH), for Planetiler.
Not available in the bundled Docker image (python:3.12-slim has no
JRE) -- check_availability() reports that clearly instead of the
feature failing obscurely.
"""

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import requests

PLANETILER_VERSION = "0.9.0"
PLANETILER_JAR_URL = (
    f"https://github.com/onthegomap/planetiler/releases/download/"
    f"v{PLANETILER_VERSION}/planetiler.jar"
)


def _is_frozen():
    return getattr(sys, "frozen", False)


def _state_dir():
    """Where downloaded .mbtiles / .osm.pbf / planetiler.jar / job logs /
    active_map.json live.

    - Local checkout or Docker (not frozen): tiles-pipeline/data/, same
      place build_offline_map.sh and the docs already point people to,
      and the same volume docker-compose.yml mounts for manually-built
      files -- no behavior change there.
    - Packaged desktop app (frozen): a per-user app-data directory,
      since the app's own install directory may not be writable (a
      Linux AppImage is a read-only squashfs; a Windows install done
      via the lowest-privilege installer, or a macOS .app bundle, may
      not be either).
    """
    if not _is_frozen():
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_dir, "tiles-pipeline", "data")

    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(root, "Aeronis", "offline-maps")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Aeronis/offline-maps")
    root = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(root, "aeronis", "offline-maps")


DATA_DIR = _state_dir()
ACTIVE_MAP_FILE = os.path.join(DATA_DIR, "active_map.json")
PLANETILER_JAR_PATH = os.path.join(DATA_DIR, "planetiler.jar")

# Curated subset of Geofabrik extracts. "geofabrik_path" is relative to
# https://download.geofabrik.de/. approx_pbf_mb is only indicative (raw
# OSM extract size before tiling -- the built .mbtiles is usually much
# smaller).
REGIONS = {
    "spain":           {"label": "Spain",           "geofabrik_path": "europe/spain",         "approx_pbf_mb": 1100},
    "france":          {"label": "France",          "geofabrik_path": "europe/france",        "approx_pbf_mb": 4300},
    "portugal":        {"label": "Portugal",        "geofabrik_path": "europe/portugal",      "approx_pbf_mb": 400},
    "italy":           {"label": "Italy",           "geofabrik_path": "europe/italy",         "approx_pbf_mb": 2000},
    "germany":         {"label": "Germany",         "geofabrik_path": "europe/germany",       "approx_pbf_mb": 4000},
    "united-kingdom":  {"label": "United Kingdom",  "geofabrik_path": "europe/great-britain", "approx_pbf_mb": 1600},
    "belgium":         {"label": "Belgium",         "geofabrik_path": "europe/belgium",       "approx_pbf_mb": 500},
    "netherlands":     {"label": "Netherlands",     "geofabrik_path": "europe/netherlands",   "approx_pbf_mb": 1300},
    "switzerland":     {"label": "Switzerland",     "geofabrik_path": "europe/switzerland",   "approx_pbf_mb": 400},
}

_jobs_lock = threading.Lock()
_jobs = {}  # job_id -> dict(status, region_id, output_name, log_path, started_at, returncode)


class OfflineMapsUnavailable(RuntimeError):
    """Raised when this feature can't run in the current deployment
    (e.g. the Docker image, whose python:3.12-slim base has no JRE)."""


def _check_available():
    if shutil.which("java") is None:
        raise OfflineMapsUnavailable(
            "Java (JRE) is required by Planetiler to build offline maps -- install one and try again."
        )


def check_availability():
    """(is_available, error_message) -- cheap enough to call on page load."""
    try:
        _check_available()
        return True, None
    except OfflineMapsUnavailable as e:
        return False, str(e)


def list_regions():
    return [{"id": rid, **info} for rid, info in REGIONS.items()]


def _safe_slug(text):
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", (text or "").strip().lower()).strip("-")
    return slug or "custom"


def _read_mbtiles_metadata(path):
    try:
        conn = sqlite3.connect(path)
        rows = dict(conn.execute("SELECT name, value FROM metadata").fetchall())
        conn.close()
    except sqlite3.DatabaseError:
        return {}

    bounds = None
    if "bounds" in rows:
        try:
            bounds = [float(v) for v in rows["bounds"].split(",")]
        except ValueError:
            bounds = None

    return {"name": rows.get("name"), "bounds": bounds}


def _get_active_path():
    try:
        with open(ACTIVE_MAP_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("path")
    except (FileNotFoundError, json.JSONDecodeError, KeyError, OSError):
        return None


def list_downloaded_maps():
    """Every .mbtiles present in tiles-pipeline/data/, with metadata read
    straight from the file (no separate index to keep in sync)."""
    if not os.path.isdir(DATA_DIR):
        return []

    active_path = _get_active_path()
    active_abspath = os.path.abspath(active_path) if active_path else None

    maps = []
    for fname in sorted(os.listdir(DATA_DIR)):
        if not fname.endswith(".mbtiles"):
            continue
        path = os.path.join(DATA_DIR, fname)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        meta = _read_mbtiles_metadata(path)
        map_id = fname[: -len(".mbtiles")]
        maps.append({
            "id": map_id,
            "path": path,
            "label": meta.get("name") or map_id,
            "bounds": meta.get("bounds"),
            "size_mb": round(stat.st_size / (1024 * 1024), 1),
            "built_at": int(stat.st_mtime),
            "active": os.path.abspath(path) == active_abspath,
        })
    return maps


def set_active_map(map_id):
    maps = {m["id"]: m for m in list_downloaded_maps()}
    if map_id not in maps:
        raise ValueError(f"Unknown offline map: {map_id!r}")
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ACTIVE_MAP_FILE, "w", encoding="utf-8") as f:
        json.dump({"path": maps[map_id]["path"]}, f)
    return maps[map_id]


def delete_map(map_id):
    maps = {m["id"]: m for m in list_downloaded_maps()}
    if map_id not in maps:
        raise ValueError(f"Unknown offline map: {map_id!r}")
    if maps[map_id]["active"]:
        raise ValueError("Cannot delete the map currently used offline -- switch to another one first.")
    os.remove(maps[map_id]["path"])


def _download_with_retry(url, dest_path, log, attempts=3, min_size_bytes=1_000_000):
    """Streams url to dest_path, retrying on transient failures and
    rejecting suspiciously small responses (truncated download / an
    HTML error page instead of the real file) -- same safety check
    build_offline_map.sh's download_with_retry() does."""
    for attempt in range(1, attempts + 1):
        log(f"Download attempt {attempt}/{attempts}: {url}")
        tmp_path = dest_path + ".part"
        try:
            with requests.get(url, stream=True, timeout=30) as resp:
                resp.raise_for_status()
                with open(tmp_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
            size = os.path.getsize(tmp_path)
            if size >= min_size_bytes:
                os.replace(tmp_path, dest_path)
                log(f"Downloaded {size / (1024 * 1024):.1f} MB")
                return
            log(f"Downloaded file too small ({size} bytes), probably an error page -- retrying.")
            os.remove(tmp_path)
        except (requests.RequestException, OSError) as e:
            log(f"Download failed: {e}")
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        if attempt < attempts:
            time.sleep(5)

    raise RuntimeError(f"Could not download {url} after {attempts} attempts")


def _ensure_planetiler(log):
    if os.path.isfile(PLANETILER_JAR_PATH):
        log("Planetiler already present, skip.")
        return
    _download_with_retry(PLANETILER_JAR_URL, PLANETILER_JAR_PATH, log, min_size_bytes=1_000_000)


def _run_pipeline(geofabrik_path, bounds, output_path, memory, log):
    """The exact same two steps as build_offline_map.sh, as Python:
    ensure Planetiler + the region's OSM extract are downloaded (each
    only once, reused across builds), then run Planetiler to produce
    the .mbtiles -- optionally clipped to `bounds`."""
    os.makedirs(DATA_DIR, exist_ok=True)

    log("=== Step 1/3: Planetiler ===")
    _ensure_planetiler(log)

    log("")
    log(f"=== Step 2/3: OSM data for '{geofabrik_path}' ===")
    pbf_path = os.path.join(DATA_DIR, os.path.basename(geofabrik_path) + "-latest.osm.pbf")
    if os.path.isfile(pbf_path):
        log("File already present, skip. (delete it to force a re-download)")
    else:
        pbf_url = f"https://download.geofabrik.de/{geofabrik_path}-latest.osm.pbf"
        _download_with_retry(pbf_url, pbf_path, log)

    log("")
    log("=== Step 3/3: Building vector tiles (.mbtiles) ===")
    if bounds:
        log(f"Custom bounds: {bounds}")
    output_uri = Path(output_path).resolve().as_uri()
    java_args = [
        "java", f"-Xmx{memory}", "-jar", PLANETILER_JAR_PATH,
        f"--osm-path={pbf_path}", f"--output={output_uri}", "--download", "--force",
    ]
    if bounds:
        java_args.append(f"--bounds={bounds}")

    proc = subprocess.Popen(java_args, cwd=DATA_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in proc.stdout:
        log(line.rstrip("\n"))
    returncode = proc.wait()
    if returncode != 0:
        raise RuntimeError(f"Planetiler exited with code {returncode}")
    log("")
    log(f"Done. File: {output_path} ({os.path.getsize(output_path) / (1024 * 1024):.1f} MB)")


def start_download_job(region_id, bounds=None, custom_name=None, memory="4g"):
    """
    Builds an .mbtiles in the background: same pipeline as
    build_offline_map.sh (Geofabrik extract + Planetiler), reimplemented
    in Python so it also works on Windows (no bash) and inside the
    packaged desktop app (see _state_dir()).

    - region_id: key into REGIONS -- the Geofabrik extract to source data
      from (Geofabrik doesn't offer custom-bbox extracts, so a custom
      zone still needs a covering region as its source).
    - bounds: optional (west, south, east, north) to clip the output to a
      hand-drawn zone instead of building the whole region.
    - custom_name: display name for the resulting file when bounds is set.

    Returns a job_id to poll via get_job_status().
    """
    _check_available()

    if region_id not in REGIONS:
        raise ValueError(f"Unknown region: {region_id!r}")

    geofabrik_path = REGIONS[region_id]["geofabrik_path"]

    bounds_str = None
    if bounds:
        if len(bounds) != 4:
            raise ValueError("bounds must be [west, south, east, north]")
        west, south, east, north = (float(v) for v in bounds)
        bounds_str = f"{west},{south},{east},{north}"
        output_name = _safe_slug(custom_name) + f"-{int(time.time())}"
    else:
        output_name = os.path.basename(geofabrik_path)

    os.makedirs(DATA_DIR, exist_ok=True)
    output_path = os.path.join(DATA_DIR, f"{output_name}.mbtiles")

    job_id = uuid.uuid4().hex[:12]
    log_path = os.path.join(DATA_DIR, f".job-{job_id}.log")

    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running",
            "region_id": region_id,
            "output_name": output_name,
            "log_path": log_path,
            "started_at": int(time.time()),
            "returncode": None,
        }

    def _run():
        returncode = 0
        try:
            with open(log_path, "w", encoding="utf-8") as log_file:
                def log(msg):
                    log_file.write(msg + "\n")
                    log_file.flush()
                _run_pipeline(geofabrik_path, bounds_str, output_path, memory, log)
        except Exception as e:
            returncode = 1
            try:
                with open(log_path, "a", encoding="utf-8") as log_file:
                    log_file.write(f"\n[error] {e}\n")
            except OSError:
                pass
        with _jobs_lock:
            _jobs[job_id]["status"] = "done" if returncode == 0 else "error"
            _jobs[job_id]["returncode"] = returncode

    threading.Thread(target=_run, daemon=True).start()
    return job_id


def get_job_status(job_id, log_tail_lines=60):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        job = dict(job)

    tail = ""
    try:
        with open(job["log_path"], "r", encoding="utf-8", errors="replace") as f:
            tail = "".join(f.readlines()[-log_tail_lines:])
    except FileNotFoundError:
        pass

    return {
        "status": job["status"],
        "region_id": job["region_id"],
        "output_name": job["output_name"],
        "started_at": job["started_at"],
        "returncode": job["returncode"],
        "log_tail": tail,
    }
