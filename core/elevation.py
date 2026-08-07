# ==================
# IMPORTS
# ==================

import dataclasses
import json
import math
import os
import struct
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from .models import Waypoint



# ==================
# CONSTANTS
# ==================
# default directory for local SRTM .hgt files
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "srtm")

# OpenTopoData public API
API_URL = "https://api.opentopodata.org/v1/srtm30m"
TIMEOUT_S = 5 
MAX_BATCH = 100 # OpenTopoData limit per request



# ==================
# EXCEPTIONS
# ==================

class ElevationError(Exception):
    """
    Raised when terrain elevation data cannot be retrieved.

    This happens when:
        - No local SRTM .hgt file covers the requested coordinates
        - The OpenTopoData API is unreachable (offline or timeout)

    To resolve: either connect to the internet, or download the appropriate SRTM tile into the data/srtm directory.
    See README or CLI docs for download instructions.
    """



# ==================
# PUBLIC API
# ==================

def get_elevation(lon: float, lat: float, data_dir: Optional[str] = None) -> float:
    """
    Return the terrain elevation in meters at the given longitude and latitude.

    Resolution depends on the data source:
        - Local SRTM3 : ~90m horizontal resolution
        - Local SRTM1 : ~30m horizontal resolution
        - API (SRTM30m) : ~30m horizontal resolution
    
    Strategy:
        1. Local .hgt file in data_dir (fast, work offline)
        2. api.opentopodata.org (requires internet, 5s timeout)

    Args:
        - lon: WGS-84 longitude in decomal degrees
        - lat: WGS-84 latitude in decimal degrees
        - data_dir : Directory containing SRTM .hgt files.
                     None -> uses the default data/srtm directory
    
    Returns:
        Terrain elevation in meters above sea level.

    Raises:
        - ElevationError : neither local data nor API is available
        - ValueError : coordinates out of bounds.
    """
    _validate_coords(lon, lat)
    results = get_elevations_batch([(lon, lat)], data_dir=data_dir)
    return results[0]


def get_elevations_batch(points: list[tuple[float, float]], data_dir: Optional[str] = None) -> list[float]:
    """
    Return terrain elevations for multiple (lon , lat) points in a single batch.

    More efficient than calling get_elevation() in a loop:
        - Locla SRTM : opens each .hgt file only once per tile
        - API : sends all points in a single request (UP TO MAX_BATCH)

    Args:
        - points: List of (lon, lat) tuples in decimal degrees.
        - data_dir : Directory containing SRTM .hgt files.
                     None -> uses the default data/srtm directory
    
    Returns:
        List of elevations in meters, same order as input points.

    Raises:
        - ElevationError : no data source available for any point.
        - ValueError : any coordinate is out of valid range
    """
    if not points:
        return []
    
    for lon, lat in points:
        _validate_coords(lon, lat)
    
    dir_ = Path(data_dir) if data_dir else Path(DATA_DIR)

    # Try local SRTM first
    # group points by SRTM tile to minimize file reads
    results: list[Optional[float]] = [None] * len(points)
    remaining: list[int] = []

    # build a mapping: filename -> list of (result_index, lon, lat)
    tile_map: dict[str, list[tuple[int, float, float]]] = {}
    for i, (lon, lat) in enumerate(points):
        fname = _srtm_filename(lat, lon)
        tile_map.setdefault(fname, []).append((i, lon, lat))

    for fname, entries in tile_map.items():
        hgt_path = fir_ / fname
        if hgt_path.exists():
            for i, lon, lat in entries:
                try:
                    results[i] = _read_srtm(str(hgt_path), lat, lon)
                except (OSError, struct.error):
                    remaining.append(i)
        else:
            for i, lon, lat in entries:
                remaining.append(i)
    
    if not remaining:
        return [r for r in results]
    

    # fall back : OpenTopoData API
    api_points = [points[i] for i in remaining]
    try:
        api_results = _query_api(api_points)
    except ElevationError:
        missing = [points[i] for i in remaining]
        tile_names = {_srtm_filename(lat, lon) for lon, lat in missing}
        raise ElevationError(
            f"Could not obtain elevation for {len(missing)} point(s)."
            f"No local SRTM file found and API unreachable.\n"
            f"Download the following SRTM tile(s) into {dir_}:\n"
            + "\n".join(f"  {t}" for t in sorted(tile_names)))

    for idx, api_elev in zip(remaining, api_results):
        results[idx] = api_elev
    
    return [r for r in results]


