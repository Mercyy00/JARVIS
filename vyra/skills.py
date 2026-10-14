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
import inspect
import io
import os
import re
import shutil
import subprocess
import time
import webbrowser
from datetime import datetime
from urllib.parse import quote_plus

import psutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from . import office_skills as _office

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


PROTECTED_PATH_PATTERNS = [
    r"\\windows\\system32\\config",
    r"\\windows\\system32\\drivers\\etc\\hosts",
    r"\.env($|\.)",
    r"id_rsa($|\.)",
    r"id_ed25519($|\.)",
    r"\.pem$",
    r"\\user data\\default\\(cookies|login data|web data)",
]


def is_path_safe(resolved_path: str) -> bool:
    norm = os.path.normpath(resolved_path).lower()
    for pat in PROTECTED_PATH_PATTERNS:
        if re.search(pat, norm):
            return False
    return True


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


def see_screen(memory, question: str = "", progress_callback=None) -> str:
    """Capture and analyze what is visible on the user's screen using AI vision."""
    if progress_callback:
        progress_callback("Capturing screen display and analyzing visual details, Sir...", speak=True)
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

    screenshot = None
    try:
        from PIL import ImageGrab, Image
        screenshot = ImageGrab.grab()
    except Exception:
        pass

    if screenshot is None:
        try:
            import mss
            from PIL import Image
            with mss.MSS() as s:
                shot = s.grab(s.monitors[1] if len(s.monitors) > 1 else s.monitors[0])
                screenshot = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
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
        client = OpenAI(api_key=cfg["api_key"], base_url=base_url, timeout=35.0)

        models_to_try = [cfg.get("model", "gemini-flash-lite-latest")]
        for m in ["gemini-1.5-flash", "gemini-2.0-flash"]:
            if m not in models_to_try:
                models_to_try.append(m)

        last_exc = None
        for vis_model in models_to_try:
            try:
                resp = client.chat.completions.create(
                    model=vis_model,
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
            except Exception as e:
                last_exc = e
                err_s = str(e).lower()
                if any(x in err_s for x in ("503", "429", "404", "400", "not supported", "invalid")):
                    continue
                break
        return f"Error analyzing screen: {last_exc}"
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


def open_file(memory, path: str) -> str:
    """Open a file on Jay's computer with its default application or browser.
    Accepts full paths, relative paths, or names of files created under Desktop/Rusty."""
    if not path or not path.strip():
        return "Please specify which file you would like me to open, Sir."
    raw = path.strip().strip('"').strip("'")
    full = _resolve_path(raw)

    # If not found directly, search Desktop/Rusty subdirectories (documents, presentations, sheets, projects)
    if not os.path.exists(full):
        rusty_base = os.path.join(os.path.expandvars(r"%USERPROFILE%\Desktop"), "Rusty")
        if os.path.exists(rusty_base):
            target_name = os.path.basename(raw).lower()
            for root, _, files in os.walk(rusty_base):
                for f in files:
                    if f.lower() == target_name or f.lower().startswith(target_name):
                        full = os.path.join(root, f)
                        break
                if os.path.exists(full):
                    break

    if not os.path.exists(full):
        return f"I couldn't locate '{path}' on your system, Sir."

    if not is_path_safe(full):
        return f"Access denied: '{os.path.basename(full)}' is protected for security, Sir."

    from .office_skills import _open
    opened = _open(full)
    if opened:
        return f"Opened '{os.path.basename(full)}' for you, Sir."
    return f"Located '{os.path.basename(full)}', but could not launch a viewer on Windows."


def switch_mode(memory, mode: str) -> str:
    """Switch Rusty's operational mode between 'tactical', 'engineer', and 'ghost'.
    Tactical: Military/Stark brevity, fast assistance, spoken replies.
    Engineer: Senior Software Architect, deep reasoning, code generation, terminal/git mastery.
    Ghost: Silent stealth focus mode, muted voice narration, pure HUD visual streaming."""
    clean = str(mode or "").strip().lower()
    if clean in ("stealth", "silent"):
        clean = "ghost"
    if clean not in ("tactical", "engineer", "ghost"):
        return f"Unknown mode '{mode}'. Available modes are: tactical, engineer, ghost."

    try:
        from .config import load_config, save_config
        cfg = load_config()
        if "assistant" not in cfg:
            cfg["assistant"] = {}
        cfg["assistant"]["mode"] = clean
        save_config(cfg)
    except Exception:
        pass

    try:
        from . import gui_server
        gui_server.set_active_mode(clean)
    except Exception:
        pass

    if clean == "tactical":
        return "Tactical mode engaged, Sir. Fast, high-readiness operational protocol active."
    elif clean == "engineer":
        return "Engineer mode engaged, Sir. Neural parameters tuned for systems architecture, code mastery, and deep technical reasoning."
    else:
        return "Ghost mode engaged, Sir. Voice audio muted — operating in silent stealth focus."


def read_file(memory, path: str, max_chars: int = 4000) -> str:
    """Read a text, PDF, Word, or presentation file so Rusty can inspect and discuss it."""
    full = _resolve_path(path)

    # If not found directly, check Desktop/Rusty
    if not os.path.exists(full):
        rusty_base = os.path.join(os.path.expandvars(r"%USERPROFILE%\Desktop"), "Rusty")
        if os.path.exists(rusty_base):
            target_name = os.path.basename(path).lower()
            for root, _, files in os.walk(rusty_base):
                for f in files:
                    if f.lower() == target_name or f.lower().startswith(target_name):
                        full = os.path.join(root, f)
                        break
                if os.path.exists(full):
                    break

    if not is_path_safe(full):
        return f"Access denied: '{os.path.basename(full)}' is protected for system security, Sir."
    if not os.path.exists(full):
        return f"There's no file at {full}."
    if os.path.isdir(full):
        return f"'{full}' is a folder — use list_folder for that."

    low = full.lower()
    # 1. PDF handling via pypdf
    if low.endswith(".pdf"):
        try:
            import pypdf
            reader = pypdf.PdfReader(full)
            text_parts = []
            for idx, page in enumerate(reader.pages):
                txt = page.extract_text() or ""
                if txt.strip():
                    text_parts.append(f"--- Page {idx + 1} ---\n{txt.strip()}")
                if sum(len(p) for p in text_parts) > max_chars:
                    break
            data = "\n\n".join(text_parts)
            if not data:
                return f"Contents of {os.path.basename(full)}: (empty or scanned image PDF without extractable text)"
        except Exception as exc:
            return f"Error reading PDF '{os.path.basename(full)}': {exc}"
    # 2. Word handling (.docx)
    elif low.endswith(".docx"):
        try:
            import docx
            doc = docx.Document(full)
            paras = [p.text for p in doc.paragraphs if p.text.strip()]
            data = "\n".join(paras)
        except Exception as exc:
            return f"Error reading Word document '{os.path.basename(full)}': {exc}"
    # 3. PowerPoint handling (.pptx)
    elif low.endswith(".pptx"):
        try:
            import pptx
            prs = pptx.Presentation(full)
            slide_texts = []
            for idx, slide in enumerate(prs.slides, 1):
                bullets = []
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        for p in shape.text_frame.paragraphs:
                            if p.text.strip():
                                bullets.append(p.text.strip())
                if bullets:
                    slide_texts.append(f"Slide {idx}:\n" + "\n".join(f"  • {b}" for b in bullets))
            data = "\n\n".join(slide_texts)
        except Exception as exc:
            return f"Error reading PowerPoint presentation '{os.path.basename(full)}': {exc}"
    # 4. Standard text/code file
    else:
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


DANGEROUS_COMMANDS = [
    r"\bformat\s+[a-z]:",
    r"\bdiskpart\b",
    r"\bbcdedit\b",
    r"rmdir\s+/[sq]\s+[a-z]:\\?$",
    r"del\s+/[fsq]+\s+[a-z]:\\?$",
    r"remove-item\s+.*-(recurse|force)\s+[a-z]:\\?$",
]


def run_terminal_command(memory, command: str, progress_callback=None) -> str:
    """Execute a PowerShell or CMD command directly on Jay's computer and return output."""
    if progress_callback:
        progress_callback("Executing terminal command on system, Sir...", speak=False)
    cmd_lower = command.lower().strip()
    for pat in DANGEROUS_COMMANDS:
        if re.search(pat, cmd_lower):
            return "Command execution blocked: Command matches destructive drive or partition patterns, Sir. Please run critical disk operations manually."

    try:
        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(ROOT)
        )
        try:
            out, err = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            return f"Command timed out after 30 seconds, Sir.\nPartial output:\n{(out or '')[:1000]}"

        out = (out or "").strip()
        err = (err or "").strip()
        combined = out
        if err:
            combined = (combined + "\n[STDERR]: " + err).strip() if combined else f"[STDERR]: {err}"
        if not combined:
            return f"Command executed successfully (exit code {proc.returncode}) with no output."
        if len(combined) > 2500:
            combined = combined[:2500] + "\n...[output truncated]"
        return f"Output:\n{combined}"
    except Exception as exc:
        return f"Error executing command: {exc}"


