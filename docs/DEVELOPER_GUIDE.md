# Developer Guide

This guide covers the codebase: how it's laid out, how the mission engine works, the HTTP API the frontend talks to, and how to extend the project. For end-user instructions, see the [User Guide](USER_GUIDE.md) (web app) or the [CLI Documentation](CLI_DOCUMENTATION.md).

## Table of Contents

- [Developer Guide](#developer-guide)
  - [Table of Contents](#table-of-contents)
  - [Design principle: one engine, three frontends](#design-principle-one-engine-three-frontends)
  - [Project layout](#project-layout)
  - [The `core/` mission engine](#the-core-mission-engine)
    - [`models.py`](#modelspy)
    - [`geometry.py`](#geometrypy)
    - [`generator.py` / `parser.py`](#generatorpy--parserpy)
    - [`validator.py`](#validatorpy)
    - [`editor.py`](#editorpy)
    - [`flight_modes.py`](#flight_modespy)
    - [`elevation.py`](#elevationpy)
  - [The Flask API (`server.py`)](#the-flask-api-serverpy)
  - [The frontend (`web/`)](#the-frontend-web)
  - [The AI assistant (`core/llm/`)](#the-ai-assistant-corellm)
  - [Running locally without Docker](#running-locally-without-docker)
  - [Environment variables](#environment-variables)
  - [Extending the project](#extending-the-project)
  - [Code style](#code-style)

---

## Design principle: one engine, three frontends

All mission logic -- building, parsing, validating, editing `.kmz` files -- lives in `core/` and knows nothing about Flask, Qt, or the CLI. Three thin frontends sit on top of it:

- **`core/cli/`** -- a [Typer](https://typer.tiangolo.com/) CLI, for scripting and batch processing.
- **`server.py`** -- a Flask app exposing `core/` as a JSON API, plus serving the static `web/` frontend. This is the piece both the browser-based deployment and the desktop app actually run.
- **`desktop.py`** -- a PySide6/QtWebEngine window that runs `server.py`'s Flask app in a background thread of the *same* process, and simply points a native webview at it. `web/` and `server.py` are reused completely unchanged; there's no separate desktop-specific frontend to maintain.

The consequence: any bug fix or new feature in `core/` benefits the CLI, the web app, and the desktop app at once, and there's exactly one implementation of mission validation, KMZ generation, and geometry to keep correct.

## Project layout

```
core/
  models.py
  geometry.py
  generator.py
  parser.py
  validator.py
  editor.py
  flight_modes.py
  elevation.py
  llm/
  cli/

server.py
desktop.py
web/
tiles-pipeline/
samples/
```

**Inside `core/`:**

| Module | Purpose |
|---|---|
| `models.py` | `Waypoint`, `MissionConfig`, enums (`DroneType`, `FinishAction`, `HeightMode`...), drone metadata |
| `geometry.py` | Distance/duration calculations, zone-to-grid generation, path simplification (RDP) |
| `generator.py` | Waypoint list + `MissionConfig` → `.kmz` bytes/file |
| `parser.py` | `.kmz` → Waypoint list + `MissionConfig` (the inverse of `generator.py`) |
| `validator.py` | Mission-level validation (waypoint count, distances, DJI/legal limits) |
| `editor.py` | `MissionEditor`: stateful, safe mutation of an in-memory mission |
| `flight_modes.py` | Camera database (real DJI sensor specs) + photo/video mode application, GSD math |
| `elevation.py` | SRTM-based terrain elevation lookup, with an OpenTopoData API fallback -- **not wired into the CLI/API/frontend yet** |
| `llm/` | Natural-language mission planning/editing on top of a local Ollama model |
| `cli/` | Typer CLI wrapping the above |

**Top level:**

| Path | Purpose |
|---|---|
| `server.py` | Flask JSON API + static file server for `web/` |
| `desktop.py` | PySide6/QtWebEngine shell around `server.py` |
| `web/` | MapLibre-based frontend (vanilla JS, no build step) |
| `tiles-pipeline/` | Offline vector tile server (`serve_tiles.py`) + OSM raster tile downloader (`download_tiles.py`) |
| `samples/` | Example `.kmz` files for manual testing / import |

## The `core/` mission engine

### `models.py`

Defines the two central dataclasses:

- **`Waypoint`** -- one point in the mission: `lon`, `lat`, `altitude`, optional `speed`/`pitch`, a list of `CameraAction` values, plus heading/turn behavior. Field ranges (longitude, latitude, altitude, speed, pitch) and camera action names are validated in `__post_init__`, so an invalid `Waypoint` simply cannot be constructed -- callers don't need to re-check these elsewhere.
- **`MissionConfig`** -- mission-wide settings: name, drone model, finish action, height reference mode, transit speed, RC-lost behavior.

Drone models are declared in the `DroneType` enum and mapped to their DJI WPML `droneEnumValue`/`droneSubEnumValue` pair via `DRONE_INFO_BY_NAME` / `get_drone_info()`.

### `geometry.py`

Pure math: `haversine()` for great-circle distance, `compute_total_distance()` / `estimate_flight_time()` for mission stats, and `grid_from_polygon()` -- the core of the zone-drawing feature -- which takes a polygon and generates a lawnmower-pattern set of waypoints via point-in-polygon filtering, a sweep-line scan, and serpentine (boustrophedon) ordering, followed by an RDP simplification pass.

### `generator.py` / `parser.py`

`generate_kmz()` / `generate_kmz_bytes()` turn a `Waypoint` list + `MissionConfig` into a DJI-compatible `.kmz` (a zip containing `wpmz/template.kml` and `wpmz/waylines.wpml`). `parse_kmz()` does the reverse. Between them, they're the only place that needs to know the WPML XML schema -- everything else in the codebase works with plain `Waypoint`/`MissionConfig` objects.

### `validator.py`

`validate(waypoints, config)` checks mission-level constraints that a single `Waypoint` can't check on its own: waypoint count bounds, minimum distance between consecutive points, altitude/speed warnings against legal or battery-life limits. Returns `(is_valid, errors, warnings)` -- errors block export, warnings don't.

### `editor.py`

`MissionEditor` wraps a waypoint list + config and exposes safe bulk-mutation methods (`set_altitude_all`, `set_speed_all`, `add_action_all`, `remove_action_all`, `reverse`, `simplify`, ...), re-indexing automatically after any structural change. This is what both the web API's `/api/set-mode` and the AI assistant's edit tool calls go through -- the AI never manipulates coordinates directly, only these vetted operations.

### `flight_modes.py`

Holds `DRONE_CAMERAS`, a table of real sensor width/height, focal length, and resolution per drone model, used to compute Ground Sample Distance (GSD) and photo-trigger spacing for a target overlap. `apply_photo_mode()` / `apply_video_mode()` apply that to a `MissionEditor`.

### `elevation.py`

Looks up ground elevation for waypoint coordinates from local SRTM `.hgt` tiles (`DATA_DIR`), falling back to the OpenTopoData public API when a tile isn't available locally, exposing `adjust_waypoint_altitudes()` to correct a waypoint list's altitudes against actual terrain height rather than a flat reference plane.

**Not currently wired into anything.** No route in `server.py`, no command in `core/cli/cli.py`, and no control in `web/js/*.js` calls this module -- it's a complete, working piece of `core/` with no caller yet. Hooking it up would mean: a CLI flag (e.g. `--terrain-follow <height>`) calling `adjust_waypoint_altitudes()` before writing the `.kmz`, and/or an API route + a frontend toggle doing the same before `/api/generate`.

## The Flask API (`server.py`)

`server.py` is a single Flask app serving both the JSON API and the static `web/` files. It never duplicates mission logic -- every route deserializes JSON into `core/` objects, calls into `core/`, and serializes the result back.

| Route | Method | Purpose |
|---|---|---|
| `/api/camera-specs` | GET | Camera specs table (`DRONE_CAMERAS`), used by the frontend's live GSD display |
| `/api/validate` | POST | Validate a waypoint list; returns errors/warnings + mission stats |
| `/api/generate` | POST | Validate then generate a `.kmz` (returned as base64) |
| `/api/import` | POST | Parse a base64-encoded `.kmz`/`.kml` into waypoints + config |
| `/api/grid-polygon` | POST | Generate a lawnmower-pattern waypoint list covering a drawn polygon |
| `/api/set-mode` | POST | Apply photo or video capture mode to a waypoint list via `MissionEditor` |
| `/api/llm/config` | GET | Report local Ollama availability/host/model list to the frontend |
| `/api/llm/plan` | POST | Natural-language mission generation (place name + parameters -> waypoints) |
| `/api/llm/edit` | POST | Natural-language editing of an existing waypoint list |
| `/` | GET | Serves `web/index.html`; any other static path is served by Flask's static handler |

All endpoints return `{"ok": true/false, ...}`, with `ok: false` responses carrying an `"error"` string and an appropriate 4xx status.

`server.py` resolves its own `WEB_DIR` differently depending on how it's launched (env var set by the Tauri sidecar path that was tried and abandoned, PyInstaller's frozen-app path, or the plain source-checkout path), so the same file works unmodified whether it's run directly, from Docker, or embedded in `desktop.py`.

## The frontend (`web/`)

Vanilla JS, no build step, no framework -- split by concern rather than by page, since it's a single-page app:

| File | Responsibility |
|---|---|
| `js/map.js` | MapLibre map setup, style/layers, wiring other modules to the map instance |
| `js/zones.js` | Rectangle/polygon zone drawing, live preview, mission splitting |
| `js/waypoints.js` | Waypoint list state, markers, manual add/move/delete/reorder, multi-mission tabs |
| `js/llm.js` | AI assistant panel (generate/edit tabs), talking to `/api/llm/*` |
| `js/import.js` | Drag-and-drop / file-picker import, base64 encoding, calling `/api/import` |
| `js/gsd.js` | Client-side GSD calculation mirroring `core/flight_modes.py`, fed by `/api/camera-specs` |
| `js/history.js` | Undo/redo stack over `wpState.waypoints` snapshots |
| `js/zip.js` | Minimal dependency-free ZIP writer, used to bundle multiple exported `.kmz` files |
| `js/splash.js` | Splash screen shown while the map performs its initial load |

## The AI assistant (`core/llm/`)

The assistant is deliberately constrained so it can't silently corrupt a mission:

- `providers.py` defines the `Provider` interface and an `OllamaProvider` implementation talking to a local Ollama instance (`OLLAMA_HOST`, default `http://127.0.0.1:11434`) via function calling. There is no cloud provider -- this is local-only by design.
- `planner.py` / `edit_planner.py` define narrow, schema-validated "plans" (`schema.py`, `edit_schema.py`) the model is allowed to return: for generation, a place name plus mission parameters; for editing, a fixed set of `MissionEditor` operations to apply (set altitude/speed, add/remove an action, switch capture mode, reverse, simplify) with their arguments. The LLM picks *which* operations to run and with what parameters -- it never emits waypoint coordinates itself for an edit, and for generation the coordinates come from the same deterministic `grid_from_polygon()` used by manual zone drawing, not from the model.
- `geocode.py` resolves a place name to coordinates via OpenStreetMap Nominatim (rate-limited to 1 request/second, per Nominatim's usage policy) and builds a square polygon of the requested radius around it.

## Running locally without Docker

```bash
pip install -e . --break-system-packages
python server.py
```

This starts the Flask dev-adjacent server on `http://127.0.0.1:5000` (use a WSGI server like `gunicorn` for anything beyond local development -- see the Dockerfile for the production command). The offline tile server and Ollama are independent processes; start them separately if you need them (see the [Deployment Guide](DEPLOYMENT.md)).

Set `FLASK_DEBUG=1` to enable Flask's debug mode (auto-reload, interactive debugger) during development.

## Environment variables

| Variable | Read by | Default | Purpose |
|---|---|---|---|
| `HOST`, `PORT` | Docker/Dockerfile only (baked into the `gunicorn --bind` command) | `0.0.0.0`, `5000` | Bind address for the app container |
| `FLASK_DEBUG` | `server.py` | `0` | Set to `1` to enable Flask debug mode |
| `WEB_DIR` | `server.py` | unset | Overrides where static frontend files are served from (Tauri sidecar path; not used in the current Docker/desktop setup) |
| `OLLAMA_HOST` | `server.py`, `core/llm/providers.py` | `http://127.0.0.1:11434` | Where to reach the Ollama server; must be reachable *from inside the container* -- see [Deployment Guide](DEPLOYMENT.md) |
| `OLLAMA_MODEL` | `server.py` | `llama3.1` | Default model name reported to the frontend |
| `TILES_HOST` | `tiles-pipeline/serve_tiles.py` | `127.0.0.1` (`0.0.0.0` in Docker) | Bind address for the offline tile server |
| `TILES_FILE` | `tiles-pipeline/Dockerfile` CMD | `/app/data/spain.mbtiles` | Path to the `.mbtiles` file to serve |
| `TILES_PORT` | `tiles-pipeline/Dockerfile` CMD | `8765` | Port for the offline tile server |

## Extending the project

**Add a new drone model.** Add it to the `DroneType` enum and `DRONE_INFO_BY_NAME` in `core/models.py` (WPML enum/sub-enum values), and to `DRONE_CAMERAS` in `core/flight_modes.py` (real sensor specs, needed for photo spacing and GSD). Nothing else needs to change -- the CLI, API, and frontend all read from these tables.

**Add a new CLI command.** Add a Typer command in `core/cli/cli.py` that calls into existing `core/` functions; keep any new mission logic in `core/` itself rather than in the CLI module, so the web app can use it too.

**Add a new API endpoint.** Add a route in `server.py` following the existing pattern: deserialize the request with `waypoint_from_json`/`config_from_json`, call into `core/`, serialize the result, return `{"ok": ..., ...}`. Update the route table above and, if the frontend needs it, the corresponding `web/js/*.js` module.

**Add a new AI assistant capability.** Extend the relevant schema in `core/llm/schema.py` or `edit_schema.py` and handle the new field in `planner.py`/`edit_planner.py` and the matching `server.py` route -- keep the model choosing *parameters*, not raw coordinates, to preserve the reliability guarantee described above.

## Code style

The codebase favors explicit section-comment banners (`# ===\n# SECTION\n# ===`) to separate imports/constants/public API within a module, and descriptive docstrings with `Args`/`Returns`/`Raises`/`Example` blocks on public functions -- follow the existing pattern in the file you're editing rather than introducing a new convention. There is currently no automated test suite (`conftest.py` exists but no `tests/` directory is checked in yet); validate changes to `core/` manually against the sample missions in `samples/` (`aeronis validate`, `aeronis read -v`) until one is added.