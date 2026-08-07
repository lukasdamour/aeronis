# ======================================
# IMPORTS
# ======================================
from typing import Optional

from .providers import LLMProvider, ProviderError, SYSTEM_PROMPT, _user_prompt
from .schema import MissionPlan, extract_explicit_values, PLAN_JSON_SCHEMA
from .place_schema import PLACE_JSON_SCHEMA, PLACE_SYSTEM_PROMPT, parse_place_result


class PlannerError(Exception):
    """Raised when no usable plan could be produced."""


def plan_mission(provider: LLMProvider, prompt: str, current_params: Optional[dict] = None) -> MissionPlan:
    """
    Turn a free-text instruction into a validated MissionPlan.

    Runs two separate, narrow LLM calls rather than one big one:
    1. place detection (see core.llm.place_schema) -- a tiny 2-field
       schema, much more reliable for small local models than deciding
       this alongside 9 other mission parameters at once.
    2. the mission parameters themselves (altitude, speed, overlap...).

    Args:
        provider: an LLMProvider instance (see core.llm.providers.get_provider).
        prompt: the user's natural-language request, e.g.
                "Survole ce champ a 50m en mode photo, recouvrement 80%".
        current_params: the zone panel's current values (ZONE_PARAMS from
                        web/js/zones.js), used as defaults for anything the
                        request doesn't mention.

    Returns:
        A MissionPlan with clamped, schema-valid values -- safe to apply
        directly to the zone panel's inputs.

    Raises:
        PlannerError: if the provider is unreachable or returns something
                      that cannot be salvaged into a plan at all.
    """
    if not prompt or not prompt.strip():
        raise PlannerError("Empty prompt.")
    prompt = prompt.strip()

    try:
        place_raw = provider.complete_json(PLACE_SYSTEM_PROMPT, prompt, PLACE_JSON_SCHEMA["input_schema"])
    except ProviderError as e:
        raise PlannerError(str(e)) from e
    place, radius_m = parse_place_result(place_raw)

    try:
        raw = provider.complete_json(SYSTEM_PROMPT, _user_prompt(prompt, current_params), PLAN_JSON_SCHEMA["input_schema"])
    except ProviderError as e:
        raise PlannerError(str(e)) from e

    if not isinstance(raw, dict):
        raise PlannerError("Provider returned a non-object response.")

    explicit = extract_explicit_values(prompt)
    return MissionPlan.from_raw(raw, fallback=current_params, explicit=explicit, place=place, radius_m=radius_m)
