# ========================================
# IMPORTS
# ========================================
import re
from dataclasses import dataclass, asdict
from typing import Optional

from ..models import DroneType, FinishAction


# ========================================
# JSON SCHEMA handed to the LLM
# ========================================
# Kept intentionally small and flat: this is exactly the set of fields
# the zone-panel UI already exposes (web/index.html #zone-*), so the
# frontend can apply the result by just writing these values into the
# existing inputs and re-running the existing preview pipeline.

CAPTURE_MODES = ["photo", "video", "none"]

PLAN_JSON_SCHEMA = {
    "name": "propose_mission_plan",
    "description": (
        "Propose parameters for a DJI drone mapping/filming mission over "
        "an area the user has already drawn on the map, or over an area "
        "centered on a place already resolved separately. Do NOT invent "
        "coordinates or waypoints yourself: only choose the mission "
        "parameters."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "altitude": {
                "type": "number",
                "description": "Flight altitude in meters above the takeoff point (5-500).",
            },
            "speed": {
                "type": "number",
                "description": "Flight speed in m/s (1-15).",
            },
            "overlap": {
                "type": "number",
                "description": "Photo overlap between flight lines, as a fraction 0-0.95 (e.g. 0.8 = 80%). Only meaningful for photo mode, but always provide a sensible value.",
            },
            "angle": {
                "type": "number",
                "description": "Flight line angle in degrees, 0-179. 0 keeps the default orientation.",
            },
            "drone": {
                "type": "string",
                "enum": [d.value for d in DroneType],
                "description": "DJI drone model to use.",
            },
            "capture_mode": {
                "type": "string",
                "enum": CAPTURE_MODES,
                "description": "'photo' = takePhoto at each computed waypoint, 'video' = continuous recording start/stop, 'none' = no camera action.",
            },
            "finish_action": {
                "type": "string",
                "enum": [f.value for f in FinishAction],
                "description": "What the drone does once the mission is finished.",
            },
            "max_waypoints_per_mission": {
                "type": "integer",
                "description": "Split large missions into chunks of at most this many waypoints (1-200).",
            },
            "reasoning": {
                "type": "string",
                "description": "One short sentence, in the same language as the user's request, explaining the choices made.",
            },
        },
        "required": [
            "altitude", "speed", "overlap", "angle", "drone",
            "capture_mode", "finish_action", "max_waypoints_per_mission",
            "reasoning",
        ],
    },
}


# ========================================
# Bounds also enforced server-side
# ========================================

_BOUNDS = {
    "altitude": (5.0, 500.0),
    "speed": (1.0, 15.0),
    "overlap": (0.0, 0.95),
    "angle": (0.0, 179.0),
    "max_waypoints_per_mission": (1, 200),
    "radius_m": (10.0, 2000.0),
}


_DISALLOWED = re.compile(r'["\'\n\r\t]')


def _clamp(value, lo, hi):
    try:
        value = type(lo)(value)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, value))


# ========================================
# Deterministic "ground truth" extraction
# ========================================
# Defense in depth, same spirit as clamping: local models sometimes get
# tool/structured-output arguments *mostly* right but still mistype a
# number the user explicitly gave (e.g. asked for 50m, returns 45).
# Numbers stated explicitly with a unit in the prompt are unambiguous,
# so they're extracted with plain regex and used to override whatever
# the model answered for that field -- the model is only trusted to
# interpret genuinely ambiguous requests (no explicit number given).

_RE_SPEED = re.compile(r"(\d+(?:\.\d+)?)\s*m\s*/\s*s\b", re.IGNORECASE)
_RE_OVERLAP = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_RE_ANGLE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:°|deg(?:ree)?s?\b)", re.IGNORECASE)
# "50m" / "50 meters", but not the "m" in "10m/s" (handled by the
# negative lookahead) and not a bare "%"/"°" number already matched above.
_RE_ALTITUDE = re.compile(r"(\d+(?:\.\d+)?)\s*m(?:eters)?\b(?!\s*/\s*s)", re.IGNORECASE)


