"""Microsoft Edge neural voices via the ``edge-tts`` package.

Free, no API key, but needs an internet connection. The Mexican Spanish
neural voices (``es-MX-DaliaNeural``) and other Latin American ones sound far more
natural than the local Kokoro Spanish voice.

Requires: pip install edge-tts
"""

from __future__ import annotations

import asyncio
import io
import threading
from typing import List

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSBackend, TTSResult

_DEFAULT_VOICE_ID = (
    "pt-BR-ThalitaMultilingualNeural"  # multilingual; speaks Spanish naturally
)
# Used when the chosen voice returns no audio twice: same service, fast and
# reliable, so a hiccup doesn't drop to a slow local voice mid-reply.
_FALLBACK_VOICE_ID = "es-MX-DaliaNeural"


def _rate_for_speed(speed: float) -> str:
    """Translate a 1.0-based speed multiplier into edge-tts' ``+N%`` rate."""
    pct = round((float(speed) - 1.0) * 100)
    return f"{pct:+d}%"


def _run(coro):
    """Run *coro* to completion even if the caller already has a loop running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    box: dict = {}

    def target() -> None:
        try:
            box["value"] = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - re-raised below
            box["error"] = exc

    thread = threading.Thread(target=target, name="edge-tts", daemon=True)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box["value"]


async def _synthesize_mp3(text: str, voice: str, rate: str) -> bytes:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice, rate=rate)
    chunks: list[bytes] = []
    async for chunk in communicate.stream():
        if chunk.get("type") == "audio":
            chunks.append(chunk["data"])
    return b"".join(chunks)


def _mp3_to_wav(mp3: bytes) -> tuple[bytes, int, float]:
    import soundfile as sf

    data, sample_rate = sf.read(io.BytesIO(mp3), dtype="float32")
    out = io.BytesIO()
    sf.write(out, data, sample_rate, format="WAV")
    return out.getvalue(), int(sample_rate), len(data) / float(sample_rate)


@TTSRegistry.register("edge_tts")
class EdgeTTSBackend(TTSBackend):
    """Microsoft Edge neural TTS — free, online, very natural Spanish voices."""

    backend_id = "edge_tts"

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = _DEFAULT_VOICE_ID,
        speed: float = 1.0,
        output_format: str = "mp3",
    ) -> TTSResult:
        voice = voice_id or _DEFAULT_VOICE_ID
        rate = _rate_for_speed(speed)
        mp3 = b""
        # The service sometimes answers "No audio was received" at random:
        # retry once, then use a steadier voice instead of failing over to
        # another (slower) backend.
        attempts = [voice, voice]
        if voice != _FALLBACK_VOICE_ID:
            attempts.append(_FALLBACK_VOICE_ID)
        last_error: Exception | None = None
        for attempt in attempts:
            try:
                mp3 = _run(_synthesize_mp3(text, attempt, rate))
            except Exception as exc:  # edge_tts.exceptions.NoAudioReceived, etc.
                last_error = exc
                continue
            if mp3:
                voice = attempt
                break
        if not mp3 and last_error is not None:
            raise last_error
        metadata = {"backend": "edge_tts"}
        if output_format.lower() == "wav" and mp3:
            wav, sample_rate, duration = _mp3_to_wav(mp3)
            return TTSResult(
                audio=wav,
                format="wav",
                voice_id=voice,
                sample_rate=sample_rate,
                duration_seconds=duration,
                metadata=metadata,
            )
        return TTSResult(audio=mp3, format="mp3", voice_id=voice, metadata=metadata)

    def available_voices(self) -> List[str]:
        return [
            "es-MX-DaliaNeural",
            "es-US-PalomaNeural",
            "es-CO-SalomeNeural",
            "en-US-AvaMultilingualNeural",
            "pt-BR-ThalitaMultilingualNeural",
            "es-ES-ElviraNeural",
            "es-MX-JorgeNeural",
        ]

    def health(self) -> bool:
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            return False
        return True
