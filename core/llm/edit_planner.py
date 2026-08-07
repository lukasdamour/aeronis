# ======================================
# IMPORTS
# ======================================
import json
from typing import Optional

from .providers import LLMProvider, ProviderError
from .edit_schema import EDIT_JSON_SCHEMA, EditPlan, extract_explicit_values
from .planner import PlannerError


EDIT_SYSTEM_PROMPT = (
    "You are a mission-editing assistant embedded in a DJI drone mission "
    "planner. The user already has a mission (a list of waypoints) placed "
    "on the map; you cannot see their exact coordinates and must never "
    "invent or move any. Your only job is to output a single JSON object "
    "describing which bulk edits to apply, based on the user's request "
    "and the mission's current parameters.\n"
    "Rules:\n"
    "- Always include EVERY field of the schema. For altitude/speed/"
    "overlap, if the request doesn't mention them, repeat the current "
    "value unchanged. For every other field, the 'not requested' value "
    "is '' (empty string) or false.\n"
    "- If the request states an explicit number (e.g. '60m', '8m/s', "
    "'70% overlap'), use that exact number -- do not round, guess, or "
    "substitute.\n"
    "- If the request asks to switch to photo mode, video mode, or to "
    "stop taking photos/recording entirely, use 'capture_mode' ('photo' / "
    "'video' / 'none') -- NEVER use add_action for this, since photo/video "
    "setup needs different actions on different waypoints, not the same "
    "action added everywhere.\n"
    "- Only use add_action/remove_action for a single specific action the "
    "request names that ISN'T a full photo/video mode switch.\n"
    "- Only set clear_actions/reverse to true, or simplify_level to "
    "anything other than 'none', if the request clearly asks for that "
    "specific change.\n"
    "- Reply with the JSON object only, no prose, no markdown fences."
)


def _user_prompt(prompt: str, current_params: Optional[dict]) -> str:
    context = ""
    if current_params:
        context = f"\nCurrent mission parameters: {json.dumps(current_params)}"
    return f"Request: {prompt}{context}"


def plan_edit(provider: LLMProvider, prompt: str, current_params: Optional[dict] = None) -> EditPlan:
    """
    Turn a free-text instruction (e.g. "lower altitude to 60m and remove
    all photos") into a validated EditPlan describing which
    MissionEditor bulk operations to run.
    """
    if not prompt or not prompt.strip():
        raise PlannerError("Empty prompt.")

    try:
        raw = provider.complete_json(
            EDIT_SYSTEM_PROMPT, _user_prompt(prompt.strip(), current_params),
            EDIT_JSON_SCHEMA["input_schema"],
        )
    except ProviderError as e:
        raise PlannerError(str(e)) from e

    if not isinstance(raw, dict):
        raise PlannerError("Provider returned a non-object response.")

    explicit = extract_explicit_values(prompt)
    explicit = {k: v for k, v in explicit.items() if k in ("altitude", "speed", "overlap")}

    return EditPlan.from_raw(raw, fallback=current_params, explicit=explicit)
