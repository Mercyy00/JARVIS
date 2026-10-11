"""VYRA's skills — the things she can actually DO on your machine.

Each skill is a plain function taking the Memory object plus named arguments,
returning a short status string that VYRA relays to you. SKILLS holds their
JSON schemas so the LLM knows what it may call. All Phase 1 skills are
non-destructive (open / search / save), so none require confirmation yet.
"""

from __future__ import annotations

import base64
import csv
import ctypes
import io
import os
import shutil
import subprocess
import time
import webbrowser
from datetime import datetime
from urllib.parse import quote_plus

import psutil

RAAGA_APP_PATH = os.path.expandvars(r"%USERPROFILE%\Desktop\raaga.lnk")
if not os.path.exists(RAAGA_APP_PATH):
    RAAGA_APP_PATH = os.path.expandvars(r"%LOCALAPPDATA%\raaga\raaga-app.exe")

APP_ALIASES = {
    "files": "explorer",
    "file explorer": "explorer",
    "calculator": "calc",
    "terminal": "cmd",
    "settings": "ms-settings:",
    "browser": "brave",
    "raga": RAAGA_APP_PATH,
    "raaga": RAAGA_APP_PATH,
    "raga app": RAAGA_APP_PATH,
    "raaga app": RAAGA_APP_PATH,
    "music": RAAGA_APP_PATH,
}

SYSTEM_PROTECTED = {
    "dwm.exe", "svchost.exe", "csrss.exe", "smss.exe", "wininit.exe", 
    "services.exe", "lsass.exe", "sihost.exe", "taskhostw.exe", "explorer.exe",
    "searchhost.exe", "startmenuexperiencehost.exe", "textinputhost.exe",
    "shellexperiencehost.exe", "shellhost.exe", "runtimebroker.exe",
    "applicationframehost.exe", "systemsettings.exe", "lockapp.exe",
    "nvdisplay.container.exe", "crossdeviceresume.exe", "crossdeviceservice.exe",
    "msedgewebview2.exe", "vgtray.exe", "yasb.exe", "onedrive.sync.service.exe",
    "nearby_share.exe", "flow.launcher.exe", "jusched.exe", "komorebi.exe",
    "whkd.exe", "powershell.exe", "pwsh.exe", "cmd.exe", "dllhost.exe",
    "rtkauduservice64.exe", "sdxhelper.exe", "unsecapp.exe", "python.exe"
}

IGNORE_TITLES = {
    "n/a", "", "olemainthreadwndname", "dde server window", "task host window",
    "olechannelwnd", "default ime", "msctfime ui", "program manager",
    "hotkey sink", "c:\\users\\perfect\\scoop\\shims\\komorebi.exe", "komorebi-hidden",
    "c:\\users\\perfect\\scoop\\shims\\whkd.exe", "fn_hotkey_capslknumlk", "fnformonitormic",
    "realtekaudiobackgroundprocessclass", "realtekaudioadminbackgroundprocessclass",
    "quick settings"
}

FOLDER_SHORTCUTS = {
    "downloads": r"%USERPROFILE%\Downloads",
    "documents": r"%USERPROFILE%\Documents",
    "desktop": r"%USERPROFILE%\Desktop",
    "pictures": r"%USERPROFILE%\Pictures",
    "home": r"%USERPROFILE%",
}

_BROWSER = None  # preferred browser (e.g. "brave"); None = system default
_VISION_CONFIG = None  # llm config for screen vision queries


def configure_browser(browser):
    global _BROWSER
    _BROWSER = browser or None


def configure_vision(llm_config: dict):
    global _VISION_CONFIG
    _VISION_CONFIG = llm_config


def _open_in_browser(url: str):
    if _BROWSER:
        try:
            subprocess.Popen(f'start "" "{_BROWSER}" "{url}"', shell=True)
            return
        except Exception:
            pass
    webbrowser.open(url)


def open_app(memory, name: str) -> str:
    target = APP_ALIASES.get(name.lower().strip(), name)
    try:
        subprocess.Popen(f'start "" "{target}"', shell=True)
        return f"Opening {name}."
    except Exception as exc:
        return f"Couldn't open {name}: {exc}"


def open_folder(memory, path: str) -> str:
    resolved = os.path.expandvars(FOLDER_SHORTCUTS.get(path.lower().strip(), path))
    if not os.path.exists(resolved):
        return f"That folder doesn't exist: {resolved}"
    subprocess.Popen(["explorer", resolved])
    return f"Opening folder {resolved}."


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


