# ===========
# IMPORTS
# ===========
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


# ===========
# NAMESPACES
# ===========

KML_NS = 'http://www.opengis.net/kml/2.2'
WPML_NS = 'http://www.dji.com/wpmz/1.0.4'

NS = {
    "kml": KML_NS,
    "wpml": WPML_NS
}


# ===========
# ENUMS
# ===========

class FinishAction(str, Enum):
    """
    Action performed by the drone at the end of the mission.
    """
    GO_HOME             = 'goHome'  # default value (recommended)
    HOVER               = 'hover'
    AUTO_LAND           = 'autoLand'
    GOTO_FIRST_WAYPOINT = 'gotoFirstWaypoint'
    NO_ACTION           = 'noAction'

class HeightMode(str, Enum):
    """
    Reference frame used for waypoint altitudes.
    """
    RELATIVE    = 'relativeToStartPoint'   # altitude relative to the takeoff point
    WGS84       = 'WGS84' # GPS absolute altitude
    FOLLOW      = 'realTimeFollowSurface' # real-time field monitoring

class HeadingMode(str, Enum):
    """
    Controls the yaw heading of the drone during the mission.
    """
    FOLLOW_WAYLINE      = 'followWayline' # orient the drone along the flight path
    MANUALLY            = 'manually'
    FIXED               = 'fixed'
    SMOOTH_TRANSITION   = 'smoothTransition' # smoothly transition between waypoints


class TurnMode(str, Enum):
    """
    Controls the turning behavior of the drone at each waypoint.
    """
    STOP_DISCONTINUOUS  = 'toPointAndStopWithDiscontinuityCurvature' # stop at the waypoint and make a sharp turn (useful for photos)
    STOP_CONTINUOUS     = 'toPointAndStopWithContinuityCurvature'
    PASS_CONTINUOUS     = 'toPointAndPassWithContinuityCurvature' # pass through the waypoint without stopping, making a smooth turn (useful for videos)
    COORDINATE          = 'coordinateTurn'

class DroneType(str, Enum):
    """
    DJI drone models.
    """
    # -- Consumer drones (DJI Fly) --
    MINI_3_PRO      = "MINI_3_PRO"
    MINI_4_PRO      = "MINI_4_PRO"
    MAVIC_3         = "MAVIC_3"
    MAVIC_3_CLASSIC = "MAVIC_3_CLASSIC"
    AIR_3           = "AIR_3"
    AIR_3S          = "AIR_3S"
    
    # -- Mavic 3 Enterprise series (DJI Pilot 2) --
    MAVIC_3_ENTERPRISE    = "MAVIC_3_ENTERPRISE"
    MAVIC_3_THERMAL       = "MAVIC_3_THERMAL"
    MAVIC_3_MULTISPECTRAL = "MAVIC_3_MULTISPECTRAL"

    # -- Matrice 30 series (DJI Pilot 2 + Dock) --
    MATRICE_30  = "MATRICE_30"
    MATRICE_30T = "MATRICE_30T"

    # -- Matrice 3D series (DJI Pilot 2 + Dock 2) --
    MATRICE_3D  = "MATRICE_3D"
    MATRICE_3TD = "MATRICE_3TD"

    # -- Matrice 300 / 350 series (DJI Pilot 2) --
    MATRICE_300     = "MATRICE_300"
    MATRICE_350_RTK = "MATRICE_350_RTK"

class CameraAction(str, Enum):
    """
    Camera / gimbal actions that can be triggered at a waypoint.
    """
    TAKE_PHOTO = 'takePhoto'
    START_RECORD = 'startRecord'
    STOP_RECORD = 'stopRecord'
    HOVER = 'hover'
    ROTATE_YAW = 'rotateYaw'
    GIMBAL_ROTATE = 'gimbalRotate'


# ===========
# DATACLASSES
# ===========

# DroneInfo
@dataclass(frozen=True)
class DroneInfo:
    """
    Holds both WPML identifiers for a drone model.

    Attributes:
      - enum_value      : wpml:droneEnumValue       (e.g., "68" for Mavic 3 series)
      - sub_enum_value  : wpml:droneSubEnumValue    (e.g., "0" for Mavic 3 Pro, "1" for Mavic 3 Classic)
    """
    enum_value: str
    sub_enum_value: int


DRONE_INFO_BY_NAME: dict[str, DroneInfo] = {
    # --- Consumer drones ---
    "MINI_3_PRO":               DroneInfo("68", 0),
    "MINI_4_PRO":               DroneInfo("68", 0),
    "MAVIC_3":                  DroneInfo("68", 0),
    "MAVIC_3_CLASSIC":          DroneInfo("68", 0),
    "AIR_3":                    DroneInfo("68", 0),
    "AIR_3S":                   DroneInfo("68", 0),

    # --- Mavic 3 Enterprise series ---
    "MAVIC_3_ENTERPRISE":       DroneInfo("77", 0),
    "MAVIC_3_THERMAL":          DroneInfo("77", 1),
    "MAVIC_3_MULTISPECTRAL":    DroneInfo("77", 2),

    # --- Matrice 30 series ---
    "MATRICE_30":               DroneInfo("67", 0),
    "MATRICE_30T":              DroneInfo("67", 1),

    # --- Matrice 3D series ---
    "MATRICE_3D":               DroneInfo("91", 0),
    "MATRICE_3TD":              DroneInfo("91", 1),

    # --- Matrice 300/350 series ---
    "MATRICE_300":              DroneInfo("60", 0),
    "MATRICE_350_RTK":          DroneInfo("89", 0),
}

