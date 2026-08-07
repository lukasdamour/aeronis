# ===============================
# IMPORTS
# ===============================
import re

from .schema import _clamp, _DISALLOWED


# ===============================
# JSON SCHEMA handed to the LLM
# ===============================
# Deliberately isolated from PLAN_JSON_SCHEMA (see core.llm.schema):
# small local models are noticeably more reliable at a single, narrow
# 2-field decision ("does this name a real place, and if so what?")
# than at getting the same decision right buried among 9 other mission
# parameters in one shot -- the same lesson already learned for
# altitude/speed/overlap (see extract_explicit_values) and for the
# flat, all-required design of the edit/name schemas.

PLACE_JSON_SCHEMA = {
    "name": "detect_place",
    "description": (
        "Detect whether a drone mission request names a specific "
        "real-world place, landmark, building, or address to fly over, "
        "as opposed to referring to a zone already drawn on a map."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "place": {
                "type": "string",
                "description": (
                    "The place/landmark/address named in the request, copied "
                    "verbatim (include the city if given), e.g. 'Eiffel Tower, "
                    "Paris'. Even a single well-known landmark name counts. "
                    "Must be exactly '' if the request names no real place at "
                    "all -- e.g. 'this field', 'the area I selected/drew', or "
                    "no location mentioned."
                ),
            },
            "radius_m": {
                "type": "number",
                "description": (
                    "Only meaningful if 'place' is set: half-width in meters of "
                    "the square area to cover around it (10-2000). Use the "
                    "request's stated size if given (e.g. '200m radius' -> 200), "
                    "otherwise ~150."
                ),
            },
        },
        "required": ["place", "radius_m"],
    },
}

PLACE_SYSTEM_PROMPT = (
    "You detect whether a drone mission request names a specific "
    "real-world place, landmark, building, or address to fly over.\n"
    "Examples that DO name a place -> place should be set:\n"
    "- 'survey the Eiffel Tower area at 60m' -> place: 'Eiffel Tower, Paris'\n"
    "- 'fly over Stade Allianz Riviera in Nice' -> place: 'Stade Allianz Riviera, Nice'\n"
    "- 'map 12 rue de la Paix, Paris' -> place: '12 rue de la Paix, Paris'\n"
    "Examples that do NOT name a place -> place must be '':\n"
    "- 'survey this field at 50m in photo mode'\n"
    "- 'generate a mission for the area I drew, 80% overlap'\n"
    "- 'fly at 50m, 10m/s, 60% overlap' (no location at all)\n"
    "Reply with the JSON object only, no prose, no markdown fences."
)


# ===============================
# Validation
# ===============================

_BOUNDS_RADIUS = (10.0, 2000.0)


def parse_place_result(data: dict) -> tuple:
    """
    Validates/sanitizes the raw dict returned for PLACE_JSON_SCHEMA.
    Returns (place: str, radius_m: float). place is '' if none was
    detected or if the raw value fails basic sanity checks.
    """
    if not isinstance(data, dict):
        return "", 150.0

    place = _DISALLOWED.sub("", str(data.get("place", "") or "").strip())[:120]
    radius_m = _clamp(data.get("radius_m", 150), *_BOUNDS_RADIUS)

    return place, radius_m