def remember(memory, fact: str) -> str:
    memory.add_about(fact)
    return "Noted. I'll remember that."


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


def get_datetime(memory) -> str:
    return datetime.now().strftime("It's %A, %d %B %Y, %H:%M.")


def _resolve_path(path_str: str) -> str:
    path_str = (path_str or "").strip().strip('"').strip("'")
    if not path_str:
        return ""
    lower = path_str.lower()
    for shortcut, target in FOLDER_SHORTCUTS.items():
        if lower == shortcut or lower.startswith(shortcut + "/") or lower.startswith(shortcut + "\\"):
            remainder = path_str[len(shortcut):].lstrip("/\\")
            expanded_base = os.path.expandvars(target)
            return os.path.join(expanded_base, remainder) if remainder else expanded_base
    return os.path.abspath(os.path.expandvars(path_str))


def _get_user_windows() -> list[dict]:
    try:
        out = subprocess.check_output(['tasklist', '/v', '/fo', 'csv'], text=True, errors='replace', timeout=8)
    except Exception:
        try:
            out = subprocess.check_output(['tasklist', '/fo', 'csv', '/fi', 'SESSIONNAME eq Console'], text=True, errors='replace', timeout=5)
        except Exception:
            return []
    reader = csv.DictReader(io.StringIO(out))
    
    current_pid = os.getpid()
    user_windows = []
    seen_pids = set()

    for row in reader:
        proc_name = (row.get('Image Name') or '').strip()
        pid_str = (row.get('PID') or '').strip()
        title = (row.get('Window Title') or '').strip()

        if not pid_str.isdigit():
            continue
        pid = int(pid_str)

        if pid == current_pid or pid in seen_pids:
            continue
        if proc_name.lower() in SYSTEM_PROTECTED:
            continue
        if title.lower() in IGNORE_TITLES:
            continue
        if "stark industries hud" in title.lower() or "vyra" in title.lower():
            continue

        seen_pids.add(pid)
        user_windows.append({
            "pid": pid,
            "proc": proc_name,
            "title": title
        })
    return user_windows


def close_app(memory, name: str) -> str:
    """Close/terminate an application by name or window title."""
    name_clean = name.lower().strip()
    target = APP_ALIASES.get(name_clean, name_clean)
    closed = []
    
    # Check running processes
    for p in psutil.process_iter(['pid', 'name']):
        try:
            p_name = p.info['name'].lower()
            if target in p_name or name_clean in p_name or (target + ".exe") == p_name:
                p.terminate()
                closed.append(p.info['name'])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # If not found directly by process name, check open window titles
    if not closed:
        for w in _get_user_windows():
            if name_clean in w['title'].lower() or name_clean in w['proc'].lower():
                try:
                    p = psutil.Process(w['pid'])
                    p.terminate()
                    closed.append(w['proc'])
                except Exception:
                    pass

    if closed:
        return f"Closed {len(closed)} instance(s) of {name}."
    return f"Could not find any running window or process matching '{name}'."


def close_other_windows(memory, keep: list[str]) -> str:
    """Close all open user application windows EXCEPT the ones specified in `keep`."""
    if isinstance(keep, str):
        keep = [k.strip() for k in keep.split(",")]
    
    keep_lower = [k.lower().strip() for k in keep]
    # Expand aliases (e.g. 'browser' matches brave, chrome, zen, edge)
    if any("browser" in k for k in keep_lower):
        keep_lower.extend(["brave", "chrome", "edge", "firefox", "zen", "opera"])
    if any("antigravity" in k for k in keep_lower):
        keep_lower.extend(["antigravity", "cursor", "vscode", "code"])

    windows = _get_user_windows()
    closed = []
    kept = []

    for w in windows:
        p_name = w['proc'].lower()
        title = w['title'].lower()
        
        should_keep = any(k in p_name or k in title for k in keep_lower)
        if should_keep:
            kept.append(w['proc'])
        else:
            try:
                p = psutil.Process(w['pid'])
                p.terminate()
                closed.append(w['proc'])
            except Exception:
                pass

    msg_parts = []
    if closed:
        msg_parts.append(f"Closed {len(closed)} window(s): {', '.join(closed[:4])}{' and others' if len(closed) > 4 else ''}.")
    else:
        msg_parts.append("No other windows needed closing.")
        
    if kept:
        msg_parts.append(f"Kept open: {', '.join(set(kept))}.")
        
    return " ".join(msg_parts)


