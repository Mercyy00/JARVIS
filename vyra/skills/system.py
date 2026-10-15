"""System, OS, window management, hardware and terminal execution skills for Rusty."""

from __future__ import annotations

import ctypes
import os
import platform
import re
import subprocess
import time

import psutil

from .common import (
    ROOT,
    KNOWN_BROWSERS,
    _attach_input_desktop,
    _get_user_windows,
    focus_window,
)

APP_ALIASES = {
    "files": "explorer",
    "file explorer": "explorer",
    "calculator": "calc",
    "terminal": "cmd",
    "settings": "ms-settings:",
    "browser": "brave",
}

BLOCKED_COMMAND_PATTERNS = [
    r"\bformat\s+[a-z]:",
    r"\bdiskpart\b",
    r"\bbcdedit\b",
    r"\bbootrec\b",
    r"\bvssadmin\s+delete\s+shadows\b",
    r"reg\s+delete\s+(hklm|hkcr)",
    r"set-mppreference\s+.*-disablerealtime",
    r"netsh\s+advfirewall\s+set\s+allprofiles\s+state\s+off",
    r"powershell\s+-[eE][a-zA-Z]*\s+[a-zA-Z0-9+/=]{10,}",
    r"iex\s*\(",
    r"invoke-expression",
    r"\.downloadstring\(",
    r"\.downloadfile\(",
    r"curl\s+.*\|\s*(powershell|cmd|pwsh)",
    r"wget\s+.*\|\s*(powershell|cmd|pwsh)",
    r"\bmimikatz\b",
]

DESTRUCTIVE_COMMAND_PATTERNS = [
    r"\brmdir\b",
    r"\bdel\b",
    r"\bremove-item\b",
    r"\bformat\b",
    r"git\s+reset\s+--hard",
    r"git\s+clean\s+-[a-zA-Z]*f",
    r"git\s+push\s+.*--force",
    r"git\s+branch\s+-[a-zA-Z]*D",
    r"taskkill\s+.*(/f|-f)",
    r"stop-process\s+.*-force",
    r"\bshutdown\b",
    r"\brestart-computer\b",
    r"clear-recyclebin\b",
]


def run_terminal_command(memory, command: str, confirm: bool = False, progress_callback=None) -> str:
    """Execute a PowerShell or CMD command directly on Jay's computer and return output."""
    cmd = (command or "").strip()
    if not cmd:
        return "Please specify a terminal command to execute, Sir."

    if progress_callback:
        progress_callback("Executing terminal command on system, Sir...", speak=False)
    cmd_lower = cmd.lower()

    # 1. Catastrophic/Prohibited Security Block
    for pat in BLOCKED_COMMAND_PATTERNS:
        if re.search(pat, cmd_lower):
            return "Security Policy Violation: Command contains prohibited system destruction, defense tampering, or payload execution patterns, Sir."

    # 2. Destructive Commands Require Code-Level Confirmation
    if not confirm:
        for pat in DESTRUCTIVE_COMMAND_PATTERNS:
            if re.search(pat, cmd_lower):
                return f"Safety Hold: That terminal command is potentially destructive, Sir. To proceed, confirm and I will execute it: {cmd}"

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


def open_app(memory, name: str) -> str:
    clean_name = name.lower().strip()
    target = APP_ALIASES.get(clean_name, clean_name)
    try:
        if os.path.exists(target):
            os.startfile(target)
        else:
            subprocess.Popen(["cmd", "/c", "start", "", target])
        return f"Opening {name}."
    except Exception as exc:
        return f"Couldn't open {name}: {exc}"