def inspect_active_window(memory) -> str:
    """Identify which application and document window is currently active/focused on screen."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "No active foreground window detected, Sir."

        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value

        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        pname = "Unknown"
        try:
            pname = psutil.Process(pid.value).name()
        except Exception:
            pass

        return f"Active Application: {pname} (PID: {pid.value})\nWindow Title: '{title or '(Untitled)'}'"
    except Exception as exc:
        return f"Could not inspect active window: {exc}"


def delete_link(memory, name: str) -> str:
    """Delete a saved shortcut link from memory."""
    ok = memory.delete_link(name)
    return f"Removed the link for '{name}', Sir." if ok else f"I couldn't find a saved link named '{name}', Sir."


def forget_fact(memory, fact: str) -> str:
    """Remove a fact or detail from long-term memory about Jay."""
    ok = memory.delete_about(fact)
    return f"Understood, Sir — I've removed that from my memory." if ok else f"I couldn't find any memory matching '{fact}', Sir."


def delete_note(memory, query: str) -> str:
    """Delete a note from memory."""
    ok = memory.delete_note(query)
    return f"Deleted matching note, Sir." if ok else f"No note matching '{query}' found to delete, Sir."


def press_hotkey(memory, combo: str) -> str:
    """Press a keyboard shortcut/hotkey (e.g. 'ctrl+c', 'ctrl+v', 'alt+tab', 'win+d', 'enter', 'esc')."""
    combo = combo.strip().lower()
    sendkeys_map = {
        "ctrl+c": "^c", "ctrl+v": "^v", "ctrl+x": "^x", "ctrl+z": "^z", "ctrl+y": "^y",
        "ctrl+a": "^a", "ctrl+s": "^s", "ctrl+w": "^w", "ctrl+t": "^t", "ctrl+f": "^f",
        "alt+f4": "%{F4}", "alt+tab": "%{TAB}", "enter": "{ENTER}", "esc": "{ESC}",
        "escape": "{ESC}", "space": " ", "tab": "{TAB}", "backspace": "{BACKSPACE}",
        "delete": "{DELETE}"
    }
    try:
        if combo in ("win+d", "windows+d"):
            subprocess.run(["powershell", "-NoProfile", "-Command", "(New-Object -ComObject Shell.Application).ToggleDesktop()"], capture_output=True)
            return "Toggled show desktop."
        if combo in ("win+e", "windows+e"):
            subprocess.run(["explorer.exe"], capture_output=True)
            return "Opened File Explorer."
        
        sk = sendkeys_map.get(combo)
        if not sk:
            parts = combo.split("+")
            sk_parts = []
            for p in parts:
                p = p.strip()
                if p in ("ctrl", "control"): sk_parts.append("^")
                elif p == "alt": sk_parts.append("%")
                elif p == "shift": sk_parts.append("+")
                elif p in ("enter", "return"): sk_parts.append("{ENTER}")
                elif p in ("esc", "escape"): sk_parts.append("{ESC}")
                elif p == "tab": sk_parts.append("{TAB}")
                elif len(p) == 1: sk_parts.append(p)
                else: sk_parts.append(f"{{{p.upper()}}}")
            sk = "".join(sk_parts)
            
        ps_code = f"$w = New-Object -ComObject wscript.shell; Start-Sleep -Milliseconds 100; $w.SendKeys('{sk}')"
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_code], capture_output=True)
        return f"Pressed '{combo}'."
    except Exception as exc:
        return f"Failed to press hotkey: {exc}"


def click_mouse(memory, x: int = None, y: int = None, button: str = "left", double: bool = False) -> str:
    """Click or double-click the mouse at specified coordinates (x, y) or at current cursor."""
    try:
        user32 = ctypes.windll.user32
        if x is not None and y is not None:
            user32.SetCursorPos(int(x), int(y))
            time.sleep(0.05)
        btn = button.lower()
        if btn == "right":
            down, up = 0x0008, 0x0010
        else:
            down, up = 0x0002, 0x0004
            
        user32.mouse_event(down, 0, 0, 0, 0)
        user32.mouse_event(up, 0, 0, 0, 0)
        if double:
            time.sleep(0.08)
            user32.mouse_event(down, 0, 0, 0, 0)
            user32.mouse_event(up, 0, 0, 0, 0)
        loc_str = f"at ({x}, {y})" if x is not None and y is not None else "at current cursor"
        act_str = f"Double-clicked {btn} button" if double else f"Clicked {btn} button"
        return f"{act_str} {loc_str}."
    except Exception as exc:
        return f"Failed to click mouse: {exc}"


def write_file(memory, path: str, content: str) -> str:
    """Create or write content to a text or code file."""
    try:
        full_path = _resolve_path(path)
        if not is_path_safe(full_path):
            return f"Access denied: '{os.path.basename(full_path)}' is in a protected path, Sir."
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Saved file to '{full_path}' ({len(content)} characters)."
    except Exception as exc:
        return f"Failed to write file: {exc}"


def search_files(memory, query: str, folder: str = "D:\\engineers\\JAY", progress_callback=None) -> str:
    """Search for files and directories matching query name."""
    if progress_callback:
        progress_callback(f"Scanning storage directories for '{query}', Sir...", speak=False)
    try:
        root_dir = _resolve_path(folder)
        if not os.path.exists(root_dir):
            root_dir = "D:\\engineers\\JAY"
            if not os.path.exists(root_dir):
                root_dir = os.path.expanduser("~")
        matches = []
        q_lower = query.lower()
        for root, dirs, files in os.walk(root_dir):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', '__pycache__', 'venv', '.venv')]
            for f in files:
                if q_lower in f.lower():
                    matches.append(os.path.join(root, f))
                    if len(matches) >= 15:
                        break
            if len(matches) >= 15:
                break
        if not matches:
            return f"No files found matching '{query}' in {root_dir}."
        res = [f"Found {len(matches)} match(es) for '{query}':"]
        for m in matches:
            res.append(f"  - {m}")
        return "\n".join(res)
    except Exception as exc:
        return f"Error searching files: {exc}"


def send_whatsapp_message(memory, phone: str = "", message: str = "", open_chat: bool = True) -> str:
    """Send a WhatsApp TEXT message. Defaults to Jay's own number when none given.
    (Text only — to send a FILE to his phone, use send_file_to_phone / Telegram.)"""
    import urllib.parse
    phone_clean = re.sub(r'[^0-9+]', '', phone or "").strip()
    if not phone_clean:
        try:
            from .config import load_config
            phone_clean = re.sub(r'[^0-9+]', '', str(load_config().get("user", {}).get("whatsapp", "")))
        except Exception:
            phone_clean = ""
    if phone_clean and not phone_clean.startswith("+") and len(phone_clean) == 10:
        phone_clean = "91" + phone_clean
    encoded_msg = urllib.parse.quote(message or "")
    if phone_clean:
        url = f"https://web.whatsapp.com/send?phone={phone_clean}&text={encoded_msg}"
    else:
        url = f"https://web.whatsapp.com/send?text={encoded_msg}" if message else "https://web.whatsapp.com"
    _open_in_browser(url)
    return f"Opened WhatsApp to {phone_clean or 'WhatsApp'}, Sir — your message is ready, just tap send."


def mobile_phone_gateway(memory, action: str = "status") -> str:
    """Get the local network URL and setup info so Jay can control JARVIS directly from his phone."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "192.168.31.12"
    pin = ""
    try:
        from .config import load_config
        pin = str(load_config().get("remote", {}).get("pin", "") or "")
    except Exception:
        pass
    url = f"http://{local_ip}:8765" + (f"/?pin={pin}" if pin else "")
    return (
        f"Sir, your mobile phone gateway is ready!\n"
        f"Connect your phone to the same Wi-Fi network and open:\n"
        f"-> {url}\n"
        + (f"PIN: {pin}\n" if pin else "(No PIN set — remote access is disabled for safety.)\n")
        + f"\nFrom your phone you can:\n"
        f"1. Tap the mic to speak to me anywhere in your room.\n"
        f"2. Type commands and chat in real time.\n"
        f"3. Trigger any PC skill, run code, or view system status."
    )


