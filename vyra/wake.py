"""Always-on wake-word detection with openWakeWord.

Instant, fully-local keyword spotting (~80ms frames) that replaces the old
"record 5s then transcribe with Whisper" wake path. It fires a callback the
moment it hears the trigger (default: the pretrained "hey jarvis" model).

The listener cooperatively releases the microphone whenever it's paused (while
Rusty is actively recording a command or speaking), so it never fights the
recorder for the device.
"""

from __future__ import annotations

import threading
import time

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
FRAME = 1280  # 80 ms at 16 kHz — the chunk size openWakeWord expects


class WakeListener:
    def __init__(self, on_wake, model: str = "hey_jarvis_v0.1", threshold: float = 0.5,
                 enabled_fn=None, pause_fn=None):
        from openwakeword.model import Model
        import openwakeword
        import os
        # Only hit the network if the shared feature models are missing — keeps
        # startup instant and offline-safe once everything is downloaded.
        mdir = os.path.join(os.path.dirname(openwakeword.__file__), "resources", "models")
        have_features = (os.path.exists(os.path.join(mdir, "melspectrogram.onnx"))
                         and os.path.exists(os.path.join(mdir, "embedding_model.onnx")))
        if not have_features:
            try:
                openwakeword.utils.download_models()
            except Exception:
                pass
        self.model = Model(wakeword_models=[model], inference_framework="onnx")
        self.on_wake = on_wake
        self.threshold = threshold
        self.enabled_fn = enabled_fn or (lambda: True)
        self.pause_fn = pause_fn or (lambda: False)
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        stream = None
        print("[WAKE] openWakeWord listening (say 'Hey Jarvis').")
        while not self._stop.is_set():
            try:
                # Release the mic while paused/disabled so the recorder can use it.
                if not self.enabled_fn() or self.pause_fn():
                    if stream is not None:
                        stream.stop(); stream.close(); stream = None
                        try:
                            self.model.reset()
                        except Exception:
                            pass
                    time.sleep(0.08)
                    continue

                if stream is None:
                    stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                            dtype="int16", blocksize=FRAME)
                    stream.start()

                data, _ = stream.read(FRAME)
                audio = np.frombuffer(data, dtype=np.int16).reshape(-1)
                scores = self.model.predict(audio)
                if scores and max(scores.values()) >= self.threshold:
                    try:
                        self.model.reset()
                    except Exception:
                        pass
                    # Hand off; the recorder will take the mic, so drop our stream.
                    if stream is not None:
                        stream.stop(); stream.close(); stream = None
                    try:
                        self.on_wake()
                    except Exception as exc:
                        print(f"[WAKE] on_wake error: {exc}")
                    time.sleep(0.8)  # debounce
            except Exception as exc:
                print(f"[WAKE] listener error: {exc}")
                if stream is not None:
                    try:
                        stream.stop(); stream.close()
                    except Exception:
                        pass
                    stream = None
                time.sleep(0.4)
        if stream is not None:
            try:
                stream.stop(); stream.close()
            except Exception:
                pass
