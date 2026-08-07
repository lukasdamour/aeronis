"""
Single Flask server exposing both:
  - the business API (core/), without duplicating any logic in JS
  - frontend static files (web/)

API endpoints:
    POST /api/validate -> validates a waypoint list
    POST /api/generate -> generates a KMZ file (returned as base64)
    POST /api/import -> parses a KMZ/KML sent as base64
    POST /api/grid-polygon -> generates a mapping grid (lawnmower pattern)

Static files:
    GET / -> web/index.html
    GET /<path> -> any file under web/ (js, css, fonts, data...)

Startup (single server for everything, except offline tiles which
still run on tiles-pipeline/serve_tiles.py:8765):
    pip install flask --break-system-packages
    python server.py
    -> http://127.0.0.1:5000
"""

import base64
import tempfile
import os
import sys

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

from core.models import (
    Waypoint, MissionConfig, DroneType, FinishAction, HeightMode, CameraAction,
)
from core.geometry import (
    grid_from_polygon, compute_total_distance, estimate_flight_time
)
from core.validator import validate
from core.generator import generate_kmz_bytes
from core.parser import parse_kmz
from core.editor import MissionEditor
from core.flight_modes import apply_photo_mode, apply_video_mode, DRONE_CAMERAS
from core.llm import get_provider, plan_mission, plan_edit, PlannerError, ProviderError
from core.llm.providers import list_ollama_models
from core.llm.geocode import geocode_place, square_polygon_around, GeocodeError
from core import offline_maps
from core.offline_maps import OfflineMapsUnavailable


if os.environ.get("WEB_DIR"):
    # Provided by the Tauri sidecar launcher: web/ is shipped as a
    # Tauri "resource" (plain files, no extraction needed) rather
    # than bundled inside the PyInstaller onefile archive. This avoids
    # the multi-second re-extraction delay onefile mode would otherwise
    # incur on every app startup.
    BASE_DIR = os.environ["WEB_DIR"]
    WEB_DIR = BASE_DIR
elif getattr(sys, "frozen", False):
    # Running as a PyInstaller-frozen sidecar without WEB_DIR set
    # (e.g. built standalone, outside of Tauri): fall back to
    # whatever was bundled via --add-data, if anything.
    BASE_DIR = sys._MEIPASS
    WEB_DIR = os.path.join(BASE_DIR, "web")
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    WEB_DIR = os.path.join(BASE_DIR, "web")

app = Flask(__name__, static_folder=WEB_DIR, static_url_path="")
CORS(app)



# -----------------------------------------------------------
# (De)serialization helpers between browser JSON and the
# Waypoint / MissionConfig dataclasses from core/models.py
# -----------------------------------------------------------

def waypoint_from_json(data: dict) -> Waypoint:
    """Builds a Waypoint from the format sent by waypoints.js:
    {lon, lat, altitude, speed, actions}
    """
    return Waypoint(
        lon=data["lon"],
        lat=data["lat"],
        altitude=data.get("altitude", 0.0),
        speed=data.get("speed"),
        pitch=data.get("pitch"),
        actions=data.get("actions", []),
    )


def waypoint_to_json(wp: Waypoint) -> dict:
    """Converts a Waypoint back to the format expected by the frontend."""
    return {
        "lon": wp.lon,
        "lat": wp.lat,
        "altitude": wp.altitude,
        "speed": wp.speed,
        "actions": wp.actions,
    }


def config_from_json(data: dict) -> MissionConfig:
    return MissionConfig(
        name=data.get("name", "Mission"),
        drone_type=DroneType(data.get("drone", "MAVIC_3")),
        finish_action=FinishAction(data.get("finishAction", "goHome")),
        height_mode=HeightMode(data.get("heightMode", "relativeToStartPoint")),
        transit_speed=float(data.get("transitSpeed", 10.0)),
    )



# ===========
# Endpoints
# ===========

@app.route("/api/camera-specs", methods=["GET"])
def api_camera_specs():
    return jsonify({
        "ok": True,
        "cameras": {
            model: {
                "sensor_width_mm": cam.sensor_width_mm,
                "sensor_height_mm": cam.sensor_height_mm,
                "focal_length_mm": cam.focal_length_mm,
                "image_width_px": cam.image_width_px,
                "image_height_px": cam.image_height_px,
            }
            for model, cam in DRONE_CAMERAS.items()
        },
    })