def web_answer(memory, query: str, progress_callback=None) -> str:
    """Look something up and answer concisely — Wikipedia for facts, with the
    model's own knowledge as backup. Use for 'what/who is', facts, definitions."""
    if progress_callback:
        progress_callback(f"Researching '{query[:40]}' across knowledge sources, Sir...", speak=True)
    import urllib.request
    import urllib.parse
    import json
    context = ""
    try:
        s = ("https://en.wikipedia.org/w/api.php?action=query&list=search&format=json"
             "&srlimit=1&srsearch=" + urllib.parse.quote(query))
        sr = json.loads(urllib.request.urlopen(
            urllib.request.Request(s, headers={"User-Agent": "RustyAI/1.0"}), timeout=8).read())
        hits = sr.get("query", {}).get("search", [])
        if hits:
            title = hits[0]["title"].replace(" ", "_")
            su = "https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title)
            sd = json.loads(urllib.request.urlopen(
                urllib.request.Request(su, headers={"User-Agent": "RustyAI/1.0"}), timeout=8).read())
            context = (sd.get("extract") or "")[:2000]
    except Exception:
        context = ""
    cfg = _VISION_CONFIG
    if not cfg:
        try:
            from .config import load_config
            cfg = load_config().get("llm")
        except Exception:
            cfg = None
    if not cfg or not cfg.get("api_key"):
        return context[:400] if context else "I couldn't look that up right now, Sir."
    try:
        from .llm import make_client
        client = make_client({"llm": cfg})
        sysmsg = ("You are Rusty. Answer in one or two spoken sentences. Use the reference if provided; "
                  "otherwise answer from your own knowledge. Be accurate and concise.")
        user = f"Question: {query}" + (f"\n\nReference:\n{context}" if context else "")
        resp = client.complete(sysmsg, [{"role": "user", "content": user}], [])
        return (resp.text or "").strip() or (context[:400] if context else "I'm not certain on that one, Sir.")
    except Exception:
        return context[:400] if context else "I couldn't look that up right now, Sir."


