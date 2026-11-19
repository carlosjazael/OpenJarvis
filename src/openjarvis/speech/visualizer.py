"""Stream the spectrum of audio being played to the desktop clock widget.

While a reply is played, a daemon thread sends one small UDP datagram per
animation frame to ``127.0.0.1`` with the loudness of ``N_BANDS`` frequency
bands. The widget (``openjarvis.widgets.reloj``) listens on that port and
draws them as a ring of sound waves. Nothing listening is fine: UDP to a
closed local port is silently dropped, and any error here is swallowed so
voice output never breaks because of the visualizer.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_PORT = 47811
FPS = 30
N_BANDS = 36
# Voice energy lives roughly between 80 Hz and 8 kHz.
_F_MIN = 80.0
_F_MAX = 8000.0


def visualizer_port() -> int:
    try:
        return int(os.environ.get("OPENJARVIS_VISUALIZER_PORT", DEFAULT_PORT))
    except ValueError:
        return DEFAULT_PORT


def compute_bands(
    data: Any, sample_rate: int, *, fps: int = FPS, n_bands: int = N_BANDS
) -> Any:
    """Return a ``(frames, n_bands)`` array of levels in ``[0, 1]``.

    Bands are log-spaced between 80 Hz and 8 kHz; levels are in dB relative to
    the loudest band of the whole clip, so quiet and loud voices both fill the
    ring.
    """
    import numpy as np

    samples = np.asarray(data, dtype="float32")
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    hop = max(1, int(sample_rate / fps))
    n_frames = int(np.ceil(len(samples) / hop)) if len(samples) else 0
    if n_frames == 0:
        return np.zeros((0, n_bands), dtype="float32")

    win_len = 2 * hop
    padded = np.concatenate([samples, np.zeros(win_len, dtype="float32")])
    window = np.hanning(win_len).astype("float32")
    frames = np.stack(
        [padded[i * hop : i * hop + win_len] * window for i in range(n_frames)]
    )
    spectrum = np.abs(np.fft.rfft(frames, axis=1))
    freqs = np.fft.rfftfreq(win_len, 1.0 / sample_rate)

    f_max = min(_F_MAX, sample_rate / 2.0)
    edges = np.geomspace(_F_MIN, f_max, n_bands + 1)
    bands = np.zeros((n_frames, n_bands), dtype="float32")
    for b in range(n_bands):
        mask = (freqs >= edges[b]) & (freqs < edges[b + 1])
        if not mask.any():  # very narrow low band: use the nearest bin
            mask = np.zeros_like(freqs, dtype=bool)
            mask[int(np.argmin(np.abs(freqs - edges[b])))] = True
        bands[:, b] = spectrum[:, mask].mean(axis=1)

    peak = float(bands.max())
    if peak <= 0.0:
        return bands
    db = 20.0 * np.log10(np.maximum(bands / peak, 1e-6))
    return np.clip((db + 50.0) / 50.0, 0.0, 1.0).astype("float32")


class _Broadcast:
    def __init__(self, levels: Any, port: int, fps: int) -> None:
        self._levels = levels
        self._port = port
        self._fps = fps
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="voice-visualizer", daemon=True
        )

    def start(self) -> "_Broadcast":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        addr = ("127.0.0.1", self._port)
        try:
            start = time.monotonic()
            for i, row in enumerate(self._levels):
                delay = start + i / self._fps - time.monotonic()
                if delay > 0 and self._stop.wait(delay):
                    break
                if self._stop.is_set():
                    break
                payload = {"b": [int(round(v * 100)) for v in row]}
                try:
                    sock.sendto(json.dumps(payload).encode(), addr)
                except OSError:
                    pass
            try:
                sock.sendto(b'{"end": true}', addr)
            except OSError:
                pass
        finally:
            sock.close()


def start_broadcast(data: Any, sample_rate: int) -> _Broadcast | None:
    """Start streaming *data*'s spectrum in real time; never raises."""
    if os.environ.get("OPENJARVIS_VISUALIZER", "1") == "0":
        return None
    try:
        levels = compute_bands(data, sample_rate)
        return _Broadcast(levels, visualizer_port(), FPS).start()
    except Exception:
        logger.debug("voice visualizer unavailable", exc_info=True)
        return None


def stop_broadcast(handle: _Broadcast | None) -> None:
    if handle is not None:
        try:
            handle.stop()
        except Exception:  # pragma: no cover - best effort
            pass


__all__ = [
    "DEFAULT_PORT",
    "FPS",
    "N_BANDS",
    "compute_bands",
    "start_broadcast",
    "stop_broadcast",
    "visualizer_port",
]
