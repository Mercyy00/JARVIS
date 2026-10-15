"""Personal assistant, memory facts, notes, reminders, routines, briefing, and deep reasoning skills for Rusty."""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta

import psutil


def get_datetime(memory) -> str:
    return datetime.now().strftime("It's %A, %d %B %Y, %H:%M.")


def remember(memory, fact: str) -> str:
    memory.add_about(fact)
    return "Noted. I'll remember that."


def forget_fact(memory, fact: str) -> str:
    ok = memory.delete_about(fact)
    return "Understood, Sir — I've removed that from my memory." if ok else f"I couldn't find any memory matching '{fact}', Sir."


def set_my_name(memory, name: str) -> str:
    memory.set_name(name)
    return f"Got it — I'll call you {name}."


def save_note(memory, text: str) -> str:
    memory.add_note(text)
    return "Saved that note."


def list_notes(memory) -> str:
    notes = memory.list_notes()
    if not notes:
        return "No notes yet."
    return "Notes:\n" + "\n".join(f"  - [{n['ts']}] {n['text']}" for n in notes)


def delete_note(memory, query: str) -> str:
    ok = memory.delete_note(query)
    return "Deleted matching note, Sir." if ok else f"No note matching '{query}' found to delete, Sir."


def read_clipboard(memory) -> str:
    """Read the current text content copied to the Windows clipboard."""
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; Get-Clipboard"],
            text=True, errors="replace", timeout=5
        ).strip()
        if not out:
            return "The clipboard is currently empty."
        if len(out) > 500:
            preview = out[:500]
            return f"Clipboard text ({len(out)} characters):\n\"{preview}\"\n...(truncated)"
        return f"Clipboard text:\n\"{out}\""
    except Exception as exc:
        return f"Could not read clipboard: {exc}"


def write_clipboard(memory, text: str) -> str:
    """Copy given text to the Windows clipboard."""
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", "$input | Set-Clipboard"],
            input=text, text=True, capture_output=True, timeout=5
        )
        preview = text[:80] + ("..." if len(text) > 80 else "")
        return f"Copied to clipboard: \"{preview}\""
    except Exception as exc:
        return f"Could not copy to clipboard: {exc}"


def _parse_at(at_str: str, now: datetime):
    s = (at_str or "").strip().lower().replace(" ", "")
    for fmt in ("%H:%M", "%I:%M%p", "%I%p"):
        try:
            t = datetime.strptime(s, fmt).time()
        except ValueError:
            continue
        fire = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        if fire <= now:
            fire = fire + timedelta(days=1)
        return fire
    return None


def set_reminder(memory, text: str, minutes: float = None, at: str = None) -> str:
    from ..reminders import get_service
    now = datetime.now()
    if at:
        fire = _parse_at(at, now)
        if not fire:
            return f"I couldn't read the time '{at}'. Try like '17:30' or '5pm'."
    elif minutes is not None:
        try:
            fire = now + timedelta(minutes=float(minutes))
        except (ValueError, TypeError):
            return "Tell me how many minutes, Sir."
    else:
        return "When should I remind you — a time, or how many minutes?"
    get_service().add(text, fire.timestamp())
    when = fire.strftime("%H:%M") if fire.date() == now.date() else fire.strftime("%a %H:%M")
    return f"Reminder set for {when}, Sir — \"{text}\"."


def list_reminders(memory) -> str:
    from ..reminders import get_service
    items = get_service().list_pending()
    if not items:
        return "No reminders set, Sir."
    lines = ["Pending reminders:"]
    for i in items:
        when = datetime.fromtimestamp(i["fire_ts"]).strftime("%a %H:%M")
        lines.append(f"  - {when}: {i['text']}")
    return "\n".join(lines)


def cancel_reminder(memory, which: str) -> str:
    from ..reminders import get_service
    n = get_service().cancel(which)
    return f"Cancelled {n} reminder(s)." if n else f"No matching reminder for '{which}'."


def daily_briefing(memory) -> str:
    """A short spoken briefing: greeting, date/time, reminders, battery."""
    now = datetime.now()
    h = now.hour
    salut = "Good morning" if 4 <= h < 12 else "Good afternoon" if 12 <= h < 17 else "Good evening"
    parts = [f"{salut}, Sir.", now.strftime("It's %A, %d %B, %H:%M.")]
    try:
        from .. import reminders
        items = reminders.get_service().list_pending()
        if items:
            parts.append(f"You've got {len(items)} reminder{'s' if len(items) != 1 else ''} lined up.")
    except Exception:
        pass
    try:
        b = psutil.sensors_battery()
        if b is not None:
            parts.append(f"Battery's at {round(b.percent)}%{' and charging' if b.power_plugged else ''}.")
    except Exception:
        pass
    return " ".join(parts)


def run_routine(memory, name: str) -> str:
    """Run a named multi-step routine (e.g. 'start my day', 'focus mode', 'wind down')."""
    from .. import routines
    steps = routines.get_steps(name)
    if steps is None:
        return f"No routine called '{name}', Sir. I've got: {', '.join(routines.list_names())}."
    
    from . import execute
    outputs = []
    for step in steps:
        sk = step.get("skill")
        if not sk:
            continue
        outputs.append(execute(sk, step.get("args", {}), memory))
    brief = next((o for o in outputs if o and o.startswith(("Good morning", "Good afternoon", "Good evening"))), None)
    if brief:
        return brief
    return f"Done, Sir — {name} is set."


