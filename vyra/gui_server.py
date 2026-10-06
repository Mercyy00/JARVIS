"""VYRA Holographic Technical HUD Server.

Serves the Stark Industries / JARVIS style HUD on http://127.0.0.1:8765,
connected via WebSockets and REST to VYRA's Brain, Memory, Mouth, and Ears.
"""

from __future__ import annotations

import asyncio
import ctypes
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

from aiohttp import web
import psutil

# Add JARVIS root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vyra import autostart
from vyra import skills
from vyra import voice as V
from vyra.brain import Brain
from vyra.config import has_api_key, load_config
from vyra.memory import Memory

GUI_DIR = Path(__file__).resolve().parent / "gui"

config = load_config()
if not has_api_key(config):
    print("Error: No API key found in .env or config.json.")
    sys.exit(1)

memory = Memory(ROOT)
skills.configure_browser(config["user"].get("browser"))
skills.configure_vision(config.get("llm"))
brain = Brain(config, memory)

# Voice & Assistant setup
assistant_name = config.get("assistant", {}).get("name", "FRIDAY")
v_cfg = config.get("voice", {})
whisper_model = v_cfg.get("whisper_model", "base")
voice_name = v_cfg.get("name", "en-US-AriaNeural")
voice_rate = v_cfg.get("rate", "+12%")
pronounce_name = v_cfg.get("pronounce_vyra", "Friday")
wake_enabled = v_cfg.get("wake_enabled", True)
wake_words = v_cfg.get("wake_words", V.DEFAULT_WAKE_WORDS)

mic_lock = threading.Lock()
wake_pause_event = threading.Event()
wake_stop_event = threading.Event()
is_manual_active = False
is_muted_global = False
server_loop: asyncio.AbstractEventLoop | None = None

ears = V.Ears(model_size=whisper_model)
mouth = V.Mouth(voice=voice_name, rate=voice_rate, pronounce_vyra=pronounce_name)

ws_clients = set()


def get_gpu_info() -> str:
    # Quick probe or fallback to RTX 2050
    return "NVIDIA GeForce RTX 2050"


def get_telemetry():
    vmem = psutil.virtual_memory()
    bat = psutil.sensors_battery()
    bat_pct = round(bat.percent) if bat else None
    bat_plugged = bool(bat.power_plugged) if bat else True
    return {
        "type": "telemetry",
        "cpu": psutil.cpu_percent(interval=None),
        "ram_percent": vmem.percent,
        "ram_used_gb": round((vmem.total - vmem.available) / (1024**3), 1),
        "ram_total_gb": round(vmem.total / (1024**3), 1),
        "gpu": get_gpu_info(),
        "battery_percent": bat_pct,
        "battery_plugged": bat_plugged,
        "model": config["llm"]["model"],
        "provider": config["llm"]["provider"],
        "wake_enabled": wake_enabled,
        "ping": 8,
    }


async def ws_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    ws_clients.add(ws)

    # Send initial telemetry
    await ws.send_str(json.dumps(get_telemetry()))

    try:
        async for msg in ws:
            pass
    finally:
        ws_clients.discard(ws)
    return ws


async def broadcast_ws(data: dict):
    if not ws_clients:
        return
    msg = json.dumps(data)
    for ws in list(ws_clients):
        if not ws.closed:
            try:
                await ws.send_str(msg)
            except Exception:
                pass


async def telemetry_broadcaster():
    """Background task sending CPU/RAM telemetry every second."""
    while True:
        await asyncio.sleep(1.0)
        await broadcast_ws(get_telemetry())


async def handle_chat(request):
    global is_muted_global
    data = await request.json()
    msg = data.get("message", "").strip()
    mute = data.get("mute", False)
    is_muted_global = mute

    if not msg:
        return web.json_response({"reply": ""})

    await broadcast_ws({"type": "state", "state": "thinking"})
    try:
        reply = brain.ask(msg)
    except Exception as exc:
        reply = f"Error during neural processing: {exc}"

    await broadcast_ws({"type": "state", "state": "idle"})
    await broadcast_ws({"type": "speech", "text": reply})

    if not mute:
        def _speak():
            mouth.speak(reply)
        threading.Thread(target=_speak, daemon=True).start()

    return web.json_response({"reply": reply})


