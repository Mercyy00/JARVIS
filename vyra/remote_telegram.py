"""Command Rusty from your phone, anywhere, via a Telegram bot.

Set `remote.telegram_token` in config.json to a bot token from @BotFather, then
message your bot. The first chat that messages it gets locked in as the owner
(saved to config as remote.telegram_chat_id); after that only that chat is
accepted. Each message is handed to Rusty's brain and the reply is sent back.
Supports both text commands and bidirectional voice notes!
"""

from __future__ import annotations

import hmac
import json
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"


class TelegramBridge:
    def __init__(self, token: str, on_message, allowed_chat_id: str = "", ears=None, pin: str = ""):
        self.token = token
        self.on_message = on_message
        self.allowed = str(allowed_chat_id or "").strip()
        self.ears = ears
        self.pin = str(pin or "").strip()
        self.base = f"https://api.telegram.org/bot{token}"
        self._stop = threading.Event()
        self._offset = 0
        self._thread = None
        self._failed_attempts: dict[str, list[float]] = {}
        self._lockout_until: dict[str, float] = {}

    @classmethod
    def from_config(cls, config: dict, on_message, ears=None) -> TelegramBridge:
        rc = config.get("remote", {})
        return cls(
            token=rc.get("telegram_token", ""),
            on_message=on_message,
            allowed_chat_id=rc.get("telegram_chat_id", ""),
            ears=ears,
            pin=rc.get("pin", "")
        )

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

    def send_action(self, chat_id, action="typing"):
        try:
            self._call_post("sendChatAction", chat_id=chat_id, action=action)
        except Exception:
            pass

    def _download_file(self, file_id: str, out_path: Path) -> bool:
        try:
            info = self._call("getFile", file_id=file_id)
            file_path = info.get("result", {}).get("file_path")
            if not file_path:
                return False
            url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
            with urllib.request.urlopen(url, timeout=40) as r, open(out_path, "wb") as f:
                f.write(r.read())
            return True
        except Exception:
            return False

    def _persist_chat_id(self, cid: str):
        try:
            data = json.loads(CONFIG_PATH.read_text("utf-8"))
            data.setdefault("remote", {})["telegram_chat_id"] = str(cid)
            CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
        except Exception:
            pass

    def _process_turn(self, chat: str, text: str):
        self.send_action(chat, "typing")
        try:
            reply = self.on_message(text)
        except Exception as exc:
            reply = f"Something went wrong, Sir: {exc}"
        self.send(chat, reply or "...")

    def authenticate_chat(self, chat: str, text: str) -> str:
        """Authenticate an incoming chat pairing attempt. Returns status string."""
        now = time.time()
        if chat in self._lockout_until and now < self._lockout_until[chat]:
            rem = int(self._lockout_until[chat] - now)
            return f"Locked out due to excessive failed attempts. Try again in {rem} seconds."

        if self.pin is not None:
            cfg_pin = self.pin
        else:
            try:
                cfg_pin = str(json.loads(CONFIG_PATH.read_text("utf-8")).get("remote", {}).get("pin", "") or "").strip()
            except Exception:
                cfg_pin = ""

        if not cfg_pin:
            return "Pairing disabled: No PIN configured in config.json ('remote.pin'). Set a secure PIN on the host machine first."

        parts = text.split()
        submitted_pin = ""
        if parts and parts[0].lower() in ("/link", "/auth", "/pin") and len(parts) > 1:
            submitted_pin = parts[1].strip()
        elif text.strip().isdigit() and len(text.strip()) >= 4:
            submitted_pin = text.strip()

        is_authed = False
        if submitted_pin and hmac.compare_digest(submitted_pin, cfg_pin):
            is_authed = True

        if is_authed:
            self.allowed = chat
            self._failed_attempts.pop(chat, None)
            self._lockout_until.pop(chat, None)
            self._persist_chat_id(chat)
            return "Rusty linked to this chat, Sir. Send me a command or voice note anytime."
        else:
            attempts = self._failed_attempts.get(chat, [])
            attempts = [t for t in attempts if now - t < 600]
            attempts.append(now)
            self._failed_attempts[chat] = attempts
            if len(attempts) >= 3:
                self._lockout_until[chat] = now + 900
                return "Too many failed pairing attempts. Locked out for 15 minutes."
            else:
                rem_attempts = 3 - len(attempts)
                return f"Locked. To link this Telegram account with Rusty, send: /link <your_pin> ({rem_attempts} attempt{'s' if rem_attempts != 1 else ''} remaining)."

    def _run(self):
        print("[TELEGRAM] Bridge online — waiting for messages and voice notes.")
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

                # Handle Voice Notes & Audio files via Whisper
                voice = msg.get("voice") or msg.get("audio")
                if voice and voice.get("file_id"):
                    self.send_action(chat, "record_voice")
                    temp_path = ROOT / "data" / f"tg_voice_{int(time.time()*1000)}.ogg"
                    if self._download_file(voice["file_id"], temp_path):
                        try:
                            if self.ears:
                                transcribed = self.ears.transcribe(str(temp_path))
                            else:
                                from .voice import Ears
                                e = Ears()
                                transcribed = e.transcribe(str(temp_path))
                            text = transcribed.strip()
                            if text:
                                self.send(chat, f"🎙️ Heard: \"{text}\"")
                        except Exception as exc:
                            self.send(chat, f"Could not process voice note: {exc}")
                            continue
                        finally:
                            if temp_path.exists():
                                try:
                                    temp_path.unlink()
                                except Exception:
                                    pass

                if not chat or not text:
                    continue

                if not self.allowed:
                    auth_reply = self.authenticate_chat(chat, text)
                    self.send(chat, auth_reply)
                    continue

                if chat != self.allowed:
                    self.send(chat, "Not authorized.")
                    continue

                if text.lower() in ("/start", "start"):
                    self.send(chat, "At your service, Sir. What do you need?")
                    continue

                # Run message handling in background worker so polling is non-blocking
                threading.Thread(target=self._process_turn, args=(chat, text), daemon=True).start()
