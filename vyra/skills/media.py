"""Media playback, music control, screen vision analysis, and image generation skills for Rusty."""

from __future__ import annotations

import base64
import ctypes
import io
import os
import subprocess
import time
from datetime import datetime

import psutil

from .common import _data_dir

RAAGA_APP_PATH = os.path.expandvars(r"%USERPROFILE%\Desktop\raaga.lnk")
if not os.path.exists(RAAGA_APP_PATH):
    RAAGA_APP_PATH = os.path.expandvars(r"%LOCALAPPDATA%\raaga\raaga-app.exe")

_VISION_CONFIG = None  # llm config for screen vision queries


def configure_vision(llm_config: dict):
    global _VISION_CONFIG
    _VISION_CONFIG = llm_config


def media_play_pause(memory) -> str:
    """Toggle media playback (play / pause) for Spotify, YouTube, media player."""
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
            if os.path.exists(target):
                os.startfile(target)
            else:
                subprocess.Popen(["cmd", "/c", "start", "", target])
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


def see_screen(memory, question: str = "", progress_callback=None) -> str:
    """Capture and analyze what is visible on the user's screen using AI vision."""
    if progress_callback:
        progress_callback("Capturing screen display and analyzing visual details, Sir...", speak=True)
    global _VISION_CONFIG
    cfg = _VISION_CONFIG
    if not cfg:
        try:
            from ..config import load_config
            cfg = load_config().get("llm")
        except Exception:
            cfg = None

    if not cfg or not cfg.get("api_key"):
        return "Screen vision requires a valid LLM API key configured in .env or config.json."

    screenshot = None
    try:
        from PIL import ImageGrab
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
        from PIL import Image
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
    """Generate an image from a text prompt by driving the logged-in browser (Gemini web)."""
    try:
        from .. import browser
        result = browser.generate_image(prompt)
        if result and os.path.exists(result):
            try:
                os.startfile(result)
            except Exception:
                pass
            return f"Done, Sir — generated your image and opened it: {os.path.basename(result)}."
        return result
    except Exception as exc:
        return f"Image generation failed: {exc}"


MEDIA_SKILLS = [
    {"name": "media_play_pause", "fn": media_play_pause, "description": "Play or pause current media (Spotify, YouTube, media player).",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "media_next", "fn": media_next, "description": "Skip to the next media song/track.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "media_previous", "fn": media_previous, "description": "Return to the previous media song/track.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "play_music", "fn": play_music, "description": "Open Jay's Raaga music app from desktop and start playing songs or good music.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "Optional song, artist or playlist query"}}, "required": []}},
    {"name": "save_screenshot", "fn": save_screenshot, "description": "Capture a screenshot of the whole screen, save it to data/screenshots, and open it.",
     "parameters": {"type": "object", "properties": {"open_after": {"type": "boolean", "description": "Open the image after saving (default true)"}}, "required": []}},
    {"name": "see_screen", "fn": see_screen, "description": "Inspect and analyze what is currently visible on the user's screen or open windows using AI vision.",
     "parameters": {"type": "object", "properties": {"question": {"type": "string", "description": "Specific question or request about what is on screen"}}, "required": []}},
    {"name": "generate_image", "fn": generate_image, "description": "Generate / create / draw a picture or image from a text description, using the browser (Gemini web). Use whenever Jay asks to make, create, draw, or generate an image, picture, art, or wallpaper.",
     "parameters": {"type": "object", "properties": {"prompt": {"type": "string", "description": "Detailed description of the image to generate"}}, "required": ["prompt"]}},
]
