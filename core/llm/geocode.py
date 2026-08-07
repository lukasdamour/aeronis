# ======================================
# IMPORTS
# ======================================
import math
import time
from typing import Tuple

import requests


class GeocodeError(Exception):
    """Raised when a place name couldn't be resolved to coordinates."""


# ======================================
# Nominatim (OpenStreetMap) geocoding
# ======================================
# Free, keyless, same spirit as the OSM raster tiles this project
# already falls back to (see web/js/map.js). Nominatim's usage policy
# requires a descriptive User-Agent and at most 1 request/second --
# both enforced here.

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_USER_AGENT = "aeronis/0.2 (student project; local use)"
_MIN_INTERVAL_S = 1.0
_last_request_ts = 0.0


def geocode_place(place: str, timeout: float = 10.0) -> dict:
    """
    Resolves a free-text place name (e.g. "Stade Allianz Riviera, Nice")
    to real-world coordinates via Nominatim. This is the ONLY source of
    truth for coordinates in the place-based mission flow -- the LLM
    only ever supplies the place name string, never a lat/lon itself.

    Returns {"lat": float, "lon": float, "display_name": str}.
    Raises GeocodeError if the place can't be resolved or the service
    is unreachable.
    """
    global _last_request_ts

    if not place or not place.strip():
        raise GeocodeError("No place name given.")

    elapsed = time.monotonic() - _last_request_ts
    if elapsed < _MIN_INTERVAL_S:
        time.sleep(_MIN_INTERVAL_S - elapsed)

    try:
        resp = requests.get(
            _NOMINATIM_URL,
            params={"q": place.strip(), "format": "json", "limit": 1},
            headers={"User-Agent": _USER_AGENT},
            timeout=timeout,
        )
    except requests.RequestException as e:
        raise GeocodeError(
            f"Could not reach the geocoding service ({e}). Check your internet connection."
        ) from e
    finally:
        _last_request_ts = time.monotonic()

    if resp.status_code != 200:
        raise GeocodeError(f"Geocoding service returned HTTP {resp.status_code}.")

    try:
        results = resp.json()
    except ValueError as e:
        raise GeocodeError(f"Geocoding service returned an invalid response: {e}") from e

    if not results:
        raise GeocodeError(f"Could not find a location for '{place}'.")

    r = results[0]
    try:
        return {
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
            "display_name": r.get("display_name", place),
        }
    except (KeyError, ValueError, TypeError) as e:
        raise GeocodeError(f"Unexpected geocoding response: {e}") from e


# ======================================
# Deterministic area construction
# ======================================

def square_polygon_around(lat: float, lon: float, radius_m: float) -> list:
    """
    Axis-aligned square polygon of side 2*radius_m meters, centered on
    (lat, lon), as a list of [lon, lat] pairs (same convention as the
    rest of this app -- see web/js/zones.js / core.geometry). Uses an
    equirectangular approximation, accurate enough for the small areas
    (<= a couple km) this planner targets.
    """
    radius_m = max(10.0, min(radius_m, 2000.0))
    dlat = radius_m / 111_320.0
    cos_lat = math.cos(math.radians(lat)) or 1e-9
    dlon = radius_m / (111_320.0 * cos_lat)
    return [
        [lon - dlon, lat - dlat],
        [lon + dlon, lat - dlat],
        [lon + dlon, lat + dlat],
        [lon - dlon, lat + dlat],
    ]
