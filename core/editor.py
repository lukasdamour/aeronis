# ==================================
# IMPORTS
# ==================================
from __future__ import annotations
import copy
import dataclasses

from .models import CameraAction, MissionConfig, Waypoint
from .geometry import compute_total_distance, estimate_flight_time, simplify_waypoints
from .generator import generate_kmz, generate_kmz_bytes
from .parser import parse_kmz



# ==================================
# MISSION EDITOR
# ==================================

class MissionEditor:
    """
    Stateful editor for a DJI waypoint mission.

    Encapsulates a list of Waypoint objects and a MissionConfig, and exposes safe mutation methods that maintain mission validity at all times (index integrity, minimum waypoint count, validates fields).

    Typical workflow:
        # Start from an existing mission
        editor = MissionEditor.from_kmz("original.kmz")

        # Edit
        editor.set_altitude_all(80)
        editor.remove_action_all("takePhoto")
        editor.simplify(eps=0.00005)

        # Export
        editor.to_kmz("modified.kmz)

    All structural modifications (add, remove, move, simplify, reverse) call _reindex() automatically so that callers never need to think about wpml:index consistency.
    """


    # ==================================
    # Construction
    # ==================================
    def __init__(self, waypoints: list[Waypoint], config: MissionConfig) -> None:
        """
        Create a MissionEditor from an existing list of waypoints and config.
        Make a deep copy of both arguments so the editor owns its data independently of the caller.

        Args:
            - waypoints : List of Waypoint objects (may be empty at construction).
            - config : Global mission configuration.

        Raises:
            TypeError : if waypoints is not a list.
        """
        if not isinstance(waypoints, list):
            raise TypeError(
                f"waypoints must be a list, got {type(waypoints).__name__!r}"
            )
        self._waypoints: list[Waypoint] = copy.deepcopy(waypoints)
        self._config: MissionConfig = copy.deepcopy(config)
    
    @classmethod
    def from_kmz(cls, path: str) -> MissionEditor:
        """
        Create a MissionEditor by parsing an existing .kmz file.
        This is the primary entry point when editing an existing mission.

        Args:
            - path : File-system path to the .kmz file.
        
        Returns:
            A new MissionEditor loaded with the mission's waypoints and config.
        
        Raises:
            - FileNotFoundError : file does not exist.
            - ValueError : file is not a valid KMZ or contains no waypoints.

        Example:
            >>> editor = MissionEditor.from_kmz("mission.kmz")
            >>> editor.set_altitude_all(80)
            >>> editor.to_kmz("mission_80m.kmz")
        """
        waypoints, config = parse_kmz(path)
        return cls(waypoints, config)
    

    # ==================================
    # Read-only properties
    # ==================================
    @property
    def waypoints(self) -> list[Waypoint]:
        """
        Return a shallow copy of the internal waypoint list.

        Returning a copy prevents callers from mutating the list directly (which would bypass _reindex() and break index consistency).
        """
        return list(self._waypoints)

    @property
    def config(self) -> MissionConfig:
        """
        Return the mission configuration.
        """
        return self._config
    
    @property
    def count(self) -> int:
        """
        Number of waypoints in the mission.
        """
        return len(self._waypoints)

    def __len__(self) -> int:
        return len(self._waypoints)

    def __repr__(self) -> str:
        return (
            f"MissionEditor("
            f"{len(self._waypoints)} waypoints, "
            f"config={self._config.name!r}"
            f")"
        )
    

    # ==================================
    # Individual waypoint modifications
    # ==================================
    def add_waypoint(self, wp: waypoint, index: int | None = None) -> None:
        """
        Add a waypoint to the mission.

        Args:
            - wp: The Waypoint to add (deep-copied internally).
            - index: Insertion position.
                    None -> append at the end.
                    0 -> insert before the first waypoint.
        
        Raises:
            IndexError : if index > len(waypoints).
        """
        if index is None:
            self._waypoints.append(copy.deepcopy(wp))
        else:
            if not (0 <= index <= len(self._waypoints)):
                raise IndexError(
                    f"Insertion index {index} out of range "
                    f"[0, {len(self._waypoints)}]"
                )
            self._waypoints.insert(index, copy.deepcopy(wp))
        self._reindex()
    
    def remove_waypoint(self, index: int) -> Waypoint:
        """
        Remove and return the waypoint at the given position.

        Args:
          index : Zero-based position of the waypoint to remove.

        Returns:
            The removed Waypoint object.

        Raises:
            - IndexError : index out of range.
            - ValueError : removal would leave fewer than 2 waypoints.
        """
        self._check_index(index)
        if len(self.waypoints) <=2:
            raise ValueError(
                "Cannot remove waypoint: mission would have fewer than 2 waypoints."
            )
        removed = self._waypoints.pop(index)
        self._reindex()
        return removed
    
    def update_waypoint(self, index: int, **kwargs) -> None:
        """
        Update one or more fields of an existing waypoint.

        Only the fields provided as keyword arguments are modified:
        all other fields keep their current values.

        Args:
            - indexError : index out of range.
            - ValueError : unknown field name or invalid value (Waypoint.__post_init__ validation runs).

        Example:
            >>> editor.update_waypoint(3, altitude=120.0, speed=7.5)
        """
        self._check_index(index)

        # Validate field names before applying
        valid_fields = {f.name for f in dataclasses.fields(Waypoint)}
        unknown = set(kwargs) - valid_fields
        if unknown:
            raise ValueError(
                f"Unknown Waypoint field(s): {sorted(unknown)}. "
                f"Valid fields: {sorted(valid_fields)}"
            )

        current = dataclasses.asdict(self._waypoints[index])
        current.update(kwargs)

        self._waypoints[index] = Waypoint(**current)

    def move_waypoint(self, from_index: int, to_index: int) -> None:
        """
        Move a waypoint from one position to another.

        Args:
            - from_index : Current position of the waypoint.
            - to_index : Target position after the move.

        Raises:
            IndexError : either index out of range.
        """
        self._check_index(from_index)
        if not(0 <= to_index <= len(self._waypoints) - 1):
            raise IndexError(
                f"Target index {to_index} out of range "
                f"[0, {len(self._waypoints) - 1}]"
            )
        if from_index == to_index:
            return
        wp = self._waypoints.pop(from_index)
        self._waypoints.insert(to_index, wp)
        self._reindex()


    # ==================================
    # Bulk modifications
    # ==================================
    def set_altitude_all(self, altitude: float) -> None:
        """
        Set the same altitude for every waypoint.

        Args:
            altitude: New altitude in metres (must be >= 0).
        
        Raises:
            ValueError : altitude < 0
        """
        self._waypoints = [
            dataclasses.replace(wp, altitude=altitude) for wp in self._waypoints
        ]
    
    def set_speed_all(self, speed: float | None) -> None:
        """
        Set the same speed for every waypoint.

        Args:
            speed: Speed in m/s (0 < speed <= 15), or None to fall back to the misison transit speed.
        """
        self._waypoints = [
            dataclasses.replace(wp, speed=speed) for wp in self._waypoints
        ]
    
    def set_pitch_all(self, pitch: float | None ) -> None:
        """
        Set the same gimbal pitch angle for every waypoint.

        Args:
            pitch : Angle in degrees [-90, 30], or None to remove the gimbal action from all waypoints.
        """
        self._waypoints = [
            dataclasses.replace(wp, pitch=pitch) for wp in self._waypoints
        ]
    
    def add_action_all(self, action: str) -> None:
        """
        Add a camera action to every waypoint (no duplicates).

        Args:
            action : a CameraAction string value (e.g. "takePhoto").

        Raises:
            ValueError : action is not a valid CameraAction value.
        """
        valid = {a.value for a in CameraAction}
        if action not in valid:
            raise ValueError(
                f"Unknown camera action {action!r}. "
                f"Valid values: {sorted(valid)}"
            )
        new_wps = []
        for wp in self._waypoints:
            if action not in wp.actions:
                new_wps.append(
                    dataclasses.replace(wp, actions=wp.actions + [action])
                )
            else:
                new_wps.append(wp)
        self._waypoints = new_wps

    def remove_action_all(self, action: str) -> None:
        """
        Remove a camera action from every waypoint.
        Does not raise if the action is absent on some (or all) waypoints.

        Args:
            action : a CameraAction string value (e.g. "takePhoto").
        """
        self._waypoints = [
            dataclasses.replace(
                wp, actions=[a for a in wp.actions if a != action]
            ) for wp in self._waypoints
        ]
    
    def reverse(self) -> None:
        """
        Reverse the order of all waypoints in the mission.

        Useful when you want to fly the same path in the opposite direction.
        Calls _reindex() automatically.
        """
        self._waypoints.reverse()
        self._reindex()


    # ==================================
    # Optimisation
    # ==================================
    def simplify(self, eps: float = 0.00001) -> int:
        """
        Reduce the waypoint count using the Ramer-Douglas-Peucker algorithm.

        Removes waypoints that are nearyly collinear with their neighbours, keeping only those that define the actual shape of path.

        Args:
            eps : Tolerance in degrees.
                  0.00001° ~= 1m at the equator.
                  Larger value = more aggressive simplification.
        
        Returns:
            Number of waypoints removed.

        Raises:
            ValueError : simplification would leave fewer than 2 waypoints.

        Example:
            >>> removed = editor.simplify(eps=0.0001)
            >>> print(f"Removed {removed} redundant waypoints")
        """
        original_count = len(self._waypoints)
        simplified = simplify_waypoints(self._waypoints, eps)

        if len(simplified) < 2:
            raise ValueError(
                f"Simplification with eps={eps} would leave only "
                f"{len(simplified)} waypoint(s). "
                "Use a smaller epsilon value."
            )

        self._waypoints = simplified
        self._reindex()
        return original_count - len(self._waypoints)
    

    # ==================================
    # Statistics
    # ==================================
    def stats(self) -> dict:
        """
        Return a summary of the current mission state.

        Returns:
            dict with keys:
                count           : number of waypoints
                distance_m      : total path length in meters
                duration_s      : estimated flight time in seconds
                min_altitude    : lowest waypoint altitude
                max_altitude    : highest waypoint altitude
                avg_speed       : mean of per-waypoint speeds (None if all unset)
        """
        if not self._waypoints:
            return {
                "count": 0,
                "distance_m": 0.0,
                "duration_s": 0.0,
                "min_altitude": None,
                "max_altitude": None,
                "avg_speed": None,
            }
        
        speeds = [wp.speed for wp in self._waypoints if wp.speed is not None]

        return {
            "count": len(self._waypoints),
            "distance_m": compute_total_distance(self._waypoints),
            "duration_s": estimate_flight_time(self._waypoints, default_speed=self._config.transit_speed),
            'min_altitude': min(wp.altitude for wp in self._waypoints),
            'max_altitude': max(wp.altitude for wp in self._waypoints),
            "avg_speed": sum(speeds) / len(speeds) if speeds else None
        }


    # ==================================
    # Export
    # ==================================
    def to_kmz(self, output_path: str) -> None:
        """
        Write the current mission to a .kmz file on disk.

        Args:
            output_path: Destination file path.

        Raises:
            ValueError : fewer than 2 waypoints.
        """
        if len(self._waypoints) < 2:
            raise ValueError(
                "Cannot export : mission has less than 2 waypoints."
            )
        generate_kmz(self._waypoints, self._config, output_path)
    
    
    def to_kmz_bytes(self) -> bytes:
        """
        Return the current mission as raw KMZ bytes (in-memory).
        Useful for the web server /api/generate endpoint.

        Raises:
            ValueError : less than 2 waypoints.
        """
        if len(self._waypoints) < 2:
            raise ValueError(
                "Cannot export : mission has less than 2 waypoints."
            )
        return generate_kmz_bytes(self._waypoints, self._config)

    
    # ==================================
    # Private helpers
    # ==================================
    def _check_index(self, index: int) -> None:
        """
        Raise IndexError if index is out of bounds.
        """
        if not (0 <= index < len(self._waypoints)):
            raise IndexError(
                f"Waypoint index {index} out of range "
                f"[0, {len(self._waypoints) - 1}]"
            )
    
    def _reindex(self) -> None:
        """
        Ensure wpml:index values are 0, 1, 2, ... after any structural change.

        The wpml:index is NOT stored in the Waypoint detaclass. It is computed at generation time by generator.py using enuemrate().
        This method therefore is a no-op in the current implementation, but it is called explicitly after every structural mutation (add, remove, move, reverse, simplify) to document the intent and to make future extensions straightforward if an index field is ever added to the dataclass.
        """
        pass