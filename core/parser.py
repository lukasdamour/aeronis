# ===============
# IMPORTS
# ===============

import io
import zipfile
import xml.etree.ElementTree as ET
from typing import Optional

from .models import (
    CameraAction, DroneType, FinishAction,
    HeadingMode, HeightMode, MissionConfig, TurnMode,
    Waypoint, DRONE_INFO_BY_NAME, KML_NS,
)



# ===============
# CONSTANTS
# ===============

# All known WPML namespace versions.
KNOWN_WPML_NS: list[str] = [
    "http://www.dji.com/wpmz/1.0.2",
    "http://www.dji.com/wpmz/1.0.3",
    "http://www.dji.com/wpmz/1.0.4",
    "http://www.dji.com/wpmz/1.0.6",
]

# Priority order of WPML files inside a KMZ archive.
# waylines.wpml is the file actually executed by the drone.
# template.kml is the fallback (used by the mission editor UI). 
WPML_FILES: list[str] = [
    "wpmz/waylines.wpml",
    "wpmz/template.kml"
]



# ===============
# PUBLIC API
# ===============

def parse_kmz(path: str) -> tuple[list[Waypoint], MissionConfig]:
    """
    Parse a DJI .kmz file and return its waypoints and global config.

    The function reads the archive entirely in memory (no extractall, no temp files on disk) and detects the wpml namespace version automatically.

    Priority: wpmz/waylines.wpml > wpmz/template.kml

    Args:
        path: File-system path to the .kmz file.
    
    Returns:
        A tuple (waypoints, config) where:
          - waypoints is an ordered list of Waypoint objects.
          - config is the MissionConfig extracted from missionConfig.

    Raises:
        - FileNotFoundError: the file does not exist or is not readable.
        - ValueError: the archive contains no recognized WPML file, or the WPML file namespace cannot be identified, or no valid Placemark was found.
    
    Example:
        >>> waypoints, config = parse_kmz("mission.kmz")
        >>> print(len(waypoints)) # 183
    """
    try:
        zf = zipfile.ZipFile(path, "r")
    except FileNotFoundError:
        raise FileNotFoundError(f"KMZ file not found: {path!r}")
    except zipfile.BadZipFile:
        raise ValueError(f"File is not a valid ZIP/KMZ archive: {path!r}")

    with zf:
        available = zf.namelist()
        for candidate in WPML_FILES:
            if candidate in available:
                data = zf.read(candidate)
                return _parse_wpml_bytes(data)

    raise ValueError(
        f"No WPML file found in {path!r}."
        f"Expected one of: {WPML_FILES}."
        f"Found: {available}."
    )


def print_report(waypoints: list[Waypoint], config: MissionConfig) -> None:
    """
    Print a human-readable mission report to stdout.

    Args:
        waypoints : Parsed list of Waypoint objects.
        config    : Parsed MissionConfig.
    """

    from .geometry import compute_total_distance, estimate_flight_time

    total_dist = compute_total_distance(waypoints)
    total_time = estimate_flight_time(
        waypoints, default_speed=config.transit_speed
    )
    minutes, seconds = divmod(int(total_time), 60)

    print("=" * 60)
    print("MISSION REPORT")
    print("=" * 60)
    print(f"  Name            : {config.name}")
    print(f"  Author          : {config.author}")
    print(f"  Drone           : {config.drone_type.name}")
    print(f"  Finish action   : {config.finish_action.value}")
    print(f"  Height mode     : {config.height_mode.value}")
    print(f"  Transit speed   : {config.transit_speed} m/s")
    print(f"  RC lost action  : {config.rc_lost_action}")
    print("-" * 60)
    print(f"  Waypoints       : {len(waypoints)}")
    print(f"  Total distance  : {total_dist:.1f} m")
    print(f"  Estimated time  : {minutes}m {seconds:02d}s")
    print("-" * 60)
    for i, wp in enumerate(waypoints):
        actions_str = ", ".join(wp.actions) if wp.actions else "—"
        pitch_str   = f"{wp.pitch:.1f}°" if wp.pitch is not None else "—"
        speed_str   = f"{wp.speed} m/s" if wp.speed is not None else "default"
        print(
            f"  WP {i:>3}  "
            f"lon={wp.lon:.6f}  lat={wp.lat:.6f}  "
            f"alt={wp.altitude:.1f}m  "
            f"speed={speed_str}  "
            f"pitch={pitch_str}  "
            f"actions=[{actions_str}]"
        )
    print("=" * 60)



