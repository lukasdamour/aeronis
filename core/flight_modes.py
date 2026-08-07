# =================
# IMPORTS
# =================
from dataclasses import dataclass

from .editor import MissionEditor
from .geometry import haversine_wp
from .models import CameraAction, Waypoint



# =================
# CAMERA DATABASE
# =================

@dataclass(frozen=True)
class CameraParams:
    """
    Physical parameters of a drone camera.

    All values come from official DJI specifications.
    The true focal length (not the 35mm equivalent) is used for photogrammetric calculations.
    """
    sensor_width_mm: float      # physical sensor width in mm
    sensor_height_mm: float     # physical sensor height in mm
    focal_length_mm: float      # true focal length in mm
    image_width_px: int         # native image width in pixels
    image_height_px: int        # native image height in pixels


# Camera parameters per drone model, as specified by DJI.
DRONE_CAMERAS: dict[str, CameraParams] = {
    "MAVIC_3": CameraParams(17.3, 13.0, 12.3, 5820, 3956),
    "MAVIC_3_CLASSIC": CameraParams(17.3, 13.0, 12.3, 5820, 3956),

    "MAVIC_3_ENTERPRISE": CameraParams(17.3, 13.0, 12.3, 5820, 3956),
    "MAVIC_3_THERMAL": CameraParams(17.3, 13.0, 12.3, 5820, 3956),
    "MAVIC_3_MULTISPECTRAL": CameraParams(17.3, 13.0, 12.3, 5820, 3956),

    "MINI_3_PRO": CameraParams(9.7, 7.3, 8.4, 4032, 3024),
    "MINI_4_PRO": CameraParams(9.7, 7.3, 8.4, 4032, 3024),

    "AIR_3": CameraParams(9.7, 7.3, 8.4, 4032, 3024),
    "AIR_3S": CameraParams(9.7, 7.3, 8.4, 4032, 3024),

    "MATRICE_30": CameraParams(6.4, 4.8, 4.5, 5000, 3750),
    "MATRICE_30T": CameraParams(6.4, 4.8, 4.5, 5000, 3750),

    "MATRICE_3D": CameraParams(17.3, 13.0, 12.3, 5280, 3956),
    "MATRICE_3TD": CameraParams(17.3, 13.0, 12.3, 5280, 3956),

    "MATRICE_300": CameraParams(13.2, 8.8, 8.8, 4000, 3000),
    "MATRICE_350_RTK": CameraParams(13.2, 8.8, 8.8, 4000, 3000)
}

# Generic fallback when drone model is not in the database.
_GENERIC_CAMERA = CameraParams(13.2, 8.8, 8.8, 4000, 3000)



# =================
# BATTERY DATABASE
# =================
# Manufacturer-published max flight time in minutes (no wind, no
# payload, hovering/cruising until 0% battery -- see DJI's own spec
# pages, e.g. https://www.dji.com/<model>/specs). These are best-case
# lab conditions: real-world flights (wind, cold, payload, RTH reserve)
# are shorter, so callers should apply a safety margin rather than use
# these numbers directly -- see get_max_flight_time_s().
DRONE_BATTERY_MAX_MINUTES: dict[str, float] = {
    "MINI_3_PRO": 34,
    "MINI_4_PRO": 34,

    "MAVIC_3": 40,
    "MAVIC_3_CLASSIC": 40,

    "AIR_3": 46,
    "AIR_3S": 45,

    "MAVIC_3_ENTERPRISE": 45,
    "MAVIC_3_THERMAL": 45,
    "MAVIC_3_MULTISPECTRAL": 43,

    "MATRICE_30": 41,
    "MATRICE_30T": 41,

    "MATRICE_3D": 50,
    "MATRICE_3TD": 50,

    "MATRICE_300": 55,
    "MATRICE_350_RTK": 55,
}

# Generic fallback (matches the previous fixed 25-minute constant) when
# the drone model isn't in the database above.
_GENERIC_MAX_FLIGHT_MINUTES = 25

# Applied to the manufacturer's rated max flight time to get a realistic
# planning threshold: real flights rarely match lab conditions (wind,
# temperature, payload), and DJI's own smart-RTH logic already reserves
# battery near the end, so planning for the full rated time leaves no
# safety margin at all.
DEFAULT_SAFETY_MARGIN = 0.75


