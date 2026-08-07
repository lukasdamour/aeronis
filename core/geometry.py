# ======================================
# IMPORTS
# ======================================

import math
from typing import List, Tuple

from .models import CameraAction, Waypoint


# ======================================
# CONSTANTS
# ======================================

EARTH_RADIUS = 6_371_000  # in meters


# ======================================
# DISTANCE
# ======================================

def haversine(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """
    Return the great-circle distance in meters between two GPS points.

    Args:
        p1: A tuple of (longitude, latitude) in degrees.
        p2: A tuple of (longitude, latitude) in degrees.
    
    Returns:
        The distance in meters.

    Example:
        >>> round(haversine((55.45, -20.88), (55.48, -21.34)))
        51244   # Saint-Denis -> Saint-Pierre, Réunion ~= 51 km
    """
    lon1, lat1 = math.radians(p1[0]), math.radians(p1[1])
    lon2, lat2 = math.radians(p2[0]), math.radians(p2[1])

    dlon = lon2 - lon1
    dlat = lat2 - lat1

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2

    # atan2 is more numerically stable than asin for small distances
    return 2 * EARTH_RADIUS * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def haversine_wp(wp1: Waypoint, wp2: Waypoint) -> float:
    """
    Convenience wrapper: distance in meters between two Waypoint objects.
    Avoids extracting lat/lon tuples manually.
    """
    return haversine(wp1.coord(), wp2.coord())


def compute_total_distance(waypoints: List[Waypoint]) -> float:
    """
    Return the total mission distance in meters.
    Returns 0.0 for missions with fewer than 2 waypoints.
    """
    if len(waypoints) < 2:
        return 0.0
    return sum(haversine_wp(waypoints[i], waypoints[i+1]) for i in range(len(waypoints) -1))



# ======================================
# TIME ESTIMATION
# ======================================

def estimate_flight_time(waypoints: List[Waypoint], default_speed: float = 10.0) -> float:
    """
    Estimate total flight time in seconds.
    Use each waypoint's individual speed when set, otherwise falls back to default_speed.

    Args:
        waypoints: List of Waypoint objects.
        default_speed: Fallback speed in m/s (default 10).

    Returns:
        Estimated flight time in seconds (float).
        Return 0.0 for missions with fewer than 2 waypoints.
    """

    if len(waypoints) < 2:
        return 0.0
    
    total_time = 0.0
    for i in range(len(waypoints) - 1):
        dist = haversine_wp(waypoints[i], waypoints[i+1])
        speed = waypoints[i].speed or default_speed
        total_time += dist / speed
    
    return total_time



# ======================================
# BEARING
# ======================================

def bearing(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """
    Return the initial bearing in degrees [0,360] from p1 to p2.
    0° = North, 90° = East, 180° = South, 270° = West

    Args:
        p1: A tuple of (longitude, latitude) in decimal degrees.
        p2: A tuple of (longitude, latitude) in decimal degrees.

    Example:
        >>> round(bearing((55.45, -20.88), (55.48, -21.34)), 1)
        176.5   # Bearing from Saint-Denis to Saint-Pierre, Réunion is almost due South
    """
    lon1, lat1 = math.radians(p1[0]), math.radians(p1[1])
    lon2, lat2 = math.radians(p2[0]), math.radians(p2[1])

    dlon = lon2 - lon1

    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)

    # Convert from radians to degrees and normalize to [0,360]
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def bearing_wp(wp1: Waypoint, wp2: Waypoint) -> float:
    """
    Convenience wrapper: bearing from wp1 to wp2.
    """
    return bearing(wp1.coord(), wp2.coord())



# ======================================
# BOUNDING BOX
# ======================================

def bounding_box(waypoints: List[Waypoint]) -> Tuple[float, float, float, float]:
    """
    Return the axis-aligned bounding box of a list of waypoints.
    Useful for auto-fitting the map view after loading a mission.

    Returns:
        (lon_min, lat_min, lon_max, lat_max)
    
    Raises:
        ValueError: if waypoints is empty.
    """
    if not waypoints:
        raise ValueError("Cannot compute boundig box of an empty waypoint list.")
    
    lons = [wp.lon for wp in waypoints]
    lats = [wp.lat for wp in waypoints]

    return min(lons), min(lats), max(lons), max(lats)



# ======================================
# GRID GENERATION
# ======================================

def grid_waypoints(
    center_lon: float,
    center_lat: float,
    width_m: float,
    height_m: float,
    spacing_m: float,
    altitude: float,
    speed: float = 10.0,
    angle_deg: float = 0.0,
    with_photo: bool = True
) -> List[Waypoint]:
    """
    Generate a lawnmower survey grid centered on (center_lon, center_lat).
    The grid is made of parallel columns separated by spacing_m.
    Odd columns are traversed bottom-to-top, even columns top-to-bottom (serpentine / boustrophedon pattern) to minimise travel distance.

    Args:
        center_lon: Longitude of the grid center in decimal degrees.
        center_lat: Latitude of the grid center in decimal degrees.
        width_m: Total width of the area to cover in meters (East-West)
        height_m: Total height of the area to cover in meters (North-South)
        spacing_m: Distance between adjacent flight lines in meters.
        altitude: Flight altitude in meters for every waypoint.
        speed: Waypoint speed in m/s (default 10.0).
        angle_deg: Rotation of the grid in degrees (0 = axis-aligned).
                   Useful to align lines with a field boundary.
        with_photo: If True, add CameraAction.TAKE_PHOTO to every waypoint.

    Returns:
        Ordered list of Waypoint objects ready to be passed to generator.py.

    Example:
        >>> wps = grid_waypoints(55.45, -20.88, 200, 200, 50, 80)
        >>> len(wps)
        25  # 5 columns x 5 rows

    Raises:
        ValueError: if spacing_m <= 0 or width_m / height_m <= 0.
    """
    if spacing_m <= 0:
        raise ValueError("spacing_m must be positive.")
    if width_m <= 0 or height_m <= 0:
        raise ValueError("width_m and height_m must be positive.")
    
    # Degrees per meter (approximate, valid for small areas)
    deg_per_m_lat = 1.0 / 111_320.0
    deg_per_m_lon = 1.0 / (111_320.0 * math.cos(math.radians(center_lat)))

    angle_rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)

    half_w = width_m / 2.0
    half_h = height_m / 2.0

    n_cols = int(width_m / spacing_m) + 1
    n_rows = int(height_m / spacing_m) + 1

    actions = [CameraAction.TAKE_PHOTO.value] if with_photo else []
    waypoints: List[Waypoint] = []

    for col in range(n_cols):
        x_offset = -half_w + col * spacing_m    # meters, East direction

        # Serpentine pattern: odd columns go bottom-to-top, even columns top-to-bottom
        row_range = range(n_rows) if col % 2 == 0 else range(n_rows - 1, -1, -1)

        for row in row_range:
            y_offset = -half_h + row * spacing_m    # meters, North direction

            # Apply optional rotation around the center
            x_rot = x_offset * cos_a - y_offset * sin_a
            y_rot = x_offset * sin_a + y_offset * cos_a

            lon = center_lon + x_rot * deg_per_m_lon
            lat = center_lat + y_rot * deg_per_m_lat

            waypoints.append(
                Waypoint(
                    lon = lon,
                    lat = lat,
                    altitude = altitude,
                    speed = speed,
                    pitch = None,
                    actions = list(actions)
                )
            )
    return waypoints



