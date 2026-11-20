"""Open web pages in the user's own browser ("abre YouTube", "abre sat.gob.mx").

Only ``http``/``https`` addresses are opened, with the system's default
browser, exactly like clicking a link.  Nothing is typed or clicked on the
page.  :func:`detect_open_request` lets the orchestrator open the page in code,
so small local models don't have to get a tool call right.
"""

from __future__ import annotations

import re
import unicodedata
import webbrowser
from typing import Any, Optional, Tuple
from urllib.parse import quote_plus, urlparse

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

# Well-known sites by the name people say out loud (accents removed).
KNOWN_SITES: dict[str, str] = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "correo": "https://mail.google.com",
    "outlook": "https://outlook.live.com",
    "hotmail": "https://outlook.live.com",
    "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "whatsapp": "https://web.whatsapp.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "tiktok": "https://www.tiktok.com",
    "netflix": "https://www.netflix.com",
    "spotify": "https://open.spotify.com",
    "amazon": "https://www.amazon.com.mx",
    "mercado libre": "https://www.mercadolibre.com.mx",
    "mercadolibre": "https://www.mercadolibre.com.mx",
    "wikipedia": "https://es.wikipedia.org",
    "google maps": "https://maps.google.com",
    "maps": "https://maps.google.com",
    "mapas": "https://maps.google.com",
    "traductor": "https://translate.google.com",
    "google drive": "https://drive.google.com",
    "drive": "https://drive.google.com",
    "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai",
    "github": "https://github.com",
    "sat": "https://www.sat.gob.mx",
    "imss": "https://www.imss.gob.mx",
    "linkedin": "https://www.linkedin.com",
    "twitch": "https://www.twitch.tv",
    "disney": "https://www.disneyplus.com",
    "disney plus": "https://www.disneyplus.com",
    "prime video": "https://www.primevideo.com",
}

_VERB = (
    r"(?:abre|abreme|abrir|abras|abrime|entra a|entra en|entrar a|ll[eé]vame a|"
    r"vete a|ve a|navega a|m[eé]tete a|pon|ponme|reproduce)"
)
_URL = re.compile(
    r"(https?://[^\s,;]+|www\.[^\s,;]+|"
    r"(?<![@\w])[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|mx|org|net|io|gob|edu|tv|app|"
    r"dev|ai|es|co|us|info|me)(?:\.mx)?(?:/[^\s,;]*)?)",
    re.IGNORECASE,
)
_ON_YOUTUBE = re.compile(
    rf"\b(?:{_VERB}|busca|buscame)\s+(.+?)\s+en\s+(?:el\s+)?you\s?tube\b",
    re.IGNORECASE,
)
_ON_GOOGLE = re.compile(
    rf"\b(?:{_VERB})\s+(?:en\s+google\s+)(.+)$",
    re.IGNORECASE,
)
_OPEN_NAME = re.compile(
    rf"\b{_VERB}\s+(?:(?:la|el|mi)\s+)?"
    r"(?:(?:p[aá]gina|sitio|web|portal)\s+(?:web\s+)?(?:de(?:l)?\s+)?)?"
    r"(?:(?:la|el|mi)\s+)?(.+?)\s*[.!?]*\s*$",
    re.IGNORECASE,
)
_EXPLICIT_WEB = re.compile(r"\b(p[aá]gina|sitio|web|portal)\b", re.IGNORECASE)


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c)).strip()


def normalize_url(raw: str) -> Optional[str]:
    """Return an ``http(s)`` URL for *raw*, or None if it isn't a web address."""
    raw = raw.strip().rstrip(".,;:!?)\"'")
    if not raw:
        return None
    if re.match(r"^[a-z][a-z0-9+.-]*:(?!\d)", raw, re.IGNORECASE):
        # Has a scheme: only http(s) is allowed (no file:, javascript:...).
        if not re.match(r"^https?://", raw, re.IGNORECASE):
            return None
    else:
        raw = "https://" + raw
    parsed = urlparse(raw)
    host = parsed.hostname or ""
    if not host or ("." not in host and host != "localhost"):
        return None
    return raw


def detect_open_request(text: str) -> Optional[Tuple[str, str]]:
    """Return ``(url, label)`` when *text* asks to open a web page, else None."""
    text = (text or "").strip()
    if not text or not re.search(rf"\b{_VERB}\b", _plain(text), re.IGNORECASE):
        if not _ON_YOUTUBE.search(text):
            return None
    m = _ON_YOUTUBE.search(text)
    if m:
        query = m.group(1).strip()
        return (
            "https://www.youtube.com/results?search_query=" + quote_plus(query),
            f"YouTube con la búsqueda «{query}»",
        )
    m = _ON_GOOGLE.search(text)
    if m:
        query = m.group(1).strip(" .!?")
        return (
            "https://www.google.com/search?q=" + quote_plus(query),
            f"Google con la búsqueda «{query}»",
        )
    m = _URL.search(text)
    if m:
        url = normalize_url(m.group(1))
        if url:
            return url, m.group(1).rstrip(".,;:!?")
    m = _OPEN_NAME.search(_plain(text))
    if m:
        name = re.sub(r"^(?:por favor\s+)", "", m.group(1)).strip(" .!?,")
        name = re.sub(r"\s+por favor$", "", name)
        if name in KNOWN_SITES:
            return KNOWN_SITES[name], name.title() if len(name) > 3 else name.upper()
        if _EXPLICIT_WEB.search(_plain(text)) and name:
            return (
                "https://www.google.com/search?q=" + quote_plus(name),
                f"la búsqueda de «{name}» en Google",
            )
    return None


def open_url(url: str) -> bool:
    """Open *url* in the default browser. Refuses anything that isn't http(s)."""
    safe = normalize_url(url)
    if not safe:
        return False
    return bool(webbrowser.open(safe, new=2))


@ToolRegistry.register("open_url")
class OpenUrlTool(BaseTool):
    """Open a web address in the user's normal browser."""

    tool_id = "open_url"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="open_url",
            description=(
                "Abre una dirección web (http/https) en el navegador del "
                "usuario, como dar clic a un enlace. No abre programas ni "
                "archivos."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Dirección web, p. ej. youtube.com",
                    }
                },
                "required": ["url"],
            },
            category="web",
        )

    def execute(self, **params: Any) -> ToolResult:
        raw = str(params.get("url", ""))
        url = KNOWN_SITES.get(_plain(raw)) or normalize_url(raw)
        if not url:
            return ToolResult(
                tool_name="open_url",
                content="Solo puedo abrir direcciones web (http o https).",
                success=False,
            )
        ok = open_url(url)
        return ToolResult(
            tool_name="open_url",
            content=f"Abrí {url} en el navegador." if ok else f"No pude abrir {url}.",
            success=ok,
        )


__all__ = ["KNOWN_SITES", "OpenUrlTool", "detect_open_request", "open_url"]
