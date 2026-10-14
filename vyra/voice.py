"""VYRA's voice — Phase 2. Local ears (faster-whisper) + Edge-TTS mouth.

Heavy audio deps live in requirements-voice.txt.
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
import time
import collections
import threading
from pathlib import Path

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
BLOCK = 800                   # 0.05s (50ms) audio blocks
DEFAULT_START_RMS = 0.006     # Speech start detection threshold
DEFAULT_SILENCE_RMS = 0.0035  # Trailing silence threshold
DEFAULT_INITIAL_TIMEOUT = 10.0 # Allow up to 10s for speaker to begin talking
DEFAULT_TRAIL_SILENCE = 1.25   # 1250ms trailing silence allows natural Indian pauses
DEFAULT_MAX_SECONDS = 40.0    # Utterance hard limit
PRE_BUFFER_BLOCKS = 14        # 700ms pre-speech audio buffer so onset words are never clipped


def _rms(block: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(block))) + 1e-9)


def compute_spectrum(block: np.ndarray, num_bins: int = 32) -> list[float]:
    """Compute normalized frequency spectrum bins from audio chunk using real FFT."""
    try:
        fft = np.abs(np.fft.rfft(block))
        if len(fft) < num_bins:
            return [0.0] * num_bins
        chunk_size = len(fft) // num_bins
        bins = []
        for i in range(num_bins):
            start = i * chunk_size
            end = min(len(fft), (i + 1) * chunk_size)
            val = float(np.mean(fft[start:end])) if end > start else 0.0
            norm_val = min(1.0, max(0.0, val * 3.5))
            bins.append(round(norm_val, 3))
        return bins
    except Exception:
        return [0.0] * num_bins


def record_until_silence(
    push_to_talk: bool = False,
    initial_timeout: float = DEFAULT_INITIAL_TIMEOUT,
    trail_silence: float = DEFAULT_TRAIL_SILENCE,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    stop_event: threading.Event | None = None,
    level_callback: callable | None = None,
) -> np.ndarray | None:
    """Listen on the mic; wait for user to speak, and return mono float32 audio when done."""
    frames = []
    pre_buffer = collections.deque(maxlen=PRE_BUFFER_BLOCKS)
    has_spoken = False
    silent_for = 0.0
    start = time.time()

    start_rms = DEFAULT_START_RMS
    silence_rms = DEFAULT_SILENCE_RMS
    ambient_samples = []

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                        blocksize=BLOCK) as stream:
        while True:
            # Check external manual stop or cancel
            if stop_event and stop_event.is_set():
                break

            block, _ = stream.read(BLOCK)
            block = block.reshape(-1)
            level = _rms(block)

            # Sample first 8 blocks to calibrate ambient noise floor accurately
            if len(ambient_samples) < 8:
                ambient_samples.append(level)
                if len(ambient_samples) == 8:
                    floor = float(np.median(ambient_samples))
                    if floor < 0.01:
                        start_rms = max(DEFAULT_START_RMS, floor * 2.8)
                        silence_rms = max(DEFAULT_SILENCE_RMS, floor * 1.6)

            if level_callback:
                try:
                    spec = compute_spectrum(block, 32) if (level > 0.002 or has_spoken) else None
                    level_callback(level, has_spoken, spec)
                except TypeError:
                    level_callback(level, has_spoken)
                except Exception:
                    pass

            if not has_spoken:
                pre_buffer.append(block)
                if level >= start_rms:
                    has_spoken = True
                    frames = list(pre_buffer)  # preserve onset speech
                    silent_for = 0.0
                elif time.time() - start > initial_timeout:
                    return None
                continue

            frames.append(block)
            if level < silence_rms:
                silent_for += (BLOCK / SAMPLE_RATE)
            else:
                silent_for = 0.0

            if silent_for >= trail_silence or time.time() - start > max_seconds:
                break

    if has_spoken and frames:
        concatenated = np.concatenate(frames)
        if len(concatenated) >= 4000:  # at least 0.25s of speech
            return concatenated
    return None


DEFAULT_WAKE_WORDS = [
    "friday", "fraiday", "fridey", "phriday", "priday", "fryday",
    "buddy", "badi", "jarvis", "vyra", "vira", "viera"
]


def detect_wake_word(
    text: str,
    wake_words: list[str] | None = None
) -> tuple[bool, str, str]:
    """
    Check if an utterance contains a wake phrase (e.g. 'Hey FRIDAY', 'FRIDAY', 'Hey buddy', 'Buddy', 'Jarvis').
    Returns (is_wake: bool, wake_phrase: str, command: str).
    """
    if not text:
        return False, "", ""

    words = wake_words or DEFAULT_WAKE_WORDS
    pattern = re.compile(
        r'\b((?:hey|hi|hello|ok|okay|yo)\s+)?(' + '|'.join(re.escape(w) for w in words) + r'|fri\s*day|frai\s*day|phri\s*day)\b',
        re.IGNORECASE
    )

    for match in pattern.finditer(text):
        start = match.start()
        before_text = text[:start].strip()
        last_word = before_text.split()[-1].lower() if before_text else ""
        if last_word in ("my", "his", "her", "their", "our", "a", "an", "any"):
            continue

        wake_phrase = match.group().strip()
        after = text[match.end():].strip(" ,.!?-")
        before = text[:start].strip(" ,.!?-")
        command = after if after else before
        return True, wake_phrase, command

    return False, "", ""


def normalize_indian_phonetics(text: str) -> str:
    """Normalize common speech-to-text phonetic misrecognitions for Indian English."""
    if not text:
        return ""
    # Raaga music app variations
    text = re.sub(r'\b(?:raaga|raga|ragaa|raagha|ragga)\s+app\b', 'Raaga app', text, flags=re.IGNORECASE)
    text = re.sub(r'\b(?:raaga|raga|ragaa|raagha|ragga)\b', 'Raaga', text, flags=re.IGNORECASE)
    # Antigravity IDE
    text = re.sub(r'\b(?:anti\s*gravity|anti-gravity|antigraviti)\b', 'Antigravity', text, flags=re.IGNORECASE)
    # Rusty name (common speech-to-text mis-hears)
    text = re.sub(r'\b(?:rusti|rusdy|rasty|rustie|trusty|dusty|rusty\'s)\b', 'Rusty', text, flags=re.IGNORECASE)
    # Claude / Claude Code misrecognitions
    text = re.sub(r'\b(?:claud|claud code|cloud code)\b', 'Claude Code', text, flags=re.IGNORECASE)
    # WhatsApp / Telegram
    text = re.sub(r'\b(?:whats\s*app|what\s*app)\b', 'WhatsApp', text, flags=re.IGNORECASE)
    text = re.sub(r'\b(?:tele\s*gram)\b', 'Telegram', text, flags=re.IGNORECASE)
    # Common system actions
    text = re.sub(r'\b(?:screanshot|screen\s*shot)\b', 'screenshot', text, flags=re.IGNORECASE)
    return text.strip()


def _add_cuda_dll_dirs():
    """On Windows, make pip-installed CUDA libs (nvidia-cublas-cu12,
    nvidia-cudnn-cu12, nvidia-cuda-runtime-cu12, ...) discoverable so
    faster-whisper/CTranslate2 can use the GPU. Adds every nvidia/*/bin to the
    DLL search path AND prepends them to PATH (CTranslate2's loader uses PATH)."""
    if os.name != "nt":
        return
    try:
        import importlib.util as iu
        spec = iu.find_spec("nvidia")
        roots = list(spec.submodule_search_locations) if (spec and spec.submodule_search_locations) else []
        bins = []
        for root in roots:
            for sub in os.listdir(root):
                binp = os.path.join(root, sub, "bin")
                if os.path.isdir(binp):
                    bins.append(binp)
        for binp in bins:
            try:
                os.add_dll_directory(binp)
            except Exception:
                pass
        if bins:
            os.environ["PATH"] = os.pathsep.join(bins) + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass


class Ears:
    """Speech-to-text with faster-whisper. Multilingual (English + Hindi/Hinglish),
    tuned for an Indian accent, with automatic GPU->CPU fallback."""

    def __init__(self, model_size: str = "small", device: str = "auto", compute_type: str | None = None):
        if device in ("auto", "cuda"):
            _add_cuda_dll_dirs()
        from faster_whisper import WhisperModel
        attempts = []
        if device in ("auto", "cuda"):
            attempts.append(("cuda", "float16"))
        attempts.append(("cpu", "int8"))
        self.model, self.device, last = None, "cpu", None
        for dev, ct in attempts:
            try:
                model = WhisperModel(model_size, device=dev, compute_type=compute_type or ct)
                if dev == "cuda":
                    # Loading can succeed while inference still fails if the CUDA
                    # math libs (cuBLAS/cuDNN) are missing — verify with a tiny
                    # run and fall back to CPU rather than hang at first use.
                    list(model.transcribe(np.zeros(1600, dtype="float32"), beam_size=1)[0])
                self.model, self.device = model, dev
                break
            except Exception as exc:
                last = exc
        if self.model is None:
            raise last

    def transcribe(self, audio: np.ndarray) -> str:
        # language=None lets Whisper auto-detect English, Hindi, or mixed Hinglish.
        segments, _ = self.model.transcribe(
            audio,
            language=None,
            beam_size=2,
            initial_prompt="Jay, Jayesh, Rusty, Rusty's, Friday, Raaga, Raaga app, Antigravity, YouTube, Brave, WhatsApp, Telegram, music, volume, songs, battery, clipboard, buddy, Jarvis. Indian English, Hindi, and Hinglish.",
            condition_on_previous_text=False,
        )
        raw_text = " ".join(s.text for s in segments).strip()
        return normalize_indian_phonetics(raw_text)


def _has_devanagari(text: str) -> bool:
    return any('ऀ' <= c <= 'ॿ' for c in text)


def _parse_rate(s) -> int:
    try:
        return int(str(s).replace('%', '').replace('+', '').strip())
    except (ValueError, TypeError):
        return 10


def _prosody(text: str, base_rate: int):
    """Light emotional colouring: brighter on excitement, softer on bad news."""
    rate, pitch = base_rate, 0
    low = text.lower()
    if '!' in text:
        rate += 6; pitch += 3
    if any(w in low for w in ("sorry", "unfortunately", "afraid", "couldn't", "can't", "cannot")):
        rate -= 4; pitch -= 2
    rate = max(-20, min(40, rate))
    return (f"{'+' if rate >= 0 else ''}{rate}%", f"{'+' if pitch >= 0 else ''}{pitch}Hz")


def _split_sentences(text: str) -> list:
    parts = re.split(r'(?<=[.!?।])\s+', text)
    return [p.strip() for p in parts if p.strip()]


_PIPER_DIR = Path(__file__).resolve().parent.parent / "data" / "piper"


def _find_piper_model(explicit=None):
    if explicit and os.path.exists(explicit):
        return explicit
    try:
        models = sorted(_PIPER_DIR.glob("*.onnx"))
        return str(models[0]) if models else None
    except Exception:
        return None


class _PiperEngine:
    """Offline, instant neural TTS for short confirmations."""

    def __init__(self, model_path):
        from piper import PiperVoice
        self.voice = PiperVoice.load(str(model_path))

    def synth(self, text, out_path):
        import wave
        with wave.open(str(out_path), "wb") as wf:
            self.voice.synthesize_wav(text, wf)

    def warm(self):
        try:
            p = Path(tempfile.gettempdir()) / f"piper_warm_{os.getpid()}.wav"
            self.synth("ready", p)
            p.unlink(missing_ok=True)
        except Exception:
            pass


class Mouth:
    """Text-to-speech with Edge-TTS (free) + pygame playback.
    Streams long replies sentence-by-sentence so speech starts sooner, adds light
    emotional prosody, and switches to a Hindi voice for Devanagari text."""

    def __init__(self, voice: str = "en-US-GuyNeural", rate: str = "+19%",
                 pronounce_vyra: str = "Rusty", voice_hindi: str | None = None,
                 piper_model: str | None = None, use_piper: bool = True):
        import pygame
        self.voice = voice
        self.voice_hindi = voice_hindi
        self.rate = rate
        self.pronounce_name = pronounce_vyra
        self._pygame = pygame
        self._interrupt = threading.Event()
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        # Optional instant-local engine for short confirmations (off → one Edge voice).
        self._piper = None
        if use_piper:
            try:
                mp = _find_piper_model(piper_model)
                if mp:
                    self._piper = _PiperEngine(mp)
                    threading.Thread(target=self._piper.warm, daemon=True).start()
            except Exception:
                self._piper = None

    def _prepare_text(self, text: str) -> str:
        """Strip markdown syntax and fix phonetic pronunciation of names."""
        cleaned = re.sub(r'[*_`#~]', '', text)
        cleaned = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', cleaned)
        if self.pronounce_name:
            cleaned = re.sub(r'\bVYRA\b', self.pronounce_name, cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    def stop(self):
        """Interrupt any in-progress speech (barge-in)."""
        self._interrupt.set()
        try:
            music = self._pygame.mixer.music
            if music.get_busy():
                music.stop()
                music.unload()
        except Exception:
            pass

    def speak(self, text: str):
        clean_text = self._prepare_text(text)
        if not clean_text:
            return
        self._interrupt.clear()
        # Hindi (Devanagari) → natural Edge Hindi voice.
        if self.voice_hindi and _has_devanagari(clean_text):
            self._speak_edge(clean_text, self.voice_hindi)
            return
        # Short confirmations → instant local Piper; longer replies → natural Edge.
        if self._piper and len(clean_text) <= 90:
            if self._speak_piper(clean_text):
                return
        self._speak_edge(clean_text, self.voice)

    def _speak_piper(self, text: str) -> bool:
        ts = int(time.time() * 1000)
        path = Path(tempfile.gettempdir()) / f"voice_{os.getpid()}_{ts}.wav"
        try:
            self._piper.synth(text, path)
            if not self._interrupt.is_set():
                self._play(path)
            return True
        except Exception:
            return False
        finally:
            try:
                if path.exists():
                    path.unlink()
            except Exception:
                pass

    def _run_async(self, coro):
        """Safely execute an async coroutine even if an event loop is running on the current thread."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
        else:
            return asyncio.run(coro)

    def _speak_edge(self, text: str, voice: str):
        base = _parse_rate(self.rate)
        # Stream long replies sentence-by-sentence so the first words start quickly.
        chunks = _split_sentences(text) if len(text) > 140 else [text]
        for chunk in chunks:
            if self._interrupt.is_set():
                break
            rate, pitch = _prosody(chunk, base)
            ts = int(time.time() * 1000)
            path = Path(tempfile.gettempdir()) / f"voice_{os.getpid()}_{ts}.mp3"
            try:
                self._run_async(self._synth(chunk, path, voice, rate, pitch))
                if self._interrupt.is_set():
                    break
                self._play(path)
            except Exception:
                pass
            finally:
                try:
                    if path.exists():
                        path.unlink()
                except Exception:
                    pass

    async def _synth(self, text: str, path: Path, voice: str, rate: str, pitch: str):
        import edge_tts
        await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(str(path))

    def _play(self, path: Path):
        music = self._pygame.mixer.music
        music.load(str(path))
        music.play()
        while music.get_busy():
            if self._interrupt.is_set():
                music.stop()
                break
            time.sleep(0.05)
        music.unload()
