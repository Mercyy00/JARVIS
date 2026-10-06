"""Configuration loading for VYRA.

Reads config.json (if present) layered over sensible defaults, then lets
environment variables (from .env) override — so you can switch providers or
swap an API key without editing code.

To change brains, set in config.json or .env:
    provider: "claude" | "openrouter" | "google"
    model:    the model id for that provider
    api_key:  that provider's key  (better: put it in .env as VYRA_API_KEY)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"

load_dotenv(ROOT / ".env")

DEFAULTS: dict = {
    "assistant": {
        "name": "FRIDAY",
    },
    "llm": {
        "provider": "google",
        "model": "gemini-flash-lite-latest",
        "api_key": "",
        "base_url": None,
        "max_tokens": 1024,
    },
    "user": {
        "name": "Jay",
        "browser": None,  # path/name of preferred browser, e.g. "brave"; None = system default
    },
    "voice": {
        "name": "en-US-GuyNeural",
        "rate": "+10%",
        "pronounce_vyra": "Friday",
        "wake_enabled": True,
        "wake_words": ["friday", "buddy", "jarvis", "vyra"],
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config() -> dict:
    """Return the merged config: DEFAULTS < config.json < environment."""
    config = json.loads(json.dumps(DEFAULTS))  # deep copy

    if CONFIG_PATH.exists():
        try:
            config = _deep_merge(config, json.loads(CONFIG_PATH.read_text("utf-8")))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"config.json is not valid JSON: {exc}")

    # Environment overrides (highest priority)
    env_map = {
        "VYRA_PROVIDER": ("provider", str),
        "VYRA_MODEL": ("model", str),
        "VYRA_BASE_URL": ("base_url", str),
        "VYRA_API_KEY": ("api_key", str),
    }
    for env_name, (key, _cast) in env_map.items():
        value = os.environ.get(env_name)
        if value:
            config["llm"][key] = value

    return config


def has_api_key(config: dict) -> bool:
    return bool(config["llm"].get("api_key"))
