"""Named multi-step routines / macros for Rusty.

A routine is a named list of steps; each step runs one of Rusty's skills. Stored
in data/routines.json so they're easy to edit; sensible defaults are seeded on
first use. Say "start my day", "focus mode", "wind down", etc.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "data" / "routines.json"

DEFAULTS = {
    "start my day": [
        {"skill": "open_app", "args": {"name": "brave"}},
        {"skill": "open_app", "args": {"name": "antigravity"}},
        {"skill": "daily_briefing", "args": {}},
    ],
    "focus mode": [
        {"skill": "close_other_windows", "args": {"keep": ["brave", "antigravity"]}},
        {"skill": "set_brightness", "args": {"level": 90}},
    ],
    "wind down": [
        {"skill": "set_brightness", "args": {"level": 30}},
        {"skill": "open_app", "args": {"name": "raaga"}},
    ],
}


def _load() -> dict:
    if STORE.exists():
        try:
            return json.loads(STORE.read_text("utf-8"))
        except Exception:
            pass
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(DEFAULTS, indent=2, ensure_ascii=False), "utf-8")
    return dict(DEFAULTS)


def list_names() -> list:
    return list(_load().keys())


def get_steps(name: str):
    """Return steps for a routine by exact or fuzzy (substring) name match."""
    data = _load()
    key = (name or "").lower().strip()
    if key in data:
        return data[key]
    for k in data:
        if key and (key in k or k in key):
            return data[k]
    return None