@app.route("/api/validate", methods=["POST"])
def api_validate():
    body = request.get_json()
    try:
        waypoints = [waypoint_from_json(w) for w in body["waypoints"]]
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    config = config_from_json(body.get("config", {}))
    is_valid, errors, warnings = validate(waypoints, config)

    stats = {}
    if len(waypoints) >=2:
        stats = {
            "distance_m": round(compute_total_distance(waypoints)),
            "duration_s": round(estimate_flight_time(waypoints, config.transit_speed))
        }
    
    return jsonify({
        "ok": True,
        "valid": is_valid,
        "errors": errors,
        "warnings": warnings,
        "stats": stats
    })


@app.route("/api/generate", methods=["POST"])
def api_generate():
    body = request.get_json()
    try:
        waypoints = [waypoint_from_json(w) for w in body["waypoints"]]
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    config = config_from_json(body)
    is_valid, errors, warnings = validate(waypoints, config)
    if not is_valid:
        return jsonify({"ok": False, "error": "; ".join(errors)}), 400
    
    kmz_bytes = generate_kmz_bytes(waypoints, config)
    kmz_b64 = base64.b64encode(kmz_bytes).decode("ascii")

    safe_name = "".join(c if c.isalnum() else "_" for c in config.name) or "mission"

    return jsonify({
        "ok": True,
        "kmz_b64": kmz_b64,
        "filename": f"{safe_name}.kmz",
        "stats": {
            "waypoints": len(waypoints),
            "distance_m": round(compute_total_distance(waypoints)),
            "duration_s": round(estimate_flight_time(waypoints, config.transit_speed)),
            "warnings": warnings
        },
    })


