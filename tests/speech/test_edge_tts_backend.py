"""Tests for the edge-tts backend, with the network client stubbed out."""

from __future__ import annotations

import io
import sys
import types

import numpy as np
import pytest
import soundfile as sf

from openjarvis.speech import edge_tts_backend as mod


def _fake_edge_tts(monkeypatch, payload: bytes, seen: dict):
    class Communicate:
        def __init__(self, text, voice, rate="+0%"):
            seen.update(text=text, voice=voice, rate=rate)

        async def stream(self):
            yield {"type": "WordBoundary"}
            yield {"type": "audio", "data": payload[:10]}
            yield {"type": "audio", "data": payload[10:]}

    monkeypatch.setitem(
        sys.modules, "edge_tts", types.SimpleNamespace(Communicate=Communicate)
    )


def _wav_bytes() -> bytes:
    buf = io.BytesIO()
    sf.write(buf, np.zeros(2400, dtype="float32"), 24000, format="WAV")
    return buf.getvalue()


@pytest.mark.parametrize(
    ("speed", "rate"), [(1.0, "+0%"), (1.2, "+20%"), (0.8, "-20%")]
)
def test_rate_for_speed(speed, rate):
    assert mod._rate_for_speed(speed) == rate


def test_synthesize_defaults_to_thalita_and_joins_audio(monkeypatch):
    seen: dict = {}
    _fake_edge_tts(monkeypatch, b"0123456789abcdef", seen)
    result = mod.EdgeTTSBackend().synthesize("Hola", voice_id="", speed=1.1)
    assert seen == {
        "text": "Hola",
        "voice": "pt-BR-ThalitaMultilingualNeural",
        "rate": "+10%",
    }
    assert result.audio == b"0123456789abcdef"
    assert result.format == "mp3"


def test_synthesize_wav_is_decodable(monkeypatch):
    # soundfile decodes the stubbed payload, standing in for the real mp3.
    _fake_edge_tts(monkeypatch, _wav_bytes(), {})
    result = mod.EdgeTTSBackend().synthesize(
        "Hola", voice_id="es-MX-RenataNeural", output_format="wav"
    )
    data, sample_rate = sf.read(io.BytesIO(result.audio))
    assert result.format == "wav"
    assert sample_rate == 24000
    assert len(data) == 2400
    assert result.voice_id == "es-MX-RenataNeural"


def test_health_reflects_package(monkeypatch):
    monkeypatch.setitem(sys.modules, "edge_tts", types.SimpleNamespace())
    assert mod.EdgeTTSBackend().health() is True
    monkeypatch.setitem(sys.modules, "edge_tts", None)
    assert mod.EdgeTTSBackend().health() is False


def test_backend_id_and_female_default():
    from openjarvis.speech._tts_discovery import TTS_BACKEND_ORDER, default_voice_for

    assert mod.EdgeTTSBackend.backend_id == "edge_tts"
    assert "edge_tts" in TTS_BACKEND_ORDER
    assert default_voice_for("edge_tts") == "pt-BR-ThalitaMultilingualNeural"


def test_retries_then_falls_back_to_dalia(monkeypatch):
    from openjarvis.speech import edge_tts_backend as mod

    calls: list[str] = []

    async def flaky(text, voice, rate, pitch="+0Hz"):
        calls.append(voice)
        if voice == "pt-BR-ThalitaMultilingualNeural":
            raise RuntimeError("No audio was received")
        return b"audio"

    monkeypatch.setattr(mod, "_synthesize_mp3", flaky)
    result = mod.EdgeTTSBackend().synthesize("Hola")
    assert calls == [
        "pt-BR-ThalitaMultilingualNeural",
        "pt-BR-ThalitaMultilingualNeural",
        "es-MX-DaliaNeural",
    ]
    assert result.voice_id == "es-MX-DaliaNeural" and result.audio == b"audio"


def test_pitch_suffix_in_voice_id(monkeypatch):
    from openjarvis.speech import edge_tts_backend as mod

    seen: dict = {}

    async def fake(text, voice, rate, pitch="+0Hz"):
        seen.update(voice=voice, pitch=pitch)
        return b"audio"

    monkeypatch.setattr(mod, "_synthesize_mp3", fake)
    mod.EdgeTTSBackend().synthesize("Hola", voice_id="es-MX-DaliaNeural;pitch=-8Hz")
    assert seen == {"voice": "es-MX-DaliaNeural", "pitch": "-8Hz"}