def extract_explicit_values(prompt: str) -> dict:
    """
    Returns a dict with only the keys the prompt explicitly and
    unambiguously states, e.g. {"altitude": 50.0, "speed": 10.0,
    "overlap": 0.6, "angle": 40.0}. Missing keys mean "not stated";
    callers should leave those to the model / current params.
    """
    out = {}

    m = _RE_SPEED.search(prompt)
    if m:
        out["speed"] = float(m.group(1))

    m = _RE_OVERLAP.search(prompt)
    if m:
        out["overlap"] = float(m.group(1)) / 100.0

    m = _RE_ANGLE.search(prompt)
    if m:
        out["angle"] = float(m.group(1))

    m = _RE_ALTITUDE.search(prompt)
    if m:
        out["altitude"] = float(m.group(1))

    return out


@dataclass
class MissionPlan:
    """
    Validated, clamped mission plan. Mirrors ZONE_PARAMS in web/js/zones.js
    plus a couple of extra fields (finish_action, max_waypoints_per_mission,
    place/radius_m, reasoning) surfaced to the user.
    """
    altitude: float
    speed: float
    overlap: float
    angle: float
    drone: str
    capture_mode: str
    finish_action: str
    max_waypoints_per_mission: int
    place: str
    radius_m: float
    reasoning: str

    @classmethod
    def from_raw(
        cls, data: dict, fallback: Optional[dict] = None, explicit: Optional[dict] = None,
        place: str = "", radius_m: float = 100,
    ) -> "MissionPlan":
        """
        Build a MissionPlan from the (untrusted) raw dict returned by an
        LLM provider, clamping numeric fields and falling back to safe
        defaults (or to the UI's current params, if given) for anything
        missing or invalid. `explicit` (see extract_explicit_values)
        overrides the model's answer for any field the user's prompt
        stated unambiguously, as a defense against the model mistyping
        a number it was actually given. `place`/`radius_m` come from a
        separate, dedicated place-detection call (see
        core.llm.place_schema) -- a single flat 2-field schema is far
        more reliable for small local models than asking for it
        alongside 9 other mission parameters in one shot.
        """
        fallback = fallback or {}
        explicit = explicit or {}

        def pick(key, default):
            if key in explicit:
                return explicit[key]
            return data.get(key, fallback.get(key, default))

        drone = str(pick("drone", "MAVIC_3")).upper()
        if drone not in DroneType._value2member_map_:
            drone = "MAVIC_3"

        capture_mode = str(pick("capture_mode", "photo")).lower()
        if capture_mode not in CAPTURE_MODES:
            capture_mode = "photo"

        finish_action = str(pick("finish_action", FinishAction.GO_HOME.value))
        if finish_action not in FinishAction._value2member_map_:
            finish_action = FinishAction.GO_HOME.value

        reasoning = str(pick("reasoning", ""))[:400]
        place = _DISALLOWED.sub("", str(place or "").strip())[:120]

        return cls(
            altitude=_clamp(pick("altitude", 80), *_BOUNDS["altitude"]),
            speed=_clamp(pick("speed", 5), *_BOUNDS["speed"]),
            overlap=_clamp(pick("overlap", 0.8), *_BOUNDS["overlap"]),
            angle=_clamp(pick("angle", 0), *_BOUNDS["angle"]),
            drone=drone,
            capture_mode=capture_mode,
            finish_action=finish_action,
            max_waypoints_per_mission=int(_clamp(
                pick("max_waypoints_per_mission", 150),
                *_BOUNDS["max_waypoints_per_mission"]
            )),
            place=place,
            radius_m=_clamp(radius_m, *_BOUNDS["radius_m"]),
            reasoning=reasoning,
        )

    def to_dict(self) -> dict:
        return asdict(self)
