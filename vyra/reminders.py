"""Timed reminders / alarms for VYRA.

A tiny background service that fires reminders at their due time and speaks
them aloud (in the HUD) or prints them (in the REPL). Reminders persist to
data/reminders.json, so they survive a restart — anything overdue on startup
fires right away.

A skill schedules reminders; `gui_server` wires `set_notifier` so they're
spoken through FRIDAY's voice.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "data" / "reminders.json"


class ReminderService:
    def __init__(self):
        self._lock = threading.RLock()
        self._items = self._load()
        self._notifier = None          # callable(text) -> None
        self._stop = threading.Event()
        self._thread = None

    # --- persistence ---
    def _load(self) -> list:
        if STORE.exists():
            try:
                return json.loads(STORE.read_text("utf-8"))
            except Exception:
                return []
        return []

    def _save(self):
        STORE.parent.mkdir(parents=True, exist_ok=True)
        STORE.write_text(json.dumps(self._items, indent=2, ensure_ascii=False), "utf-8")

    # --- public API ---
    def set_notifier(self, fn):
        self._notifier = fn

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def add(self, text: str, fire_ts: float) -> dict:
        item = {
            "id": str(int(time.time() * 1000)),
            "text": text,
            "fire_ts": float(fire_ts),
            "created": time.time(),
            "done": False,
        }
        with self._lock:
            self._items.append(item)
            self._save()
        self.start()
        return item

    def list_pending(self) -> list:
        with self._lock:
            return sorted((i for i in self._items if not i["done"]),
                          key=lambda i: i["fire_ts"])

    def cancel(self, which: str) -> int:
        """Cancel by id or by case-insensitive substring of the text."""
        w = (which or "").lower().strip()
        removed = 0
        with self._lock:
            for i in self._items:
                if i["done"]:
                    continue
                if i["id"] == which or w and w in i["text"].lower():
                    i["done"] = True
                    removed += 1
            if removed:
                self._save()
        return removed

    # --- background loop ---
    def _run(self):
        while not self._stop.is_set():
            now = time.time()
            due = []
            with self._lock:
                for i in self._items:
                    if not i["done"] and i["fire_ts"] <= now:
                        i["done"] = True
                        due.append(i)
                if due:
                    self._save()
            for i in due:
                self._fire(i)
            time.sleep(3.0)

    def _fire(self, item: dict):
        text = item["text"]
        if self._notifier:
            try:
                self._notifier(text)
                return
            except Exception:
                pass
        print(f"\n[REMINDER] {text}\n")


_service: ReminderService | None = None


def get_service() -> ReminderService:
    global _service
    if _service is None:
        _service = ReminderService()
    return _service
