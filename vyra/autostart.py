"""Windows Auto-Start and Desktop App Shortcut Manager for VYRA.

Allows VYRA to launch automatically on Windows boot/login without any
annoying command prompt window (using pythonw.exe), and creates Desktop shortcuts.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Paths
ROOT = Path(__file__).resolve().parent.parent
PYTHON_DIR = Path(sys.executable).parent
PYTHONW_EXE = PYTHON_DIR / "pythonw.exe"
if not PYTHONW_EXE.exists():
    PYTHONW_EXE = Path(sys.executable)

STARTUP_DIR = Path(os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"))
DESKTOP_DIR = Path(os.path.expandvars(r"%USERPROFILE%\Desktop"))

STARTUP_SHORTCUT = STARTUP_DIR / "Rusty AI.lnk"
DESKTOP_SHORTCUT = DESKTOP_DIR / "Rusty AI.lnk"
STARTUP_BOT_SHORTCUT = STARTUP_DIR / "Rusty Bot.lnk"
_OLD_SHORTCUTS = [STARTUP_DIR / "FRIDAY AI.lnk", DESKTOP_DIR / "FRIDAY AI.lnk"]


def enable_bot_autostart() -> bool:
    """Always-on headless Telegram bot at logon (invisible, no window)."""
    _disable_startup_delay()
    return _create_windows_shortcut(
        link_path=STARTUP_BOT_SHORTCUT,
        target_path=str(PYTHONW_EXE),
        arguments="-m vyra.bot_service",
        working_dir=str(ROOT),
        description="Rusty always-on Telegram bot (headless)",
    )


def disable_bot_autostart() -> bool:
    try:
        if STARTUP_BOT_SHORTCUT.exists():
            STARTUP_BOT_SHORTCUT.unlink()
        return True
    except Exception:
        return False


def _disable_startup_delay():
    """Remove Windows Explorer's artificial delay on Startup-folder apps so Rusty
    launches the moment you log in instead of ~10s later. Reversible (HKCU only)."""
    try:
        subprocess.run(
            ["reg", "add",
             r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Serialize",
             "/v", "StartupDelayInMSec", "/t", "REG_DWORD", "/d", "0", "/f"],
            capture_output=True, text=True,
        )
    except Exception as exc:
        print(f"[AUTOSTART] Could not clear startup delay: {exc}")


def _create_windows_shortcut(
    link_path: Path,
    target_path: str,
    arguments: str = "",
    working_dir: str = "",
    description: str = "VYRA AI Desktop HUD",
    icon_location: str = ""
) -> bool:
    """Create a Windows .lnk shortcut using Windows Script Host (WScript.Shell)."""
    try:
        link_path.parent.mkdir(parents=True, exist_ok=True)
        vbs_script = (
            'Set oWS = WScript.CreateObject("WScript.Shell")\n'
            f'Set oLink = oWS.CreateShortcut("{link_path}")\n'
            f'oLink.TargetPath = "{target_path}"\n'
            f'oLink.Arguments = "{arguments}"\n'
            f'oLink.WorkingDirectory = "{working_dir}"\n'
            f'oLink.Description = "{description}"\n'
        )
        if icon_location:
            vbs_script += f'oLink.IconLocation = "{icon_location}"\n'
        vbs_script += "oLink.Save\n"

        with tempfile.NamedTemporaryFile("w", suffix=".vbs", delete=False, encoding="utf-8") as f:
            f.write(vbs_script)
            vbs_tmp = f.name

        res = subprocess.run(
            ["cscript", "//nologo", vbs_tmp],
            capture_output=True,
            text=True,
            check=True
        )
        try:
            os.unlink(vbs_tmp)
        except OSError:
            pass

        return link_path.exists()
    except Exception as exc:
        print(f"[AUTOSTART] Error creating shortcut {link_path}: {exc}")
        return False


def is_autostart_enabled() -> bool:
    """Check if VYRA is configured to start automatically on Windows boot."""
    return STARTUP_SHORTCUT.exists()


def enable_autostart() -> bool:
    """Enable Rusty auto-start at logon, as early as possible."""
    _disable_startup_delay()
    for old in _OLD_SHORTCUTS:
        try:
            if old.exists():
                old.unlink()
        except Exception:
            pass
    ok = _create_windows_shortcut(
        link_path=STARTUP_SHORTCUT,
        target_path=str(PYTHONW_EXE),
        arguments="-m vyra.gui_server --startup",
        working_dir=str(ROOT),
        description="Rusty — autonomous AI partner (starts in the corner at logon)"
    )
    return ok


def disable_autostart() -> bool:
    """Disable FRIDAY auto-start by removing the Startup shortcut."""
    try:
        if STARTUP_SHORTCUT.exists():
            STARTUP_SHORTCUT.unlink()
        return True
    except Exception as exc:
        print(f"[AUTOSTART] Error disabling autostart: {exc}")
        return False


def create_desktop_shortcut() -> bool:
    """Create a desktop app launcher shortcut for FRIDAY."""
    ok = _create_windows_shortcut(
        link_path=DESKTOP_SHORTCUT,
        target_path=str(PYTHONW_EXE),
        arguments="-m vyra.gui_server",
        working_dir=str(ROOT),
        description="Launch Rusty AI Desktop HUD"
    )
    return ok


if __name__ == "__main__":
    if "--enable" in sys.argv:
        if enable_autostart():
            print("Auto-start ENABLED successfully in Windows Startup folder.")
        else:
            print("Failed to enable auto-start.")
    elif "--disable" in sys.argv:
        if disable_autostart():
            print("Auto-start DISABLED successfully.")
        else:
            print("Failed to disable auto-start.")
    elif "--desktop" in sys.argv:
        if create_desktop_shortcut():
            print("Desktop shortcut created successfully.")
        else:
            print("Failed to create desktop shortcut.")
    else:
        status = "ENABLED" if is_autostart_enabled() else "DISABLED"
        print(f"VYRA Auto-start Status: {status}")
        print(f"Startup Shortcut: {STARTUP_SHORTCUT}")
        print(f"Desktop Shortcut: {DESKTOP_SHORTCUT}")