@app.route("/api/import", methods=["POST"])
def api_import():
    body = request.get_json()
    try:
        kmz_bytes = base64.b64decode(body["kmz_b64"])
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "error": f"invalid base64 : {e}"}), 400

    # parse_kmz expects a file path -> write to a temporary file
    with tempfile.NamedTemporaryFile(suffix=".kmz", delete=False) as tmp:
        tmp.write(kmz_bytes)
        tmp_path = tmp.name
    
    try:
        waypoints, config = parse_kmz(tmp_path)
    except (FileNotFoundError, ValueError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    finally:
        os.unlink(tmp_path)

    return jsonify({
        "ok": True, 
        "waypoints": [waypoint_to_json(w) for w in waypoints],
        "config": {
            "name": config.name,
            "drone": config.drone_type.name,
            "finishAction": config.finish_action.value,
            "heightMode": config.height_mode.value,
            "transitSpeed": config.transit_speed
        },
        "stats": {
            "waypoints": len(waypoints)
        },
    })


@app.route("/api/grid-polygon", methods=["POST"])
def api_grid_polygon():
    body = request.get_json()
    try:
        polygon = [(float(p[0]), float(p[1])) for p in body["polygon"]]
        waypoints = grid_from_polygon(
            polygon=polygon,
            altitude=body["altitude"],
            overlap=body.get("overlap", 0.8),
            drone_model=body.get("drone", "MAVIC_3"),
            angle_deg=body.get("angle", 0.0),
            speed=body.get("speed", 5.0),
        )
    except (KeyError, ValueError, IndexError, TypeError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    
    return jsonify({
        "ok": True,
        "waypoints": [waypoint_to_json(w) for w in waypoints]
    })


@app.route("/api/set-mode", methods=["POST"])
def api_set_mode():
    body = request.get_json()
    try:
        waypoints = [waypoint_from_json(w) for w in body["waypoints"]]
        mode = body.get("mode", "photo")
        drone = body.get("drone", "MAVIC_3")
        overlap = float(body.get("overlap", 0.8))
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    
    from core.editor import MissionEditor
    from core.flight_modes import apply_photo_mode, apply_video_mode

    config = config_from_json(body)
    editor = MissionEditor(waypoints, config)


    try:
        if mode == "photo":
            apply_photo_mode(editor, overlap=overlap, drone_model=drone)
        elif mode == "video":
            apply_video_mode(editor)
        else:
            return jsonify({"ok": False, "error": f"Unknown mode: {mode!r}"}), 400
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    
    return jsonify({
        "ok": True,
        "waypoints": [waypoint_to_json(w) for w in editor.waypoints],
    })

# ========================
# LLM assistant (optional)
# ========================

@app.route("/api/llm/config", methods=["GET"])
def api_llm_config():
    """
    Lets the frontend know what the local Ollama setup looks like.
    Local-only by design: this project doesn't use paid cloud APIs.
    """
    ollama_host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    return jsonify({
        "ok": True,
        "local": {
            "available": True,
            "host": ollama_host,
            "default_model": os.environ.get("OLLAMA_MODEL", "llama3.1"),
            "installed_models": list_ollama_models(ollama_host),
        },
    })


@app.route("/api/llm/plan", methods=["POST"])
def api_llm_plan():
    body = request.get_json(silent=True) or {}
    prompt = body.get("prompt", "")
    model = body.get("model")
    current_params = body.get("current_params")

    try:
        provider = get_provider("local", model=model)
        plan = plan_mission(provider, prompt, current_params)
    except (PlannerError, ProviderError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    if not plan.place:
        return jsonify({"ok": True, "mode": "params", "plan": plan.to_dict()})

    try:
        geo = geocode_place(plan.place)
    except GeocodeError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    polygon = square_polygon_around(geo["lat"], geo["lon"], plan.radius_m)

    try:
        waypoints = grid_from_polygon(
            polygon=polygon,
            altitude=plan.altitude,
            overlap=plan.overlap,
            drone_model=plan.drone,
            angle_deg=plan.angle,
            speed=plan.speed,
        )
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    if plan.capture_mode in ("photo", "video") and waypoints:
        editor = MissionEditor(waypoints, MissionConfig(drone_type=DroneType(plan.drone)))
        if plan.capture_mode == "photo":
            apply_photo_mode(editor, overlap=plan.overlap, drone_model=plan.drone)
        else:
            apply_video_mode(editor)
        waypoints = editor.waypoints

    return jsonify({
        "ok": True,
        "mode": "place",
        "plan": plan.to_dict(),
        "waypoints": [waypoint_to_json(w) for w in waypoints],
        "polygon": polygon,
        "place_name": geo["display_name"],
    })


@app.route("/api/llm/edit", methods=["POST"])
def api_llm_edit():
    """
    Natural-language editing of an already-placed mission, e.g.
    "lower altitude to 60m and remove all photos". Same reliability
    principle as /api/llm/plan: the LLM only picks which MissionEditor
    bulk operations to run (and their parameters) -- it never touches
    coordinates, which stay exactly as the user placed them.
    """
    body = request.get_json(silent=True) or {}
    prompt = body.get("prompt", "")
    model = body.get("model")
    wps_json = body.get("waypoints", [])

    if len(wps_json) < 2:
        return jsonify({"ok": False, "error": "Need at least 2 waypoints to edit."}), 400

    try:
        waypoints = [waypoint_from_json(w) for w in wps_json]
    except (KeyError, TypeError, ValueError) as e:
        return jsonify({"ok": False, "error": f"Invalid waypoints: {e}"}), 400

    config = config_from_json(body.get("config", {}) or {})
    editor = MissionEditor(waypoints, config)

    current_params = {
        "altitude": waypoints[0].altitude,
        "speed": waypoints[0].speed if waypoints[0].speed is not None else config.transit_speed,
    }

    try:
        provider = get_provider("local", model=model)
        plan = plan_edit(provider, prompt, current_params)
    except (PlannerError, ProviderError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    before = editor.stats()
    applied = []

    if plan.altitude != current_params["altitude"]:
        editor.set_altitude_all(plan.altitude)
        applied.append(f"Altitude set to {plan.altitude:g}m")

    if plan.speed != current_params["speed"]:
        editor.set_speed_all(plan.speed)
        applied.append(f"Speed set to {plan.speed:g}m/s")

    if plan.clear_actions:
        for action in [a.value for a in CameraAction]:
            editor.remove_action_all(action)
        applied.append("Cleared all camera actions")

    if plan.capture_mode == "photo":
        apply_photo_mode(editor, overlap=plan.overlap, drone_model=config.drone_type.value)
        applied.append(f"Switched to photo mode ({int(plan.overlap * 100)}% overlap)")
    elif plan.capture_mode == "video":
        apply_video_mode(editor)
        applied.append("Switched to video mode (record start/stop only)")
    elif plan.capture_mode == "none":
        for action in [a.value for a in CameraAction]:
            editor.remove_action_all(action)
        applied.append("Removed all camera actions")

    if plan.remove_action:
        editor.remove_action_all(plan.remove_action)
        applied.append(f"Removed '{plan.remove_action}' action")

    if plan.add_action:
        editor.add_action_all(plan.add_action)
        applied.append(f"Added '{plan.add_action}' action")

    if plan.reverse:
        editor.reverse()
        applied.append("Reversed flight direction")

    if plan.simplify_level != "none":
        try:
            removed = editor.simplify(eps=plan.simplify_eps)
            applied.append(
                f"Simplified path ({plan.simplify_level}, {removed} waypoint(s) removed)" if removed
                else f"Path already simple for '{plan.simplify_level}' level -- nothing removed"
            )
        except ValueError as e:
            applied.append(f"Could not simplify: {e}")

    after = editor.stats()

    return jsonify({
        "ok": True,
        "waypoints": [waypoint_to_json(wp) for wp in editor.waypoints],
        "applied": applied,
        "reasoning": plan.reasoning,
        "stats_before": before,
        "stats_after": after,
    })


# ========================
# Offline Maps
# ========================
# Lets users download real map data (Geofabrik + Planetiler, same
# pipeline as tiles-pipeline/build_offline_map.sh) for a whole region or
# a hand-drawn custom zone, so the mission-planning map keeps working
# with no internet connection in the field. See core/offline_maps.py.

@app.route("/api/offline-maps/availability", methods=["GET"])
def api_offline_maps_availability():
    available, error = offline_maps.check_availability()
    return jsonify({"ok": True, "available": available, "error": error})


@app.route("/api/offline-maps/regions", methods=["GET"])
def api_offline_maps_regions():
    return jsonify({"ok": True, "regions": offline_maps.list_regions()})


@app.route("/api/offline-maps", methods=["GET"])
def api_offline_maps_list():
    return jsonify({"ok": True, "maps": offline_maps.list_downloaded_maps()})


@app.route("/api/offline-maps/download", methods=["POST"])
def api_offline_maps_download():
    body = request.get_json(silent=True) or {}
    region_id = body.get("region")
    bounds = body.get("bounds")  # optional [west, south, east, north]
    name = body.get("name")

    try:
        job_id = offline_maps.start_download_job(region_id, bounds=bounds, custom_name=name)
    except OfflineMapsUnavailable as e:
        return jsonify({"ok": False, "error": str(e)}), 501
    except (ValueError, TypeError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/offline-maps/jobs/<job_id>", methods=["GET"])
def api_offline_maps_job(job_id):
    status = offline_maps.get_job_status(job_id)
    if status is None:
        return jsonify({"ok": False, "error": "Unknown job"}), 404
    return jsonify({"ok": True, **status})


@app.route("/api/offline-maps/activate", methods=["POST"])
def api_offline_maps_activate():
    body = request.get_json(silent=True) or {}
    try:
        m = offline_maps.set_active_map(body.get("id"))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "map": m})


@app.route("/api/offline-maps/<map_id>", methods=["DELETE"])
def api_offline_maps_delete(map_id):
    try:
        offline_maps.delete_map(map_id)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True})


# ========================
# Static files (frontend)
# ========================

@app.route("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.route("/offline-maps")
def offline_maps_page():
    return send_from_directory(WEB_DIR, "offline-maps.html")


if __name__ == "__main__":
    print("Aeronis server started: http://127.0.0.1:5000")
    print("  Frontend: http://127.0.0.1:5000/")
    print("  API : /api/validate /api/generate /api/import /api/grid-polygon /api/llm/plan /api/offline-maps")
    print("\nRemember to start the offline tile server in parallel:")
    print("  python tiles/pipeline/serve_tiles.py tiles-pipeline/data/spain.mbtiles 9765")
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="127.0.0.1", port=5000, debug=debug_mode, use_reloader=False)