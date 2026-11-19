"""Tests for the voice visualizer stream and the desktop clock's pure logic."""

from __future__ import annotations

import json
import socket

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


def test_parse_packet_feed_end_and_garbage():
    assert reloj.parse_packet(b'{"b": [10, 200, -5, "x"]}') == ("feed", [10, 100, 0, 0])
    assert reloj.parse_packet(b'{"end": true}') == ("end", None)
    assert reloj.parse_packet(b"not json") is None
    assert reloj.parse_packet(b"[1, 2]") is None


def test_drain_keeps_newest_event():
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.setblocking(False)
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for packet in (b'{"b": [1]}', b'{"end": true}', b'{"b": [7]}'):
        tx.sendto(packet, rx.getsockname())
    import time

    time.sleep(0.05)
    assert reloj.drain(rx) == ("feed", [7])
    assert reloj.drain(rx) is None
    tx.close()
    rx.close()


def test_js_call_and_html_hooks():
    assert reloj.js_call(("end", None)) == "window.kasiEnd && window.kasiEnd()"
    assert reloj.js_call(("feed", [1, 2])).endswith("kasiFeed([1, 2])")
    html = reloj.HTML_PATH.read_text(encoding="utf-8")
    assert "window.kasiFeed" in html and "window.kasiEnd" in html
    assert f"const N_BANDS = {visualizer.N_BANDS};" in html


def test_text_bridge_helpers():
    assert reloj.parse_send('KASI_SEND:"hola"') == "hola"
    assert reloj.parse_send('KASI_SEND:"   "') is None
    assert reloj.parse_send("otro log") is None
    assert reloj.parse_send("KASI_SEND:{bad") is None
    history = [{"role": "user", "content": str(i)} for i in range(20)]
    payload = reloj.build_payload("qwen3.5:9b", history)
    assert payload["model"] == "qwen3.5:9b" and len(payload["messages"]) == 12
    ok = {"choices": [{"message": {"content": "Listo"}}]}
    assert reloj.extract_reply(ok) == "Listo"
    assert reloj.extract_reply({}) == ""


def test_clean_for_speech_strips_markdown():
    text = "# Título\n- **uno**\n1. `dos`\n```py\ncode\n```\n[link](http://x)"
    assert reloj.clean_for_speech(text) == "Título uno dos link"


def test_html_has_text_box_hooks():
    html = reloj.HTML_PATH.read_text(encoding="utf-8")
    for hook in ("window.kasiReply", "window.kasiThinking", "window.kasiStatus"):
        assert hook in html
    assert reloj.SEND_PREFIX in html
    assert f"const PANEL = {reloj.PANEL};" in html
