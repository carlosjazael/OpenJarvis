"""Do quick things on the user's PC by voice: play a song, open a favorite,
a program or a file.

``resolve_request("pon Hotel California")`` turns a message into a
:class:`PcAction` (or None), and ``action.run()`` does it.  Everything here
only *opens* things:

* songs open the first YouTube result in the default browser;
* favorites are read (never changed) from Edge, Chrome, Brave and Firefox;
* programs are only the ones with a shortcut in the Start menu, or listed
  by Windows as installed apps;
* files are searched by name in Desktop, Documents, Downloads (plus the
  folders in ``OPENJARVIS_CARPETAS``), and executables/scripts are never run.
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from glob import glob
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Tuple
from urllib.parse import quote_plus

from openjarvis.tools.abrir_web import (
    KNOWN_SITES,
    _plain,
    detect_open_request,
    normalize_url,
    open_url,
)

logger = logging.getLogger(__name__)

# The only kinds of files a voice request may open: documents, images, media,
# CAD drawings and archives.  Anything else (scripts, installers, shortcuts,
# disk images, help files...) is never opened, whatever its name.
OPENABLE_EXTENSIONS = frozenset(
    ".pdf .txt .rtf .md .csv .doc .docx .xls .xlsx .ppt .pptx .odt .ods .odp "
    ".jpg .jpeg .png .gif .bmp .webp .heic .tif .tiff "
    ".mp3 .wav .m4a .flac .ogg .aac .wma .mp4 .mkv .avi .mov .wmv .webm "
    ".dwg .dxf .dwf .skp .rvt .kmz .kml .zip .rar .7z".split()
)

# Kept as a second, independent check right before opening.
UNSAFE_EXTENSIONS = frozenset(
    ".exe .msi .msp .bat .cmd .com .ps1 .psm1 .vbs .vbe .js .jse .wsf .wsh .scr "
    ".pif .reg .lnk .url .hta .cpl .jar .appref-ms .dll .sys .inf .gadget "
    ".application .msc .scf".split()
)
_SKIP_DIRS = frozenset(
    "node_modules .git __pycache__ appdata $recycle.bin .venv venv site-packages "
    ".cache .vs".split()
)
_PROGRAM_NOISE = re.compile(
    r"(uninstall|desinstal|readme|l[eé]ame|help|ayuda|manual|website|sitio web|"
    r"release notes|license|licencia)",
    re.IGNORECASE,
)
MAX_REQUEST_CHARS = 200

_STOPWORDS = frozenset(
    "de del la el los las mi mis un una unos unas en por favor kasi oye que me "
    "a al y o porfa porfavor ahora ya tu su".split()
)

_LEAD = r"^(?:oye\s+)?(?:kasi\b[,\s]*)?(?:por\s*favor\s+|porfa\s+)?"
_PLAY = re.compile(
    _LEAD + r"(pon(?:me)?|reproduce|reprod[uú]ceme|toca|quiero (?:escuchar|o[ií]r|ver))"
    r"\s+(.+?)(?:\s+en\s+(?:el\s+)?you\s?tube)?(?:\s+por\s*favor)?\s*[.!?]*$",
    re.IGNORECASE,
)
_NOT_A_SONG = re.compile(
    r"^(atenci[oó]n|cuidado|orden|una? alarma|alarma|un recordatorio|recordatorio|"
    r"un temporizador|temporizador|el volumen|volumen|m[aá]s|menos|la mesa|"
    r"a prueba|un ejemplo|ejemplos?|nota|una nota|en|el|la|los|las|esto|eso|"
    r"mis?|tus?|el archivo|la carpeta|el programa)\b",
    re.IGNORECASE,
)
_SONG_WORDS = re.compile(
    r"^(?:la canci[oó]n|una canci[oó]n|la rola|una rola|el video|un video|"
    r"el tema|el videoclip)\s+(?:de\s+)?",
    re.IGNORECASE,
)
_OPEN = re.compile(
    _LEAD + r"(?:abre|[aá]breme|abrir|abrirme|inicia|in[ií]ciame|ejecuta|arranca|"
    r"lanza|corre|entra a|entra en|ll[eé]vame a|ve a|vete a)\s+(.+?)"
    r"(?:\s+por\s*favor)?\s*[.!?]*$",
    re.IGNORECASE,
)
_FAVORITE = re.compile(
    r"\b(favoritos?|marcadores?|marcador|bookmarks?)\b", re.IGNORECASE
)
_FILE = re.compile(
    r"\b(archivo|documento|doc|foto|fotos|imagen|pdf|hoja de c[aá]lculo|excel de|"
    r"word de|presentaci[oó]n|plano|dibujo|video de|carpeta)\b",
    re.IGNORECASE,
)
_SITE_WORDS = re.compile(
    r"\b(?:p[aá]gina|sitio|portal)(?:\s+web)?(?:\s+(?:de|del))?\b", re.IGNORECASE
)
_PROGRAM = re.compile(r"\b(programa|aplicaci[oó]n|app)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def query_tokens(text: str) -> List[str]:
    words = re.findall(r"[a-z0-9ñ]+", _plain(text))
    return [w for w in words if w not in _STOPWORDS and len(w) > 1] or words


def match_score(query: str, name: str) -> float:
    """0..1: how well *name* matches the words of *query* (1 = all words)."""
    tokens = query_tokens(query)
    if not tokens:
        return 0.0
    plain = _plain(name)
    words = set(re.findall(r"[a-z0-9ñ]+", plain))
    found = sum(1 for t in tokens if t in words or (len(t) > 3 and t in plain))
    score = found / len(tokens)
    if score < 1:
        ratio = difflib.SequenceMatcher(None, " ".join(tokens), plain).ratio()
        score = max(score, ratio if ratio >= 0.8 else 0.0)
    return score


def best_matches(
    query: str, items: Iterable[Tuple[str, object]], minimum: float = 1.0
) -> List[Tuple[float, str, object]]:
    """Items whose name matches *query* well, best (and shortest name) first."""
    scored = []
    for name, value in items:
        s = match_score(query, name)
        if s >= minimum:
            scored.append((s, name, value))
    scored.sort(key=lambda x: (-x[0], len(x[1])))
    return scored


# ---------------------------------------------------------------------------
# What is on this PC (Windows); cached and refreshed in the background
# ---------------------------------------------------------------------------


@dataclass
class Program:
    name: str
    path: str = ""  # a .lnk/.url shortcut
    app_id: str = ""  # a Windows "AppsFolder" id (Store apps)


@dataclass
class LocalCatalog:
    """Favorites, programs and files on this PC, read lazily and cached."""

    ttl: float = 600.0
    _cache: dict = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _cached(self, key: str, loader: Callable[[], list]) -> list:
        with self._lock:
            hit = self._cache.get(key)
            if hit and time.monotonic() - hit[0] < self.ttl:
                return hit[1]
        try:
            value = loader()
        except Exception:
            logger.warning("No se pudo leer %s", key, exc_info=True)
            value = hit[1] if hit else []
        with self._lock:
            self._cache[key] = (time.monotonic(), value)
        return value

    def warm_up(self) -> None:
        """Read everything once in the background so the first ask is fast."""

        def _load() -> None:
            self.bookmarks()
            self.programs()
            self.files()

        threading.Thread(target=_load, daemon=True, name="kasi-catalog").start()

    def bookmarks(self) -> List[Tuple[str, str]]:
        return self._cached("bookmarks", read_bookmarks)

    def programs(self) -> List[Program]:
        return self._cached("programs", read_programs)

    def files(self) -> List[Tuple[str, str, bool]]:
        return self._cached("files", index_files)


def _env_path(name: str) -> Optional[Path]:
    value = os.environ.get(name)
    return Path(value) if value else None


def read_bookmarks() -> List[Tuple[str, str]]:
    """``(title, url)`` from Edge, Chrome, Brave and Firefox (read-only)."""
    out: List[Tuple[str, str]] = []
    local = _env_path("LOCALAPPDATA")
    roaming = _env_path("APPDATA")
    if local:
        for browser in (
            "Microsoft/Edge",
            "Google/Chrome",
            "BraveSoftware/Brave-Browser",
        ):
            for f in glob(str(local / browser / "User Data" / "*" / "Bookmarks")):
                out.extend(_safely(_chromium_bookmarks, Path(f)))
    if roaming:
        for f in glob(str(roaming / "Mozilla/Firefox/Profiles/*/places.sqlite")):
            out.extend(_safely(_firefox_bookmarks, Path(f)))
    seen: set = set()
    unique = []
    for title, url in out:
        if (title, url) not in seen and normalize_url(url):
            seen.add((title, url))
            unique.append((title, url))
    return unique


def _safely(reader: Callable[[Path], list], path: Path) -> list:
    """One broken or empty browser profile must not hide all the others."""
    try:
        return reader(path)
    except Exception:
        logger.info("No se pudieron leer favoritos de %s", path, exc_info=True)
        return []


def _chromium_bookmarks(path: Path) -> List[Tuple[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: List[Tuple[str, str]] = []

    def walk(node: dict) -> None:
        if node.get("type") == "url":
            out.append((node.get("name", ""), node.get("url", "")))
        for child in node.get("children", []) or []:
            walk(child)

    for root in (data.get("roots") or {}).values():
        if isinstance(root, dict):
            walk(root)
    return out


def _firefox_bookmarks(path: Path) -> List[Tuple[str, str]]:
    # Firefox keeps the file locked while open: read a private copy.
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "places.sqlite"
        shutil.copy2(path, copy)
        con = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
        try:
            rows = con.execute(
                "SELECT b.title, p.url FROM moz_bookmarks b "
                "JOIN moz_places p ON b.fk = p.id "
                "WHERE b.type = 1 AND b.title IS NOT NULL AND b.title != ''"
            ).fetchall()
        finally:
            con.close()
    return [(t, u) for t, u in rows]


def _start_menu_dirs() -> List[Tuple[Path, bool]]:
    """``(folder, recursive)``: the Start menu folders."""
    dirs = []
    for env, sub, recursive in (
        # Only the Start menu: anything (even a download) can land on the
        # Desktop, so its shortcuts are not trusted as "programs".
        ("APPDATA", "Microsoft/Windows/Start Menu/Programs", True),
        ("PROGRAMDATA", "Microsoft/Windows/Start Menu/Programs", True),
    ):
        base = _env_path(env)
        if base and (base / sub).is_dir():
            dirs.append((base / sub, recursive))
    return dirs


def read_programs() -> List[Program]:
    """Shortcuts in the Start menu, plus Windows' installed apps."""
    programs: dict = {}
    for d, recursive in _start_menu_dirs():
        # Only .lnk program shortcuts (no .url files: they can point anywhere).
        for pattern in ("**/*.lnk",) if recursive else ("*.lnk",):
            for f in d.glob(pattern):
                name = f.stem
                if not _PROGRAM_NOISE.search(name):
                    programs.setdefault(_plain(name), Program(name, path=str(f)))
    if sys.platform == "win32":
        for name, app_id in _start_apps():
            if not _PROGRAM_NOISE.search(name):
                programs.setdefault(_plain(name), Program(name, app_id=app_id))
    return list(programs.values())