def send_file_to_phone(memory, path: str) -> str:
    """Send a file (or every file in a folder) from the PC to Jay's Telegram chat."""
    try:
        from .config import load_config
        rc = load_config().get("remote", {})
    except Exception:
        rc = {}
    token, chat_id = rc.get("telegram_token", ""), rc.get("telegram_chat_id", "")
    if not token or not chat_id:
        return "Telegram isn't linked yet, Sir — set it up first."
    try:
        import requests
    except Exception:
        return "The requests library isn't available to upload files, Sir."
    full = _resolve_path(path)
    if not os.path.exists(full):
        return f"I couldn't find '{path}', Sir."
    if os.path.isdir(full):
        targets = [os.path.join(full, f) for f in sorted(os.listdir(full))
                   if os.path.isfile(os.path.join(full, f))][:10]
    else:
        targets = [full]
    if not targets:
        return f"Nothing to send in '{path}', Sir."
    sent, skipped = 0, 0
    for fp in targets:
        try:
            if not is_path_safe(fp):
                skipped += 1
                continue
            if os.path.getsize(fp) > 49 * 1024 * 1024:
                skipped += 1
                continue
            with open(fp, "rb") as fh:
                r = requests.post(
                    f"https://api.telegram.org/bot{token}/sendDocument",
                    data={"chat_id": chat_id},
                    files={"document": (os.path.basename(fp), fh)},
                    timeout=180,
                )
            if r.ok and r.json().get("ok"):
                sent += 1
            else:
                skipped += 1
        except Exception:
            skipped += 1
    if sent:
        extra = f" ({skipped} skipped — too big or failed)" if skipped else ""
        return f"Sent {sent} file(s) to your Telegram, Sir.{extra}"
    return "Couldn't send that, Sir — the file may be too large (50 MB limit) or the upload failed."


