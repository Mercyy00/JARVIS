"""Command Rusty from your phone, anywhere, via a Telegram bot.

Set `remote.telegram_token` in config.json to a bot token from @BotFather, then
message your bot. The first chat that messages it gets locked in as the owner
(saved to config as remote.telegram_chat_id); after that only that chat is
accepted. Each message is handed to Rusty's brain and the reply is sent back.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"


class TelegramBridge:
    def __init__(self, token: str, on_message, allowed_chat_id: str = ""):
        self.token = token
        self.on_message = on_message
        self.allowed = str(allowed_chat_id or "")
        self.base = f"https://api.telegram.org/bot{token}"
        self._stop = threading.Event()
        self._offset = 0
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _call(self, method: str, **params):
        url = f"{self.base}/{method}?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=35) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    def _call_post(self, method: str, **params):
        url = f"{self.base}/{method}"
        data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=35) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    def send(self, chat_id, text: str):
        try:
            if not text:
                text = "..."
            for i in range(0, len(text), 4000):
                chunk = text[i:i+4000]
                self._call_post("sendMessage", chat_id=chat_id, text=chunk)
        except Exception:
            pass

    def _persist_chat_id(self, cid: str):
        try:
            data = json.loads(CONFIG_PATH.read_text("utf-8"))
            data.setdefault("remote", {})["telegram_chat_id"] = str(cid)
            CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
        except Exception:
            pass

    def _run(self):
        print("[TELEGRAM] Bridge online — waiting for messages.")
        while not self._stop.is_set():
            try:
                resp = self._call("getUpdates", offset=self._offset, timeout=30)
            except Exception:
                time.sleep(3)
                continue
            for u in resp.get("result", []):
                self._offset = u["update_id"] + 1
                msg = u.get("message") or u.get("edited_message") or {}
                chat = str((msg.get("chat") or {}).get("id", ""))
                text = (msg.get("text") or "").strip()
                if not chat or not text:
                    continue
                if not self.allowed:
                    try:
                        cfg_pin = str(json.loads(CONFIG_PATH.read_text("utf-8")).get("remote", {}).get("pin", "") or "")
                    except Exception:
                        cfg_pin = ""
                    parts = text.split()
                    is_authed = False
                    if cfg_pin:
                        if (parts[0].lower() in ("/link", "/auth", "/pin") and len(parts) > 1 and parts[1] == cfg_pin) or text == cfg_pin:
                            is_authed = True
                    else:
                        is_authed = True

                    if is_authed:
                        self.allowed = chat
                        self._persist_chat_id(chat)
                        self.send(chat, "Rusty linked to this chat, Sir. Send me a command anytime.")
                        continue
                    else:
                        self.send(chat, "Locked. To link this Telegram account with Rusty, send: /link <your_pin>")
                        continue

                if chat != self.allowed:
                    self.send(chat, "Not authorized.")
                    continue
                if text.lower() in ("/start", "start"):
                    self.send(chat, "At your service, Sir. What do you need?")
                    continue
                try:
                    reply = self.on_message(text)
                except Exception as exc:
                    reply = f"Something went wrong, Sir: {exc}"
                self.send(chat, reply or "...")
