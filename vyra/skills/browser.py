"""Browser automation, link management, tab handling, and web search skills for Rusty."""

from __future__ import annotations

import ctypes
import json
import subprocess
import time
import urllib.parse
import urllib.request
import webbrowser
from urllib.parse import quote_plus

from .common import (
    KNOWN_BROWSERS,
    _get_user_windows,
    focus_window,
)

_BROWSER = None  # preferred browser (e.g. "brave"); None = system default


def configure_browser(browser):
    global _BROWSER
    _BROWSER = browser or None


def _open_in_browser(url: str):
    if _BROWSER:
        try:
            subprocess.Popen([_BROWSER, url])
            return
        except Exception:
            try:
                subprocess.Popen(["cmd", "/c", "start", "", _BROWSER, url])
                return
            except Exception:
                pass
    webbrowser.open(url)


def _send_ctrl_w():
    """Send Ctrl+W key combination using native Win32 keybd_event."""
    user32 = ctypes.windll.user32
    VK_CONTROL = 0x11
    VK_W = 0x57
    KEYEVENTF_KEYUP = 0x0002
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_W, 0, 0, 0)
    time.sleep(0.05)
    user32.keybd_event(VK_W, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def close_browser_tab(memory, query: str = "") -> str:
    """Close a specific tab by title/website (or the active tab) in the browser (Ctrl+W)."""
    wins = _get_user_windows()
    browser_wins = [w for w in wins if any(b in w['proc'] for b in KNOWN_BROWSERS)]
    if not browser_wins:
        return "No active browser window found to close tabs from, Sir."

    target_win = None
    q_clean = query.lower().strip() if query else ""
    for prefix in ("the ", "a ", "my "):
        if q_clean.startswith(prefix):
            q_clean = q_clean[len(prefix):].strip()
    if q_clean.endswith(" tab") or q_clean.endswith(" page"):
        q_clean = q_clean.rsplit(" ", 1)[0].strip()

    if q_clean:
        for w in browser_wins:
            if q_clean in w['title'].lower():
                target_win = w
                break
        if not target_win:
            for w in wins:
                if q_clean in w['title'].lower():
                    target_win = w
                    break

    if not target_win:
        target_win = browser_wins[0]

    # Focus the browser window and send Ctrl+W
    focus_window(target_win['hwnd'])
    time.sleep(0.12)
    _send_ctrl_w()

    b_name = target_win['proc'].replace('.exe', '').capitalize()
    if q_clean and q_clean in target_win['title'].lower():
        return f"Closed the '{target_win['title']}' tab in {b_name}, Sir."
    return f"Closed the active tab in {b_name}, Sir."


def web_search(memory, query: str) -> str:
    _open_in_browser(f"https://www.google.com/search?q={quote_plus(query)}")
    return f"Searching Google for '{query}'."


def open_url(memory, url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    _open_in_browser(url)
    return f"Opening {url}."


def open_youtube(memory, query: str = None) -> str:
    if query:
        _open_in_browser(f"https://www.youtube.com/results?search_query={quote_plus(query)}")
        return f"Searching YouTube for '{query}'."
    _open_in_browser("https://www.youtube.com")
    return "Opening YouTube."


def save_link(memory, name: str, url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    memory.save_link(name, url)
    return f"Saved '{name}'. Say \"open {name}\" anytime."


def open_saved_link(memory, name: str) -> str:
    url = memory.get_link(name)
    if not url:
        saved = ", ".join(memory.list_links().keys()) or "nothing yet"
        return f"I don't have a link called '{name}'. Saved: {saved}."
    _open_in_browser(url)
    return f"Opening {name}."


def list_saved_links(memory) -> str:
    links = memory.list_links()
    if not links:
        return "No saved links yet."
    return "Saved links:\n" + "\n".join(f"  - {n}: {u}" for n, u in links.items())


def delete_link(memory, name: str) -> str:
    """Delete a saved shortcut link from memory."""
    ok = memory.delete_link(name)
    return f"Removed the link for '{name}', Sir." if ok else f"I couldn't find a saved link named '{name}', Sir."


def web_answer(memory, query: str, progress_callback=None) -> str:
    """Look something up and answer concisely — Wikipedia for facts, with the
    model's own knowledge as backup. Use for 'what/who is', facts, definitions."""
    if progress_callback:
        progress_callback(f"Researching '{query[:40]}' across knowledge sources, Sir...", speak=True)
    context = ""
    try:
        s = ("https://en.wikipedia.org/w/api.php?action=query&list=search&format=json"
             "&srlimit=1&srsearch=" + urllib.parse.quote(query))
        req = urllib.request.Request(s, headers={"User-Agent": "RustyAI/1.0"})
        with urllib.request.urlopen(req, timeout=8) as response:
            sr = json.loads(response.read())
        hits = sr.get("query", {}).get("search", [])
        if hits:
            title = hits[0]["title"].replace(" ", "_")
            su = "https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title)
            req2 = urllib.request.Request(su, headers={"User-Agent": "RustyAI/1.0"})
            with urllib.request.urlopen(req2, timeout=8) as resp2:
                sd = json.loads(resp2.read())
            context = (sd.get("extract") or "")[:2000]
    except Exception:
        context = ""

    from .media import _VISION_CONFIG
    cfg = _VISION_CONFIG
    if not cfg:
        try:
            from ..config import load_config
            cfg = load_config().get("llm")
        except Exception:
            cfg = None
    if not cfg or not cfg.get("api_key"):
        return context[:400] if context else "I couldn't look that up right now, Sir."
    try:
        from ..llm import make_client
        client = make_client({"llm": cfg})
        sysmsg = ("You are Rusty. Answer in one or two spoken sentences. Use the reference if provided; "
                  "otherwise answer from your own knowledge. Be accurate and concise.")
        user = f"Question: {query}" + (f"\n\nReference:\n{context}" if context else "")
        resp = client.complete(sysmsg, [{"role": "user", "content": user}], [])
        return (resp.text or "").strip() or (context[:400] if context else "I'm not certain on that one, Sir.")
    except Exception:
        return context[:400] if context else "I couldn't look that up right now, Sir."


BROWSER_SKILLS = [
    {"name": "web_search", "fn": web_search, "description": "Open a Google search in the browser (visual). For a spoken answer, prefer web_answer.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "web_answer", "fn": web_answer, "description": "Search the web and give Jay a concise spoken answer. Use for current events, facts, prices, 'what is / who is / latest', or anything you're unsure about — don't guess, look it up.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "What to look up"}}, "required": ["query"]}},
    {"name": "open_url", "fn": open_url, "description": "Open a specific URL in the browser.",
     "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
    {"name": "open_youtube", "fn": open_youtube, "description": "Open YouTube, optionally searching for something.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "Optional search terms"}}, "required": []}},
    {"name": "close_browser_tab", "fn": close_browser_tab, "description": "Close a specific tab by title/site (e.g. 'youtube', 'meet', 'google', 'whatsapp') or the active tab in the browser (Ctrl+W). Focuses the browser first.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "Optional tab title or website name to close (e.g. 'youtube', 'meet', 'reddit')"}}, "required": []}},
    {"name": "save_link", "fn": save_link, "description": "Save a named link/shortcut for later (e.g. a Google Meet link).",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "url": {"type": "string"}}, "required": ["name", "url"]}},
    {"name": "open_saved_link", "fn": open_saved_link, "description": "Open a link previously saved with save_link, by its name.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "list_saved_links", "fn": list_saved_links, "description": "List all saved named links.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "delete_link", "fn": delete_link, "description": "Delete a saved named link/shortcut from memory.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "Name of the link to remove"}}, "required": ["name"]}},
]