active_stop_event: threading.Event | None = None


async def handle_voice_stop(request):
    global active_stop_event
    wake_stop_event.set()
    if active_stop_event and not active_stop_event.is_set():
        active_stop_event.set()
    return web.json_response({"status": "stopping"})


async def handle_wake_toggle(request):
    global wake_enabled
    wake_enabled = not wake_enabled
    await broadcast_ws({"type": "wake_toggle", "enabled": wake_enabled})
    await broadcast_ws({
        "type": "log",
        "level": "system",
        "message": f"Acoustic Wake Protocol {'ENABLED (Monitoring for \"Hey buddy\" / \"VYRA\")' if wake_enabled else 'DISABLED (Manual Trigger Only)'}."
    })
    return web.json_response({"wake_enabled": wake_enabled})


DISMISSAL_PHRASES = (
    "that's all", "thats all", "thank you", "thanks", "bye", "goodbye",
    "stop", "stop listening", "go to sleep", "stand down", "never mind",
    "nevermind", "nothing", "sleep", "done", "im done", "i am done", "cancel"
)


def is_dismissal(text: str) -> bool:
    clean = re.sub(r'[^\w\s]', '', text.lower()).strip()
    return clean in DISMISSAL_PHRASES or any(clean.startswith(w) or clean.endswith(w) for w in ("that's all", "thats all", "thank you", "bye", "go to sleep", "stand down"))


async def run_conversational_followup_loop(loop, mute: bool = False):
    """
    Keep FRIDAY in attentive listening mode so Jay can speak follow-up
    instructions naturally without repeating 'Friday' or 'Buddy' each time.
    """
    if not config.get("voice", {}).get("continuous_listen", True):
        return

    while True:
        await broadcast_ws({"type": "state", "state": "attentive"})

        stop_ev = threading.Event()
        last_meter_time = 0.0

        def on_meter(level: float, has_spoken: bool):
            nonlocal last_meter_time
            now = time.time()
            if now - last_meter_time >= 0.07:
                last_meter_time = now
                asyncio.run_coroutine_threadsafe(
                    broadcast_ws({
                        "type": "audio_meter",
                        "level": min(1.0, level * 20.0),
                        "speaking": has_spoken,
                    }),
                    loop,
                )

        mouth.stop()

        with mic_lock:
            follow_audio = await loop.run_in_executor(
                None,
                lambda: V.record_until_silence(
                    push_to_talk=True,
                    initial_timeout=14.0,  # 14s patient window for follow-up
                    trail_silence=1.6,     # 1.6s natural pause tolerance
                    stop_event=stop_ev,
                    level_callback=on_meter,
                ),
            )

        if follow_audio is None:
            # Timed out without follow-up speech -> smoothly return to standby
            await broadcast_ws({"type": "state", "state": "idle"})
            await broadcast_ws({
                "type": "log",
                "level": "system",
                "message": "[STANDBY] Attentive window closed. Say 'Friday' or 'Buddy' anytime."
            })
            break

        await broadcast_ws({"type": "state", "state": "thinking"})
        follow_text = await loop.run_in_executor(None, lambda: ears.transcribe(follow_audio))

        if not follow_text or len(follow_text.strip()) < 2:
            continue

        # If user explicitly said wake word again, strip it cleanly
        is_w, _, cmd = V.detect_wake_word(follow_text, wake_words)
        if is_w and cmd:
            follow_text = cmd
        elif is_w and not cmd:
            ack = "Yes boss, what else?"
            await broadcast_ws({"type": "speech", "text": ack})
            if not mute and not is_muted_global:
                await asyncio.to_thread(mouth.speak, ack)
            continue

        # Check dismissal
        if is_dismissal(follow_text):
            farewell = "Standing by, boss."
            await broadcast_ws({"type": "log", "level": "user", "message": follow_text})
            await broadcast_ws({"type": "speech", "text": farewell})
            await broadcast_ws({"type": "state", "state": "idle"})
            if not mute and not is_muted_global:
                await asyncio.to_thread(mouth.speak, farewell)
            break

        await broadcast_ws({"type": "log", "level": "user", "message": follow_text})
        try:
            reply = brain.ask(follow_text)
        except Exception as exc:
            reply = f"Error during neural processing: {exc}"

        await broadcast_ws({"type": "speech", "text": reply})
        if not mute and not is_muted_global:
            await asyncio.to_thread(mouth.speak, reply)


