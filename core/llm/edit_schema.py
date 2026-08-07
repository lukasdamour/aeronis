# ======================================
# IMPORTS
# ======================================
from dataclasses import dataclass, asdict
from typing import Optional

from ..models import CameraAction
from .schema import extract_explicit_values, _clamp, _BOUNDS


# ======================================
# JSON SCHEMA handed to the LLM
# ======================================
# Flat and all-required, same reasoning as core/llm/schema.py: local
# models are far more reliable at filling in every field of a flat
# object (via Ollama's constrained-decoding `format`) than at deciding
# which of several fields to omit. "Not requested" has an explicit,
# unambiguous sentinel per field (current value / "" / false) instead
# of relying on the model to correctly omit something.

_ACTION_VALUES = [a.value for a in CameraAction]

# Semantic simplification levels, mapped deterministically to a
# Ramer-Douglas-Peucker epsilon (see core.geometry.simplify_waypoints).
# Same reasoning as clamping/enums elsewhere: the model has no reliable
# sense of what "0.00002 degrees" means, but it can reliably classify
# how aggressive a cleanup the request implies -- the actual numeric
# tolerance is then applied deterministically, not chosen by the model.
SIMPLIFY_LEVEL_EPS = {
    "none": 0.0,
    "light": 0.000005,       # ~0.5m -- drop only near-duplicate points
    "moderate": 0.00002,     # ~2m   -- typical hand-drawn path cleanup
    "aggressive": 0.00005,   # ~5m   -- drastic reduction, messy paths only
}

EDIT_JSON_SCHEMA = {
    "name": "propose_mission_edit",
    "description": (
        "Propose edits to apply to an existing DJI drone mission "
        "(a list of waypoints already placed on the map). Only choose "
        "actual operations to run; never invent coordinates."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "altitude": {
                "type": "number",
                "description": "New altitude in meters (5-500) for every waypoint. If the request doesn't mention altitude, repeat the current altitude unchanged.",
            },
            "speed": {
                "type": "number",
                "description": "New speed in m/s (1-15) for every waypoint. If the request doesn't mention speed, repeat the current speed unchanged.",
            },
            "overlap": {
                "type": "number",
                "description": (
                    "Photo overlap between flight lines, as a fraction 0-0.95 "
                    "(e.g. 0.8 = 80%). Only used if switching capture_mode to "
                    "'photo'; if the request doesn't mention overlap, repeat the "
                    "current value unchanged."
                ),
            },
            "add_action": {
                "type": "string",
                "enum": _ACTION_VALUES + [""],
                "description": (
                    "A single camera action to add to every waypoint, or '' if "
                    "not requested. Do NOT use this for switching to photo/video "
                    "mode -- use 'capture_mode' for that instead, since photo/video "
                    "setup needs different actions on different waypoints (e.g. "
                    "video only starts/stops recording once, at the first/last "
                    "waypoint), not the same action repeated everywhere."
                ),
            },
            "remove_action": {
                "type": "string",
                "enum": _ACTION_VALUES + [""],
                "description": "A camera action to remove from every waypoint, or '' if the request doesn't ask to remove one.",
            },
            "capture_mode": {
                "type": "string",
                "enum": ["", "photo", "video", "none"],
                "description": (
                    "Set only if the request asks to switch the whole mission's "
                    "capture behavior: 'photo' = takePhoto at each computed "
                    "waypoint, 'video' = start recording at the first waypoint "
                    "and stop at the last (nothing in between), 'none' = remove "
                    "all camera actions. '' if the request doesn't ask to change "
                    "the capture mode."
                ),
            },
            "clear_actions": {
                "type": "boolean",
                "description": "True only if the request asks to remove ALL camera actions from every waypoint (e.g. 'no more photos or video').",
            },
            "reverse": {
                "type": "boolean",
                "description": "True only if the request asks to fly the path in the opposite direction.",
            },
            "simplify_level": {
                "type": "string",
                "enum": list(SIMPLIFY_LEVEL_EPS.keys()),
                "description": (
                    "How aggressively to reduce/simplify the waypoint path. "
                    "'none' if not requested. 'light' for 'remove duplicates' "
                    "or 'clean up slightly'. 'moderate' for a general "
                    "'simplify the path' request. 'aggressive' only if the "
                    "request explicitly says the path is very messy/redundant "
                    "or asks for a drastic reduction."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": "One short sentence, in the same language as the request, explaining what was changed.",
            },
        },
        "required": [
            "altitude", "speed", "overlap", "add_action", "remove_action",
            "capture_mode", "clear_actions", "reverse", "simplify_level", "reasoning",
        ],
    },
}


@dataclass
class EditPlan:
    altitude: float
    speed: float
    overlap: float
    add_action: str
    remove_action: str
    capture_mode: str
    clear_actions: bool
    reverse: bool
    simplify_level: str
    reasoning: str

    @classmethod
    def from_raw(cls, data: dict, fallback: Optional[dict] = None, explicit: Optional[dict] = None) -> "EditPlan":
        fallback = fallback or {}
        explicit = explicit or {}

        def pick(key, default):
            if key in explicit:
                return explicit[key]
            return data.get(key, fallback.get(key, default))

        add_action = str(pick("add_action", "")).strip()
        if add_action not in _ACTION_VALUES:
            add_action = ""

        remove_action = str(pick("remove_action", "")).strip()
        if remove_action not in _ACTION_VALUES:
            remove_action = ""

        capture_mode = str(data.get("capture_mode", "")).strip().lower()
        if capture_mode not in ("", "photo", "video", "none"):
            capture_mode = ""

        simplify_level = str(data.get("simplify_level", "none")).strip().lower()
        if simplify_level not in SIMPLIFY_LEVEL_EPS:
            simplify_level = "none"

        return cls(
            altitude=_clamp(pick("altitude", 80), *_BOUNDS["altitude"]),
            speed=_clamp(pick("speed", 5), *_BOUNDS["speed"]),
            overlap=_clamp(pick("overlap", 0.8), *_BOUNDS["overlap"]),
            add_action=add_action,
            remove_action=remove_action,
            capture_mode=capture_mode,
            clear_actions=bool(data.get("clear_actions", False)),
            reverse=bool(data.get("reverse", False)),
            simplify_level=simplify_level,
            reasoning=str(pick("reasoning", ""))[:400],
        )

    @property
    def simplify_eps(self) -> float:
        return SIMPLIFY_LEVEL_EPS[self.simplify_level]

    def to_dict(self) -> dict:
        return asdict(self)


__all__ = ["EDIT_JSON_SCHEMA", "EditPlan", "SIMPLIFY_LEVEL_EPS", "extract_explicit_values"]
