"""Communications, mobile messaging, cloud backup, and GitHub integration skills for Rusty."""

from __future__ import annotations

import os
import re
import shlex
import socket
import subprocess
import urllib.parse

from .common import (
    ROOT,
    _resolve_path,
    is_path_safe,
)


def send_whatsapp_message(memory, phone: str = "", message: str = "", open_chat: bool = True) -> str:
    """Send a WhatsApp TEXT message. Defaults to Jay's own number when none given."""
    phone_clean = re.sub(r'[^0-9+]', '', phone or "").strip()
    if not phone_clean:
        try:
            from ..config import load_config
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
    
    from .browser import _open_in_browser
    _open_in_browser(url)
    return f"Opened WhatsApp to {phone_clean or 'WhatsApp'}, Sir — your message is ready, just tap send."


def mobile_phone_gateway(memory, action: str = "status") -> str:
    """Get the local network URL and setup info so Jay can control JARVIS directly from his phone."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "127.0.0.1"
    pin = ""
    try:
        from ..config import load_config
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


def send_file_to_phone(memory, path: str) -> str:
    """Send a file (or every file in a folder) from the PC to Jay's Telegram chat."""
    try:
        from ..config import load_config
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
    """Back up a file or folder to Google Drive via rclone, so Jay can reach it anywhere."""
    try:
        from ..config import load_config
        dc = load_config().get("drive", {})
    except Exception:
        dc = {}
    rclone = dc.get("rclone_path", "rclone")
    remote = dc.get("remote", "gdrive")
    base = dc.get("base_folder", "RustyBackup")
    full = _resolve_path(path)
    if not is_path_safe(full):
        return f"Access denied: '{os.path.basename(full)}' contains protected credentials or system files and cannot be uploaded to remote storage, Sir."
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
    """Run a GitHub CLI (gh) command to manage Jay's GitHub."""
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


COMMS_SKILLS = [
    {"name": "send_whatsapp_message", "fn": send_whatsapp_message, "description": "Send a WhatsApp TEXT message. Use ONLY when Jay explicitly says 'WhatsApp'. Text only — it cannot attach files. If no number is given it goes to Jay's own number. To send a FILE to his phone, do NOT use this — use send_file_to_phone.",
     "parameters": {"type": "object", "properties": {"phone": {"type": "string", "description": "Optional phone number with country code; leave empty to message Jay himself"}, "message": {"type": "string", "description": "Message text to send"}}, "required": ["message"]}},
    {"name": "mobile_phone_gateway", "fn": mobile_phone_gateway, "description": "Get the mobile connection URL so Jay can control JARVIS directly from his phone browser over Wi-Fi.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "send_file_to_phone", "fn": send_file_to_phone, "description": "Send a file (or all files in a folder) from the PC to Jay's phone via Telegram. Use whenever Jay asks you to send/share/get a file to his phone or Telegram (e.g. 'send me resume.pdf', 'send me the files in downloads').",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "File or folder path/shortcut (e.g. 'downloads/resume.pdf' or 'downloads')"}}, "required": ["path"]}},
    {"name": "backup_to_drive", "fn": backup_to_drive, "description": "Back up / upload a file or folder to Jay's Google Drive (via rclone) so he can access it anywhere. Use when he says 'back up X to drive', 'upload X to my drive', 'save this to drive'.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "File or folder to back up (path or shortcut like 'downloads', 'documents', or the project folder)"}}, "required": ["path"]}},
    {"name": "github", "fn": github, "description": "Manage Jay's GitHub via the gh CLI. Pass the gh subcommand WITHOUT 'gh' — e.g. 'repo list', 'repo create myapp --private', 'issue create -R owner/repo -t Title -b Body', 'pr list', 'api user'. Use for anything GitHub.",
     "parameters": {"type": "object", "properties": {"command": {"type": "string", "description": "The gh subcommand, e.g. 'repo list --limit 10'"}, "confirm": {"type": "boolean", "description": "Set true to run a destructive command (delete/archive)"}}, "required": ["command"]}},
]