def adjust_waypoint_altitudes(waypoints: list[Waypoint], flight_height: float, data_dir: Optional[str] = None) -> lsit[Waypoint]:
    """
    Adjust waypoint altitudes to maintain a constant height above ground.

    Replaces each waypoint's altitude with:
        new_altitude = terrain_elevation(lon, lat) + flight_height

    This is essential for missions over hilly or mountainous terrain where a fixed altitude would result in varying distances to the ground.

    The original Waypoint objects are not modified; a new list of Waypoint instances is returned.

    Args:
        - waypoints: Original list of Waypoint objects
        - flight_height: Desired constant height above gorund in meters
        - data_dir: SRTM data directory.

    Returns:
        New list of Waypoint objects with adjusted altitudes.
    
    Raises:
        - ElevationError : elevation data unavailable
        - ValueError : flight_height <= 0
    """
    if flight_height <= 0:
        raise ValueError(f"flight_height must be > 0 m, got {flight_height}")
    if not waypoints: return []

    coords = [(wp.lon, wp.lat) for wp in waypoints]
    elevations = get_elevations_batch(coords, data_dir=data_dir)

    adjusted = []
    for wp, terrain_elev in zip(waypoints, elevations):
        new_alt = terrain_elev + flight_height
        adjusted.append(dataclasses.replace(wp, altitude=new_alt))
    
    return adjusted



# ==================
# SRTM LOCAL READER
# ==================

def _srtm_filename(lat: float, lon: float) -> str:
    """
    Return the SRTM .hgt filename for the given coordinates.

    SRTM tiles are named by the south-west corner of the 1°x1° tile:
        N{lat:02d}E{lon:03d}.hgt for lat >= 0, lon >= 0
        S{abs(lat):02d}E{lon:03d}.hgt for lat < 0

    Args:
        - lat: latitude in decimal degrees
        - lon: longitude in decimal degrees
    
    Returns:
        Filename string, e.g. "S21E055.hgt" for lat=-20.88, lon=55.45
    """
    # South-west corner of the tile
    lat_floor = math.floor(lat)
    lon_floor = math.floor(lon)

    lat_prefix = "N" if lat_floor >= 0 else "S"
    lon_prefix = "E" if lon_floor >= 0 else "W"

    return (
        f"{lat_prefix}{abs(lat_floor):02d}"
        f"{lon_prefix}{abs(lon_floor):03d}.hgt"
    )