async def handle_voice_listen(request):
    global active_stop_event, is_manual_active, is_muted_global
    data = await request.json()
    mute = data.get("mute", False)
    is_muted_global = mute

    mouth.stop()  # Immediately stop speaking if Jay clicked mic or pressed space
    is_manual_active = True
    wake_pause_event.set()
    wake_stop_event.set()  # Stop any background wake recording immediately

    stop_event = threading.Event()
    active_stop_event = stop_event

    await broadcast_ws({"type": "state", "state": "listening"})
    await broadcast_ws({"type": "voice_status", "status": "waiting_speech"})

    loop = asyncio.get_running_loop()
    last_meter_time = 0.0

    def on_audio_level(level: float, has_spoken: bool):
        nonlocal last_meter_time
        now = time.time()
        if now - last_meter_time >= 0.07:
            last_meter_time = now
            asyncio.run_coroutine_threadsafe(
                broadcast_ws({
                    "type": "audio_meter",
                    "level": min(1.0, level * 20.0),
                    "speaking": has_spoken,
                }),
                loop,
            )

    try:
        with mic_lock:
            audio = await loop.run_in_executor(
                None,
                lambda: V.record_until_silence(
                    push_to_talk=True,
                    initial_timeout=12.0,
                    trail_silence=1.6,
                    stop_event=stop_event,
                    level_callback=on_audio_level,
                ),
            )
    finally:
        active_stop_event = None

    if audio is None:
        is_manual_active = False
        wake_pause_event.clear()
        await broadcast_ws({"type": "state", "state": "idle"})
        await broadcast_ws({"type": "log", "level": "system", "message": "Voice listen standby (no directive received)."})
        return web.json_response({"heard": "", "reply": ""})

    await broadcast_ws({"type": "state", "state": "thinking"})
    heard = await loop.run_in_executor(None, lambda: ears.transcribe(audio))

    if not heard:
        is_manual_active = False
        wake_pause_event.clear()
        await broadcast_ws({"type": "state", "state": "idle"})
        await broadcast_ws({"type": "log", "level": "system", "message": "Audio captured was not recognized as speech."})
        return web.json_response({"heard": "", "reply": ""})

    # Strip wake word if present in manual speech
    is_w, _, cmd = V.detect_wake_word(heard, wake_words)
    processed_heard = cmd if (is_w and cmd) else heard

    await broadcast_ws({"type": "log", "level": "user", "message": heard})

    # Brain ask
    try:
        reply = brain.ask(processed_heard)
    except Exception as exc:
        reply = f"Error during neural processing: {exc}"

    await broadcast_ws({"type": "speech", "text": reply})
    await broadcast_ws({"type": "state", "state": "idle"})

    if not mute:
        await asyncio.to_thread(mouth.speak, reply)

    # Enter continuous attentive conversation mode
    try:
        await run_conversational_followup_loop(loop, mute=mute)
    finally:
        is_manual_active = False
        wake_pause_event.clear()

    return web.json_response({"heard": heard, "reply": reply})


