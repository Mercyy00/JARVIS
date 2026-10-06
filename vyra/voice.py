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
DEFAULT_START_RMS = 0.007     # Speech start detection threshold
DEFAULT_SILENCE_RMS = 0.004   # Trailing silence threshold
DEFAULT_INITIAL_TIMEOUT = 10.0 # Allow up to 10s for speaker to begin talking
DEFAULT_TRAIL_SILENCE = 1.6   # 1600ms trailing silence allows natural Indian pauses and mid-sentence thinking
DEFAULT_MAX_SECONDS = 35.0    # Utterance hard limit
PRE_BUFFER_BLOCKS = 10        # 500ms pre-speech audio buffer so onset words are not clipped


def _rms(block: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(block))) + 1e-9)


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

            # Sample first 4 blocks to calibrate ambient noise floor if user is quiet
            if len(ambient_samples) < 4:
                ambient_samples.append(level)
                if len(ambient_samples) == 4:
                    floor = float(np.median(ambient_samples))
                    if floor < 0.008:
                        start_rms = max(DEFAULT_START_RMS, floor * 3.0)
                        silence_rms = max(DEFAULT_SILENCE_RMS, floor * 1.8)

            if level_callback:
                try:
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
    # FRIDAY name
    text = re.sub(r'\b(?:fri\s*day|frai\s*day|fridey|fraidey|priday|phriday)\b', 'Friday', text, flags=re.IGNORECASE)
    return text.strip()


class Ears:
    """Speech-to-text with faster-whisper, running locally with Indian English tuning."""

    def __init__(self, model_size: str = "base", device: str = "cpu", compute_type: str = "int8"):
        from faster_whisper import WhisperModel
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, audio: np.ndarray) -> str:
        # beam_size=1 provides fast decoding, initial_prompt provides vocabulary biasing for Indian English
        segments, _ = self.model.transcribe(
            audio,
            language="en",
            beam_size=1,
            initial_prompt="Jay, Jayesh, FRIDAY, Friday, Raga, Raaga, Raaga app, Indian English, Antigravity, YouTube, Brave, music, volume, desktop, songs, playlist, Mark, battery, clipboard, directive, buddy, Jarvis.",
            condition_on_previous_text=False
        )
        raw_text = " ".join(s.text for s in segments).strip()
        return normalize_indian_phonetics(raw_text)


class Mouth:
    """Text-to-speech with Edge-TTS (free) + pygame playback."""

    def __init__(self, voice: str = "en-US-GuyNeural", rate: str = "+10%", pronounce_vyra: str = "Friday"):
        import pygame
        self.voice = voice
        self.rate = rate
        self.pronounce_name = pronounce_vyra
        self._pygame = pygame
        if not pygame.mixer.get_init():
            pygame.mixer.init()

    def _prepare_text(self, text: str) -> str:
        """Strip markdown syntax and fix phonetic pronunciation of names."""
        cleaned = re.sub(r'[*_`#~]', '', text)
        cleaned = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', cleaned)
        if self.pronounce_name:
            cleaned = re.sub(r'\bVYRA\b', self.pronounce_name, cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    def stop(self):
        """Immediately stop and unload any active speech playback."""
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
        ts = int(time.time() * 1000)
        path = Path(tempfile.gettempdir()) / f"voice_{os.getpid()}_{ts}.mp3"
        try:
            asyncio.run(self._synth(clean_text, path))
            self._play(path)
        finally:
            try:
                if path.exists():
                    path.unlink()
            except Exception:
                pass

    async def _synth(self, text: str, path: Path):
        import edge_tts
        await edge_tts.Communicate(text, self.voice, rate=self.rate).save(str(path))

    def _play(self, path: Path):
        music = self._pygame.mixer.music
        music.load(str(path))
        music.play()
        while music.get_busy():
            time.sleep(0.05)
        music.unload()
