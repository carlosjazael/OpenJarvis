"""Tests for the voice visualizer stream and the desktop clock's pure logic."""

from __future__ import annotations

import json
import socket
from datetime import datetime

import numpy as np

from openjarvis.speech import visualizer
from openjarvis.widgets import reloj


def _tone(freq: float, seconds: float = 0.5, sr: int = 24000) -> np.ndarray:
    t = np.arange(int(seconds * sr)) / sr
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype("float32")


def test_compute_bands_shape_and_range():
    bands = visualizer.compute_bands(_tone(440), 24000)
    assert bands.shape == (15, visualizer.N_BANDS)
    assert bands.min() >= 0.0 and bands.max() <= 1.0


def test_low_and_high_tones_light_different_bands():
    low = visualizer.compute_bands(_tone(150), 24000).mean(axis=0)
    high = visualizer.compute_bands(_tone(4000), 24000).mean(axis=0)
    assert int(low.argmax()) < int(high.argmax())


def test_silence_and_empty_audio():
    assert visualizer.compute_bands(np.zeros(2400), 24000).max() == 0.0
    assert visualizer.compute_bands(np.zeros(0), 24000).shape == (0, 36)


def test_broadcast_streams_frames_then_end(monkeypatch):
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(2.0)
    monkeypatch.setenv("OPENJARVIS_VISUALIZER_PORT", str(rx.getsockname()[1]))
    monkeypatch.setattr(visualizer, "FPS", 200)  # finish quickly

    handle = visualizer.start_broadcast(_tone(440, 0.1), 24000)
    packets = []
    while True:
        packet = json.loads(rx.recvfrom(4096)[0])
        packets.append(packet)
        if packet.get("end"):
            break
    visualizer.stop_broadcast(handle)
    rx.close()

    assert len(packets[0]["b"]) == visualizer.N_BANDS
    assert all(0 <= v <= 100 for v in packets[0]["b"])
    assert packets[-1] == {"end": True}


def test_broadcast_can_be_disabled(monkeypatch):
    monkeypatch.setenv("OPENJARVIS_VISUALIZER", "0")
    assert visualizer.start_broadcast(_tone(440), 24000) is None


def test_bars_are_mirrored_and_complete():
    bars = reloj.bars_from_bands([i / 36 for i in range(36)])
    assert len(bars) == reloj.N_BARS
    assert bars[:36] == bars[36:][::-1]
    assert len(reloj.bars_from_bands([0.5])) == reloj.N_BARS


def test_wave_state_attack_release_and_end():
    state = reloj.WaveState()
    state.feed({"b": [100] * 36}, now=10.0)
    assert state.speaking
    assert state.step(10.0)[0] == 1.0  # instant attack
    state.feed({"end": True}, now=10.1)
    assert not state.speaking
    after = state.step(10.1)[0]
    assert 0.0 < after < 1.0  # smooth release towards the idle ring


def test_wave_state_times_out_without_end_packet():
    state = reloj.WaveState()
    state.feed({"b": [50] * 36}, now=1.0)
    state.step(2.0)
    assert not state.speaking


def test_colors_and_date():
    assert reloj.bar_color(0.0) == "#22d3ee"
    assert reloj.bar_color(1.0) == "#f472b6"
    assert reloj.fecha_es(datetime(2026, 11, 18)) == "miércoles 18 nov"


def test_draw_issues_canvas_calls():
    class Canvas:
        def __init__(self):
            self.calls = []

        def __getattr__(self, name):
            return lambda *a, **k: self.calls.append(name)

    canvas = Canvas()
    reloj.draw(canvas, [0.5] * reloj.N_BARS, datetime(2026, 11, 18, 20, 30), True)
    assert canvas.calls[0] == "delete"
    assert canvas.calls.count("create_line") >= reloj.N_BARS
    assert "create_arc" in canvas.calls
