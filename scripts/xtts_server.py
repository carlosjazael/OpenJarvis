"""Tiny local XTTS-v2 server for Kasandra (OpenJarvis ``xtts`` voice backend).

Run it from its own environment (it needs PyTorch + coqui-tts):

    python scripts/xtts_server.py            # http://127.0.0.1:47812

XTTS-v2 is under the Coqui Public Model License: personal, non-commercial
use only (set COQUI_TOS_AGREED=1 once you have accepted it).

Endpoints:
    GET  /health            -> 200 when the model is loaded
    GET  /voices            -> JSON list of built-in speakers
    POST /tts  {"text", "language"="es", "speaker" | "speaker_wav", "speed"=1.0,
               "temperature"=0.75}
                            -> audio/wav
"""

from __future__ import annotations

import argparse
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"

_tts = None
_lock = threading.Lock()


def _load(device: str):
    global _tts
    from TTS.api import TTS  # coqui-tts

    _tts = TTS(MODEL_NAME).to(device)


def _synthesize(body: dict) -> bytes:
    import numpy as np
    import soundfile as sf

    kwargs = {
        "text": body["text"],
        "language": body.get("language", "es"),
        "speed": float(body.get("speed", 1.0)),
    }
    if body.get("temperature") is not None:
        kwargs["temperature"] = float(body["temperature"])
    if body.get("speaker_wav"):
        ref = str(body["speaker_wav"])
        # Local .wav files only: a \\server\share path would make Windows
        # try to log in to that server.
        if not ref.lower().endswith(".wav") or ref.startswith(("\\\\", "//")):
            raise ValueError("speaker_wav must be a local .wav file")
        kwargs["speaker_wav"] = body["speaker_wav"]
    else:
        kwargs["speaker"] = body.get("speaker") or "Tanja Adelina"
    with _lock:  # one GPU synthesis at a time
        wav = _tts.tts(**kwargs)
    out = io.BytesIO()
    sf.write(out, np.asarray(wav, dtype="float32"), 24000, format="WAV")
    return out.getvalue()


_LOOPBACK = {"localhost", "127.0.0.1", "::1"}
_MAX_BODY = 64 * 1024


def _host_name(host: str) -> str:
    host = (host or "").strip().lower()
    if host.startswith("["):
        return host[1:].split("]", 1)[0]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


class Handler(BaseHTTPRequestHandler):
    def _refused(self) -> bool:
        """Only local programs may use the voice, never a web page."""
        bad = (
            self.headers.get("Origin")
            or (self.headers.get("Sec-Fetch-Site") or "").lower() == "cross-site"
            or (
                _host_name(self.server.server_address[0]) in _LOOPBACK
                and _host_name(self.headers.get("Host", "")) not in _LOOPBACK
            )
        )
        if bad:
            self._send(403, b"forbidden", "text/plain")
        return bool(bad)

    def _send(self, code: int, data: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self._refused():
            return
        if self.path == "/health":
            ready = _tts is not None
            status = (200, b"ok") if ready else (503, b"loading")
            self._send(status[0], status[1], "text/plain")
        elif self.path == "/voices":
            manager = _tts.synthesizer.tts_model.speaker_manager
            names = json.dumps(list(manager.name_to_id)).encode()
            self._send(200, names, "application/json")
        else:
            self._send(404, b"", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        if self._refused():
            return
        if self.path != "/tts" or _tts is None:
            self._send(404 if self.path != "/tts" else 503, b"", "text/plain")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > _MAX_BODY:
                self._send(413, b"too large", "text/plain")
                return
            body = json.loads(self.rfile.read(length) or b"{}")
            self._send(200, _synthesize(body), "audio/wav")
        except Exception as exc:  # report, keep serving
            self._send(500, str(exc).encode(), "text/plain")

    def log_message(self, *args) -> None:  # quiet
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=47812)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    threading.Thread(target=_load, args=(args.device,), daemon=True).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
