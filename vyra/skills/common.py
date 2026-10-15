"""Common utilities, path resolvers, security checks, and Win32 helpers for Rusty's skills."""

from __future__ import annotations

import ctypes
import os
import re
import time
from pathlib import Path

import psutil

# Base project root
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FOLDER_SHORTCUTS = {
    "downloads": r"%USERPROFILE%\Downloads",
    "documents": r"%USERPROFILE%\Documents",
    "desktop": r"%USERPROFILE%\Desktop",
    "pictures": r"%USERPROFILE%\Pictures",
    "home": r"%USERPROFILE%",
}

KNOWN_BROWSERS = (
    "brave.exe",
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "zen.exe",
    "opera.exe",
    "vivaldi.exe",
    "arc.exe",
)

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

PROTECTED_PATH_PATTERNS = [
    r"\\windows\\system32\\config",
    r"\\windows\\system32\\drivers\\etc",
    r"\\windows\\system32\\sam",
    r"\.env($|\.)",
    r"secrets?\.(json|yaml|yml|toml)$",
    r"credentials?\.(json|yaml|yml|xml)$",
    r"id_rsa($|\.)",
    r"id_ed25519($|\.)",
    r"id_ecdsa($|\.)",
    r"\.pem$",
    r"\.key$",
    r"\.pfx$",
    r"\\\.ssh($|\\)",
    r"\\\.gnupg($|\\)",
    r"\\\.aws\\credentials",
    r"\\user data\\.*\\(cookies|login data|web data|history)",
]


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


def is_path_safe(resolved_path: str) -> bool:
    norm = os.path.normpath(resolved_path).lower()
    for pat in PROTECTED_PATH_PATTERNS:
        if re.search(pat, norm):
            return False
    return True


def _data_dir(sub: str) -> str:
    d = os.path.join(ROOT, "data", sub)
    os.makedirs(d, exist_ok=True)
    return d


def _attach_input_desktop():
    """Synchronize calling thread with the Windows interactive user desktop."""
    try:
        user32 = ctypes.windll.user32
        hdesk = user32.OpenInputDesktop(0, False, 0x01FF)
        if hdesk:
            user32.SetThreadDesktop(hdesk)
            return hdesk
    except Exception:
        pass
    return None


def _get_user_windows() -> list[dict]:
    """Blazingly fast, native Win32 window enumeration. Returns real user windows with HWNDs and titles."""
    user32 = ctypes.windll.user32
    hdesk = _attach_input_desktop()
    windows = []
    current_pid = os.getpid()

    from ctypes import wintypes
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()
            if not title:
                return True

            title_lower = title.lower()
            if title_lower in IGNORE_TITLES:
                return True
            if "stark industries hud" in title_lower or "vyra" in title_lower or "rusty hud" in title_lower:
                return True

            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == current_pid:
                return True

            proc_name = "unknown"
            try:
                proc_name = psutil.Process(pid.value).name().lower()
            except Exception:
                pass

            if proc_name in SYSTEM_PROTECTED:
                return True

            windows.append({
                "hwnd": hwnd,
                "pid": pid.value,
                "proc": proc_name,
                "title": title
            })
        except Exception:
            pass
        return True

    cb = WNDENUMPROC(callback)
    if hdesk:
        try:
            user32.EnumDesktopWindows(hdesk, cb, 0)
        finally:
            user32.CloseDesktop(hdesk)
    else:
        user32.EnumWindows(cb, 0)

    return windows


def focus_window(hwnd: int) -> bool:
    """Bring the target window to the foreground with full input focus."""
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        _attach_input_desktop()
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE

        cur_tid = kernel32.GetCurrentThreadId()
        fg_hwnd = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
        tgt_tid = user32.GetWindowThreadProcessId(hwnd, None)

        if fg_tid and fg_tid != cur_tid:
            user32.AttachThreadInput(cur_tid, fg_tid, True)
        if tgt_tid and tgt_tid != cur_tid:
            user32.AttachThreadInput(cur_tid, tgt_tid, True)

        # Alt key tap trick bypasses Windows SetForegroundWindow restrictions
        user32.keybd_event(0x12, 0, 0, 0)
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
        user32.keybd_event(0x12, 0, 0x0002, 0)

        if fg_tid and fg_tid != cur_tid:
            user32.AttachThreadInput(cur_tid, fg_tid, False)
        if tgt_tid and tgt_tid != cur_tid:
            user32.AttachThreadInput(cur_tid, tgt_tid, False)

        time.sleep(0.08)
        return True
    except Exception:
        return False