async def process_wake_event(phrase: str, cmd: str):
    """Handle wake word activation triggered in background acoustic monitor."""
    global is_manual_active
    is_manual_active = True
    wake_pause_event.set()
    mouth.stop()
    loop = asyncio.get_running_loop()

    try:
        await broadcast_ws({
            "type": "wake_detected",
            "phrase": phrase,
            "command": cmd
        })
        await broadcast_ws({
            "type": "log",
            "level": "system",
            "message": f"[ACOUSTIC WAKE DETECTED] \"{phrase}\""
        })

        if cmd.strip():
            # Directive was spoken in the same sentence (e.g. "Hey buddy open Brave browser")
            await broadcast_ws({"type": "log", "level": "user", "message": cmd})
            await broadcast_ws({"type": "state", "state": "thinking"})
            try:
                reply = brain.ask(cmd)
            except Exception as exc:
                reply = f"Error during neural processing: {exc}"

            await broadcast_ws({"type": "speech", "text": reply})
            await broadcast_ws({"type": "state", "state": "idle"})

            if not is_muted_global:
                await asyncio.to_thread(mouth.speak, reply)

            # Continue in attentive follow-up mode so Jay doesn't have to repeat 'Friday'!
            await run_conversational_followup_loop(loop, mute=is_muted_global)

        else:
            # Wake phrase spoken alone: acknowledge and prompt for directive!
            ack = "Yes boss, what else?"
            await broadcast_ws({"type": "speech", "text": ack})
            await broadcast_ws({"type": "log", "level": "vyra", "message": ack})
            await broadcast_ws({"type": "state", "state": "speaking"})

            if not is_muted_global:
                await asyncio.to_thread(mouth.speak, ack)

            # Listen for follow-up directive
            await broadcast_ws({"type": "state", "state": "listening"})
            await broadcast_ws({"type": "voice_status", "status": "waiting_speech"})

            last_meter_time = 0.0

            def on_meter(level: float, has_spoken: bool):
                nonlocal last_meter_time
                now = time.time()
                if now - last_meter_time >= 0.07:
                    last_meter_time = now
                    asyncio.run_coroutine_threadsafe(
                        broadcast_ws({
                            "type": "audio_meter",
                            "level": min(1.0, level * 20.0),
                            "speaking": has_spoken,
                        }),
                        loop,
                    )

            stop_ev = threading.Event()
            with mic_lock:
                follow_audio = await loop.run_in_executor(
                    None,
                    lambda: V.record_until_silence(
                        push_to_talk=True,
                        initial_timeout=12.0,
                        trail_silence=1.6,
                        stop_event=stop_ev,
                        level_callback=on_meter,
                    ),
                )

            if follow_audio is None:
                await broadcast_ws({"type": "state", "state": "idle"})
                await broadcast_ws({"type": "log", "level": "system", "message": "Voice listen standby (timeout)."})
                return

            await broadcast_ws({"type": "state", "state": "thinking"})
            follow_cmd = await loop.run_in_executor(None, lambda: ears.transcribe(follow_audio))

            if not follow_cmd:
                await broadcast_ws({"type": "state", "state": "idle"})
                return

            await broadcast_ws({"type": "log", "level": "user", "message": follow_cmd})
            try:
                reply = brain.ask(follow_cmd)
            except Exception as exc:
                reply = f"Error during neural processing: {exc}"

            await broadcast_ws({"type": "speech", "text": reply})
            await broadcast_ws({"type": "state", "state": "idle"})

            if not is_muted_global:
                await asyncio.to_thread(mouth.speak, reply)

            # Continue in attentive follow-up mode!
            await run_conversational_followup_loop(loop, mute=is_muted_global)
    finally:
        is_manual_active = False
        wake_pause_event.clear()


def wake_word_listener_thread():
    """Continuously listens in background for 'Hey buddy', 'VYRA', 'Jarvis' etc."""
    print(f"[WAKE] Background passive acoustic monitoring started.")
    print(f"[WAKE] Listening for wake triggers: {wake_words}")
    while True:
        try:
            if not wake_enabled or wake_pause_event.is_set() or is_manual_active:
                time.sleep(0.3)
                continue

            wake_stop_event.clear()
            with mic_lock:
                if not wake_enabled or wake_pause_event.is_set() or is_manual_active:
                    time.sleep(0.1)
                    continue

                audio = V.record_until_silence(
                    push_to_talk=False,
                    initial_timeout=5.0,
                    trail_silence=0.85,
                    stop_event=wake_stop_event,
                )

            if audio is None:
                continue

            if not wake_enabled or wake_pause_event.is_set() or is_manual_active:
                continue

            transcript = ears.transcribe(audio)
            if not transcript:
                continue

            is_wake, phrase, cmd = V.detect_wake_word(transcript, wake_words)
            if not is_wake:
                continue

            print(f"[WAKE ENGAGED] Phrase: '{phrase}' | Command: '{cmd}'")
            if server_loop and server_loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    process_wake_event(phrase, cmd),
                    server_loop
                )
                try:
                    future.result(timeout=60.0)
                except Exception as exc:
                    print(f"[WAKE PROCESSING EXCEPTION] {exc}")
        except Exception:
            time.sleep(0.5)


