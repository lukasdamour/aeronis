# ========================
# IMPORTS
# ========================
import json
import os
from abc import ABC, abstractmethod
from typing import Optional

import requests


class ProviderError(Exception):
    """Raised for any provider-side failure (network, auth, bad model output)."""


# ========================
# Common system prompt
# ========================

SYSTEM_PROMPT = (
    "You are a mission-planning assistant embedded in a DJI drone mission "
    "planner. The user has already drawn a coverage zone on a map (or "
    "one was just resolved from a place name); you cannot see it and "
    "must never invent coordinates or waypoints yourself. Your only job "
    "is to output a single JSON object with mission parameters, based "
    "on the user's request and the currently configured parameters.\n"
    "Rules:\n"
    "- Always include EVERY field of the schema, even ones the request "
    "doesn't mention -- for those, copy the current parameter's value "
    "unchanged. Never omit a field.\n"
    "- If the request states an explicit number (e.g. '50m', '10m/s', "
    "'60% overlap'), use that exact number for the matching field -- do "
    "not round, guess, or substitute a default.\n"
    "- Reply with the JSON object only, no prose, no markdown fences."
)


def _user_prompt(prompt: str, current_params: Optional[dict]) -> str:
    context = ""
    if current_params:
        context = f"\nCurrent parameters (change only what the request implies): {json.dumps(current_params)}"
    return f"Request: {prompt}{context}"


# ========================
# Abstract base
# ========================

class LLMProvider(ABC):
    @abstractmethod
    def complete_json(self, system_prompt: str, user_prompt: str, json_schema: dict) -> dict:
        raise NotImplementedError


# ========================
# Local provider (Ollama)
# ========================

def list_ollama_models(host: Optional[str] = None, timeout: float = 5.0) -> list:
    """
    Returns the list of model names currently pulled in the local Ollama
    instance (e.g. ["llama3.1:latest", "qwen2.5:7b"]), or [] if Ollama
    isn't reachable.
    """
    host = (host or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
    try:
        resp = requests.get(f"{host}/api/tags", timeout=timeout)
        resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]
    except (requests.RequestException, ValueError, KeyError):
        return []


class OllamaProvider(LLMProvider):
    """
    Talks to a local Ollama instance (https://ollama.com). No API key,
    no network egress beyond localhost.
    """

    def __init__(self, model: str = "llama3.1", host: Optional[str] = None, timeout: float = 60.0):
        self.model = model
        self.host = (host or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
        self.timeout = timeout

    def complete_json(self, system_prompt: str, user_prompt: str, json_schema: dict) -> dict:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "format": json_schema,
            "options": {"temperature": 0},
            "stream": False,
        }
        try:
            resp = requests.post(f"{self.host}/api/chat", json=payload, timeout=self.timeout)
        except requests.RequestException as e:
            raise ProviderError(
                f"Could not reach Ollama at {self.host} ({e}). "
                "Is 'ollama serve' running?"
            ) from e

        if resp.status_code == 404:
            raise ProviderError(
                f"Model '{self.model}' is not installed in Ollama. "
                f"Run: ollama pull {self.model}  (or pick another installed model)."
            )
        if resp.status_code != 200:
            raise ProviderError(f"Ollama returned HTTP {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        content = data.get("message", {}).get("content", "")
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return _extract_json_object(content)


# ========================
# Helpers
# ========================

def _extract_json_object(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ProviderError("Model response did not contain any JSON object.")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise ProviderError(f"Could not parse model response as JSON: {e}") from e


# ========================
# Factory
# ========================

def get_provider(kind: str = "local", model: Optional[str] = None, **kwargs) -> LLMProvider:
    kind = (kind or "local").lower()
    if kind != "local":
        raise ProviderError(
            "Only the local provider (Ollama) is supported -- "
            "this project doesn't use paid cloud APIs."
        )
    return OllamaProvider(model=model or "llama3.1", **kwargs)
