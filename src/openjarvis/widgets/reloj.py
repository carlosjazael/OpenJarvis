"""Kasandra's desktop clock: a floating round clock ringed by sound waves.

The ring of bars reacts to Kasandra's voice in real time. Whenever a reply is
played through ``openjarvis.speech.voice_io``, the spectrum of the audio is
streamed over UDP on ``127.0.0.1`` (see ``openjarvis.speech.visualizer``);
this window listens on that port and animates the bars. When she is silent the
ring breathes softly.

Run it with ``kasandra-reloj`` (no console window on Windows) or
``python -m openjarvis.widgets.reloj``. Drag it with the left mouse button;
right-click for options. Its position is remembered.
"""

from __future__ import annotations

import json
import math
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, List, Sequence

from openjarvis.speech.visualizer import N_BANDS, visualizer_port

SIZE = 320
CENTER = SIZE / 2
N_BARS = 2 * N_BANDS  # bands mirrored left/right, low tones at the bottom
BAR_START = 112
BAR_MAX = 36
DISK_RADIUS = 104
FRAME_MS = 33
KEY_COLOR = "#010203"  # painted transparent on Windows

BG = "#0a0f1f"
TEXT = "#e6f1ff"
MUTED = "#8aa0c8"
CYAN = (0x22, 0xD3, 0xEE)
PURPLE = (0xA8, 0x55, 0xF7)
PINK = (0xF4, 0x72, 0xB6)

_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = [
    "ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sep", "oct", "nov", "dic",
]  # fmt: skip


def fecha_es(now: datetime) -> str:
    return f"{_DIAS[now.weekday()]} {now.day} {_MESES[now.month - 1]}"


def _mix(a: Sequence[int], b: Sequence[int], t: float) -> tuple[int, int, int]:
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))  # type: ignore[return-value]


def bar_color(level: float) -> str:
    """Cyan when soft, through purple, to pink when loud."""
    level = max(0.0, min(1.0, level))
    rgb = (
        _mix(CYAN, PURPLE, level * 2)
        if level < 0.5
        else _mix(PURPLE, PINK, (level - 0.5) * 2)
    )
    return "#%02x%02x%02x" % rgb


def bars_from_bands(bands: Sequence[float]) -> List[float]:
    """Mirror ``N_BANDS`` levels onto ``N_BARS`` bars around the circle.

    Bar 0 sits at the bottom; lows are at the bottom and highs meet at the top,
    so the ring looks symmetric like a sound-wave flower.
    """
    half = list(bands[:N_BANDS]) + [0.0] * max(0, N_BANDS - len(bands))
    return half + half[::-1]


def idle_levels(t: float) -> List[float]:
    return [
        0.05 + 0.04 * math.sin(t * 1.8 + i * 2 * math.pi / N_BARS * 3)
        for i in range(N_BARS)
    ]


@dataclass
class WaveState:
    """Smoothed bar levels: fast attack, slow release."""

    levels: List[float] = field(default_factory=lambda: [0.0] * N_BARS)
    target: List[float] = field(default_factory=lambda: [0.0] * N_BARS)
    last_packet: float = 0.0
    speaking: bool = False

    def feed(self, payload: dict, now: float) -> None:
        if payload.get("end"):
            self.speaking = False
            self.target = [0.0] * N_BARS
            return
        bands = [max(0.0, min(1.0, v / 100.0)) for v in payload.get("b", [])]
        self.target = bars_from_bands(bands)
        self.last_packet = now
        self.speaking = True

    def step(self, now: float) -> List[float]:
        if self.speaking and now - self.last_packet > 0.5:
            self.speaking = False  # lost the end packet
        target = self.target if self.speaking else idle_levels(now)
        self.levels = [
            t if t > cur else cur * 0.80 + t * 0.20
            for cur, t in zip(self.levels, target)
        ]
        return self.levels


def bar_segments(levels: Sequence[float]) -> List[tuple[float, float, float, float]]:
    """Line endpoints ``(x0, y0, x1, y1)`` for each bar."""
    segs = []
    for i, lvl in enumerate(levels):
        ang = math.pi / 2 + 2 * math.pi * i / len(levels)  # start at the bottom
        length = 3 + max(0.0, min(1.0, lvl)) * BAR_MAX
        c, s = math.cos(ang), math.sin(ang)
        segs.append(
            (
                CENTER + c * BAR_START,
                CENTER + s * BAR_START,
                CENTER + c * (BAR_START + length),
                CENTER + s * (BAR_START + length),
            )
        )
    return segs