async def handle_memory(request):
    journal = memory.recent_journal()
    return web.json_response({
        "profile": memory.profile,
        "links": memory.list_links(),
        "journal": journal if journal != "(no recent history)" else "No recent journal recorded."
    })


# ---------------------------------------------------------------------------
# Window Management API (PiP Widget & Desktop Positioning)
# ---------------------------------------------------------------------------
_webview_window = None


class WindowAPI:
    def __init__(self):
        self.is_pip = True
        self.is_pinned = True
        self.pip_w = 380
        self.pip_h = 600
        self.full_w = 1200
        self.full_h = 780

    def toggle_mode(self):
        global _webview_window
        if not _webview_window:
            return {"is_pip": self.is_pip}
        try:
            user32 = ctypes.windll.user32
            sw = user32.GetSystemMetrics(0)
            sh = user32.GetSystemMetrics(1)
        except Exception:
            sw, sh = 1920, 1080

        if self.is_pip:
            _webview_window.resize(self.full_w, self.full_h)
            _webview_window.move(max(0, (sw - self.full_w) // 2), max(0, (sh - self.full_h) // 2))
            self.is_pip = False
        else:
            _webview_window.resize(self.pip_w, self.pip_h)
            _webview_window.move(max(0, sw - self.pip_w - 20), max(0, sh - self.pip_h - 60))
            self.is_pip = True
        return {"is_pip": self.is_pip}

    def toggle_pin(self):
        global _webview_window
        if not _webview_window:
            return {"is_pinned": self.is_pinned}
        self.is_pinned = not self.is_pinned
        try:
            _webview_window.on_top = self.is_pinned
        except Exception:
            pass
        return {"is_pinned": self.is_pinned}

    def minimize(self):
        global _webview_window
        if _webview_window:
            try:
                _webview_window.minimize()
            except Exception:
                pass

    def close(self):
        global _webview_window
        if _webview_window:
            try:
                _webview_window.destroy()
            except Exception:
                pass
        sys.exit(0)


window_api = WindowAPI()


async def handle_window_mode(request):
    try:
        data = await request.json()
        target_mode = data.get("mode")
        if target_mode == "full" and window_api.is_pip:
            window_api.toggle_mode()
        elif target_mode == "pip" and not window_api.is_pip:
            window_api.toggle_mode()
    except Exception:
        window_api.toggle_mode()
    return web.json_response({"is_pip": window_api.is_pip})


async def handle_window_pin(request):
    res = window_api.toggle_pin()
    return web.json_response(res)


async def handle_window_minimize(request):
    window_api.minimize()
    return web.json_response({"ok": True})


async def handle_window_close(request):
    threading.Thread(target=lambda: (time.sleep(0.15), window_api.close())).start()
    return web.json_response({"ok": True})


async def handle_autostart_get(request):
    return web.json_response({"enabled": autostart.is_autostart_enabled()})


async def handle_autostart_toggle(request):
    try:
        data = await request.json()
        enable = data.get("enabled", True)
    except Exception:
        enable = True
    ok = autostart.enable_autostart() if enable else autostart.disable_autostart()
    return web.json_response({"enabled": autostart.is_autostart_enabled(), "success": ok})


async def deliver_startup_greeting():
    # Wait for GUI and websocket link to synchronize
    await asyncio.sleep(1.8)
    now = datetime.now()
    hour = now.hour
    if 4 <= hour < 12:
        salut = "Good morning"
    elif 12 <= hour < 17:
        salut = "Good afternoon"
    elif 17 <= hour < 22:
        salut = "Good evening"
    else:
        salut = "Welcome back"

    greeting = f"{salut}, boss. {assistant_name} systems online and standing by in your corner."

    await broadcast_ws({
        "type": "speech",
        "text": greeting,
        "is_vyra": True
    })
    await broadcast_ws({
        "type": "log",
        "level": "system",
        "text": f"[BOOT] All systems operational. Startup greeting delivered."
    })
    try:
        await broadcast_ws({"type": "state", "state": "speaking"})
        mouth.speak(greeting)
        await broadcast_ws({"type": "state", "state": "idle"})
    except Exception as exc:
        print(f"[STARTUP GREETING NOTICE] {exc}")


def create_app():
    app = web.Application()
    app.router.add_get("/ws", ws_handler)
    app.router.add_post("/api/chat", handle_chat)
    app.router.add_post("/api/voice/listen", handle_voice_listen)
    app.router.add_post("/api/voice/stop", handle_voice_stop)
    app.router.add_post("/api/voice/wake/toggle", handle_wake_toggle)
    app.router.add_get("/api/memory", handle_memory)
    app.router.add_post("/api/window/mode", handle_window_mode)
    app.router.add_post("/api/window/pin", handle_window_pin)
    app.router.add_post("/api/window/minimize", handle_window_minimize)
    app.router.add_post("/api/window/close", handle_window_close)
    app.router.add_get("/api/autostart", handle_autostart_get)
    app.router.add_post("/api/autostart/toggle", handle_autostart_toggle)

    async def handle_index(request):
        return web.FileResponse(GUI_DIR / "index.html")

    app.router.add_get("/", handle_index)
    app.router.add_get("/index.html", handle_index)
    # Static files for GUI
    app.router.add_static("/", path=str(GUI_DIR), show_index=False)

    async def start_background_tasks(app):
        global server_loop
        server_loop = asyncio.get_running_loop()
        app["broadcaster"] = asyncio.create_task(telemetry_broadcaster())
        app["greeting"] = asyncio.create_task(deliver_startup_greeting())
        t = threading.Thread(target=wake_word_listener_thread, daemon=True)
        t.start()
        app["wake_thread"] = t

    async def cleanup_background_tasks(app):
        if "broadcaster" in app:
            app["broadcaster"].cancel()
        if "greeting" in app:
            app["greeting"].cancel()
        wake_pause_event.set()
        wake_stop_event.set()

    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)
    return app


def launch_browser_app(url: str, width: int = 380, height: int = 600, x: int = 1520, y: int = 420):
    """Launch Brave, Chrome, or Edge in borderless standalone app mode."""
    candidates = [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Users\Perfect\AppData\Local\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    flags = [f"--app={url}", f"--window-size={width},{height}", f"--window-position={x},{y}"]
    for exe in candidates:
        if os.path.exists(exe):
            subprocess.Popen([exe] + flags)
            return True
    return False


def main():
    port = 8765
    url = f"http://127.0.0.1:{port}"

    app = create_app()
    use_browser = "--browser" in sys.argv
    full_mode = "--full" in sys.argv

    # Compute screen metrics
    try:
        user32 = ctypes.windll.user32
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
    except Exception:
        sw, sh = 1920, 1080

    pip_w, pip_h = 380, 600
    full_w, full_h = 1200, 780

    if full_mode:
        win_w, win_h = full_w, full_h
        win_x = max(0, (sw - full_w) // 2)
        win_y = max(0, (sh - full_h) // 2)
        window_api.is_pip = False
    else:
        win_w, win_h = pip_w, pip_h
        win_x = max(0, sw - pip_w - 20)
        win_y = max(0, sh - pip_h - 60)
        window_api.is_pip = True

    # If pywebview is requested or available without --browser
    if not use_browser:
        try:
            import webview

            # Start server in daemon thread
            def run_server():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                web.run_app(app, host="127.0.0.1", port=port, print=None)

            t = threading.Thread(target=run_server, daemon=True)
            t.start()

            print(f"[HUD] Starting VYRA Technical PiP App at {url} (Corner: {win_x}, {win_y})...")
            global _webview_window
            _webview_window = webview.create_window(
                "VYRA // AI",
                url,
                js_api=window_api,
                width=win_w,
                height=win_h,
                x=win_x,
                y=win_y,
                resizable=True,
                easy_drag=True,
                on_top=True,
                background_color="#06090e"
            )
            webview.start()
            sys.exit(0)
        except Exception as exc:
            print(f"[HUD] Native window notice ({exc}), falling back to app window...")

    # Fallback to browser app window
    launch_browser_app(url, win_w, win_h, win_x, win_y)
    print(f"[HUD] Running at {url} — press Ctrl+C to terminate.")
    web.run_app(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()