def close_app(memory, name: str) -> str:
    """Close/terminate an application or window by name or window title."""
    name_clean = (name or "").lower().strip()
    for prefix in ("the ", "a "):
        if name_clean.startswith(prefix):
            name_clean = name_clean[len(prefix):].strip()
    if name_clean.endswith(" app") or name_clean.endswith(" application"):
        name_clean = name_clean.rsplit(" ", 1)[0].strip()

    user32 = ctypes.windll.user32
    windows = _get_user_windows()

    # 1. Close browser tab if user asks to close a web app
    browser_wins = [w for w in windows if any(b in w['proc'] for b in KNOWN_BROWSERS)]
    if browser_wins and name_clean not in ("browser", "brave", "chrome", "edge", "firefox", "zen"):
        for bw in browser_wins:
            if name_clean in bw['title'].lower():
                from .browser import close_browser_tab
                return close_browser_tab(memory, query=name_clean)

    # 2. Generic browser closure
    if name_clean in ("browser", "web browser", "internet"):
        if browser_wins:
            target_proc = browser_wins[0]['proc']
            for bw in browser_wins:
                if bw['proc'] == target_proc:
                    user32.PostMessageW(bw['hwnd'], 0x0010, 0, 0)
            time.sleep(0.2)
            subprocess.run(["taskkill", "/F", "/T", "/IM", target_proc], capture_output=True)
            b_name = target_proc.replace('.exe', '').capitalize()
            return f"Closed {b_name} browser, Sir."
        for b in KNOWN_BROWSERS:
            r = subprocess.run(["taskkill", "/F", "/T", "/IM", b], capture_output=True)
            if r.returncode == 0:
                b_name = b.replace('.exe', '').capitalize()
                return f"Closed background {b_name} browser processes, Sir."
        return "No browser was running, Sir."

    # 3. Match windows by title or proc
    target_alias = APP_ALIASES.get(name_clean, name_clean)
    matching_wins = [
        w for w in windows 
        if name_clean in w['title'].lower() 
        or name_clean in w['proc'].lower() 
        or target_alias in w['proc'].lower()
    ]

    if matching_wins:
        procs_to_kill = set()
        for w in matching_wins:
            user32.PostMessageW(w['hwnd'], 0x0010, 0, 0)
            procs_to_kill.add(w['proc'])
        time.sleep(0.25)

        for p_name in procs_to_kill:
            subprocess.run(["taskkill", "/F", "/T", "/IM", p_name], capture_output=True)

        return f"Closed {len(matching_wins)} window(s) for '{name}', Sir."

    # 4. Fallback: taskkill
    target_exe = target_alias if target_alias.endswith(".exe") else f"{target_alias}.exe"
    r = subprocess.run(["taskkill", "/F", "/T", "/IM", target_exe], capture_output=True)
    if r.returncode == 0:
        return f"Closed process {target_alias}, Sir."

    if name_clean == "chrome" and browser_wins:
        b_name = browser_wins[0]['proc']
        for bw in browser_wins:
            user32.PostMessageW(bw['hwnd'], 0x0010, 0, 0)
        time.sleep(0.2)
        subprocess.run(["taskkill", "/F", "/T", "/IM", b_name], capture_output=True)
        return f"Chrome was not open, but I closed your active {b_name.replace('.exe','').capitalize()} browser, Sir."

    return f"I couldn't find any running window or process matching '{name}', Sir."


def close_other_windows(memory, keep: list[str]) -> str:
    """Close all open user application windows EXCEPT the ones specified in `keep`."""
    if isinstance(keep, str):
        keep = [k.strip() for k in keep.split(",")]
    
    keep_lower = [k.lower().strip() for k in keep]
    if any("browser" in k for k in keep_lower):
        keep_lower.extend(["brave", "chrome", "edge", "firefox", "zen", "opera"])
    if any("antigravity" in k for k in keep_lower):
        keep_lower.extend(["antigravity", "cursor", "vscode", "code"])

    windows = _get_user_windows()
    user32 = ctypes.windll.user32
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
                user32.PostMessageW(w['hwnd'], 0x0010, 0, 0)
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


def close_active_window(memory) -> str:
    """Close the currently active window (WM_CLOSE / Alt+F4)."""
    user32 = ctypes.windll.user32
    _attach_input_desktop()
    hwnd = user32.GetForegroundWindow()
    if hwnd:
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()

        user32.PostMessageW(hwnd, 0x0010, 0, 0)
        return f"Closed the active window ('{title or 'Window'}'), Sir."

    subprocess.run(
        ["powershell", "-NoProfile", "-Command", "$wshell = New-Object -ComObject wscript.shell; $wshell.SendKeys('%{F4}')"],
        capture_output=True
    )
    return "Closed the active window, Sir."


def list_running_apps(memory) -> str:
    """List currently open user applications and window titles."""
    windows = _get_user_windows()
    if not windows:
        return "No user applications currently open."
    lines = ["Currently open applications:"]
    for w in windows:
        lines.append(f"  - {w['proc']}: '{w['title']}' (PID: {w['pid']})")
    return "\n".join(lines)


def inspect_active_window(memory) -> str:
    """Identify which application and document window is currently active/focused on screen."""
    try:
        user32 = ctypes.windll.user32
        _attach_input_desktop()
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


def press_hotkey(memory, combo: str) -> str:
    """Press a keyboard shortcut/hotkey combo."""
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


def type_text(memory, text: str) -> str:
    """Type text into the currently focused window by pasting it."""
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


def get_battery_status(memory) -> str:
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