def close_browser_tab(memory) -> str:
    """Close the active tab in the browser (Ctrl+W)."""
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", "$wshell = New-Object -ComObject wscript.shell; $wshell.SendKeys('^w')"],
        capture_output=True
    )
    return "Closed the active browser tab."


def close_active_window(memory) -> str:
    """Close the currently active window (Alt+F4)."""
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", "$wshell = New-Object -ComObject wscript.shell; $wshell.SendKeys('%{F4}')"],
        capture_output=True
    )
    return "Closed the active window."


def list_running_apps(memory) -> str:
    """List currently open user applications and window titles."""
    windows = _get_user_windows()
    if not windows:
        return "No user applications currently open."
    lines = ["Currently open applications:"]
    for w in windows:
        lines.append(f"  - {w['proc']}: '{w['title']}' (PID: {w['pid']})")
    return "\n".join(lines)


def delete_file(memory, path: str, permanent: bool = False) -> str:
    """Delete a file. By default moves to Windows Recycle Bin for safety."""
    full_path = _resolve_path(path)
    if not os.path.exists(full_path):
        return f"File does not exist: {full_path}"
    if os.path.isdir(full_path):
        return f"'{full_path}' is a folder, not a file. Use delete_folder instead."
    
    if permanent:
        try:
            os.remove(full_path)
            return f"Permanently deleted '{os.path.basename(full_path)}'."
        except Exception as exc:
            return f"Error deleting file: {exc}"
    else:
        ps_cmd = f"Add-Type -AssemblyName Microsoft.VisualBasic; [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile('{full_path}', 'OnlyErrorDialogs', 'SendToRecycleBin')"
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True)
        if res.returncode == 0:
            return f"Moved '{os.path.basename(full_path)}' to the Windows Recycle Bin."
        return f"Failed to recycle file: {res.stderr.strip()}"


def delete_folder(memory, path: str, permanent: bool = False) -> str:
    """Delete a directory. By default moves to Windows Recycle Bin for safety."""
    full_path = _resolve_path(path)
    if not os.path.exists(full_path):
        return f"Folder does not exist: {full_path}"
    if not os.path.isdir(full_path):
        return f"'{full_path}' is a file, not a folder. Use delete_file instead."

    if permanent:
        try:
            shutil.rmtree(full_path)
            return f"Permanently deleted folder '{os.path.basename(full_path)}'."
        except Exception as exc:
            return f"Error deleting folder: {exc}"
    else:
        ps_cmd = f"Add-Type -AssemblyName Microsoft.VisualBasic; [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory('{full_path}', 'OnlyErrorDialogs', 'SendToRecycleBin')"
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True)
        if res.returncode == 0:
            return f"Moved folder '{os.path.basename(full_path)}' to the Windows Recycle Bin."
        return f"Failed to recycle folder: {res.stderr.strip()}"


def list_folder(memory, path: str = "downloads") -> str:
    """List files and folders in a directory."""
    full_path = _resolve_path(path)
    if not os.path.exists(full_path):
        return f"Folder does not exist: {full_path}"
    if not os.path.isdir(full_path):
        return f"'{full_path}' is not a directory."
        
    try:
        entries = sorted(os.listdir(full_path))
        if not entries:
            return f"Folder '{os.path.basename(full_path)}' is empty."
        lines = [f"Contents of {os.path.basename(full_path)} ({len(entries)} items):"]
        for item in entries[:20]:
            item_path = os.path.join(full_path, item)
            if os.path.isdir(item_path):
                lines.append(f"  [DIR]  {item}")
            else:
                size_mb = os.path.getsize(item_path) / (1024 * 1024)
                size_str = f"{size_mb:.2f} MB" if size_mb >= 1.0 else f"{round(size_mb * 1024)} KB"
                lines.append(f"  [FILE] {item} ({size_str})")
        if len(entries) > 20:
            lines.append(f"  ... and {len(entries) - 20} more items.")
        return "\n".join(lines)
    except Exception as exc:
        return f"Could not list folder: {exc}"


def empty_recycle_bin(memory) -> str:
    """Empty the Windows Recycle Bin."""
    res = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"],
        capture_output=True, text=True
    )
    if res.returncode == 0:
        return "Emptied the Windows Recycle Bin."
    return f"Could not empty Recycle Bin: {res.stderr.strip()}"