def list_routines(memory) -> str:
    from .. import routines
    return "Routines ready to go: " + ", ".join(routines.list_names()) + "."


def send_to_claude(memory, prompt: str) -> str:
    """Copy a prepared prompt to the clipboard and open Claude so Jay can paste it."""
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", "$input | Set-Clipboard"],
                       input=prompt, text=True, capture_output=True, timeout=5)
    except Exception:
        pass
    from .browser import _open_in_browser
    _open_in_browser("https://claude.ai/new")
    return "Prompt's written and copied to your clipboard, Sir — Claude's open, just paste with Ctrl+V."


def deep_think(memory, question: str) -> str:
    """Consult a stronger model for a hard question or careful writing."""
    from .media import _VISION_CONFIG
    cfg = _VISION_CONFIG
    if not cfg:
        try:
            from ..config import load_config
            cfg = load_config().get("llm")
        except Exception:
            cfg = None
    if not cfg or not cfg.get("api_key"):
        return "I can't reach my deep-thinking model right now."
    try:
        from ..llm import make_client
        deep = dict(cfg)
        deep["model"] = cfg.get("deep_model") or cfg.get("model")
        client = make_client({"llm": deep})
        resp = client.complete(
            "You are a sharp expert advisor. Think carefully, then answer concisely and usefully.",
            [{"role": "user", "content": question}], [],
        )
        return (resp.text or "").strip() or "I turned it over but came up blank."
    except Exception as exc:
        return f"Deep-think failed: {exc}"


ASSISTANT_SKILLS = [
    {"name": "remember", "fn": remember, "description": "Store a long-term fact about the user, remembered across future sessions.",
     "parameters": {"type": "object", "properties": {"fact": {"type": "string"}}, "required": ["fact"]}},
    {"name": "forget_fact", "fn": forget_fact, "description": "Remove or forget an outdated fact from long-term memory about Jay.",
     "parameters": {"type": "object", "properties": {"fact": {"type": "string", "description": "Fact or keyword to remove from memory"}}, "required": ["fact"]}},
    {"name": "set_my_name", "fn": set_my_name, "description": "Set what the user wants to be called.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "save_note", "fn": save_note, "description": "Save a quick note/reminder for the user.",
     "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "list_notes", "fn": list_notes, "description": "List all saved notes.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "delete_note", "fn": delete_note, "description": "Delete a note from memory by a word or phrase from its content.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "Search text to identify the note to delete"}}, "required": ["query"]}},
    {"name": "read_clipboard", "fn": read_clipboard, "description": "Read text currently copied to the Windows clipboard.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "write_clipboard", "fn": write_clipboard, "description": "Copy specified text to the Windows clipboard.",
     "parameters": {"type": "object", "properties": {"text": {"type": "string", "description": "Text to copy to clipboard"}}, "required": ["text"]}},
    {"name": "set_reminder", "fn": set_reminder, "description": "Set a timed reminder that FRIDAY will speak aloud when due. Give either minutes (relative, e.g. 'in 20 minutes') or at (a clock time like '17:30' or '5pm').",
     "parameters": {"type": "object", "properties": {"text": {"type": "string", "description": "What to remind Jay about"}, "minutes": {"type": "number", "description": "Fire this many minutes from now"}, "at": {"type": "string", "description": "Clock time to fire at, e.g. '17:30' or '5pm'"}}, "required": ["text"]}},
    {"name": "list_reminders", "fn": list_reminders, "description": "List all pending reminders.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "cancel_reminder", "fn": cancel_reminder, "description": "Cancel a pending reminder by its id or by a word from its text.",
     "parameters": {"type": "object", "properties": {"which": {"type": "string", "description": "Reminder id or a substring of its text"}}, "required": ["which"]}},
    {"name": "daily_briefing", "fn": daily_briefing, "description": "Give Jay a short spoken daily briefing (greeting, date/time, pending reminders, battery). Use for 'good morning', 'brief me', 'what's my day'.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "run_routine", "fn": run_routine, "description": "Run a saved multi-step routine by name — e.g. 'start my day', 'focus mode', 'wind down'. Use whenever Jay names a routine or says things like 'start my day' / 'let's focus' / 'wind down'.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "The routine name"}}, "required": ["name"]}},
    {"name": "list_routines", "fn": list_routines, "description": "List the available routines.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "send_to_claude", "fn": send_to_claude, "description": "After writing a well-structured prompt for Claude, call this with the full prompt text — it copies it to the clipboard and opens Claude so Jay can paste it.",
     "parameters": {"type": "object", "properties": {"prompt": {"type": "string", "description": "The complete prompt text to hand to Claude"}}, "required": ["prompt"]}},
    {"name": "deep_think", "fn": deep_think, "description": "Consult a stronger model for a hard question, tricky reasoning, or careful writing, then relay the answer in your own voice.",
     "parameters": {"type": "object", "properties": {"question": {"type": "string", "description": "The question or task to think hard about"}}, "required": ["question"]}},
    {"name": "get_datetime", "fn": get_datetime, "description": "Get the current date and time.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
]