# ===============
# PRIVATE HELPERS
# ===============
def _parse_wpml_bytes(data: bytes) -> tuple[list[Waypoint], MissionConfig]:
    """
    Parse raw XML bytes (from waylines.wpml or template.kml) and return (waypoints, config).

    Args:
        data: Raw bytes of the WPML/XML file.

    Returns:
        A tuple (waypoints, config) where:
          - waypoints is an ordered list of Waypoint objects.
          - config is the MissionConfig extracted from missionConfig.
    
    Raises:
        - ValueError: namespace not detected, or no valid Placemark found.
    """
    try:
        root = ET.parse(io.BytesIO(data)).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"Invalid XML in WPML file: {exc}") from exc
    
    ns = _detect_wpml_ns(root)
    config = _parse_mission_config(root, ns)

    w = ns["wpml"]
    kml = ns["kml"]

    # Locate the Folder that holds the Placemarks.
    # In waylines.wpml the Folder is a direct child of the root Document.
    folder = root.find(f"{{{kml}}}Document/{{{kml}}}Folder")
    if folder is None:
        # Fallback: search anywhere in the tree
        folder = root.find(f".//{{{kml}}}Folder")
    if folder is None:
        raise ValueError("No <Folder> element found in WPML file.")

    placemarks = folder.findall(f"{{{kml}}}Placemark")
    if not placemarks:
        placemarks = folder.findall(f"{{{w}}}index")
    if not placemarks:
        raise ValueError("No <Placemark> elements found in WPML <Folder>.")
    
    waypoints: list[Waypoint] = []
    seen_indices: set[str] = set()

    for pm in placemarks:
        # Deduplicate by wpml:index
        idx = pm.findtext(f"{{{w}}}index")
        if idx in seen_indices:
            continue
        if idx is not None:
            seen_indices.add(idx)
        
        wp = _parse_placemark(pm, ns)
        if wp is not None:
            waypoints.append(wp)
    
    if not waypoints:
        raise ValueError("No valid waypoints could be extracted from the WPML file.")
    
    return waypoints, config


def _detect_wpml_ns(root: ET.Element) -> dict[str, str]:
    """
    Detect the WPML namespace version used in the XML tree.

    Tries each version in KNOWN_WPML_NS until it finds one that matches the root tag.

    Args:
        root: Root element of the parsed XML tree.
    
    Returns:
        {"kml": KML_NS, "wpml": detected_wpml_ns}
    
    Raises:
        ValueError: No known WPML namespace matches the XML root tag.
    """

    for candidate in KNOWN_WPML_NS:
        probe = root.find(f".//{{{candidate}}}missionConfig")
        if probe is not None:
            return {"kml": KML_NS, "wpml": candidate}
    
    raise ValueError(
        f"Could not detect a known WPML namespace in the XML."
        f"Tried: {KNOWN_WPML_NS}."
    )


def _parse_mission_config(root: ET.Element, ns: dict[str, str]) -> MissionConfig:
    """
    Extract the global mission metadata from the <missionConfig> element.
    All fields use safe defaults when a tag is absent, so parsing never fails on a partialy-written KMZ.

    Real KMZ values for reference:
        author              = "author"
        finishAction        = "noAction"
        globalTransitSpeed  = 15.0  (transit between waypoints)
        autoFlightSpeed     = 10.5  (per-waypoint speed, in Folder)
        droneEnumValue      = "68"  (consumer drone)
        droneSubEnumValue   = "0"
        executeRCLostAction = "goBack"
        executeHeightMode   = "relativeToStartPoint"
    """
    w = ns["wpml"]

    author = root.findtext(f".//{{{w}}}author") or "author"

    #finishAction
    finish_raw = root.findtext(f".//{{{w}}}finishAction") or "goHome"
    try:
        finish_action = FinishAction(finish_raw)
    except ValueError:
        finish_action = FinishAction.GO_HOME
    
    # globalTransitionalSpeed
    transit_speed = _safe_float(
        root.findtext(f".//{{{w}}}globalTransitionalSpeed"), default=10.0
    )
    transit_speed = max(0.1, min(15.0, transit_speed or 10.0))

    # Drone identification
    enum_val     = root.findtext(f".//{{{w}}}droneEnumValue")     or "68"
    sub_val_str  = root.findtext(f".//{{{w}}}droneSubEnumValue")  or "0"
    sub_val      = int(_safe_float(sub_val_str, default=0))
    drone_type   = _resolve_drone_type(enum_val, sub_val)

    # RC lost action
    rc_lost_raw = root.findtext(f".//{{{w}}}executeRCLostAction") or "hover"
    rc_lost_map = {"goBack": "goHome"}
    rc_lost_action = rc_lost_map.get(rc_lost_raw, rc_lost_raw)
    if rc_lost_action not in {"hover", "goHome", "autoLand"}:
        rc_lost_action = "hover"

    # Height mode: found inside <Folder> in waylines.wpml
    height_raw = root.findtext(f".//{{{w}}}executeHeightMode") or "relativeToStartPoint"
    try:
        height_mode = HeightMode(height_raw)
    except ValueError:
        height_mode = HeightMode.RELATIVE

    return MissionConfig(
        author        = author,
        drone_type    = drone_type,
        finish_action = finish_action,
        height_mode   = height_mode,
        transit_speed = transit_speed,
        rc_lost_action= rc_lost_action,
    )