def get_drone_info(drone_type: DroneType) -> DroneInfo:
    """
    Return the DroneInfo (enum_value + sub_enum_value) for a given DroneType.

    Raises:
        ValueError: if the drone type is not present in DRONE_INFO_BY_NAME.

    Usage:
        info = get_drone_info(DroneType.MAVIC_3_THERMAL)
        info.enum_value      # -> "77"
        info.sub_enum_value  # -> 1
    """
    if drone_type.name not in DRONE_INFO_BY_NAME:
        raise ValueError(f"Unsupported drone type: {drone_type.name}")
    return DRONE_INFO_BY_NAME[drone_type.name]


@dataclass
class Waypoint:
    """
    Represents a single waypoint in a DJI mission.

    Fields with no default value must be provided explicitly;
    optional fields default to None or sensible DJI values.

    Attributes:
        lon           : WGS-84 longitude in degrees  [-180, 180]
        lat           : WGS-84 latitude  in degrees  [-90,  90]
        altitude      : Flight height in meters (wpml:executeHeight). Must be >= 0.
        speed         : Waypoint speed in m/s (wpml:waypointSpeed).
                        None means "use the mission transit speed".
        pitch         : Gimbal pitch angle in degrees (wpml:gimbalPitchRotateAngle).
                        None means the gimbal angle is not explicitly set.
        actions       : Ordered list of CameraAction string values to execute on arrival.
        heading_mode  : Yaw behaviour during travel to this waypoint.
        turn_mode     : How the drone handles the turn at this waypoint.
        heading_angle : Required (and only used) when heading_mode is FIXED.
    """
    lon: float                                              # longitude
    lat: float                                              # latitude
    altitude: float                                         # wpml:executeHeight (m)
    speed: Optional[float]                                  # wpml:waypointSpeed (m/s) (default = None)
    pitch: Optional[float]                                  # wpml:gimbalPitchRotateAngle (°)
    actions: List[str] = field(default_factory=list)        # list of CameraAction.value
    heading_mode: HeadingMode = HeadingMode.FOLLOW_WAYLINE 
    turn_mode: TurnMode = TurnMode.STOP_DISCONTINUOUS
    heading_angle: Optional[float] = None                   # used when heading_mode is FIXED (°)

    def __post_init__(self):
        if self.heading_mode == HeadingMode.FIXED and self.heading_angle is None:
            raise ValueError(f"heading_angle is only used when heading_mode is FIXED "
                f"(current mode: {self.heading_mode.value!r})")
        if not (-180 <= self.lon <= 180):
            raise ValueError("Longitude must be between -180 and 180 degrees")
        if not (-90 <= self.lat <= 90):
            raise ValueError("Latitude must be between -90 and 90 degrees")
        if self.altitude < 0:
            raise ValueError("Altitude must be a non-negative value")
        if self.speed is not None and not (0 < self.speed <= 15):
            raise ValueError("Speed must be between 0 and 15 m/s")
        if self.pitch is not None and not (-90 <= self.pitch <= 30):
            raise ValueError("Gimbal pitch angle must be between -90 and 30 degrees")
        valid_actions = {a.value for a in CameraAction}
        invalid = [a for a in self.actions if a not in valid_actions]
        if invalid:
            raise ValueError(
                f"Unknown camera action(s): {invalid}. "
                f"Valid values: {sorted(valid_actions)}"
            )
    
    def coord(self) -> tuple:
        """ 
        return (lon, lat) tuple
        """
        return (self.lon, self.lat)
    
    def to_dict(self) -> dict:
        """
        Convert the Waypoint dataclass to a dictionary
        """
        return {
            "coord": (self.lon, self.lat),
            "alt": self.altitude,
            "pitch": self.pitch,
            "speed": self.speed,
            "actions": self.actions,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Waypoint":
        """
        Create a Waypoint instance from a dictionary
        """
        lon, lat = data["coord"]
        return cls(
            lon = lon, lat = lat,
            altitude = data.get("alt", 0.0),
            speed = data.get("speed"),
            pitch = data.get("pitch"),
            actions = data.get("actions", [])
        )

@dataclass
class MissionConfig:
    """
    Global configuration for a DJI waypoint mission.

    Attributes:
        name          : Mission display name (shown in DJI Pilot 2).
        author        : Free-text author string written to wpml:author.
        drone_type    : Target drone model — drives droneEnumValue / droneSubEnumValue.
        finish_action : What the drone does when the last waypoint is reached.
        height_mode   : Altitude reference frame for all waypoints.
        transit_speed : Default speed (m/s) used when Waypoint.speed is None.
                        Also written to wpml:globalTransitionalSpeed.
        rc_lost_action: Behaviour when RC signal is lost mid-mission.
    """
    name: str = "Mission"
    author: str = "Aeronis"
    drone_type: DroneType = DroneType.MAVIC_3
    finish_action: FinishAction = FinishAction.GO_HOME
    height_mode: HeightMode = HeightMode.RELATIVE
    transit_speed: float = 10.0
    rc_lost_action: str = "goHome"

    def __post_init__(self) -> None:
        # validate transit_speed at construction time,
        # not only when the KMZ is generated.
        if not (0 < self.transit_speed <= 15):
            raise ValueError(
                f"transit_speed must be in (0, 15] m/s, got {self.transit_speed}"
            )
        valid_rc = {"hover", "goHome", "autoLand"}
        if self.rc_lost_action not in valid_rc:
            raise ValueError(
                f"rc_lost_action must be one of {valid_rc}, "
                f"got {self.rc_lost_action!r}"
            )

    @property
    def drone_info(self) -> DroneInfo:
        """
        Returns the DroneInfo for the configured drone_type.

        Usage:
            config = MissionConfig(drone_type=DroneType.MAVIC_3_THERMAL)
            config.drone_info.enum_value    # -> "77"
            config.drone_info.sub_enum_value # -> 1
        """
        return get_drone_info(self.drone_type)