"""VYRA — Phase 1 entry point. A text conversation with your assistant.

    python main.py

In-chat commands: /help  /name <you>  /links  /notes  /bye
"""

from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from vyra import skills
from vyra.brain import Brain
from vyra.config import has_api_key, load_config
from vyra.memory import Memory

ROOT = Path(__file__).resolve().parent
console = Console()


def _say(text: str):
    console.print(f"[bold cyan]VYRA[/]  {text}")


def _startup_checks(config):
    if not has_api_key(config):
        console.print(Panel.fit(
            "No API key found.\n\n"
            "1. Copy config.example.json  ->  config.json\n"
            "2. Copy .env.example  ->  .env  and set VYRA_API_KEY=your-key\n"
            "   (or put the key in config.json under llm.api_key)\n\n"
            "Pick the brain in config.json: claude | openrouter | google.",
            title="VYRA needs a brain", border_style="yellow"))
        sys.exit(1)


def main():
    config = load_config()
    _startup_checks(config)

    memory = Memory(ROOT)
    skills.configure_browser(config["user"].get("browser"))
    skills.configure_vision(config.get("llm"))
    brain = Brain(config, memory)

    name = memory.profile.get("name") or config["user"]["name"]
    console.print(Panel.fit(
        f"VYRA online. Brain: [bold]{config['llm']['provider']}[/] ({config['llm']['model']}).\n"
        f"Hello {name}. Type to talk, /help for commands, /bye to leave.",
        title="VYRA", border_style="cyan"))

    try:
        while True:
            try:
                user = console.input("[bold green]you[/]  ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not user:
                continue
            low = user.lower()
            if low in ("/bye", "/exit", "/quit"):
                break
            if low == "/help":
                console.print("Commands: /name <you>, /links, /notes, /bye")
                continue
            if low.startswith("/name "):
                memory.set_name(user[6:].strip())
                _say(f"Noted — you're {memory.profile['name']}.")
                continue
            if low == "/links":
                _say(skills.list_saved_links(memory))
                continue
            if low == "/notes":
                _say(skills.list_notes(memory))
                continue

            try:
                with console.status("[cyan]VYRA is thinking..."):
                    reply = brain.ask(user)
            except Exception as exc:
                _say(f"Something went wrong reaching my brain: {exc}")
                continue
            _say(reply)
    finally:
        summary = brain.summarize_session()
        if summary:
            console.print(f"[dim](journal saved: {summary})[/]")
        _say("Goodbye for now.")


if __name__ == "__main__":
    main()