def _start_apps() -> List[Tuple[str, str]]:
    try:
        out = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
                "Get-StartApps | ConvertTo-Json -Compress",
            ],
            capture_output=True,
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        data = json.loads(out.stdout.decode("utf-8", "replace") or "[]")
    except Exception:
        logger.debug("Get-StartApps falló", exc_info=True)
        return []
    if isinstance(data, dict):
        data = [data]
    return [
        (d.get("Name", ""), d.get("AppID", ""))
        for d in data
        if d.get("Name") and d.get("AppID")
    ]


def file_roots() -> List[Path]:
    roots: List[Path] = []
    home = _env_path("USERPROFILE") or Path.home()
    for sub in (
        "Desktop",
        "Escritorio",
        "Documents",
        "Documentos",
        "Downloads",
        "Descargas",
        "OneDrive/Desktop",
        "OneDrive/Escritorio",
        "OneDrive/Documents",
        "OneDrive/Documentos",
    ):
        p = home / sub
        if p.is_dir():
            roots.append(p)
    for extra in (os.environ.get("OPENJARVIS_CARPETAS") or "").split(";"):
        if extra.strip() and Path(extra.strip()).is_dir():
            roots.append(Path(extra.strip()))
    unique: List[Path] = []
    for r in roots:
        if all(r.resolve() != u.resolve() for u in unique):
            unique.append(r)
    return unique


