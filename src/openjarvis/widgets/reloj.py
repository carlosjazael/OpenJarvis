"""Kasandra's holographic desktop clock.

A floating, transparent window that shows a living particle sphere ringed by
3D orbital rings (one of them is the seconds dial), with the time in
holographic glass. Whenever Kasandra speaks, the sphere blooms with the
spectrum of her voice, light rays burst outwards and a shockwave announces
the start of each reply.

The drawing lives in ``reloj.html`` (HTML canvas) and is shown in a
transparent Qt WebEngine window. The voice spectrum arrives over UDP on
``127.0.0.1`` from ``openjarvis.speech.visualizer`` while audio is played.

Run it with ``kasandra-reloj`` (no console window on Windows) or
``python -m openjarvis.widgets.reloj``. Drag it with the left mouse button;
right-click for options. ``--demo`` simulates a voice to preview the effect.
Requires the ``reloj`` extra: ``uv sync --extra reloj``.
"""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path
from typing import Any, Optional, Tuple

from openjarvis.speech.visualizer import N_BANDS, visualizer_port

SIZE = 480
POLL_MS = 15
HTML_PATH = Path(__file__).with_name("reloj.html")


def parse_packet(packet: bytes) -> Optional[Tuple[str, Any]]:
    """Decode a visualizer datagram into ``("feed", levels)`` or ``("end", None)``."""
    try:
        data = json.loads(packet)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("end"):
        return ("end", None)
    levels = data.get("b")
    if not isinstance(levels, list):
        return None
    clean = []
    for v in levels[:N_BANDS]:
        try:
            clean.append(max(0, min(100, int(v))))
        except (TypeError, ValueError):
            clean.append(0)
    return ("feed", clean)


def drain(sock: socket.socket) -> Optional[Tuple[str, Any]]:
    """Read every pending datagram and keep only the newest meaningful one.

    An ``end`` wins only if no newer frame followed it, so consecutive spoken
    sentences flow without flicker.
    """
    latest = None
    while True:
        try:
            packet, _ = sock.recvfrom(4096)
        except (BlockingIOError, InterruptedError):
            break
        except OSError:  # e.g. WSAECONNRESET on Windows; keep listening
            continue
        parsed = parse_packet(packet)
        if parsed is not None:
            latest = parsed
    return latest


def js_call(event: Tuple[str, Any]) -> str:
    kind, levels = event
    if kind == "end":
        return "window.kasiEnd && window.kasiEnd()"
    return f"window.kasiFeed && window.kasiFeed({json.dumps(levels)})"


def _settings_path() -> Path:
    from openjarvis.core.config import get_config_dir

    return Path(get_config_dir()) / "reloj.json"


def _load_position() -> Optional[Tuple[int, int]]:
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


def _bind_socket() -> Optional[socket.socket]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows: one clock at a time
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        sock.bind(("127.0.0.1", visualizer_port()))
    except OSError:
        sock.close()
        return None
    sock.setblocking(False)
    return sock


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    demo = "--demo" in argv

    try:
        from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QUrl
        from PySide6.QtGui import QAction, QColor
        from PySide6.QtWebEngineCore import QWebEngineSettings
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWidgets import QApplication, QMenu
    except ImportError:
        print(
            "El reloj necesita PySide6. Instálalo con: uv sync --extra reloj",
            file=sys.stderr,
        )
        return 1

    sock = None if demo else _bind_socket()
    if sock is None and not demo:
        return 0  # another clock is already running

    app = QApplication(sys.argv[:1])
    view = QWebEngineView()
    view.setWindowTitle("Kasandra")
    view.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
    view.setAttribute(Qt.WA_TranslucentBackground, True)
    view.setStyleSheet("background: transparent;")
    view.page().setBackgroundColor(QColor(0, 0, 0, 0))
    view.settings().setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, False)
    view.resize(SIZE, SIZE)

    pos = _load_position()
    if pos is None:
        geo = app.primaryScreen().availableGeometry()
        pos = (geo.right() - SIZE - 24, geo.top() + 24)
    view.move(*pos)

    url = QUrl.fromLocalFile(str(HTML_PATH))
    if demo:
        url.setQuery("demo=1")
    view.load(url)

    # ── menú y arrastre ──
    view.setContextMenuPolicy(Qt.CustomContextMenu)
    menu = QMenu()
    on_top = QAction("Siempre visible", menu, checkable=True, checked=True)

    def toggle_on_top(checked: bool) -> None:
        view.setWindowFlag(Qt.WindowStaysOnTopHint, checked)
        view.show()

    on_top.toggled.connect(toggle_on_top)
    menu.addAction(on_top)
    menu.addSeparator()
    menu.addAction("Cerrar reloj", app.quit)
    view.customContextMenuRequested.connect(lambda p: menu.popup(view.mapToGlobal(p)))

    class Dragger(QObject):
        def eventFilter(self, obj: Any, event: Any) -> bool:  # noqa: N802
            if (
                event.type() == QEvent.MouseButtonPress
                and event.button() == Qt.LeftButton
                and isinstance(obj, QObject)
                and (obj is view or view.isAncestorOf(obj))
            ):
                handle = view.windowHandle()
                if handle is not None and handle.startSystemMove():
                    return True
            if event.type() == QEvent.Move and obj is view:
                _save_position(view.x(), view.y())
            return False

    dragger = Dragger()
    app.installEventFilter(dragger)

    # ── voz → animación ──
    if sock is not None:

        def poll() -> None:
            event = drain(sock)
            if event is not None:
                view.page().runJavaScript(js_call(event))

        timer = QTimer()
        timer.timeout.connect(poll)
        timer.start(POLL_MS)

    view.show()
    try:
        return app.exec()
    finally:
        if sock is not None:
            sock.close()


if __name__ == "__main__":
    sys.exit(main())