def get_max_flight_time_s(drone_model: str, safety_margin: float = DEFAULT_SAFETY_MARGIN) -> float:
    """
    Realistic planning threshold for a drone's flight time, in seconds.

    Args:
        drone_model: Key in DRONE_BATTERY_MAX_MINUTES (e.g. "MAVIC_3").
        safety_margin: Fraction of the manufacturer's rated max flight
                       time to actually plan for (0-1). Defaults to 0.75
                       (i.e. 75% of the rated time) to account for wind,
                       temperature, payload, and RTH reserve -- none of
                       which apply to DJI's lab-measured rating.

    Returns:
        The safety-margined max flight time, in seconds.
    """
    rated_minutes = DRONE_BATTERY_MAX_MINUTES.get((drone_model or "").upper(), _GENERIC_MAX_FLIGHT_MINUTES)
    return rated_minutes * 60.0 * safety_margin



# =================
# VIDEO MODE
# =================

def apply_video_mode(editor: MissionEditor) -> MissionEditor:
    """
    Configure a mission for continuous video recording.

    Steps performed:
      1. Remove all takePhoto actions from every waypoint.
      2. Add startRecord to the first waypoint
      3. Add stopRecord to the last waypoint.

    The editor is modified in-place and also returned for chaining.
       >>> editor = apply_video_mode(MissionEditor.from_kmz("mission.kmz"))

    Args:
        editor: A MissionEditor instance with at least 2 waypoints.
    
    Returns:
        The modified MissionEditor instance.
    
    Raises:
        ValueError: If the mission has fewer than 2 waypoints.

    Example:
        >>> editor = MissionEditor.from_kmz("mission.kmz")
        >>> apply_video_mode(editor)
        >>> editor.to_kmz("survey_video.kmz")
    """
    if editor.count < 2:
        raise ValueError(f"Video mode requires at least 2 waypoints, got {editor.count}")

    editor.remove_action_all(CameraAction.TAKE_PHOTO.value)
    editor.update_waypoint(0, actions=[CameraAction.START_RECORD.value])
    editor.update_waypoint(editor.count - 1, actions=[CameraAction.STOP_RECORD.value])

    return editor



# =================
# PHOTO MODE
# =================
def compute_photo_spacing(altitude_m: float, overlap: float, sensor_width_mm: float, sensor_height_mm: float, focal_length_mm: float) -> tuple[float, float]:
    """
    Calculate the optimal distance between photo trigger points.
    Uses the standard photogrammetry footprint formula:
        footprint = (sensor_dim / focal_length) * altitude
        spacing = footprint * (1 - overlap)

    Args:
        - altitude_m: Flight altitude in meters.
        - overlap: Desired overlap as a fracion (e.g., 0.7 for 70% overlap).
        - sensor_width_mm: Physical sensor width in millimeters. 
        - sensor_height_mm: Physical sensor height in millimeters.
        - focal_length_mm: True focal length in millimeters.
    
    Returns:
        A tuple (spacing_along_m, spacing_across_m) where:
            - spacing_along_m = distance between photos along the flight path
            - spacing_across_m = distance between adjacent flight lines
    
    Raises:
        ValueError: overlap not in [0, 1), altitude <= 0, focal_length <= 0
    """
    if not (0.0 <= overlap < 1.0):
        raise ValueError(f"overlap must be in [0, 1), got {overlap}")
    if altitude_m <= 0:
        raise ValueError(f"altitude_m must be > 0, got {altitude_m}")
    if focal_length_mm <= 0:
        raise ValueError(f"focal_length_mm must be > 0, got {focal_length_mm}")

    footprint_w = (sensor_width_mm / focal_length_mm) * altitude_m
    footprint_h = (sensor_height_mm / focal_length_mm) * altitude_m

    spacing_along = footprint_w * (1.0 - overlap)
    spacing_across = footprint_h * (1.0 - overlap)

    return spacing_along, spacing_across