def volume_up(memory, steps: int = 5) -> str:
    """Increase system volume. Each step increases volume by ~2%."""
    try:
        steps = max(1, min(int(steps), 50))
    except (ValueError, TypeError):
        steps = 5
    VK_VOLUME_UP = 0xAF
    for _ in range(steps):
        ctypes.windll.user32.keybd_event(VK_VOLUME_UP, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_VOLUME_UP, 0, 2, 0)
        time.sleep(0.01)
    return f"Turned volume up by approximately {steps * 2}%."


def volume_down(memory, steps: int = 5) -> str:
    """Decrease system volume. Each step decreases volume by ~2%."""
    try:
        steps = max(1, min(int(steps), 50))
    except (ValueError, TypeError):
        steps = 5
    VK_VOLUME_DOWN = 0xAE
    for _ in range(steps):
        ctypes.windll.user32.keybd_event(VK_VOLUME_DOWN, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_VOLUME_DOWN, 0, 2, 0)
        time.sleep(0.01)
    return f"Turned volume down by approximately {steps * 2}%."


def volume_mute(memory) -> str:
    """Toggle master audio mute / unmute."""
    VK_VOLUME_MUTE = 0xAD
    ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, 0, 0)
    ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, 2, 0)
    return "Toggled master audio mute."


def media_play_pause(memory) -> str:
    """Toggle media playback (play / pause) for Spotify, YouTube, browsers, etc."""
    VK_MEDIA_PLAY_PAUSE = 0xB3
    ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 0, 0)
    ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 2, 0)
    return "Toggled media play/pause."


def media_next(memory) -> str:
    """Skip to next media track."""
    VK_MEDIA_NEXT = 0xB0
    ctypes.windll.user32.keybd_event(VK_MEDIA_NEXT, 0, 0, 0)
    ctypes.windll.user32.keybd_event(VK_MEDIA_NEXT, 0, 2, 0)
    return "Skipped to next track."


def media_previous(memory) -> str:
    """Return to previous media track."""
    VK_MEDIA_PREV = 0xB1
    ctypes.windll.user32.keybd_event(VK_MEDIA_PREV, 0, 0, 0)
    ctypes.windll.user32.keybd_event(VK_MEDIA_PREV, 0, 2, 0)
    return "Returned to previous track."


def play_music(memory, query: str = "") -> str:
    """Open Jay's Raaga music app from desktop and start playing songs or good music."""
    raaga_running = False
    for p in psutil.process_iter(['name']):
        try:
            if "raaga" in (p.info['name'] or '').lower():
                raaga_running = True
                break
        except Exception:
            pass

    target = RAAGA_APP_PATH if os.path.exists(RAAGA_APP_PATH) else "raaga"
    try:
        if not raaga_running:
            subprocess.Popen(f'start "" "{target}"', shell=True)
            time.sleep(1.8)  # allow app window to initialize
        else:
            subprocess.run(["powershell", "-NoProfile", "-Command", "$wshell = New-Object -ComObject wscript.shell; $wshell.AppActivate('raaga')"], capture_output=True)
            time.sleep(0.3)

        # Trigger play via Win32 media key
        VK_MEDIA_PLAY_PAUSE = 0xB3
        ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 2, 0)

        detail = f" for '{query}'" if query and query.lower() not in ("good songs", "music", "songs") else ""
        return f"Opening Raaga app and playing music{detail}."
    except Exception as exc:
        return f"Couldn't start music in Raaga app: {exc}"


def get_battery_status(memory) -> str:
    """Check laptop battery percentage, power plug, and time remaining."""
    try:
        battery = psutil.sensors_battery()
        if battery is None:
            return "No battery detected (system is operating on direct AC power)."

        pct = round(battery.percent)
        plugged = battery.power_plugged
        charging_str = "plugged in and charging" if plugged else "running on battery power"

        if not plugged and battery.secsleft > 0 and battery.secsleft != psutil.POWER_TIME_UNLIMITED:
            hrs = battery.secsleft // 3600
            mins = (battery.secsleft % 3600) // 60
            time_str = f"with approximately {hrs}h {mins}m remaining"
            return f"Battery is at {pct}%, {charging_str} ({time_str})."

        return f"Battery is at {pct}%, {charging_str}."
    except Exception as exc:
        return f"Unable to read battery status: {exc}"


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