def switch_mode(memory, mode: str) -> str:
    clean = str(mode or "").strip().lower()
    if clean in ("stealth", "silent"):
        clean = "ghost"
    if clean not in ("tactical", "engineer", "ghost"):
        return f"Unknown mode '{mode}'. Available modes are: tactical, engineer, ghost."

    try:
        from ..config import load_config, save_config
        cfg = load_config()
        if "assistant" not in cfg:
            cfg["assistant"] = {}
        cfg["assistant"]["mode"] = clean
        save_config(cfg)
    except Exception:
        pass

    try:
        from .. import gui_server
        gui_server.set_active_mode(clean)
    except Exception:
        pass

    if clean == "tactical":
        return "Tactical mode engaged, Sir. Fast, high-readiness operational protocol active."
    elif clean == "engineer":
        return "Engineer mode engaged, Sir. Neural parameters tuned for systems architecture, code mastery, and deep technical reasoning."
    else:
        return "Ghost mode engaged, Sir. Voice audio muted — operating in silent stealth focus."


SYSTEM_SKILLS = [
    {"name": "run_terminal_command", "fn": run_terminal_command, "description": "Execute a PowerShell/terminal command on Jay's computer and return output. Use for git, python, npm, system checks, script execution, inspecting files, or diagnostics. Destructive commands require confirm=True.",
     "parameters": {"type": "object", "properties": {"command": {"type": "string", "description": "The PowerShell or CMD command to execute"}, "confirm": {"type": "boolean", "description": "Set to true only when Jay explicitly confirmed running a destructive or modifying command (e.g. file removal, git reset/force, taskkill)"}}, "required": ["command"]}},
    {"name": "press_hotkey", "fn": press_hotkey, "description": "Press a keyboard shortcut/hotkey combo on Windows (e.g. 'ctrl+c', 'ctrl+v', 'alt+tab', 'win+d', 'enter', 'esc').",
     "parameters": {"type": "object", "properties": {"combo": {"type": "string", "description": "Key combination like 'ctrl+v', 'alt+tab', 'win+d', 'enter'"}}, "required": ["combo"]}},
    {"name": "click_mouse", "fn": click_mouse, "description": "Click or double-click the mouse at specified coordinates (x, y) or at current cursor position.",
     "parameters": {"type": "object", "properties": {"x": {"type": "integer", "description": "X coordinate on screen"}, "y": {"type": "integer", "description": "Y coordinate on screen"}, "button": {"type": "string", "description": "'left' or 'right'"}, "double": {"type": "boolean", "description": "True for double click"}}, "required": []}},
    {"name": "open_app", "fn": open_app, "description": "Open/launch an application (e.g. brave, chrome, notepad, calculator, explorer).",
     "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "App name"}}, "required": ["name"]}},
    {"name": "close_app", "fn": close_app, "description": "Close/terminate an application or window (e.g. brave, chrome, browser, youtube, word, notepad, spotify). If given a website/tab name like 'youtube' or 'meet', it automatically closes that tab in the active browser.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "Application, process, or website name to close (e.g. 'browser', 'brave', 'chrome', 'youtube', 'word')"}}, "required": ["name"]}},
    {"name": "close_other_windows", "fn": close_other_windows, "description": "Close all open user application windows EXCEPT the ones specified in keep (e.g. keep=['browser', 'antigravity']).",
     "parameters": {"type": "object", "properties": {"keep": {"type": "array", "items": {"type": "string"}, "description": "List of window titles or app names to keep open"}}, "required": ["keep"]}},
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
    {"name": "lock_pc", "fn": lock_pc, "description": "Lock the Windows workstation (lock screen).",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "sleep_pc", "fn": sleep_pc, "description": "Put the computer to sleep. Only when Jay clearly asks to sleep/suspend the PC.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "set_brightness", "fn": set_brightness, "description": "Set the laptop screen brightness to a level from 0 to 100 percent.",
     "parameters": {"type": "object", "properties": {"level": {"type": "integer", "description": "Brightness percentage 0-100"}}, "required": ["level"]}},
    {"name": "get_system_info", "fn": get_system_info, "description": "Report OS, CPU load, RAM usage, and system uptime.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "get_battery_status", "fn": get_battery_status, "description": "Check laptop battery percentage and whether it is charging or running on battery.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "type_text", "fn": type_text, "description": "Type/paste the given text into whatever window is currently focused.",
     "parameters": {"type": "object", "properties": {"text": {"type": "string", "description": "The text to type into the active window"}}, "required": ["text"]}},
    {"name": "switch_mode", "fn": switch_mode, "description": "Switch Rusty's operational mode between 'tactical' (fast, military brevity, spoken), 'engineer' (senior software architect, deep code & reasoning), and 'ghost' (silent stealth focus, voice muted).",
     "parameters": {"type": "object", "properties": {"mode": {"type": "string", "enum": ["tactical", "engineer", "ghost"], "description": "Target mode to switch to"}}, "required": ["mode"]}},
    {"name": "inspect_active_window", "fn": inspect_active_window, "description": "Identify which application, document, or window is currently active/focused on screen.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
]
