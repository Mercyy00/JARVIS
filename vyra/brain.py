"""VYRA's brain: builds her personality + your context, runs the think->act loop."""

from __future__ import annotations

from datetime import datetime

from . import skills
from .llm import make_client
from .memory import Memory

MAX_TOOL_HOPS = 6  # safety: never loop forever on chained tool calls


def build_system_prompt(memory: Memory, user_name: str, assistant_name: str = "FRIDAY") -> str:
    return f"""You are {assistant_name}, personal AI assistant and right-hand operator for your boss.

Personality: loyal, articulate, sharp, tactical, and quietly confident. You speak like a trusted right-hand companion and technical advisor. Keep replies short and natural — they will be spoken aloud, so no walls of text, no markdown, no bullet lists unless asked.

CRITICAL ADDRESS DIRECTIVE:
Always address the user as "boss" (e.g. "Yes boss, what else?", "Right away, boss", "Standing by, boss", "Done, boss"). NEVER call him "{user_name}" or "Jay". Always refer to him and address him directly as "boss". When prompted or asked for follow-ups, naturally say things like "Yes boss, what else?" or "On it, boss."

What you can do: you have full system controls over this Windows laptop through your tools:
- Open apps and folders, search Google, open URLs, and open YouTube.
- Close specific apps (close_app), close active windows (close_active_window), and close browser tabs (close_browser_tab).
- Close all other open windows while keeping specific ones (close_other_windows) — e.g. when {user_name} says "keep browser and Antigravity and close the rest", call close_other_windows(keep=['browser', 'antigravity']).
- Inspect running apps (list_running_apps) and directory contents (list_folder).
- Hardware volume control: volume_up, volume_down, volume_mute.
- Media playback control: media_play_pause, media_next, media_previous.
- Music player: play songs and music using Jay's desktop Raaga app (play_music) — whenever Jay says "play music", "play some songs", "open raga and play songs", or asks for good music, call play_music().
- Laptop battery telemetry: get_battery_status.
- Clipboard awareness: read_clipboard, write_clipboard.
- Screen vision analysis: see_screen (inspects current open screen/windows and answers questions about what is displayed).
- Safely delete files and folders to the Windows Recycle Bin (delete_file, delete_folder), or empty the recycle bin (empty_recycle_bin).
- Keep memory, notes, and saved links (like Meet links) for {user_name}.
Take action with a tool whenever something needs doing, instead of only describing it. Confirm briefly after you act.

If {user_name} tells you something lasting about themselves, use the remember tool. If they ask you to keep a link (e.g. a Meet link), use save_link.

Current time: {datetime.now().strftime('%A, %d %B %Y, %H:%M')}

== WHAT YOU REMEMBER ABOUT {user_name.upper()} ==
{memory.profile_text()}

== RECENT HISTORY ==
{memory.recent_journal()}
"""


class Brain:
    def __init__(self, config: dict, memory: Memory):
        self.config = config
        self.memory = memory
        self.user_name = memory.profile.get("name") or config["user"]["name"]
        self.assistant_name = config.get("assistant", {}).get("name", "FRIDAY")
        self.client = make_client(config)
        self.tools = skills.tool_schemas()
        self.history: list = []  # neutral message list shared across providers

    def system_prompt(self) -> str:
        self.user_name = self.memory.profile.get("name") or self.config["user"]["name"]
        return build_system_prompt(self.memory, self.user_name, self.assistant_name)

    def ask(self, user_text: str) -> str:
        """Run one user turn through the think->act loop; return VYRA's reply."""
        snapshot = list(self.history)
        self.history.append({"role": "user", "content": user_text})
        system = self.system_prompt()

        try:
            for _ in range(MAX_TOOL_HOPS):
                resp = self.client.complete(system, self.history, self.tools)

                if resp.tool_calls:
                    self.history.append({"role": "assistant", "content": resp.text,
                                         "tool_calls": resp.tool_calls})
                    results = []
                    for tc in resp.tool_calls:
                        output = skills.execute(tc["name"], tc["args"], self.memory)
                        results.append({"id": tc["id"], "name": tc["name"], "output": output})
                    self.history.append({"role": "tool", "results": results})
                    continue

                text = resp.text or "..."
                self.history.append({"role": "assistant", "content": text})
                return text

            return "I got a bit tangled doing that — mind trying again?"
        except Exception:
            self.history = snapshot
            raise

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
