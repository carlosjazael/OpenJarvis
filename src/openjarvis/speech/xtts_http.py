"""XTTS-v2 voices through a small local HTTP server.

XTTS (Coqui, CPML: personal / non-commercial use only) needs its own heavy
environment (PyTorch + ``coqui-tts``), so it runs as a separate process —
``scripts/xtts_server.py`` — that keeps the model loaded on the GPU. This
backend just posts text to it.

``voice_id`` is either a built-in XTTS speaker name ("Tanja Adelina") or the
path to a short reference ``.wav`` of a voice you are allowed to use.
Server address: ``OPENJARVIS_XTTS_URL`` (default ``http://127.0.0.1:47812``).
"""

from __future__ import annotations

import io
import json
import os
import urllib.error
import urllib.request
from typing import List

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSBackend, TTSResult

_DEFAULT_VOICE_ID = "Tanja Adelina"
_DEFAULT_URL = "http://127.0.0.1:47812"


def _base_url() -> str:
    return os.environ.get("OPENJARVIS_XTTS_URL", _DEFAULT_URL).rstrip("/")


def build_request(text: str, voice_id: str, speed: float, language: str) -> dict:
    """Build the server request; ``voice_id`` may carry tuning after ``;``.

    ``"Tanja Adelina;speed=0.9;temperature=0.85"`` → slower, warmer delivery
    (temperature = more intonation variety; XTTS default 0.75).
    """
    voice, _, extra = (voice_id or _DEFAULT_VOICE_ID).partition(";")
    voice = voice.strip() or _DEFAULT_VOICE_ID
    body: dict = {"text": text, "language": language, "speed": float(speed)}
    for part in extra.split(";"):
        key, _, value = part.partition("=")
        key = key.strip().lower()
        try:
            if key == "speed":
                body["speed"] = float(speed) * float(value)
            elif key == "temperature":
                body["temperature"] = float(value)
        except ValueError:
            continue
    if voice.lower().endswith(".wav"):
        body["speaker_wav"] = voice
    else:
        body["speaker"] = voice
    return body


@TTSRegistry.register("xtts")
class XTTSHttpBackend(TTSBackend):
    """Natural local voices via XTTS-v2 running in ``scripts/xtts_server.py``."""

    backend_id = "xtts"

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = _DEFAULT_VOICE_ID,
        speed: float = 1.0,
        output_format: str = "wav",
        language: str = "es",
    ) -> TTSResult:
        body = json.dumps(build_request(text, voice_id, speed, language)).encode()
        req = urllib.request.Request(
            _base_url() + "/tts",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            wav = resp.read()
        sample_rate = 24000
        duration = 0.0
        try:
            import soundfile as sf

            info = sf.info(io.BytesIO(wav))
            sample_rate, duration = int(info.samplerate), float(info.duration)
        except Exception:
            pass
        return TTSResult(
            audio=wav,
            format="wav",
            voice_id=voice_id or _DEFAULT_VOICE_ID,
            sample_rate=sample_rate,
            duration_seconds=duration,
            metadata={"backend": "xtts"},
        )

    def available_voices(self) -> List[str]:
        try:
            with urllib.request.urlopen(_base_url() + "/voices", timeout=3) as r:
                return list(json.loads(r.read()))
        except (urllib.error.URLError, OSError, ValueError):
            return [_DEFAULT_VOICE_ID]

    def health(self) -> bool:
        try:
            with urllib.request.urlopen(_base_url() + "/health", timeout=2) as r:
                return 200 <= r.status < 300
        except (urllib.error.URLError, OSError):
            return False
