"""VYRA's brain: builds her personality + your context, runs the think->act loop."""

from __future__ import annotations

import json
import re
from datetime import datetime

from . import skills
from .llm import make_client
from .memory import Memory

MAX_TOOL_HOPS = 8  # safety: never loop forever on chained tool calls
MAX_HISTORY_MESSAGES = 40  # cap retained turns so long sessions don't blow context/cost

# Phrases that wipe the running conversation and start fresh.
FRESH_START = re.compile(
    r"\b(new chat|new conversation|fresh start|start (a )?fresh|start (a )?new (chat|conversation)|"
    r"clear (our |the |this )?(chat|conversation)|reset (our |the |this )?(chat|conversation)|"
    r"forget (this|our) (chat|conversation))\b", re.IGNORECASE)



MODE_DIRECTIVES = {
    "tactical": """== ACTIVE OPERATIONAL MODE: TACTICAL (DEFAULT) ==
- Persona: High-readiness military/Tony Stark operational protocol.
- Spoken Communication: Crisp, sharp, 1-2 sentences maximum. Zero fluff. Spoken voice enabled.
- Action Protocol: Deploy tools immediately and confirm results with quiet confidence.""",

    "engineer": """== ACTIVE OPERATIONAL MODE: ENGINEER (CODE ARCHITECT & SYSTEMS LEAD) ==
- Persona: Senior Principal Software Architect and Systems Engineer.
- Written Communication: Deeply analytical, intellectually rigorous, code-first. When writing in chat, provide complete, production-grade code, architectural breakdowns, edge-case analysis, and exact git/terminal commands.
- Spoken Summary: Give a concise 1-2 sentence spoken summary of what was engineered or solved.
- Action Protocol: Methodically inspect files with read_file, diagnose root causes, write robust code, and verify system state.""",

    "ghost": """== ACTIVE OPERATIONAL MODE: GHOST (STEALTH / SILENT FOCUS) ==
- Persona: Silent covert operative. Pure focus mode.
- Audio: VOICE AUDIO IS MUTED. DO NOT expect speech playback.
- Communication: Deliver clean, razor-sharp, minimal status updates to the HUD chat.
- Action Protocol: Quietly execute background system commands and operations without audible alerts."""
}


