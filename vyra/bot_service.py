"""Rusty headless Telegram bot service — always-on phone control.

Runs just the brain + Telegram bridge (no GUI, no microphone), so it can stay
on in the background all the time and answer your phone commands even when the
HUD window isn't open. Launched invisibly at logon via pythonw (see autostart).

    python -m vyra.bot_service
"""

from __future__ import annotations

import time
from pathlib import Path

from vyra.config import load_config, has_api_key
from vyra.memory import Memory
from vyra import skills
from vyra.brain import Brain
from vyra import remote_telegram

ROOT = Path(__file__).resolve().parent.parent


def main():
    cfg = load_config()
    if not has_api_key(cfg):
        print("[BOT SERVICE] No API key configured; exiting.")
        return
    token = str(cfg.get("remote", {}).get("telegram_token", "") or "")
    if not token:
        print("[BOT SERVICE] No telegram_token in config; exiting.")
        return

    memory = Memory(ROOT)
    skills.configure_browser(cfg["user"].get("browser"))
    skills.configure_vision(cfg.get("llm"))
    brain = Brain(cfg, memory)

    bridge = remote_telegram.TelegramBridge(
        token,
        on_message=lambda text: brain.ask(text),
        allowed_chat_id=cfg.get("remote", {}).get("telegram_chat_id", ""),
    )
    bridge.start()
    print("[BOT SERVICE] Rusty Telegram bot online (headless). Ctrl+C to stop.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        bridge.stop()


if __name__ == "__main__":
    main()