_FOLDER_ALIASES = {
    "downloads": "Descargas",
    "documents": "Documentos",
    "desktop": "Escritorio",
    "pictures": "Imágenes",
    "music": "Música",
    "videos": "Videos",
}


def is_openable_file(name: str) -> bool:
    """True for a document/media file; trailing dots or spaces don't count."""
    suffix = Path(name.rstrip(" .")).suffix.lower()
    return suffix in OPENABLE_EXTENSIONS and suffix not in UNSAFE_EXTENSIONS


def index_files(
    roots: Optional[List[Path]] = None, max_depth: int = 6, limit: int = 80_000
) -> List[Tuple[str, str, bool]]:
    """``(name, path, is_dir)`` for files and folders under the user's folders."""
    out: List[Tuple[str, str, bool]] = []
    for root in roots if roots is not None else file_roots():
        # The folders themselves too ("abre la carpeta de Descargas").
        out.append((root.name, str(root), True))
        alias = _FOLDER_ALIASES.get(root.name.lower())
        if alias:
            out.append((alias, str(root), True))
        base_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            depth = len(Path(dirpath).parts) - base_depth
            dirnames[:] = [
                d
                for d in dirnames
                if not d.startswith(".") and d.lower() not in _SKIP_DIRS
            ]
            if depth >= max_depth:
                dirnames[:] = []
            for d in dirnames:
                out.append((d, os.path.join(dirpath, d), True))
            for f in filenames:
                if is_openable_file(f):
                    out.append((f, os.path.join(dirpath, f), False))
            if len(out) >= limit:
                return out
    return out


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def _start_file(path: str) -> bool:
    if not os.path.isdir(path) and not is_openable_file(os.path.basename(path)):
        raise PermissionError(f"Kasandra no abre este tipo de archivo: {path}")
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606
        return True
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, path])  # noqa: S603
    return True