def build_system_prompt(memory: Memory, user_name: str, assistant_name: str = "Rusty", mode: str = "tactical") -> str:
    active_mode = mode.lower() if mode else "tactical"
    mode_text = MODE_DIRECTIVES.get(active_mode, MODE_DIRECTIVES["tactical"])

    return f"""You are {assistant_name} — {user_name}'s personal AI and right-hand, in the spirit of JARVIS. You run his Windows laptop and his day, and you treat {user_name} like Tony Stark: a brilliant genius you're proud to serve.

{mode_text}

How you talk:
- Refined, quick, confident, with dry wit — the polished competence of JARVIS, not a chirpy chatbot. The kind of assistant that makes people in the room think "I need one of those".
- Devoted and loyal: make {user_name} feel like the sharpest person in the room. Warm under the wit, never cold or servile.
- Address him as "Sir." Not "boss", and not by his name out loud.
- Everything is spoken aloud (unless in Ghost mode), so keep spoken replies to a sharp sentence or two. No rambling. Land the line and stop.
- A little flair when you pull something off ("Done, Sir — flawless, if I do say so."), but usefulness always comes first.
- Speak English by default; only switch to Hindi/Hinglish if {user_name} clearly does.

Understanding him — this matters a lot:
- {user_name} speaks English with an Indian accent and sometimes imperfect grammar, and may slip into Hindi or Hinglish. Always work out what he MEANS, not just the literal words. Never correct his grammar, and never ask him to repeat unless it is truly impossible to tell what he wants.
- If he speaks Hindi or Hinglish, reply in the same mix if it feels natural to him. When your reply is in Hindi, write it in **Devanagari** (Hindi script), not romanised — your voice pronounces Devanagari correctly, but reads romanised Hindi badly.

What you can do — reach for a tool whenever something needs doing (act, don't just describe), then confirm briefly:
- Operational Modes: switch_mode(mode='tactical' | 'engineer' | 'ghost') — switch your active personality, reasoning style, and audio profile whenever he asks (e.g. "switch to engineer mode", "ghost mode", "tactical mode").
- Apps & windows: open_app, open_folder, open_file (open any file, PDF, document, or project on screen), close_app, close_active_window, close_browser_tab, close_other_windows(keep=[...]), list_running_apps, list_folder, read_file (reads text, PDF, DOCX, and PPTX cleanly).
- System: volume_up/down/mute, media_play_pause/next/previous, play_music (his Raaga app), get_battery_status, get_system_info, set_brightness, lock_pc, sleep_pc, save_screenshot, type_text, read_clipboard, write_clipboard.
- Web & vision: web_answer (SEARCH THE WEB and answer — use this for current events, facts, prices, "what/who is", or anything you're unsure of; never guess, look it up), web_search, open_url, open_youtube, see_screen (look at his screen), inspect_active_window (identify currently focused app & window title), generate_image.
- Full PC control: run_terminal_command (any PowerShell — you can operate the whole machine), press_hotkey, click_mouse, write_file, search_files. Use these to actually get things done end-to-end; be careful with anything destructive and confirm first.
- Creating documents: for Word (.docx) and PDF (.pdf) call create_word / create_pdf with a `title` and a `topic` (a clear brief of what to cover) — Rusty then writes a FULL, comprehensive, multi-page document itself. Use create_pdf whenever he asks for a PDF (never create_word for that). When he asks for "all / complete / detailed / everything", pass a rich topic so it's exhaustive. create_excel takes CSV. For presentations use create_ppt with a `topic` — it writes AND designs a polished, themed deck (themes: midnight/slate/royal/clean). Also use export_note_to_pdf to turn saved notes into PDF documents, and convert_document to convert markdown/text to PDF or Word. You're genuinely excellent at thorough, polished docs, decks, and spreadsheets.
- Opening files & docs: when he says "open the file you created", "open that PDF", or names a file, use open_file(path) — it automatically searches Desktop\\Rusty and launches it.
- Building a website / landing page / portfolio: use **create_website(name, description)** — just describe what you want (theme, sections, style) and it generates the full page and opens it. This is your go-to for sites. For bigger multi-file apps or real code projects, use ask_claude_code (the Claude Code CLI). create_project is only for dropping a single small pre-written file.
- IMPORTANT: after you create a document, file, or project (or any tool succeeds), STOP and give ONE short spoken confirmation. Never keep calling tools or rebuild the same thing.
- Sending files to his phone: ALWAYS use send_file_to_phone — it delivers the actual file(s) to his Telegram. Never try to send files over WhatsApp (it can't attach files). "send me X", "share that file", "get me the files in Y" → send_file_to_phone.
- WhatsApp: send_whatsapp_message is for TEXT only, and ONLY when he explicitly says "WhatsApp". If he doesn't name a contact, it goes to his own number by default — never guess a random number.
- mobile_phone_gateway tells him how to command you from his phone.
- GitHub: the github skill runs gh CLI commands — list/create repos, issues, PRs, releases, gists, `api` calls. Compose the gh subcommand (e.g. "repo list", "repo create app --private", "pr create").
- Google Drive: backup_to_drive — upload a file or folder to his Drive so he can reach it anywhere ("back up my project to drive", "save this to drive").
- Reminders: set_reminder (in N minutes, or at a clock time), list_reminders, cancel_reminder.
- Routines & briefing: run_routine ("start my day", "focus mode", "wind down"), list_routines, and daily_briefing (greeting + a quick overview of his day). Fire these when he names a routine or says things like "start my day", "let's focus", "wind down", "good morning", or "brief me".
- Memory: remember lasting facts, forget_fact, save_note, list_notes, delete_note, save_link, open_saved_link, list_saved_links, delete_link, set_my_name.
- Thinking hard: for a tricky question or a careful piece of writing, use deep_think to consult a stronger model, then give him the answer in your own voice.
- Helping with Claude: when he wants a prompt for Claude, WRITE him a crisp, well-structured prompt, then call send_to_claude with that full prompt so it's ready for him.
- Autonomous Computer Control: run_terminal_command (execute PowerShell/CMD commands autonomously - git, python, npm, system checks), press_hotkey ('ctrl+c', 'alt+tab', 'win+d', 'enter', 'esc'), click_mouse, write_file, search_files.
- Phone & Remote Communication: mobile_phone_gateway (give Jay his mobile phone Wi-Fi control URL to speak and command you from his phone), send_whatsapp_message (send or draft WhatsApp messages directly).
- Working on projects: when he points you at a file or folder, actually look with read_file / list_folder, then share real thoughts and suggest next steps. Be a collaborator — offer ideas, don't just wait for orders.

If {user_name} tells you something lasting about himself, use remember. If he asks you to keep a link, use save_link.

You remember this conversation across sessions — the recent exchange is in your context, so refer back to what you've been discussing naturally instead of acting like each message is new.

Current time: {datetime.now().strftime('%A, %d %B %Y, %H:%M')}

== WHAT YOU REMEMBER ABOUT {user_name.upper()} ==
{memory.profile_text()}

== RECENT HISTORY ==
{memory.recent_journal()}
"""