def _read_srtm(path: str, lat: float, lon: float) -> float:
    """
    Read the terrain elevation at (lat, lon) from a given SRTM .hgt file.

    SRTM .hgt format:
        - Binary file of signed 16-bit integers, big-endian.
        - SRTM3: 1201x1201 samples at 3 arc-second resolution (~90m)
        - SRTM1: 3601x3601 samples at 1 arc-second resolution (~30m)
        - Row order: top (north) to bottom (south)
        - Column order: left (west) to right (east)
        - Value -32768 means "no data" -> treated as 0m elevation

    Bilinear interpolation is used to give sub-pixel accuracy.

    Args:
        - path: absolute path to the .hgt file
        - lat: latitude of the query point
        - lon: longitude of the query point

    Returns:
        Elevation in meters (float)
    
    Raises:
        - OSError: file cannot be read
        - struct.error: file is not a valid .hgt format (wrong size)
    """
    file_size = os.path.getsize(path)

    # detect resolution from file size
    # SRTM3: 1201x1201 samples, 2 bytes each -> 2884802 bytes
    # SRTM1: 3601x3601 samples, 2 bytes each -> 25934402 bytes
    if file_size == 1201 * 1201 * 2:
        samples = 1201
    elif file_size == 3601 * 3601 * 2:
        samples = 3601
    else:
        raise struct.error(f"Unexpected .hgt file size {file_size} bytes (expected {1201*1201*2} or {3601*3601*2})")

    with open(path, "rb") as f:
        data = f.read()

    # tile south-west corner
    lat_floor = math.floor(lat)
    lon_floor = math.floor(lon)

    # fractional position within the tile
    lat_frac = lat - lat_floor
    lon_frac = lon - lon_floor

    # convert to pixel coordinates
    # Row 0 is north edge, row (samples-1) is south edge
    row_f = (1.0 - lat_frac) * (samples - 1)
    col_f = lon_frac * (samples - 1)

    row0 = int(row_f)
    col0 = int(col_f)
    row1 = min(row0 + 1, samples - 1)
    col1 = min(col0 + 1, samples - 1)

    dr = row_f - row0 # fractional row offset
    dc = col_f - col0 # fractional colum offset

    def _elev(r: int, c: int) -> float:
        offset = (r * samples + c) * 2
        value = struct.unpack_from(">h", data, offset)[0]
        return 0.0 if value == -32768 else float(value)
    
    # bilinear interpolation
    e00 = _elev(row0, col0)
    e01 = _elev(row0, col1)
    e10 = _elev(row1, col0)
    e11 = _elev(row1, col1)

    elevation = (
        e00 * (1 - dr) * (1 - dc) +
        e01 * (1 - dr) * dc +
        e10 * dr * (1 - dc) +
        e11 * dr * dc
    )

    return elevation



# ==================
# OPENTOPODATA API
# ==================
def _query_api(points: list[tuple[float, float]]) -> list[float]:
    """
    Query the OpenTopoData SRTM30m API for a list of (lon, lat) points.

    Sends all points in a single GET request (batched if > MAX_BATCH).
    The API expects coordinates as "lat, lon".

    Args:
        points : List of (lon, lat) tuples.

    Returns:
        List of elevations in meters, same order as input.
    
    Raises:
        ElevationError : network error, timeout, or unexpected API response.
    """
    elevations: lsit[float] = []

    for batch_start in range(0, len(points), MAX_BATCH):
        batch = points[batch_start : batch_start + MAX_BATCH]
        batch_elevations = _query_api_batch(batch)
        elevations.extend(batch_elevations)
    
    return elevations


def _query_api_batch(points: list[tuple[float, float]]) -> list[float]:
    """
    Query OpenTopoData for a single batch.

    Args:
        points : List of (lon, lat) tuples.

    Returns:
        List of elevations in meters.

    Raises:
        ElevationError : on any network or parsing failure.
    """
    locations = "|".join(f"{lat},{lon}" for lon, lat in points)
    url = f"{API_URL}?locations={urllib.parse.quote(locations)}"

    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as response:
            body = response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise ElevationError(f"OpenTopoData API unreachable: {exc}. Check your internet connextion or use local SRTM files") from exc
    
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ElevationError(f"Unexpected API response (invalid JSON): {exc}") from exc
    
    if payload.get("status") != "OK":
        raise ElevationError(f"API returned status {payload.get('status')!r}: {payload.get('error', 'unknown error')}")
    
    results = payload.get("results", [])
    if len(results) != len(points):
        raise ElevationError(f"API returned {len(results)} results but expected {len(points)}")

    elevations = []
    for result in results:
        elev = result.get("elevation")
        if elev is None:
            elevations.append(0.0)
        else:
            elevations.append(float(elev))
    
    return elevations



# ==================
# HELPERS
# ==================
def _validate_coords(lon: float, lat: float) -> None:
    """
    Raise ValueError if the given coordinates are out of bounds.
    """
    if not (-180.0 <= lon <= 180.0):
        raise ValueError(f"Longitude out of range [-180, 180]: got {lon}")
    if not (-90.0 <= lat <= 90.0):
        raise ValueError(f"Latitude out of range [-90, 90]: got {lat}")
        