def see_screen(memory, question: str = "") -> str:
    """Capture and analyze what is visible on the user's screen using AI vision."""
    global _VISION_CONFIG
    cfg = _VISION_CONFIG
    if not cfg:
        try:
            from .config import load_config
            cfg = load_config().get("llm")
        except Exception:
            cfg = None

    if not cfg or not cfg.get("api_key"):
        return "Screen vision requires a valid LLM API key configured in .env or config.json."

    try:
        from PIL import ImageGrab, Image
    except ImportError:
        return "Pillow library is not installed for screen capture."

    try:
        screenshot = ImageGrab.grab()
    except Exception as exc:
        return f"Could not capture screen ({exc}). Note: Screen grab requires an interactive Windows desktop session."

    try:
        max_dim = 1280
        if screenshot.width > max_dim or screenshot.height > max_dim:
            screenshot.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        screenshot.convert("RGB").save(buf, format="JPEG", quality=82)
        b64_img = base64.b64encode(buf.getvalue()).decode("utf-8")

        prompt = question.strip() if question.strip() else (
            "Describe what is currently visible on my desktop screen. "
            "Identify the active applications, documents, browser tabs, or code files open, and highlight any notable items or errors."
        )

        from openai import OpenAI
        base_url = cfg.get("base_url") or "https://generativelanguage.googleapis.com/v1beta/openai/"
        client = OpenAI(api_key=cfg["api_key"], base_url=base_url)

        resp = client.chat.completions.create(
            model=cfg.get("model", "gemini-flash-lite-latest"),
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{b64_img}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=600
        )
        ans = (resp.choices[0].message.content or "").strip()
        return ans or "Analyzed screen: No significant contents detected."
    except Exception as exc:
        return f"Error analyzing screen: {exc}"


def generate_image(memory, prompt: str) -> str:
    """Generate an image from a text prompt by driving the logged-in browser
    (Gemini web). Opens the saved image on success."""
    from . import browser
    result = browser.generate_image(prompt)
    if result and os.path.exists(result):
        try:
            os.startfile(result)  # open in the default Windows image viewer
        except Exception:
            pass
        return f"Done, Sir — generated your image and opened it: {os.path.basename(result)}."
    return result  # a readable error/status string from the browser agent


def _parse_at(at_str: str, now):
    from datetime import datetime, timedelta
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
    """Schedule a spoken reminder, either in N minutes or at a clock time."""
    from datetime import datetime, timedelta
    from .reminders import get_service
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
    from datetime import datetime
    from .reminders import get_service
    items = get_service().list_pending()
    if not items:
        return "No reminders set, Sir."
    lines = ["Pending reminders:"]
    for i in items:
        when = datetime.fromtimestamp(i["fire_ts"]).strftime("%a %H:%M")
        lines.append(f"  - {when}: {i['text']}")
    return "\n".join(lines)


def cancel_reminder(memory, which: str) -> str:
    from .reminders import get_service
    n = get_service().cancel(which)
    return f"Cancelled {n} reminder(s)." if n else f"No matching reminder for '{which}'."


def _data_dir(sub: str) -> str:
    d = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", sub)
    os.makedirs(d, exist_ok=True)
    return d


def save_screenshot(memory, open_after: bool = True) -> str:
    """Capture the whole screen to a PNG under data/screenshots and open it."""
    try:
        from PIL import ImageGrab
    except ImportError:
        return "Pillow isn't installed for screenshots."
    path = os.path.join(_data_dir("screenshots"), f"shot_{datetime.now():%Y%m%d_%H%M%S}.png")
    try:
        ImageGrab.grab().save(path)
    except Exception as exc:
        return f"Couldn't capture the screen: {exc}"
    if open_after:
        try:
            os.startfile(path)
        except Exception:
            pass
    return f"Screenshot saved to {path}."


def lock_pc(memory) -> str:
    try:
        ctypes.windll.user32.LockWorkStation()
        return "Locked the workstation, Sir."
    except Exception as exc:
        return f"Couldn't lock the PC: {exc}"


def sleep_pc(memory) -> str:
    try:
        subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        return "Putting the system to sleep, Sir."
    except Exception as exc:
        return f"Couldn't sleep the system: {exc}"


def set_brightness(memory, level: int) -> str:
    try:
        level = max(0, min(int(level), 100))
    except (ValueError, TypeError):
        return "Give me a brightness level from 0 to 100."
    ps = f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{level})"
    res = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    if res.returncode == 0:
        return f"Set screen brightness to {level}%."
    return f"Couldn't set brightness (laptop display only): {res.stderr.strip()}"


