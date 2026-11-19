"""Kasandra's holographic desktop clock.

A floating, transparent window that shows a living particle sphere ringed by
3D orbital rings (one of them is the seconds dial), with the time in
holographic glass. Whenever Kasandra speaks, the sphere blooms with the
spectrum of her voice, light rays burst outwards and a shockwave announces
the start of each reply.

The drawing lives in ``reloj.html`` (HTML canvas) and is shown in a
transparent Qt WebEngine window. The voice spectrum arrives over UDP on
``127.0.0.1`` from ``openjarvis.speech.visualizer`` while audio is played.

Below the core there is a text box to write to Kasandra when there is no
microphone: the message goes to the local OpenJarvis API server (started in
the background if needed, so she uses the same tools and memory as the voice
chat), the answer appears as a subtitle and she says it out loud.

Run it with ``kasandra-reloj`` (no console window on Windows) or
``python -m openjarvis.widgets.reloj``. Drag it with the left mouse button;
right-click for options. ``--demo`` simulates a voice to preview the effect.
Requires the ``reloj`` extra: ``uv sync --extra reloj``.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, List, Optional, Tuple

from openjarvis.speech.visualizer import N_BANDS, visualizer_port

SIZE = 480
PANEL = 96  # must match PANEL in reloj.html
MAX_HISTORY = 12
SEND_PREFIX = "KASI_SEND:"
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


def clean_for_speech(text: str) -> str:
    """Drop markdown and code so the reply sounds natural when read aloud."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\s{0,3}(#{1,6}|[-*+]|\d+[.)])\s+", "", text, flags=re.M)
    text = re.sub(r"[*_~#>|]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_send(console_message: str) -> Optional[str]:
    """Return the text the page asked to send, or None for other logs."""
    if not console_message.startswith(SEND_PREFIX):
        return None
    try:
        text = json.loads(console_message[len(SEND_PREFIX) :])
    except ValueError:
        return None
    if not isinstance(text, str) or not text.strip():
        return None
    return text.strip()[:2000]


def build_payload(model: str, history: List[dict]) -> dict:
    return {"model": model, "messages": history[-MAX_HISTORY:], "stream": False}


def extract_reply(response: dict) -> str:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return ""
    return content if isinstance(content, str) else ""


class KasandraClient:
    """Talks to the local OpenJarvis API server, starting it when needed."""

    def __init__(self, config: Any) -> None:
        self._config = config
        port = int(getattr(config.server, "port", 8000) or 8000)
        self._base = f"http://127.0.0.1:{port}"
        self._model = getattr(config.intelligence, "default_model", "") or ""
        self._history: List[dict] = []
        self._server: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    def _get(self, path: str, timeout: float = 2.0) -> bool:
        try:
            with urllib.request.urlopen(self._base + path, timeout=timeout) as r:
                return 200 <= r.status < 300
        except (urllib.error.URLError, OSError):
            return False

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        key = os.environ.get("OPENJARVIS_API_KEY", "")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def ensure_server(self, on_status: Any) -> bool:
        if self._get("/health"):
            return True
        if self._server is None or self._server.poll() is not None:
            on_status("Iniciando el núcleo de Kasandra…")
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self._server = subprocess.Popen(
                [sys.executable, "-c", "from openjarvis.cli import main; main()",
                 "serve", "--host", "127.0.0.1"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=flags,
            )  # fmt: skip
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if self._get("/health"):
                return True
            if self._server.poll() is not None:
                return False
            time.sleep(1.0)
        return False

    def ask(self, text: str, on_status: Any) -> str:
        with self._lock:
            if not self.ensure_server(on_status):
                return "No pude iniciar mi núcleo. Revisa que Ollama esté abierto."
            self._history.append({"role": "user", "content": text})
            body = json.dumps(build_payload(self._model, self._history)).encode()
            req = urllib.request.Request(
                self._base + "/v1/chat/completions",
                data=body,
                headers=self._headers(),
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=600) as r:
                    reply = extract_reply(json.loads(r.read()))
            except (urllib.error.URLError, OSError, ValueError) as exc:
                self._history.pop()
                return f"Tuve un problema al pensar la respuesta: {exc}"
            reply = reply.strip() or "No tengo una respuesta para eso."
            self._history.append({"role": "assistant", "content": reply})
            return reply

    def stop(self) -> None:
        if self._server is not None and self._server.poll() is None:
            self._server.terminate()


def speak_aloud(config: Any, text: str) -> None:
    """Say *text* with the configured voice; the clock animates from play_wav."""
    from openjarvis.speech._tts_discovery import (
        default_voice_for,
        get_tts_backend,
        voice_preferences,
    )
    from openjarvis.speech.voice_io import play_wav

    spoken = clean_for_speech(text)
    if not spoken:
        return
    preferred, voice_id, speed = voice_preferences(config)
    tried: set[str] = set()
    while (backend := get_tts_backend(preferred, attempted=tried)) is not None:
        voice = (
            voice_id
            if backend.backend_id == preferred
            else default_voice_for(backend.backend_id)
        )
        kwargs: dict = {"output_format": "wav", "speed": speed}
        if voice:
            kwargs["voice_id"] = voice
        try:
            result = backend.synthesize(spoken, **kwargs)
        except Exception:
            continue
        play_wav(result.audio, sample_rate=result.sample_rate)
        return


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
        from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, QUrl, Signal
        from PySide6.QtGui import QAction, QColor
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
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

    from openjarvis.core.config import load_config

    config = load_config()
    client = KasandraClient(config)

    app = QApplication(sys.argv[:1])
    view = QWebEngineView()

    class Bridge(QObject):
        js = Signal(str)

    bridge = Bridge()
    bridge.js.connect(lambda code: view.page().runJavaScript(code))

    def handle_text(text: str) -> None:
        def status(msg: str) -> None:
            bridge.js.emit(f"window.kasiStatus({json.dumps(msg)})")

        def work() -> None:
            reply = client.ask(text, status)
            bridge.js.emit(f"window.kasiReply({json.dumps(reply)})")
            try:
                speak_aloud(config, reply)
            except Exception:
                pass

        threading.Thread(target=work, name="kasandra-ask", daemon=True).start()

    class Page(QWebEnginePage):
        def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802
            text = parse_send(message)
            if text is not None:
                handle_text(text)

    view.setPage(Page(view))
    view.setWindowTitle("Kasandra")
    view.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
    view.setAttribute(Qt.WA_TranslucentBackground, True)
    view.setStyleSheet("background: transparent;")
    view.page().setBackgroundColor(QColor(0, 0, 0, 0))
    view.settings().setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, False)
    view.resize(SIZE, SIZE + PANEL)

    pos = _load_position()
    if pos is None:
        geo = app.primaryScreen().availableGeometry()
        pos = (geo.right() - SIZE - 24, geo.top() + 24)
    else:  # keep it on a visible screen
        screen = app.screenAt(QPoint(pos[0] + SIZE // 2, pos[1] + SIZE // 2))
        geo = (screen or app.primaryScreen()).availableGeometry()
        pos = (
            min(max(pos[0], geo.left()), geo.right() - SIZE),
            min(max(pos[1], geo.top()), geo.bottom() - SIZE - PANEL),
        )
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
                and view.mapFromGlobal(event.globalPosition().toPoint()).y() < SIZE
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

    # Warm the brain up right away so the first typed question doesn't wait for
    # the server (and the model) to load.
    if not demo:
        threading.Thread(
            target=client.ensure_server, args=(lambda _msg: None,), daemon=True
        ).start()

    view.show()
    try:
        return app.exec()
    finally:
        client.stop()
        if sock is not None:
            sock.close()


if __name__ == "__main__":
    sys.exit(main())
