"""VYRA's persistent memory — this is what makes her feel like she knows you.

Three layers, all stored as plain files under data/ (gitignored):
  * profile.json  — long-term facts about you (name, about, preferences)
  * links.json    — named shortcuts you save ("standup meet" -> url)
  * notes.json    — free-form notes she keeps for you
  * journal/      — one markdown file per day; a short summary of each session,
                    so tomorrow she remembers what you did today.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path


class Memory:
    def __init__(self, root: Path):
        self.dir = root / "data"
        self.journal_dir = self.dir / "journal"
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        self.profile_path = self.dir / "profile.json"
        self.links_path = self.dir / "links.json"
        self.notes_path = self.dir / "notes.json"
        self.profile = self._load(self.profile_path, {"name": None, "about": [], "preferences": []})
        self.links = self._load(self.links_path, {})
        self.notes = self._load(self.notes_path, [])

    # --- low-level ---
    @staticmethod
    def _load(path: Path, default):
        if path.exists():
            try:
                return json.loads(path.read_text("utf-8"))
            except json.JSONDecodeError:
                return default
        return default

    @staticmethod
    def _save(path: Path, data):
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")

    # --- profile ---
    def set_name(self, name: str):
        self.profile["name"] = name
        self._save(self.profile_path, self.profile)

    def add_about(self, fact: str):
        self.profile.setdefault("about", []).append(fact)
        self._save(self.profile_path, self.profile)

    def add_preference(self, pref: str):
        self.profile.setdefault("preferences", []).append(pref)
        self._save(self.profile_path, self.profile)

    def profile_text(self) -> str:
        p = self.profile
        lines = []
        if p.get("name"):
            lines.append(f"Name: {p['name']}")
        if p.get("about"):
            lines.append("About them:\n" + "\n".join(f"  - {x}" for x in p["about"]))
        if p.get("preferences"):
            lines.append("Preferences:\n" + "\n".join(f"  - {x}" for x in p["preferences"]))
        return "\n".join(lines) if lines else "(nothing saved yet)"

    # --- links ---
    def save_link(self, name: str, url: str):
        self.links[name.lower().strip()] = url
        self._save(self.links_path, self.links)

    def get_link(self, name: str):
        return self.links.get(name.lower().strip())

    def list_links(self) -> dict:
        return dict(self.links)

    # --- notes ---
    def add_note(self, text: str):
        self.notes.append({"text": text, "ts": datetime.now().isoformat(timespec="seconds")})
        self._save(self.notes_path, self.notes)

    def list_notes(self) -> list:
        return list(self.notes)

    # --- journal ---
    def _journal_path(self, day: date) -> Path:
        return self.journal_dir / f"{day.isoformat()}.md"

    def append_journal(self, text: str):
        path = self._journal_path(date.today())
        stamp = datetime.now().strftime("%H:%M")
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"\n- [{stamp}] {text}\n")

    def recent_journal(self) -> str:
        """Today's and yesterday's entries, for loading into context at startup."""
        chunks = []
        for day in (date.today() - timedelta(days=1), date.today()):
            path = self._journal_path(day)
            if path.exists():
                label = "Yesterday" if day != date.today() else "Today"
                chunks.append(f"## {label} ({day.isoformat()})\n{path.read_text('utf-8').strip()}")
        return "\n\n".join(chunks) if chunks else "(no recent history)"