# ======================================
# RAMER-DOUGLAS-PEUCKER
# ======================================

def perp_dist(p: Tuple[float, float], a: Tuple[float, float], b: Tuple[float, float],) -> float:
    """
    Returns the perpendicular distance from point p to the line defined by a and b.

    Coordinates are treated as 2-D (lon, lat) in degrees.
    For the RDP algorithm this is accurate enough for small segments.

    Special case: if a == b the distance from p to a is returned.
    """
    if a == b:
        return math.dist(p, a)

    x0, y0 = p
    x1, y1 = a
    x2, y2 = b

    # Signed area formula
    return abs((y2 - y1) * x0 - (x2 - x1) * y0 + x2 * y1 - y2 * x1) / math.hypot(y2 - y1, x2 - x1)


def rdp(points: List[Tuple[float, float]], eps: float) -> List[int]:
    """
    Ramer-Douglas-Peucker algorithm.

    Returns the *indices* of the points that should be kept.
    The caller is responsible for filtering the original list and for re-assigning wpml:index values (done in editor.py).

    Args:
        points: List of (lon, lat) tuples.
        eps: Tolerance in degrees.
             0.00001° ~= 1 m at the equator.
    
    Returns:
        Sorted list of indices to retain (always includes first and last point).
    """
    if len(points) < 3:
        return list(range(len(points))) # Nothing to simplify
    
    start, end = points[0], points[-1]
    max_dist = 0.0
    max_idx = 0

    for i in range(1, len(points)-1):
        d = perp_dist(points[i], start, end)
        if d > max_dist:
            max_dist = d
            max_idx = i
    
    if max_dist > eps:
        left = rdp(points[:max_idx+1], eps)
        right = rdp(points[max_idx:], eps)
        # shift right indices and merge (drop duplicate at junction)
        return left[:-1] + [max_idx + i for i in right]
    else:
        return [0, len(points)-1]