def compute_gsd(altitude_m: float, sensor_width_mm: float, sensor_height_mm: float, focal_length_mm: float, image_width_px: int, image_height_px: int) -> tuple[float, float]:
    """
    Calculate the Ground Sample Distance (GSD) in cm/px.

    GSD is the real-world distance represented by one image pixel.
    Lower GSD means higher resolution and more detail in the photos.

    Formula:
        gsd = (sensor_dim_mm / focal_mm) * altitude_m * 100 / image_dim_px
    
    Args:
        - altitude_m: Flight altitude in meters.
        - sensor_width_mm: Physical sensor width in millimeters. 
        - sensor_height_mm: Physical sensor height in millimeters.
        - focal_length_mm: True focal length in millimeters.
        - image_width_px: Native image width in pixels.
        - image_height_px: Native image height in pixels.

    Returns:
        A tuple (gsd_x_cm_per_px, gsd_y_cm_per_px)
    """
    if altitude_m <= 0 or focal_length_mm <= 0:
        raise ValueError(f"altitude_m and focal_length_mm must be > 0, got {altitude_m} and {focal_length_mm}")
    
    gsd_x = (sensor_width_mm / focal_length_mm) * altitude_m * 100.0 / image_width_px
    gsd_y = (sensor_height_mm / focal_length_mm) * altitude_m * 100.0 / image_height_px

    return gsd_x, gsd_y


def apply_photo_mode(editor: MissionEditor, overlap: float = 0.80, drone_model: str = "MAVIC_3") -> MissionEditor:
    """
    Configure a mission for automated photo capture with optimal spacing and minimal overlap.

    Steps performed:
        1. Remove all startRecord / stopRecord actions.
        2. Compute the optimal photo spacing from average altitude + overlap.
        3. Add takePhoto only at waypoints that are spaced at least the optimal distance apart.
        4. Always add takePhoto to the first and last waypoints.

    If the drone model is not in DRONE_CAMERAS, falls back to adding takePhoto to every waypoint without spacing calculations.

    Args:
        - editor: A MissionEditor instance with at least 2 waypoints.
        - overlap: Desired photo overlap as a fraction (e.g., 0.7 for 70% overlap). Default is 0.80.
        - drone_model: Key in DRONE_CAMERAS (e.g. "MAVIC_3")

    Returns:
        The modified MissionEditor instance.
    
    Raises:
        ValueError: If the mission has fewer than 2 waypoints, or if overlap is not in [0, 1).
    """
    if editor.count < 2:
        raise ValueError(f"apply_photo_mode requires at leas 2 waypoints, got {editor.count}")
    if not (0.0 <= overlap < 1.0):
        raise ValueError(f"overlap must be in [0.0, 1.0), got {overlap}")

    waypoints = editor.waypoints

    # 1. Remove video actions
    editor.remove_action_all(CameraAction.START_RECORD.value)
    editor.remove_action_all(CameraAction.STOP_RECORD.value)

    # 2. Look up camera parameters
    cam = DRONE_CAMERAS.get(drone_model.upper(), None)
    if cam is None:
        editor.add_action_all(CameraAction.TAKE_PHOTO.value)
        return editor
    
    # 3. Compute spacing from average altitude
    avg_altitude = sum(wp.altitude for wp in waypoints) / len(waypoints)
    spacing_m, _ = compute_photo_spacing(
        altitude_m = avg_altitude,
        overlap = overlap,
        sensor_width_mm = cam.sensor_width_mm,
        sensor_height_mm = cam.sensor_height_mm,
        focal_length_mm = cam.focal_length_mm
    )

    # 4. Assign takePhoto based on cumulative distance
    photo_indices: set[int] = {0, len(waypoints) - 1}
    dist_since_last = 0.0

    for i in range(1, len(waypoints)):
        dist_since_last += haversine_wp(waypoints[i-1], waypoints[i])
        if dist_since_last >= spacing_m:
            photo_indices.add(i)
            dist_since_last = 0.0
    
    # 5. Updata all waypoints - add takePhoto only where needed
    for i in range(len(waypoints)):
        current_actions = [a for a in waypoints[i].actions
        if a not in {CameraAction.TAKE_PHOTO.value, CameraAction.START_RECORD.value, CameraAction.STOP_RECORD.value}]

        if i in photo_indices:
            current_actions.append(CameraAction.TAKE_PHOTO.value)
        
        editor.update_waypoint(i, actions=current_actions)
    
    return editor