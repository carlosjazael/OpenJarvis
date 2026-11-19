"""Tests for the XTTS HTTP voice backend (no real server needed)."""

from __future__ import annotations

import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import soundfile as sf

from openjarvis.speech import xtts_http


def test_build_request_speaker_or_reference():
    assert xtts_http.build_request("Hola", "Tanja Adelina", 1.0, "es") == {
        "text": "Hola",
        "language": "es",
        "speed": 1.0,
        "speaker": "Tanja Adelina",
    }
    body = xtts_http.build_request("Hola", r"C:\voces\mia.wav", 0.9, "es")
    assert body["speaker_wav"] == r"C:\voces\mia.wav" and "speaker" not in body


def test_synthesize_against_fake_server(monkeypatch):
    seen: dict = {}
    buf = io.BytesIO()
    sf.write(buf, np.zeros(2400, dtype="float32"), 24000, format="WAV")
    wav = buf.getvalue()

    class H(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            seen.update(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Length", str(len(wav)))
            self.end_headers()
            self.wfile.write(wav)

        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("OPENJARVIS_XTTS_URL", f"http://127.0.0.1:{server.server_port}")
    try:
        backend = xtts_http.XTTSHttpBackend()
        assert backend.health()
        result = backend.synthesize("Hola, Carlos.")
    finally:
        server.shutdown()
    assert seen["speaker"] == "Tanja Adelina" and seen["language"] == "es"
    assert result.format == "wav" and result.sample_rate == 24000
    assert abs(result.duration_seconds - 0.1) < 0.01


def test_health_false_without_server(monkeypatch):
    monkeypatch.setenv("OPENJARVIS_XTTS_URL", "http://127.0.0.1:9")
    assert xtts_http.XTTSHttpBackend().health() is False


def test_voice_id_tuning_suffix():
    body = xtts_http.build_request(
        "Hola", "Tanja Adelina;speed=0.9;temperature=0.85", 1.0, "es"
    )
    assert body["speaker"] == "Tanja Adelina"
    assert body["speed"] == 0.9 and body["temperature"] == 0.85