def simplify_waypoints(waypoints: List[Waypoint], eps: float = 0.00001) -> List[Waypoint]:
    """
    Simplify a mission by removing redundant waypoints using the Ramer-Douglas-Peucker algorithm.

    This is a high-level wrapper around rdp() that works directly with Waypoint objects instead of raw coordinate tuples.

    The returned list if NOT re-indexed. wpml:index reassignment is performed in editor.py, which owns the XML layer.

    Args:
        waypoints : Original ordered list of Waypoint objects.
        eps : RDP tolerance in degrees (default 0.00001° ~= 1 m).
    
    Returns:
        Filtered list of Waypoints objects (subset of the input, same order).
    """
    if len(waypoints) < 3:
        return list(waypoints) # Nothing to simplify
    
    coords = [wp.coord() for wp in waypoints]
    indices = set(rdp(coords, eps))

    return [wp for i, wp in enumerate(waypoints) if i in indices]



# ======================================
# POLYGON SURVEY GRID
# ======================================

def grid_from_polygon(
    polygon: list[tuple[float, float]], altitude: float, overlap: float=0.80,
    drone_model: str = "MAVIC_3", angle_deg: float = 0.0,
    speed: float = 5.0, with_photo: bool = True
) -> list[Waypoint]:
    """
    Generate a lawnmower survey grid clipped to an arbitrary polygon.

    Flight lines are parallel, separated by a spacing derived from the drone camera parameters and the requested overlap. Lines are clipped to the polygon boundary and ordered in a serpentine pattern.

    Args:
        - polygon : List of (lon, lat) vertices (minimum 3 points).
                    The polygon is automatically closed.
        - altitude : Flight altitude in meters (> 0).
        - overlap : Desired frontlap as a fraction (0.0, 1.0).
                    0.80 = 80% (recommended for photogrammetry)
        - drone_model : Key in flight_modes.DRONE_CAMERAS.
                        Unknown model -> spacing = altitude / 2
        - angle_deg : Direction of flight lines in degrees.
                      0° = East-West, 90° = North-South, 45° = diagonal
        - speed : Waypoint speed in m/s
        - with_photo : Add takePhoto to every waypoint if True

    Returns:
        - Ordered list of Waypoint objects in serpentine order.
        - Empty list if the polygon is too small for the computed spacing.
    
    Raises:
        ValueError : less than 3 vertices, altitude <= 0, overlap out of [0.0, 1.0)
    """
    if len(polygon) < 3:
        raise ValueError(f"Polygon requires at least 3 vertices, got {len(polygon)}.")
    if altitude <=0:
        raise ValueError(f"altitude must be > 0m, got {altitude}.")
    if not (0.0 <= overlap < 1.0):
        raise ValueError(f"overlap must be in [0.0, 1.0), got {overlap}.")
    
    # reference point: centroid of the polygon
    ref_lon = sum(p[0] for p in polygon) / len(polygon)
    ref_lat = sum(p[1] for p in polygon) / len(polygon)

    # project polygon to local meters
    poly_m = _lonlat_to_metres(polygon, ref_lon, ref_lat)

    # compute line spacing from camera parameters
    try:
        from .flight_modes import DRONE_CAMERAS, compute_photo_spacing
        cam = DRONE_CAMERAS.get(drone_model.upper())
        if cam is not None:
            line_spacing_m, photo_spacing_m = compute_photo_spacing(
                altitude, overlap, cam.sensor_width_mm,
                cam.sensor_height_mm, cam.focal_length_mm
            )
        else:
            line_spacing_m = altitude / 2.0
            photo_spacing_m = altitude / 2.0
    except ImportError:
        photo_spacing_m = altitude / 2.0
    
    if line_spacing_m <= 0:
        line_spacing_m = altitude / 2.0
    if photo_spacing_m <= 0:
        photo_spacing_m = altitude / 2.0
    
    # generate sweep lines over the boundig box
    raw_lines = _sweep_lines(
        poly_m,
        line_spacing_m,
        angle_deg
    )

    # clip each line to the polygon
    all_segments: list[tuple[tuple, tuple]] = []
    for line_start, line_end in raw_lines:
        clipped = _clip_line_to_polygon(line_start, line_end, poly_m)
        all_segments.extend(clipped)
    
    if not all_segments:
        return []
    
    # order in serpentine pattern
    ordered_pts = _serpentine_order(
        all_segments,
        angle_deg,
        photo_spacing_m
    )

    # convert back to lon/lat and build Waypoints
    lonlat_pts = _metres_to_lonlat(ordered_pts, ref_lon, ref_lat)
    actions = [CameraAction.TAKE_PHOTO.value] if with_photo else []

    return [Waypoint(
        lon = lon, lat = lat, altitude = altitude,
        speed = speed, pitch = None, actions = list(actions)
    ) for lon, lat in lonlat_pts]