def _parse_placemark(pm: ET.Element, ns: dict[str, str]) -> Optional[Waypoint]:
    """
    Extract a single Waypoint from a <Placemark> element.
    Returns None if coordinates are missing or unparseable,
    so the caller can simply skip invalid Placemarks.
    """

    w = ns["wpml"]
    kml = ns["kml"]

    # Coordinates
    coords_text = pm.findtext(f"{{{kml}}}Point/{{{kml}}}coordinates")
    if coords_text is None:
        coords_text = pm.findtext(f"{{{w}}}Point/{{{w}}}coordinates")
    if coords_text is None:
        coords_text = pm.findtext("Point/coordinates")

    if coords_text is None:
        return None
    try:
        parts = coords_text.strip().split(",")
        lon = float(parts[0])
        lat = float(parts[1])
    except (IndexError, ValueError):
        return None
    
    # Direct Placemark fields
    altitude = _safe_float(pm.findtext(f"{{{w}}}executeHeight"), default=0.0)

    # waypointSpeed is None when absent
    speed_text = pm.findtext(f"{{{w}}}waypointSpeed")
    speed = _safe_float(speed_text)

    # Heading mode
    heading_raw = pm.findtext(f"{{{w}}}waypointHeadingParam/{{{w}}}waypointHeadingMode")
    try:
        heading_mode = HeadingMode(heading_raw) if heading_raw else HeadingMode.FOLLOW_WAYLINE
    except ValueError:
        heading_mode = HeadingMode.FOLLOW_WAYLINE

    # heading_angle: only read when mode is FIXED
    heading_angle: Optional[float] = None
    if heading_mode == HeadingMode.FIXED:
        heading_angle = _safe_float(
            pm.findtext(f"{{{w}}}waypointHeadingParam/{{{w}}}waypointHeadingAngle")
        )
    
    # Turn mode
    turn_raw = pm.findtext(f"{{{w}}}waypointTurnParam/{{{w}}}waypointTurnMode")
    try:
        turn_mode = TurnMode(turn_raw) if turn_raw else TurnMode.STOP_DISCONTINUOUS
    except ValueError:
        turn_mode = TurnMode.STOP_DISCONTINUOUS
    

    # ActionGroups
    actions: list[str] = []
    pitch: Optional[float] = None
    valid_actions = {a.value for a in CameraAction}

    for ag in pm.findall(f"{{{w}}}actionGroup"):
        trigger = ag.findtext(f"{{{w}}}actionTrigger/{{{w}}}actionTriggerType")

        if trigger == "reachPoint":
            for action in ag.findall(f"{{{w}}}action"):
                func = action.findtext(f"{{{w}}}actionActuatorFunc")
                if func is None:
                    continue

                _GIMBAL_FUNCS = {"gimbalRotate", "gimbalEvenlyRotate"}
                if func in valid_actions and func not in _GIMBAL_FUNCS:
                    if func not in actions:
                        actions.append(func)
                
                if func == "gimbalRotate":
                    pitch = _safe_float(
                        action.findtext(
                            f"{{{w}}}actionActuatorFuncParam"
                            f"{{{w}}}gimbalPitchRotateAngle"
                        )
                    )
        
        elif trigger == "betweenAdjacentPoints":
            # Pitch during travel. Use only as fallback if not already set by gimbalRotate above.
            if pitch is None:
                for action in ag.findall(f"{{{w}}}action"):
                    func = action.findtext(f"{{{w}}}actionActuatorFunc")
                    if func == "gimbalEvenlyRotate":
                        pitch = _safe_float(
                            action.findtext(
                                f"{{{w}}}actionActuatorFuncParam"
                                f"/{{{w}}}gimbalPitchRotateAngle"
                            )
                        )
    
    # Build Waypoint
    try:
        return Waypoint(
            lon = lon,
            lat = lat,
            altitude = altitude or 0.0,
            speed = speed,
            pitch = pitch,
            actions = actions,
            heading_mode = heading_mode,
            turn_mode = turn_mode,
            heading_angle = heading_angle
        )
    except ValueError:
        return None


def _resolve_drone_type(enum_value: str, sub_enum_value: int) -> DroneType:
    """
    Reverse-lookup: find the DroneType whose DroneInfo matches (enum_value, sub_enum_value).
    Iterates DRONE_INFO_BY_NAME to find the first matching entry.
    Falls back to DroneType.MAVIC_3 if nothing matches, so parsing never raises on an unknown drone.

    Args:
        - enum_value : wpml:droneEnumValue as a string (e.g. "68")
        - sub_enum_value : wpml:droneSubEnumValue as an int (e.g. 0)

        Returns:
            The matching DroneType, or DroneType.MAVIC_3 as a safe default.
    """
    for name, info in DRONE_INFO_BY_NAME.items():
        if info.enum_value == enum_value and info.sub_enum_value == sub_enum_value:
            try:
                return DroneType[name]
            except KeyError:
                continue
    return DroneType.MAVIC_3


def _safe_float(text: Optional[str], default: Optional[float] = None) -> Optional[float]:
    """
    Convert a string to float, returning default on None or parse error.
    Used throughout the parser to avoid AttributeError/ValueError on missing or malformed XML text content.

    Args:
        - text : String value from ET.findtext().
        - default : Value to return when conversion fails.

    Returns:
        - float or default
    """
    if text is None:
        return default
    try:
        return float(text.strip())
    except (ValueError, AttributeError):
        return default