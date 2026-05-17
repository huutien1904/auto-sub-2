"""Persistent app configuration stored in config.json next to this file."""

import json
import os

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

_DEFAULTS: dict = {
    "provider": "google",          # "google" | "openai" | "claude"
    "openai_api_key": "",
    "openai_model": "gpt-4o-mini",
    "anthropic_api_key": "",
    "anthropic_model": "claude-haiku-4-5-20251001",
    # TTS / dubbing
    "tts_provider": "edge",        # "edge" | "openai" | "fptai"
    "fptai_api_key": "",
}

_OPENAI_MODELS = [
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-3.5-turbo",
]

_ANTHROPIC_MODELS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6",
    "claude-opus-4-7",
]

PROVIDER_LABELS = {
    "google":  "Google Translate (miễn phí)",
    "openai":  "OpenAI GPT",
    "claude":  "Anthropic Claude",
}


def load() -> dict:
    if os.path.exists(_CONFIG_PATH):
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {**_DEFAULTS, **data}
        except Exception:
            pass
    return dict(_DEFAULTS)


def save(cfg: dict) -> None:
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def openai_models() -> list:
    return list(_OPENAI_MODELS)


def anthropic_models() -> list:
    return list(_ANTHROPIC_MODELS)