def _start_program(program: Program) -> bool:
    if program.path:
        # Program shortcuts come only from the Start menu / Desktop listing.
        if sys.platform == "win32":
            os.startfile(program.path)  # type: ignore[attr-defined]  # noqa: S606
            return True
        return False
    if program.app_id and sys.platform == "win32":
        # Store apps (Bloc de notas, Calculadora...) start through the shell.
        os.startfile("shell:AppsFolder\\" + program.app_id)  # type: ignore[attr-defined]  # noqa: S606
        return True
    return False


def first_youtube_video(query: str, timeout: float = 8.0) -> Optional[str]:
    """URL of the first YouTube result for *query*, or None."""
    req = urllib.request.Request(
        "https://www.youtube.com/results?search_query=" + quote_plus(query),
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept-Language": "es-MX,es;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", "replace")
    except Exception:
        logger.warning("No se pudo buscar en YouTube", exc_info=True)
        return None
    m = re.search(r'"videoId":"([\w-]{11})"', html)
    return f"https://www.youtube.com/watch?v={m.group(1)}" if m else None


@dataclass
class PcAction:
    """Something Kasi can do right away, with what she says afterwards."""

    kind: str
    label: str
    reply: str
    do: Callable[[], bool]
    fail_reply: str = "No pude abrirlo. ¿Me lo dices de otra forma?"

    def run(self) -> str:
        try:
            ok = bool(self.do())
        except Exception:
            logger.warning("Falló la acción %s", self.label, exc_info=True)
            ok = False
        return self.reply if ok else self.fail_reply


def _song_action(query: str) -> PcAction:
    def play() -> bool:
        url = first_youtube_video(query) or (
            "https://www.youtube.com/results?search_query=" + quote_plus(query)
        )
        return open_url(url)

    return PcAction(
        "song",
        query,
        f"Va, te pongo «{query}» en YouTube.",
        play,
        "No pude abrir YouTube.",
    )


def _web_action(url: str, label: str) -> PcAction:
    return PcAction("web", label, f"Listo, ya te abrí {label}.", lambda: open_url(url))


def _program_action(p: Program) -> PcAction:
    return PcAction(
        "program", p.name, f"Listo, abriendo {p.name}.", lambda: _start_program(p)
    )


def _file_action(matches: List[Tuple[float, str, object]]) -> PcAction:
    # Same score: open the most recently changed one, and mention the rest.
    top = [m for m in matches if m[0] == matches[0][0]]

    def mtime(m: Tuple[float, str, object]) -> float:
        try:
            return os.path.getmtime(str(m[2]))
        except OSError:
            return 0.0

    top.sort(key=mtime, reverse=True)
    name, path = top[0][1], str(top[0][2])
    reply = f"Listo, abrí {name}."
    if len(top) > 1:
        others = ", ".join(m[1] for m in top[1:3])
        reply = f"Abrí {name}, el más reciente. También encontré: {others}."
    return PcAction("file", name, reply, lambda: _start_file(path))


def _strip_words(text: str, pattern: re.Pattern) -> str:
    text = re.sub(r"\s+", " ", pattern.sub(" ", text)).strip(" ,.")
    filler = r"(?:de|del|en|mis|mi|el|la|los|las|tu|tus)"
    while True:
        cleaned = re.sub(rf"^{filler}\s+", "", text, flags=re.IGNORECASE)
        cleaned = re.sub(rf"\s+{filler}$", "", cleaned, flags=re.IGNORECASE)
        if cleaned == text:
            return text
        text = cleaned


def resolve_request(
    text: str,
    catalog: Optional[LocalCatalog] = None,
    *,
    web: bool = True,
    local: bool = True,
) -> Optional[PcAction]:
    """Return the action *text* asks for, or None when it isn't such a request."""
    text = (text or "").strip()
    if not text or len(text) > MAX_REQUEST_CHARS:
        return None  # real voice commands are short; also caps regex work
    catalog = catalog or _default_catalog()

    m = _PLAY.search(text)
    if m and web:
        what = m.group(2).strip()
        on_youtube = re.search(r"you\s?tube", text, re.IGNORECASE)
        what = _SONG_WORDS.sub("", what).strip(" ,.")
        plain_what = _plain(what)
        is_site = plain_what in KNOWN_SITES
        if what and not is_site and (on_youtube or not _NOT_A_SONG.search(what)):
            return _song_action(what)

    m = _OPEN.search(text)
    if not m:
        found = detect_open_request(text) if web else None
        return _web_action(*found) if found else None
    target = m.group(1).strip()

    if web and re.search(r"https?://|www\.|\.\w{2,4}\b", target):
        found = detect_open_request(text)
        if found and "google.com/search" not in found[0]:
            return _web_action(*found)

    if web and _FAVORITE.search(target):
        query = _strip_words(target, _FAVORITE)
        hits = best_matches(query, catalog.bookmarks(), minimum=0.67)
        if hits:
            return _web_action(str(hits[0][2]), hits[0][1])
        return PcAction(
            "bookmark",
            query,
            "",
            lambda: False,
            f"No encontré «{query}» en tus favoritos.",
        )

    if local and _FILE.search(target):
        wants_folder = re.search(r"\bcarpeta\b", target, re.IGNORECASE)
        query = _strip_words(target, _FILE)
        items = [
            (name, path)
            for name, path, is_dir in catalog.files()
            if bool(is_dir) == bool(wants_folder)
        ]
        hits = best_matches(query, items)
        if hits:
            return _file_action(hits)
        what = "esa carpeta" if wants_folder else "ese archivo"
        return PcAction(
            "file",
            query,
            "",
            lambda: False,
            f"No encontré {what} en Escritorio, Documentos ni Descargas.",
        )

    if local and _PROGRAM.search(target):
        query = _strip_words(target, _PROGRAM)
        hits = best_matches(query, [(p.name, p) for p in catalog.programs()], 0.67)
        if hits:
            return _program_action(hits[0][2])  # type: ignore[arg-type]
        return PcAction(
            "program",
            query,
            "",
            lambda: False,
            f"No encontré el programa «{query}» en tu menú Inicio.",
        )

    name = _strip_words(target, _SITE_WORDS)
    plain_name = _plain(name)
    programs = [(p.name, p) for p in catalog.programs()] if local else []
    if local:
        exact = [p for n, p in programs if _plain(n) == plain_name]
        if exact:
            return _program_action(exact[0])
    if web and plain_name in KNOWN_SITES:
        return _web_action(KNOWN_SITES[plain_name], name)
    if local:
        hits = best_matches(name, programs)
        if hits:
            return _program_action(hits[0][2])  # type: ignore[arg-type]
    if web:
        hits = best_matches(name, catalog.bookmarks())
        if hits:
            return _web_action(str(hits[0][2]), hits[0][1])
    if local:
        files = [(n, p) for n, p, _d in catalog.files()]
        hits = best_matches(name, files)
        if hits and len(query_tokens(name)) >= 2:
            return _file_action(hits)
    found = detect_open_request(text) if web else None
    return _web_action(*found) if found else None


_CATALOG: Optional[LocalCatalog] = None


def _default_catalog() -> LocalCatalog:
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = LocalCatalog()
    return _CATALOG


def warm_up() -> None:
    """Start reading favorites/programs/files in the background."""
    _default_catalog().warm_up()


__all__ = [
    "LocalCatalog",
    "PcAction",
    "Program",
    "best_matches",
    "first_youtube_video",
    "index_files",
    "match_score",
    "read_bookmarks",
    "resolve_request",
    "warm_up",
]
