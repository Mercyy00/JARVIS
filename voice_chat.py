"""VYRA with voice — Phase 2.

    python voice_chat.py          # push-to-talk: press Enter, then speak
    python voice_chat.py --wake   # always listening; say "VYRA ..." to command

Install audio deps first:  pip install -r requirements-voice.txt
Phase 1's brain, memory and skills are reused unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console

from vyra import skills
from vyra import voice as V
from vyra.brain import Brain
from vyra.config import has_api_key, load_config
from vyra.memory import Memory

ROOT = Path(__file__).resolve().parent
console = Console()
WAKE_WORD = "vyra"
QUIT_WORDS = ("quit", "goodbye", "bye", "stop listening")


def _strip_wake(text: str):
    """Return the command after the wake word, or None if not spoken."""
    i = text.lower().find(WAKE_WORD)
    if i == -1:
        return None
    return text[i + len(WAKE_WORD):].strip(" ,.!?-")


def main():
    wake_mode = "--wake" in sys.argv
    config = load_config()
    if not has_api_key(config):
        console.print("[yellow]No API key — see README setup.[/]")
        sys.exit(1)

    memory = Memory(ROOT)
    skills.configure_browser(config["user"].get("browser"))
    brain = Brain(config, memory)

    console.print("[cyan]Waking VYRA's voice (loading Whisper + audio)...[/]")
    ears, mouth = V.Ears(), V.Mouth()
    name = memory.profile.get("name") or config["user"]["name"]
    hello = f"Hello {name}, VYRA here. I'm listening."
    console.print(f"[bold cyan]VYRA[/]  {hello}")
    mouth.speak(hello)

    try:
        while True:
            if wake_mode:
                console.print("[dim](listening — say 'VYRA ...')[/]")
            else:
                try:
                    cmd = console.input("[green]Enter to talk (q to quit):[/] ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    break
                if cmd in ("q", "quit", "bye"):
                    break

            audio = V.record_until_silence()
            if audio is None:
                continue
            heard = ears.transcribe(audio)
            if not heard:
                continue

            if wake_mode:
                is_wake, phrase, command = V.detect_wake_word(heard)
                if not is_wake:
                    continue  # wake word not spoken — ignore ambient room noise
                if not command:
                    prompt_txt = f"Yes {name}?"
                    console.print(f"[bold cyan]VYRA[/]  {prompt_txt} (listening...)")
                    mouth.speak(prompt_txt)
                    follow_audio = V.record_until_silence()
                    if follow_audio is None:
                        continue
                    command = ears.transcribe(follow_audio)
                    if not command:
                        continue
            else:
                command = heard

            console.print(f"[green]you[/]  {heard}")
            if command.lower() in QUIT_WORDS:
                break
            try:
                reply = brain.ask(command)
            except Exception as exc:
                console.print(f"[red]{exc}[/]")
                reply = "Something went wrong reaching my brain."
            console.print(f"[bold cyan]VYRA[/]  {reply}")
            mouth.speak(reply)
    finally:
        summary = brain.summarize_session()
        if summary:
            console.print(f"[dim](journal saved: {summary})[/]")
        mouth.speak("Goodbye for now.")


if __name__ == "__main__":
    main()