def backup_to_drive(memory, path: str, dest: str = "") -> str:
    """Back up a file or folder to Google Drive via rclone, so Jay can reach it
    anywhere. He names what to back up; it goes under the configured base folder."""
    try:
        from .config import load_config
        dc = load_config().get("drive", {})
    except Exception:
        dc = {}
    rclone = dc.get("rclone_path", "rclone")
    remote = dc.get("remote", "gdrive")
    base = dc.get("base_folder", "RustyBackup")
    full = _resolve_path(path)
    if not os.path.exists(full):
        return f"I couldn't find '{path}', Sir."
    name = dest or os.path.basename(full.rstrip("/\\")) or "misc"
    try:
        if os.path.isdir(full):
            cmd = [rclone, "copy", full, f"{remote}:{base}/{name}", "--transfers=4"]
        else:
            cmd = [rclone, "copyto", full, f"{remote}:{base}/{os.path.basename(full)}"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if res.returncode == 0:
            return f"Backed up '{os.path.basename(full)}' to your Drive ({base}/{name}), Sir — reachable from anywhere now."
        err = (res.stderr or "").strip()
        if "didn't find section" in err.lower() or "couldn't find" in err.lower() or not err:
            return "Google Drive isn't linked yet, Sir — run 'rclone config' once to connect your account."
        return f"Backup had an issue, Sir: {err[:300]}"
    except FileNotFoundError:
        return "I need rclone installed to reach Google Drive, Sir — it's not set up yet."
    except Exception as exc:
        return f"Backup failed, Sir: {exc}"


def github(memory, command: str, confirm: bool = False) -> str:
    """Run a GitHub CLI (gh) command to manage Jay's GitHub — repos, issues, PRs,
    releases, gists, actions, `api` calls, etc. Compose the gh subcommand (without
    the leading 'gh'). Destructive commands are held back until confirm=True."""
    import shlex
    cmd = (command or "").strip()
    if cmd.lower().startswith("gh "):
        cmd = cmd[3:].strip()
    if not cmd:
        return "What GitHub command would you like, Sir?"
    if (not confirm) and any(d in cmd.lower() for d in ("delete", "destroy", "archive")):
        return f"That GitHub command looks destructive, Sir — confirm and I'll run it: gh {cmd}"
    try:
        args = ["gh"] + shlex.split(cmd)
    except Exception:
        args = ["gh"] + cmd.split()
    try:
        res = subprocess.run(args, capture_output=True, text=True, timeout=90, cwd=ROOT)
        out = (res.stdout or "").strip() or (res.stderr or "").strip()
        if "not logged" in out.lower() or "gh auth login" in out.lower():
            return "GitHub isn't linked yet, Sir — connect your account first (I need a token)."
        if len(out) > 1500:
            out = out[:1500] + " …(truncated)"
        return out or "Done, Sir."
    except FileNotFoundError:
        return "The GitHub CLI (gh) isn't installed, Sir."
    except subprocess.TimeoutExpired:
        return "That GitHub command took too long, Sir."
    except Exception as exc:
        return f"GitHub command failed, Sir: {exc}"


SKILLS = [
    {"name": "run_terminal_command", "fn": run_terminal_command, "description": "Execute a PowerShell/terminal command on Jay's computer and return output. Use for git, python, npm, system checks, script execution, inspecting files, or diagnostics.",
     "parameters": {"type": "object", "properties": {"command": {"type": "string", "description": "The PowerShell or CMD command to execute"}}, "required": ["command"]}},
    {"name": "press_hotkey", "fn": press_hotkey, "description": "Press a keyboard shortcut/hotkey combo on Windows (e.g. 'ctrl+c', 'ctrl+v', 'alt+tab', 'win+d', 'enter', 'esc').",
     "parameters": {"type": "object", "properties": {"combo": {"type": "string", "description": "Key combination like 'ctrl+v', 'alt+tab', 'win+d', 'enter'"}}, "required": ["combo"]}},
    {"name": "click_mouse", "fn": click_mouse, "description": "Click or double-click the mouse at specified coordinates (x, y) or at current cursor position.",
     "parameters": {"type": "object", "properties": {"x": {"type": "integer", "description": "X coordinate on screen"}, "y": {"type": "integer", "description": "Y coordinate on screen"}, "button": {"type": "string", "description": "'left' or 'right'"}, "double": {"type": "boolean", "description": "True for double click"}}, "required": []}},
    {"name": "write_file", "fn": write_file, "description": "Create or write content to a text or code file on Jay's computer.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "File path (relative or absolute)"}, "content": {"type": "string", "description": "Text or code content to write"}}, "required": ["path", "content"]}},
    {"name": "search_files", "fn": search_files, "description": "Search for files and folders by name across Jay's workspace or specified directory.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "Filename substring or extension to find"}, "folder": {"type": "string", "description": "Root directory to search (default D:\\engineers\\JAY)"}}, "required": ["query"]}},
    {"name": "send_whatsapp_message", "fn": send_whatsapp_message, "description": "Send a WhatsApp TEXT message. Use ONLY when Jay explicitly says 'WhatsApp'. Text only — it cannot attach files. If no number is given it goes to Jay's own number. To send a FILE to his phone, do NOT use this — use send_file_to_phone.",
     "parameters": {"type": "object", "properties": {"phone": {"type": "string", "description": "Optional phone number with country code; leave empty to message Jay himself"}, "message": {"type": "string", "description": "Message text to send"}}, "required": ["message"]}},
    {"name": "mobile_phone_gateway", "fn": mobile_phone_gateway, "description": "Get the mobile connection URL so Jay can control JARVIS directly from his phone browser over Wi-Fi.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
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
    {"name": "read_file", "fn": read_file, "description": "Read a text, code, PDF, Word (.docx), or PowerPoint (.pptx) file so you can inspect and discuss or review it (e.g. desktop/Rusty/documents/python_tips.pdf or downloads/notes.txt).",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "File path, filename, or shortcut"}}, "required": ["path"]}},
    {"name": "open_file", "fn": open_file, "description": "Open a document, PDF, presentation, spreadsheet, code, or file with its default viewer or browser on Windows. Searches Desktop\\Rusty automatically if only given a filename.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Path or name of the file to open (e.g. 'python_tips.pdf', 'World_Dog_Proposal.docx')"}}, "required": ["path"]}},
    {"name": "switch_mode", "fn": switch_mode, "description": "Switch Rusty's operational mode between 'tactical' (fast, military brevity, spoken), 'engineer' (senior software architect, deep code & reasoning), and 'ghost' (silent stealth focus, voice muted).",
     "parameters": {"type": "object", "properties": {"mode": {"type": "string", "enum": ["tactical", "engineer", "ghost"], "description": "Target mode to switch to"}}, "required": ["mode"]}},
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
    {"name": "web_search", "fn": web_search, "description": "Open a Google search in the browser (visual). For a spoken answer, prefer web_answer.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "web_answer", "fn": web_answer, "description": "Search the web and give Jay a concise spoken answer. Use for current events, facts, prices, 'what is / who is / latest', or anything you're unsure about — don't guess, look it up.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "What to look up"}}, "required": ["query"]}},
    {"name": "send_file_to_phone", "fn": send_file_to_phone, "description": "Send a file (or all files in a folder) from the PC to Jay's phone via Telegram. Use whenever Jay asks you to send/share/get a file to his phone or Telegram (e.g. 'send me resume.pdf', 'send me the files in downloads').",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "File or folder path/shortcut (e.g. 'downloads/resume.pdf' or 'downloads')"}}, "required": ["path"]}},
    {"name": "backup_to_drive", "fn": backup_to_drive, "description": "Back up / upload a file or folder to Jay's Google Drive (via rclone) so he can access it anywhere. Use when he says 'back up X to drive', 'upload X to my drive', 'save this to drive'.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "File or folder to back up (path or shortcut like 'downloads', 'documents', or the project folder)"}}, "required": ["path"]}},
    {"name": "create_word", "fn": _office.create_word, "description": "Create a Microsoft Word (.docx) document. BEST way: pass a `title` and a `topic` (what it should cover) and Rusty writes a full, comprehensive, multi-page document itself. Only pass `content` if you've already written the text. Use for reports, notes, study material, resumes.",
     "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "topic": {"type": "string", "description": "What the document should cover / detailed brief — Rusty writes a thorough document from this"}, "content": {"type": "string", "description": "Optional pre-written body ('#'/'##' headings, '- ' bullets, plain text, no markdown emphasis)"}, "filename": {"type": "string"}}, "required": ["title"]}},
    {"name": "create_pdf", "fn": _office.create_pdf, "description": "Create a real PDF (.pdf) — use whenever Jay asks for a PDF (never create_word for that). BEST way: pass a `title` and a `topic` and Rusty writes a full, comprehensive, multi-page document. Only pass `content` if already written.",
     "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "topic": {"type": "string", "description": "What the PDF should cover / detailed brief — Rusty writes a thorough document from this"}, "content": {"type": "string", "description": "Optional pre-written body"}, "filename": {"type": "string"}}, "required": ["title"]}},
    {"name": "create_ppt", "fn": _office.create_ppt, "description": "Create a polished, professionally-designed PowerPoint deck. Just pass a `topic` (a short brief of what the deck is about) and Rusty writes the full, well-structured, themed deck. Optionally choose a theme: midnight, slate, royal, or clean.",
     "parameters": {"type": "object", "properties": {"topic": {"type": "string", "description": "What the presentation is about (a brief, or detailed instructions)"}, "theme": {"type": "string", "description": "midnight (dark blue), slate (dark), royal (purple/gold), or clean (light). Default midnight"}, "filename": {"type": "string"}}, "required": ["topic"]}},
    {"name": "create_excel", "fn": _office.create_excel, "description": "Create an Excel (.xlsx) spreadsheet. Provide the data as CSV text (first row = headers). Use for tables, trackers, budgets, data.",
     "parameters": {"type": "object", "properties": {"title": {"type": "string", "description": "Sheet name"}, "content": {"type": "string", "description": "CSV rows; first row is the header"}, "filename": {"type": "string"}}, "required": ["title", "content"]}},
    {"name": "create_project", "fn": _office.create_project, "description": "Scaffold a code/web project by writing multiple files at once (e.g. a website). YOU write the code for each file; opens index.html if present. Use for building websites/apps or any multi-file deliverable.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "Project folder name"}, "files": {"type": "object", "description": "Map of relative filename -> file contents, e.g. {'index.html': '...', 'style.css': '...'}"}}, "required": ["name", "files"]}},
    {"name": "create_website", "fn": _office.create_website, "description": "Build a complete website from a short description and open it — THE reliable way to make a site/landing page/portfolio. Just pass a name and a description of what you want (theme, sections, style); the full HTML is generated and saved. Prefer this over create_project for websites.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "Short site name (folder)"}, "description": {"type": "string", "description": "What the site should be: purpose, sections, style/theme (e.g. 'dark-themed developer portfolio with hero, projects, contact')"}}, "required": ["name", "description"]}},
    {"name": "ask_claude_code", "fn": _office.ask_claude_code, "description": "Delegate a heavy coding/engineering task to the Claude Code CLI running on the PC (it can read/edit code in a folder and run commands). Use for complex multi-file coding, refactors, debugging, or building software.",
     "parameters": {"type": "object", "properties": {"task": {"type": "string", "description": "The full task/instructions for Claude Code"}, "folder": {"type": "string", "description": "Project folder to work in (default: the Rusty project)"}}, "required": ["task"]}},
    {"name": "github", "fn": github, "description": "Manage Jay's GitHub via the gh CLI. Pass the gh subcommand WITHOUT 'gh' — e.g. 'repo list', 'repo create myapp --private', 'issue create -R owner/repo -t Title -b Body', 'pr list', 'api user'. Use for anything GitHub.",
     "parameters": {"type": "object", "properties": {"command": {"type": "string", "description": "The gh subcommand, e.g. 'repo list --limit 10'"}, "confirm": {"type": "boolean", "description": "Set true to run a destructive command (delete/archive)"}}, "required": ["command"]}},
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
    {"name": "delete_note", "fn": delete_note, "description": "Delete a note from memory by a word or phrase from its content.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "Search text to identify the note to delete"}}, "required": ["query"]}},
    {"name": "delete_link", "fn": delete_link, "description": "Delete a saved named link/shortcut from memory.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "Name of the link to remove"}}, "required": ["name"]}},
    {"name": "forget_fact", "fn": forget_fact, "description": "Remove or forget an outdated fact from long-term memory about Jay.",
     "parameters": {"type": "object", "properties": {"fact": {"type": "string", "description": "Fact or keyword to remove from memory"}}, "required": ["fact"]}},
    {"name": "inspect_active_window", "fn": inspect_active_window, "description": "Identify which application, document, or window is currently active/focused on screen.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "export_note_to_pdf", "fn": _office.export_note_to_pdf, "description": "Export a saved note from memory into a clean, formatted PDF document and open it.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "Optional search term for the note (defaults to the most recent note)"}, "filename": {"type": "string", "description": "Optional custom filename"}}, "required": []}},
    {"name": "convert_document", "fn": _office.convert_document, "description": "Convert a text or markdown file into a formatted PDF or Word document.",
     "parameters": {"type": "object", "properties": {"source_path": {"type": "string", "description": "Path to the markdown or text file"}, "target_format": {"type": "string", "description": "'pdf' or 'docx'"}}, "required": ["source_path"]}},
    {"name": "get_datetime", "fn": get_datetime, "description": "Get the current date and time.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
]

_BY_NAME = {s["name"]: s for s in SKILLS}


def execute(name: str, args: dict, memory, progress_callback=None) -> str:
    skill = _BY_NAME.get(name)
    if not skill:
        return f"(unknown skill: {name})"
    try:
        sig = inspect.signature(skill["fn"])
        call_args = dict(args or {})
        if "progress_callback" in sig.parameters:
            call_args["progress_callback"] = progress_callback
        return skill["fn"](memory, **call_args)
    except TypeError as exc:
        return f"(bad arguments for {name}: {exc})"
    except Exception as exc:  # a skill failing must never crash VYRA
        return f"(error running {name}: {exc})"


def tool_schemas() -> list:
    """Neutral tool schemas (name/description/parameters) for the LLM layer."""
    return [{"name": s["name"], "description": s["description"], "parameters": s["parameters"]} for s in SKILLS]