def get_system_info(memory) -> str:
    import platform
    try:
        uptime = time.time() - psutil.boot_time()
        hrs, mins = int(uptime // 3600), int((uptime % 3600) // 60)
        vmem = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=0.3)
        return (f"{platform.system()} {platform.release()}, {cpu:.0f}% CPU, "
                f"{vmem.percent:.0f}% of {vmem.total / 1024**3:.1f} GB RAM in use, "
                f"up {hrs}h {mins}m.")
    except Exception as exc:
        return f"Couldn't read system info: {exc}"


def type_text(memory, text: str) -> str:
    """Type text into the currently focused window by pasting it (robust for any characters)."""
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", "$input | Set-Clipboard"],
                       input=text, text=True, capture_output=True, timeout=5)
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "$w = New-Object -ComObject wscript.shell; Start-Sleep -Milliseconds 200; $w.SendKeys('^v')"],
                       capture_output=True)
        preview = text[:60] + ("..." if len(text) > 60 else "")
        return f"Typed into the active window: \"{preview}\""
    except Exception as exc:
        return f"Couldn't type text: {exc}"


def read_file(memory, path: str, max_chars: int = 4000) -> str:
    """Read a text file so FRIDAY can look at and discuss it."""
    full = _resolve_path(path)
    if not os.path.exists(full):
        return f"There's no file at {full}."
    if os.path.isdir(full):
        return f"'{full}' is a folder — use list_folder for that."
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as fh:
            data = fh.read(max_chars + 1)
    except Exception as exc:
        return f"Couldn't read it: {exc}"
    truncated = len(data) > max_chars
    return f"Contents of {os.path.basename(full)}:\n{data[:max_chars]}" + ("\n...(truncated)" if truncated else "")


def send_to_claude(memory, prompt: str) -> str:
    """Copy a prepared prompt to the clipboard and open Claude so Jay can paste it."""
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", "$input | Set-Clipboard"],
                       input=prompt, text=True, capture_output=True, timeout=5)
    except Exception:
        pass
    _open_in_browser("https://claude.ai/new")
    return "Prompt's written and copied to your clipboard, Sir — Claude's open, just paste with Ctrl+V."


def deep_think(memory, question: str) -> str:
    """Consult a stronger model for a hard question or careful writing."""
    cfg = _VISION_CONFIG
    if not cfg:
        try:
            from .config import load_config
            cfg = load_config().get("llm")
        except Exception:
            cfg = None
    if not cfg or not cfg.get("api_key"):
        return "I can't reach my deep-thinking model right now."
    try:
        from .llm import make_client
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


def daily_briefing(memory) -> str:
    """A short spoken briefing: greeting, date/time, reminders, battery."""
    now = datetime.now()
    h = now.hour
    salut = "Good morning" if 4 <= h < 12 else "Good afternoon" if 12 <= h < 17 else "Good evening"
    parts = [f"{salut}, Sir.", now.strftime("It's %A, %d %B, %H:%M.")]
    try:
        from . import reminders
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
    from . import routines
    steps = routines.get_steps(name)
    if steps is None:
        return f"No routine called '{name}', Sir. I've got: {', '.join(routines.list_names())}."
    outputs = []
    for step in steps:
        sk = step.get("skill")
        if not sk:
            continue
        outputs.append(execute(sk, step.get("args", {}), memory))
    # If the routine included a briefing, lead with it so Rusty speaks something useful.
    brief = next((o for o in outputs if o and o.startswith(("Good morning", "Good afternoon", "Good evening"))), None)
    if brief:
        return brief
    return f"Done, Sir — {name} is set."


def list_routines(memory) -> str:
    from . import routines
    return "Routines ready to go: " + ", ".join(routines.list_names()) + "."