# ======================================
# PRIVATE HELPERS - PROJECTION
# ======================================

def _lonlat_to_metres(points: list[tuple[float, float]], ref_lon: float, ref_lat: float) -> list[tuple[float, float]]:
    """
    Project (lon, lat) points to local (x, y) in metres.

    Uses a simple equirectangular projection centered on (ref_lon, ref_lat).
    Accurate to ~0.1% for areas smaller than ~100 km.

    x = (lon - ref_lon) * cos(ref_lat_rad) * 111320
    y = (lat - ref_lat) * 111320
    """
    cos_lat = math.cos(math.radians(ref_lat))
    result = []
    for lon, lat in points:
        x = (lon - ref_lon) * cos_lat * 111_320.0
        y = (lat - ref_lat) * 111_320.0
        result.append((x, y))
    return result


def _metres_to_lonlat(points: list[tuple[float, float]], ref_lon: float, ref_lat: float) -> list[tuple[float, float]]:
    """
    Inverse of _lonlat_to_metres.
    """
    cos_lat = math.cos(math.radians(ref_lat))
    result = []
    for x, y in points:
        lon = ref_lon + x / (cos_lat * 111_320.0)
        lat = ref_lat + y / 111_320.0
        result.append((lon, lat))
    return result



# ======================================
# PRIVATE HELPERS - SWEEP LINES
# ======================================

def _sweep_lines(poly_m: list[tuple[float, float]], spacing_m: float, angle_deg: float) -> list[tuple[tuple, tuple]]:
    """
    Generate parallel sweep lines covering the polygon bounding box.

    Lines run in the direction angle_deg and are separated by spacing_m in the perpendicular direction.

    Returns a list of (start, end) pairs, each long enough to extend beyond the boundary box before clipping.
    """
    # unit vector along sweep direction
    a = math.radians(angle_deg)
    dx = math.cos(a)
    dy = math.sin(a)

    # perpendiculat unit vector (direction of line spacing)
    px = -dy
    py = dx

    # project al polygon vertices onto the perpendicular axis
    perp_vals = [px * x + py * y for x, y in poly_m]
    perp_min = min(perp_vals)
    perp_max = max(perp_vals)

    # project onto sweep axs to get half-length
    sweep_vals = [dx * x + dy * y for x, y in poly_m]
    sweep_min = min(sweep_vals)
    sweep_max = max(sweep_vals)
    half_len = (sweep_max - sweep_min) / 2.0 + spacing_m

    sweep_cx = (sweep_max + sweep_min) / 2.0

    # generate one line per spacing step
    lines = []
    t = perp_min
    while t <= perp_max + spacing_m * 0.5:
        cx = px * t + dx * sweep_cx
        cy = py * t + dy * sweep_cx

        start = (cx - dx * half_len, cy - dy * half_len)
        end = (cx + dx * half_len, cy + dy * half_len)
        lines.append((start, end))
        t += spacing_m
    
    return lines



# ======================================
# PRIVATE HELPERS - CLIPPING
# ======================================