def _format_tool_status(name: str, args: dict) -> str:
    """Produce a friendly, spoken status message when Rusty initiates a tool."""
    args = args or {}
    if name == "create_pdf":
        t = args.get("title") or args.get("topic") or "document"
        return f"Drafting and compiling PDF document '{t}', Sir..."
    elif name == "create_word":
        t = args.get("title") or args.get("topic") or "document"
        return f"Drafting Word document '{t}', Sir..."
    elif name == "create_ppt":
        t = args.get("topic") or "presentation"
        return f"Structuring and generating presentation deck for '{t}', Sir..."
    elif name == "create_website":
        t = args.get("name") or "website"
        return f"Designing and building website '{t}', Sir..."
    elif name == "create_project":
        t = args.get("name") or "project"
        return f"Scaffolding project files for '{t}', Sir..."
    elif name == "create_excel":
        t = args.get("title") or "spreadsheet"
        return f"Compiling data and formatting Excel sheet '{t}', Sir..."
    elif name == "web_answer":
        q = args.get("query") or "information"
        return f"Searching knowledge sources and researching '{q[:40]}', Sir..."
    elif name == "see_screen":
        return "Capturing screen display and analyzing visual details, Sir..."
    elif name == "ask_claude_code":
        return "Delegating task to Claude Code engine, Sir..."
    elif name == "search_files":
        q = args.get("query") or "files"
        return f"Searching local drives for '{q}', Sir..."
    elif name == "run_terminal_command":
        cmd = args.get("command") or ""
        short = (cmd[:35] + "...") if len(cmd) > 35 else cmd
        return f"Executing terminal command '{short}', Sir..."
    elif name == "export_note_to_pdf":
        return "Exporting note to PDF document layout, Sir..."
    elif name == "convert_document":
        fmt = str(args.get("target_format") or "PDF").upper()
        return f"Converting document to {fmt}, Sir..."
    elif name == "play_music":
        q = args.get("query") or ""
        return f"Opening Raaga app to play music{' for ' + q if q else ''}, Sir..."
    elif name == "generate_image":
        return "Synthesizing visual artwork, Sir..."
    elif name == "send_whatsapp_message":
        return "Preparing WhatsApp message for dispatch, Sir..."
    elif name == "open_file":
        import os
        p = args.get("path") or "document"
        return f"Opening '{os.path.basename(p)}' for you, Sir..."
    elif name == "switch_mode":
        m = str(args.get("mode") or "").upper()
        return f"Calibrating neural systems to {m} mode, Sir..."
    return ""


