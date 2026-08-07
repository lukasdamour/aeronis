# ===============
# IMPORTS
# ===============
from .models import MissionConfig, Waypoint
from .geometry import compute_total_distance, estimate_flight_time, haversine_wp
from .flight_modes import get_max_flight_time_s, DEFAULT_SAFETY_MARGIN



# ===============
# CONSTANTS
# ===============

# DJI hard limits
MIN_WAYPOINTS = 2
MAX_WAYPOINTS = 65_535
MAX_ALTITUDE_ERROR_M = 500.0
MIN_DISTANCE_M = 0.5

# Soft limits - legal/operational warnings
MAX_ALTITUDE_WARN_M = 120.0
MAX_TRANSIT_WARN_MS = 10.0



# ===============
# PUBLIC API
# ===============

def validate(waypoints: list[Waypoint], config: MissionConfig) -> tuple[bool, list[str], list[str]]:
    """
    Validate a DJI waypoint mission before export.

    Per-waypoint speed and altitude ranges are already enforced by Waypoint.__post_init__, so this function focuses on mission-level checks that span multiple waypoints or involve external constraints (legal limits, battery life, DJI firmware limits).

    Args:
        - waypoints : Ordered list of Waypoint objects.
        - config : Global mission configuration.

    Returns:
        A tuple (is_valid, errors, warnings) where:
          - is_valid : False if any error was found, True otherwise.
          - errors : Blocking issues - mission must not fly.
          - warnings : Non-blocking concerns - mission can fly but deserves attention.
    
    Example:
        valid, errors, warnings = validate(waypoints, config)
        if not valid:   
            for e in errors: print(f"ERROR: {e}")
        for w in warnings: print(f"WARNING: {w}")
    """
    errors : list[str] = []
    warnings : list[str] = []

    _check_waypoint_count(waypoints, errors)
    _check_altitudes(waypoints, errors, warnings)
    _check_distances(waypoints, errors)
    _check_duration(waypoints, config, warnings)
    _check_transit_speed(config, warnings)
    _check_actions(waypoints, warnings)

    return (len(errors) == 0), errors, warnings



# ===============
# PRIVATE CHECKS
# ===============

def _check_waypoint_count(waypoints: list[Waypoint], errors: list[str]) -> None:
    """
    Check minimum and maximum waypoint count.
    """
    n = len(waypoints)
    if n < MIN_WAYPOINTS:
        errors.append(f"Mission has {n} waypoint(s) - minimum is {MIN_WAYPOINTS}.")
    elif n > MAX_WAYPOINTS:
        errors.append(f"Mission has {n} waypoints - DJI firmware limit is {MAX_WAYPOINTS}.")


def _check_altitudes(waypoints: list[Waypoint], errors: list[str], warnings: list[str]) -> None:
    """
    Check altitude values for hard and soft limits.
    """
    for i, wp in enumerate(waypoints):
        if wp.altitude > MAX_ALTITUDE_ERROR_M:
            errors.append(f"WP{i}: altitude {wp.altitude} m exceeds the DJI hard limit of {MAX_ALTITUDE_ERROR_M} m.")
        elif wp.altitude > MAX_ALTITUDE_WARN_M:
            warnings.append(f"WP{i}: altitude {wp.altitude} m exceeds {MAX_ALTITUDE_WARN_M} (legal ceiling in France without DGAC authorisation).")


def _check_distances(waypoints: list[Waypoint], errors: list[str]) -> None:
    """
    Check that no two consecutive waypoints are duplicates (< 0.5 m apart).
    """
    if len(waypoints) < 2: return
    for i in range(len(waypoints) - 1):
        dist = haversine_wp(waypoints[i], waypoints[i + 1])
        if dist < MIN_DISTANCE_M:
            errors.append(f"WP{i} and WP{i+1} are only {dist:.2f} m apart (minimum is {MIN_DISTANCE_M} m) - likely duplicate coordinates")


def _check_duration(waypoints: list[Waypoint], config: MissionConfig, warnings: list[str]) -> None:
    """
    Warn if estimated flight time exceeds a realistic battery safety
    threshold for the mission's actual drone model (see
    core.flight_modes.get_max_flight_time_s) rather than one fixed
    number for every drone.
    """
    if len(waypoints) < 2: return
    duration_s = estimate_flight_time(waypoints, default_speed=config.transit_speed)

    drone_model = config.drone_type.value
    threshold_s = get_max_flight_time_s(drone_model)

    if duration_s > threshold_s:
        minutes = int(duration_s // 60)
        seconds = int(duration_s % 60)
        threshold_min = int(threshold_s // 60)
        margin_pct = int(DEFAULT_SAFETY_MARGIN * 100)
        warnings.append(
            f"Estimated flight time {minutes}m {seconds}s exceeds the recommended "
            f"{threshold_min} minutes for a {drone_model} ({margin_pct}% of its rated "
            f"max flight time, to leave a safety margin) - battery may be insufficient."
        )


def _check_transit_speed(config: MissionConfig, warnings: list[str]) -> None:
    """
    Warn if transit speed is higher than recommended.
    """
    if config.transit_speed > MAX_TRANSIT_WARN_MS:
        warnings.append(f"Transit speed {config.transit_speed} m/s is high - consider reducing it for safer operation.")


def _check_actions(waypoints: list[Waypoint], warnings: list[str]) -> None:
    """
    Warn if no waypoint has any camera action.
    """
    if not waypoints: return
    if not any(wp.actions for wp in waypoints):
        warnings.append("No camera actions defined on any waypoint - the drone will be flying without taking photos or recording.")