SKILLS = [
    {"name": "open_app", "fn": open_app, "description": "Open/launch an application (e.g. brave, chrome, notepad, calculator, explorer).",
     "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "App name"}}, "required": ["name"]}},
    {"name": "open_folder", "fn": open_folder, "description": "Open a folder in File Explorer. Accepts a full path or a shortcut: downloads, documents, desktop, pictures, home.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "close_app", "fn": close_app, "description": "Close/terminate an application by name or window title (e.g. notepad, chrome, brave, spotify, calculator).",
     "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "Application or process name"}}, "required": ["name"]}},
    {"name": "close_other_windows", "fn": close_other_windows, "description": "Close all open user application windows EXCEPT the ones specified in keep (e.g. keep=['browser', 'antigravity']).",
     "parameters": {"type": "object", "properties": {"keep": {"type": "array", "items": {"type": "string"}, "description": "List of window titles or app names to keep open"}}, "required": ["keep"]}},
    {"name": "close_browser_tab", "fn": close_browser_tab, "description": "Close the active tab in the browser (Ctrl+W).",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "close_active_window", "fn": close_active_window, "description": "Close the currently active window (Alt+F4).",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "list_running_apps", "fn": list_running_apps, "description": "List all currently open user application windows and running programs.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "volume_up", "fn": volume_up, "description": "Increase system hardware volume (steps=5 by default, each step is ~2%).",
     "parameters": {"type": "object", "properties": {"steps": {"type": "integer", "description": "Number of volume steps to increase (default 5)"}}, "required": []}},
    {"name": "volume_down", "fn": volume_down, "description": "Decrease system hardware volume (steps=5 by default, each step is ~2%).",
     "parameters": {"type": "object", "properties": {"steps": {"type": "integer", "description": "Number of volume steps to decrease (default 5)"}}, "required": []}},
    {"name": "volume_mute", "fn": volume_mute, "description": "Toggle master audio mute / unmute.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "media_play_pause", "fn": media_play_pause, "description": "Play or pause current media (Spotify, YouTube, media player).",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "media_next", "fn": media_next, "description": "Skip to the next media song/track.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "media_previous", "fn": media_previous, "description": "Return to the previous media song/track.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "play_music", "fn": play_music, "description": "Open Jay's Raaga music app from desktop and start playing songs or good music.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "Optional song, artist or playlist query"}}, "required": []}},
    {"name": "get_battery_status", "fn": get_battery_status, "description": "Check laptop battery percentage and whether it is charging or running on battery.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_clipboard", "fn": read_clipboard, "description": "Read text currently copied to the Windows clipboard.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "write_clipboard", "fn": write_clipboard, "description": "Copy specified text to the Windows clipboard.",
     "parameters": {"type": "object", "properties": {"text": {"type": "string", "description": "Text to copy to clipboard"}}, "required": ["text"]}},
    {"name": "see_screen", "fn": see_screen, "description": "Inspect and analyze what is currently visible on the user's screen or open windows using AI vision.",
     "parameters": {"type": "object", "properties": {"question": {"type": "string", "description": "Specific question or request about what is on screen"}}, "required": []}},
    {"name": "generate_image", "fn": generate_image, "description": "Generate / create / draw a picture or image from a text description, using the browser (Gemini web). Use whenever Jay asks to make, create, draw, or generate an image, picture, art, or wallpaper.",
     "parameters": {"type": "object", "properties": {"prompt": {"type": "string", "description": "Detailed description of the image to generate"}}, "required": ["prompt"]}},
    {"name": "set_reminder", "fn": set_reminder, "description": "Set a timed reminder that FRIDAY will speak aloud when due. Give either minutes (relative, e.g. 'in 20 minutes') or at (a clock time like '17:30' or '5pm').",
     "parameters": {"type": "object", "properties": {"text": {"type": "string", "description": "What to remind Jay about"}, "minutes": {"type": "number", "description": "Fire this many minutes from now"}, "at": {"type": "string", "description": "Clock time to fire at, e.g. '17:30' or '5pm'"}}, "required": ["text"]}},
    {"name": "list_reminders", "fn": list_reminders, "description": "List all pending reminders.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "cancel_reminder", "fn": cancel_reminder, "description": "Cancel a pending reminder by its id or by a word from its text.",
     "parameters": {"type": "object", "properties": {"which": {"type": "string", "description": "Reminder id or a substring of its text"}}, "required": ["which"]}},
    {"name": "save_screenshot", "fn": save_screenshot, "description": "Capture a screenshot of the whole screen, save it to data/screenshots, and open it.",
     "parameters": {"type": "object", "properties": {"open_after": {"type": "boolean", "description": "Open the image after saving (default true)"}}, "required": []}},
    {"name": "lock_pc", "fn": lock_pc, "description": "Lock the Windows workstation (lock screen).",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "sleep_pc", "fn": sleep_pc, "description": "Put the computer to sleep. Only when Jay clearly asks to sleep/suspend the PC.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "set_brightness", "fn": set_brightness, "description": "Set the laptop screen brightness to a level from 0 to 100 percent.",
     "parameters": {"type": "object", "properties": {"level": {"type": "integer", "description": "Brightness percentage 0-100"}}, "required": ["level"]}},
    {"name": "get_system_info", "fn": get_system_info, "description": "Report OS, CPU load, RAM usage, and system uptime.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "type_text", "fn": type_text, "description": "Type/paste the given text into whatever window is currently focused.",
     "parameters": {"type": "object", "properties": {"text": {"type": "string", "description": "The text to type into the active window"}}, "required": ["text"]}},
    {"name": "read_file", "fn": read_file, "description": "Read a text/code file so you can look at it and discuss or review it (e.g. downloads/notes.txt or a full path).",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "File path or shortcut"}}, "required": ["path"]}},
    {"name": "send_to_claude", "fn": send_to_claude, "description": "After writing a well-structured prompt for Claude, call this with the full prompt text — it copies it to the clipboard and opens Claude so Jay can paste it.",
     "parameters": {"type": "object", "properties": {"prompt": {"type": "string", "description": "The complete prompt text to hand to Claude"}}, "required": ["prompt"]}},
    {"name": "deep_think", "fn": deep_think, "description": "Consult a stronger model for a hard question, tricky reasoning, or careful writing, then relay the answer in your own voice.",
     "parameters": {"type": "object", "properties": {"question": {"type": "string", "description": "The question or task to think hard about"}}, "required": ["question"]}},
    {"name": "daily_briefing", "fn": daily_briefing, "description": "Give Jay a short spoken daily briefing (greeting, date/time, pending reminders, battery). Use for 'good morning', 'brief me', 'what's my day'.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "run_routine", "fn": run_routine, "description": "Run a saved multi-step routine by name — e.g. 'start my day', 'focus mode', 'wind down'. Use whenever Jay names a routine or says things like 'start my day' / 'let's focus' / 'wind down'.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "The routine name"}}, "required": ["name"]}},
    {"name": "list_routines", "fn": list_routines, "description": "List the available routines.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "delete_file", "fn": delete_file, "description": "Delete a file. By default, safely moves it to the Windows Recycle Bin so it can be restored.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "File path or shortcut (e.g. downloads/test.txt)"}, "permanent": {"type": "boolean", "description": "If true, permanently delete instead of moving to Recycle Bin (default false)"}}, "required": ["path"]}},
    {"name": "delete_folder", "fn": delete_folder, "description": "Delete a folder. By default, safely moves it to the Windows Recycle Bin.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Folder path or shortcut (e.g. downloads/old_dir)"}, "permanent": {"type": "boolean", "description": "If true, permanently delete instead of moving to Recycle Bin (default false)"}}, "required": ["path"]}},
    {"name": "list_folder", "fn": list_folder, "description": "List files and subfolders in a directory (e.g. downloads, desktop, documents).",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Folder path or shortcut (default: downloads)"}}, "required": []}},
    {"name": "empty_recycle_bin", "fn": empty_recycle_bin, "description": "Empty the Windows Recycle Bin.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "web_search", "fn": web_search, "description": "Search Google in the browser.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "open_url", "fn": open_url, "description": "Open a specific URL in the browser.",
     "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
    {"name": "open_youtube", "fn": open_youtube, "description": "Open YouTube, optionally searching for something.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "Optional search terms"}}, "required": []}},
    {"name": "save_link", "fn": save_link, "description": "Save a named link/shortcut for later (e.g. a Google Meet link).",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "url": {"type": "string"}}, "required": ["name", "url"]}},
    {"name": "open_saved_link", "fn": open_saved_link, "description": "Open a link previously saved with save_link, by its name.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "list_saved_links", "fn": list_saved_links, "description": "List all saved named links.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "remember", "fn": remember, "description": "Store a long-term fact about the user, remembered across future sessions.",
     "parameters": {"type": "object", "properties": {"fact": {"type": "string"}}, "required": ["fact"]}},
    {"name": "set_my_name", "fn": set_my_name, "description": "Set what the user wants to be called.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "save_note", "fn": save_note, "description": "Save a quick note/reminder for the user.",
     "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "list_notes", "fn": list_notes, "description": "List all saved notes.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "get_datetime", "fn": get_datetime, "description": "Get the current date and time.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
]

_BY_NAME = {s["name"]: s for s in SKILLS}


def execute(name: str, args: dict, memory) -> str:
    skill = _BY_NAME.get(name)
    if not skill:
        return f"(unknown skill: {name})"
    try:
        return skill["fn"](memory, **(args or {}))
    except TypeError as exc:
        return f"(bad arguments for {name}: {exc})"
    except Exception as exc:  # a skill failing must never crash VYRA
        return f"(error running {name}: {exc})"


def tool_schemas() -> list:
    """Neutral tool schemas (name/description/parameters) for the LLM layer."""
    return [{"name": s["name"], "description": s["description"], "parameters": s["parameters"]} for s in SKILLS]