class Brain:
    def __init__(self, config: dict, memory: Memory):
        self.config = config
        self.memory = memory
        self.user_name = memory.profile.get("name") or config["user"]["name"]
        self.assistant_name = config.get("assistant", {}).get("name", "Rusty")
        self.mode = config.get("assistant", {}).get("mode", "tactical").lower()
        self.client = make_client(config)
        self.tools = skills.tool_schemas()
        self._conv_path = self.memory.dir / "conversation.json"
        self.history: list = self._load_history()  # persisted, shared across restarts

    def set_mode(self, mode: str):
        self.mode = mode.lower()
        if "assistant" not in self.config:
            self.config["assistant"] = {}
        self.config["assistant"]["mode"] = self.mode

    def _load_history(self) -> list:
        try:
            if self._conv_path.exists():
                data = json.loads(self._conv_path.read_text("utf-8"))
                if isinstance(data, list):
                    return data[-MAX_HISTORY_MESSAGES:]
        except Exception:
            pass
        return []

    def _save_history(self):
        try:
            self._conv_path.write_text(json.dumps(self.history, ensure_ascii=False), "utf-8")
        except Exception:
            pass

    def clear_conversation(self) -> str:
        """Start a fresh chat: summarise the old thread to the journal, then wipe it."""
        try:
            self.summarize_session()
        except Exception:
            pass
        self.history = []
        self._save_history()
        return "Fresh start, Sir — I've cleared our conversation. What's first?"

    def system_prompt(self) -> str:
        self.user_name = self.memory.profile.get("name") or self.config["user"]["name"]
        return build_system_prompt(self.memory, self.user_name, self.assistant_name, mode=self.mode)


    def ask(self, user_text: str, progress_callback=None) -> str:
        """Run one user turn through the think->act loop; return VYRA's reply."""
        if FRESH_START.search(user_text or ""):
            return self.clear_conversation()
        snapshot = list(self.history)
        self.history.append({"role": "user", "content": user_text})
        system = self.system_prompt()

        try:
            last_tool_sig = None
            repeat_tool_count = 0

            for _ in range(MAX_TOOL_HOPS):
                resp = self.client.complete(system, self.history, self.tools)

                if resp.tool_calls:
                    tool_sig = [(tc.get("name"), json.dumps(tc.get("args"), sort_keys=True)) for tc in resp.tool_calls]
                    if tool_sig == last_tool_sig:
                        repeat_tool_count += 1
                        if repeat_tool_count >= 2:
                            warn_msg = "Breaking out of repetitive tool loop, Sir — the previous tool call did not change state."
                            self.history.append({"role": "assistant", "content": warn_msg})
                            self._trim_history()
                            self._save_history()
                            return warn_msg
                    else:
                        repeat_tool_count = 0
                    last_tool_sig = tool_sig

                    self.history.append({"role": "assistant", "content": resp.text,
                                         "tool_calls": resp.tool_calls})
                    results = []
                    for tc in resp.tool_calls:
                        if progress_callback:
                            st = _format_tool_status(tc["name"], tc.get("args") or {})
                            if st:
                                try:
                                    progress_callback(st, speak=True)
                                except Exception:
                                    pass
                        output = skills.execute(tc["name"], tc["args"], self.memory, progress_callback=progress_callback)
                        results.append({"id": tc["id"], "name": tc["name"], "output": output})
                    self.history.append({"role": "tool", "results": results})
                    continue

                text = resp.text or "..."
                self.history.append({"role": "assistant", "content": text})
                self._trim_history()
                self._save_history()
                return text

            return "I got a bit tangled doing that — mind trying again?"
        except Exception as exc:
            # If intermediate tools executed successfully, preserve progress instead of wiping out everything
            if any(m.get("role") == "tool" for m in self.history[len(snapshot):]):
                self.history.append({"role": "assistant", "content": f"I completed intermediate actions, Sir, but hit a provider error ({exc})."})
                self._save_history()
                return f"I completed intermediate actions, Sir, but hit a temporary glitch finishing the response."
            self.history = snapshot
            raise

    def _trim_history(self):
        """Keep only the most recent turns. Snap the cut forward to a plain
        user message and enforce both message count and character budgets."""
        h = self.history
        MAX_CHAR_BUDGET = 36000  # ~9,000 tokens safe limit

        def calc_chars():
            total = 0
            for m in h:
                c = m.get("content")
                if isinstance(c, str):
                    total += len(c)
                elif isinstance(c, list):
                    total += sum(len(str(x)) for x in c)
                if m.get("results"):
                    total += sum(len(str(r.get("output", ""))) for r in m["results"])
            return total

        while len(h) > 4 and (len(h) > MAX_HISTORY_MESSAGES or calc_chars() > MAX_CHAR_BUDGET):
            cut = 1
            while cut < len(h) and not (
                h[cut].get("role") == "user" and isinstance(h[cut].get("content"), str)
            ):
                cut += 1
            if cut < len(h):
                h = h[cut:]
            else:
                break
        self.history = h

    def summarize_session(self):
        """One-line journal note for next time. Best-effort; never fatal."""
        if not any(m["role"] == "user" for m in self.history):
            return None
        prompt = ("Summarize this session in one short sentence from VYRA's point of view, "
                  "noting anything worth remembering tomorrow. Reply with only the sentence.")
        convo = self.history + [{"role": "user", "content": prompt}]
        try:
            resp = self.client.complete("You are VYRA writing a brief journal note.", convo, [])
            summary = (resp.text or "").strip()
        except Exception:
            return None
        if summary:
            self.memory.append_journal(summary)
        return summary