def draw(canvas: Any, levels: Sequence[float], now: datetime, speaking: bool) -> None:
    """Draw one frame on a Tk canvas (or anything with the same methods)."""
    canvas.delete("all")
    c = CENTER
    canvas.create_oval(4, 4, SIZE - 4, SIZE - 4, outline="#1b2a44", width=1)

    for (x0, y0, x1, y1), lvl in zip(bar_segments(levels), levels):
        canvas.create_line(
            x0, y0, x1, y1, fill=bar_color(lvl), width=3, capstyle="round"
        )

    r = DISK_RADIUS
    ring = bar_color(0.75) if speaking else "#22d3ee"
    canvas.create_oval(c - r, c - r, c + r, c + r, fill=BG, outline=ring, width=2)

    for h in range(12):
        if h in (3, 9):  # keep the sides clear for the time digits
            continue
        ang = 2 * math.pi * h / 12
        inner = 84 if h % 3 else 80
        canvas.create_line(
            c + math.sin(ang) * inner,
            c - math.cos(ang) * inner,
            c + math.sin(ang) * 90,
            c - math.cos(ang) * 90,
            fill="#2c3e63" if h % 3 else MUTED,
            width=2,
        )

    seconds = now.second + now.microsecond / 1e6
    a = 96
    canvas.create_arc(
        c - a, c - a, c + a, c + a,
        start=90, extent=-max(0.5, seconds * 6),
        style="arc", outline="#22d3ee", width=3,
    )  # fmt: skip

    canvas.create_text(
        c, c - 46, text="K A S A N D R A", fill=ring, font=("Segoe UI", 9, "bold")
    )
    canvas.create_text(
        c, c - 4, text=now.strftime("%H:%M"), fill=TEXT, font=("Segoe UI Light", 40)
    )
    canvas.create_text(c, c + 34, text=fecha_es(now), fill=MUTED, font=("Segoe UI", 11))
    if speaking:
        canvas.create_text(
            c, c + 56, text="hablando…", fill=bar_color(0.9), font=("Segoe UI", 9)
        )


def _settings_path() -> Path:
    from openjarvis.core.config import get_config_dir

    return Path(get_config_dir()) / "reloj.json"


def _load_position() -> tuple[int, int] | None:
    try:
        data = json.loads(_settings_path().read_text())
        return int(data["x"]), int(data["y"])
    except Exception:
        return None


def _save_position(x: int, y: int) -> None:
    try:
        path = _settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"x": x, "y": y}))
    except Exception:
        pass


def main() -> None:
    import tkinter as tk

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("127.0.0.1", visualizer_port()))
    except OSError:
        return  # another clock is already running
    sock.setblocking(False)

    root = tk.Tk()
    root.title("Kasandra")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    bg = KEY_COLOR
    try:
        root.attributes("-transparentcolor", KEY_COLOR)
    except tk.TclError:
        bg = BG  # no per-color transparency on this platform
    root.configure(bg=bg)

    pos = _load_position()
    if pos is None:
        pos = (root.winfo_screenwidth() - SIZE - 40, 60)
    root.geometry(f"{SIZE}x{SIZE}+{pos[0]}+{pos[1]}")

    canvas = tk.Canvas(root, width=SIZE, height=SIZE, bg=bg, highlightthickness=0)
    canvas.pack()
    state = WaveState()
    drag = {"x": 0, "y": 0}

    def on_press(event: Any) -> None:
        drag["x"], drag["y"] = event.x, event.y

    def on_drag(event: Any) -> None:
        x = root.winfo_x() + event.x - drag["x"]
        y = root.winfo_y() + event.y - drag["y"]
        root.geometry(f"+{x}+{y}")

    def on_release(_event: Any) -> None:
        _save_position(root.winfo_x(), root.winfo_y())

    topmost = tk.BooleanVar(value=True)
    menu = tk.Menu(root, tearoff=0)
    menu.add_checkbutton(
        label="Siempre visible",
        variable=topmost,
        command=lambda: root.attributes("-topmost", topmost.get()),
    )
    menu.add_separator()
    menu.add_command(label="Cerrar reloj", command=root.destroy)

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    canvas.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

    def tick() -> None:
        now = time.monotonic()
        while True:
            try:
                packet, _ = sock.recvfrom(4096)
            except (BlockingIOError, OSError):
                break
            try:
                state.feed(json.loads(packet), now)
            except ValueError:
                continue
        draw(canvas, state.step(now), datetime.now(), state.speaking)
        root.after(FRAME_MS, tick)

    tick()
    try:
        root.mainloop()
    finally:
        sock.close()


if __name__ == "__main__":
    main()