def _clip_line_to_polygon(line_start: tuple[float, float], line_end: tuple[float, float], polygon: list[tuple[float, float]]) -> list[tuple[tuple, tuple]]:
    """
    Return the portions of a line segment that lie inside a polygon.

    Works for both convex and concave polygons. For a concave polygon, multiple disjoint segments may be returned.

    Algorithm:
        1. Find all intersections of the infinite line with polygon edges.
        2. Also include the line endpoints if inside the polygon.
        3. Sort all candidate point by their parameter t along the line.
        4. Test the midpoint of each consecutive pair - if inside, kep.
    """
    lx1, ly1 = line_start
    lx2, ly2 = line_end
    ldx = lx2 - lx1
    ldy = ly2 - ly1
    line_len = math.hypot(ldx, ldy)
    if line_len <= 1e-9:
        return []
    
    # collect (t, point) where t in [0,1] is the parameter along the line
    candidates: list[float] = []

    n = len(polygon)
    for i in range(n):
        p3 = polygon[i]
        p4 = polygon[(i+1) % n]
        pt = _segment_intersection(line_start, line_end, p3, p4)
        if pt is not None:
            # compute t for this intersection
            if abs(ldx) > abs(ldy):
                t = (pt[0] - lx1) / ldx
            elif abs(ldy) > 1e-12:
                t = (pt[1] - ly1) / ldy
            else:
                continue
            if -1e-9 <= t <= 1.0 + 1e-9:
                candidates.append(max(0.0, min(1.0, t)))
    
    # add endpoints if inside the polygon
    if _point_in_polygon(line_start, polygon):
        candidates.append(0.0)
    if _point_in_polygon(line_end, polygon):
        candidates.append(1.0)
    
    if len(candidates) < 2:
        return []
    
    candidates = sorted(set(candidates))

    # keep segments whose midpoint is inside the polygon
    result = []
    for i in range(len(candidates) - 1):
        t0, t1 = candidates[i], candidates[i+1]
        if t1 - t0 < 1e-9:
            continue
        mid_t = (t0 + t1) / 2.0
        mid = (lx1 + mid_t * ldx, ly1 + mid_t * ldy)
        if _point_in_polygon(mid, polygon):
            start = (lx1 + t0 * ldx, ly1 + t0 * ldy)
            end = (lx1 + t1 * ldx, ly1 + t1 * ldy)
            result.append((start, end))
    
    return result


def _segment_intersection(p1: tuple[float, float], p2: tuple[float, float], p3: tuple[float, float], p4: tuple[float, float]) -> tuple[float, float] | None:
    """
    Return the intersection point of segments (p1, p2) and (p3, p4), or None if they don't intersect.

    Parametric form:
        P = p1 + t*(p2-p1) with t in [0,1]
        Q = p3 + u*(p4-p3) with u in [0,1]
    """
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4

    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-12:
        return None
    
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom

    if -1e-9 <= t <= 1.0 + 1e-9 and -1e-9 <= u <= 1.0 + 1e-9:
        x = x1 + t * (x2 - x1)
        y = y1 + t * (y2 - y1)
        return (x, y)
    return None


def _point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    """
    Test if a point is inside a polygon using the ray casting algorithm.

    Casts a ray in the +x direction and counts edge crossings.
    Odd count = inside. Works for convex and concave polygons.
    """
    px, py = point
    n = len(polygon)
    inside = False

    j = n-1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]

        # check if the ray crosses this edge
        if ((yi > py) != (yj > py)):
            x_intersect = (xj - xi) * (py - yi) / (yj - yi) + xi
            if px < x_intersect:
                inside = not inside
        j = i
    
    return inside



# ======================================
# PRIVATE HELPERS - SERPENTINE ORDERING
# ======================================

def _serpentine_order(segments: list[tuple[tuple, tuple]], angle_deg: float, point_spacing_m) -> list[tuple[float, float]]:
    """
    Order clipped segments in a boustrophedon (serpentine) pattern.

    Segments are sorted by their position along the perpendicular axis (the axis along which lines are spaced). Even-indexed lines go in their natural direction: odd-indexed lines are reversed.

    Returns a flat, deduplicated list of (x,y) waypoint positions.
    """
    if not segments:
        return []

    a = math.radians(angle_deg)
    px = -math.sin(a)
    py = math.cos(a)

    def _perp_key(seg: tuple) -> float:
        """
        Position of segment midpoint along the perpendicular axis.
        """
        mx = (seg[0][0] + seg[1][0]) / 2.0
        my = (seg[0][1] + seg[1][1]) / 2.0
        return px * mx + py * my
    
    sorted_segs = sorted(segments, key=_perp_key)

    points: list[tuple[float, float]] = []
    for idx, (start, end) in enumerate(sorted_segs):
        seg_pts = _sample_segment(
            start,
            end,
            point_spacing_m,
        )

        if idx % 2 == 1:
            seg_pts.reverse()
        
        if points:
            if math.hypot(seg_pts[0][0] - points[-1][0],
                          seg_pts[0][1] - points[-1][1]) < 1e-6:
                points.append(seg_pts[1])
            else:
                points.extend(seg_pts)
        else:
            points.extend(seg_pts)
    
    return points


def _sample_segment(
    start: tuple[float, float],
    end: tuple[float, float],
    spacing_m: float,
) -> list[tuple[float, float]]:
    """
    Interpolate points along a segment so that waypoints are not only at endpoints.
    """

    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)

    if length < 1e-6:
        return [start]

    if spacing_m <= 0:
        raise ValueError("spacing_m must be > 0")

    n = max(1, math.ceil(length / spacing_m))

    return [
        (
            start[0] + dx * i / n,
            start[1] + dy * i / n,
        )
        for i in range(n + 1)
    ]