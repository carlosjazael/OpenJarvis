"""Tests for opening web pages in the user's browser."""

from __future__ import annotations

import pytest

from openjarvis.tools import abrir_web
from openjarvis.tools.abrir_web import detect_open_request, normalize_url


@pytest.mark.parametrize(
    ("text", "url"),
    [
        ("abre youtube", "https://www.youtube.com"),
        ("Kasi, ábreme YouTube por favor", "https://www.youtube.com"),
        ("abre el correo", "https://mail.google.com"),
        ("abre mercado libre", "https://www.mercadolibre.com.mx"),
        ("abre la página del SAT", "https://www.sat.gob.mx"),
        ("abre sat.gob.mx", "https://sat.gob.mx"),
        ("entra a www.milenio.com", "https://www.milenio.com"),
        ("abre https://github.com/carlosjazael", "https://github.com/carlosjazael"),
    ],
)
def test_detects_pages(text, url):
    assert detect_open_request(text)[0] == url


def test_youtube_search():
    url, label = detect_open_request("pon canciones de navidad en YouTube")
    assert url == "https://www.youtube.com/results?search_query=canciones+de+navidad"
    assert "navidad" in label


def test_google_search():
    url, _ = detect_open_request("abre en google el precio del dólar")
    assert url.startswith("https://www.google.com/search?q=el+precio+del+d")


def test_unknown_page_goes_to_google():
    url, _ = detect_open_request("abre la página de la Liga MX")
    assert url == "https://www.google.com/search?q=liga+mx"


@pytest.mark.parametrize(
    "text",
    [
        "hola kasi, ¿cómo estás?",
        "abre el archivo notas.txt de mi carpeta",
        "abre la puerta",
        "¿cuánto es 15% de 800?",
        "pon atención",
    ],
)
def test_ignores_other_messages(text):
    assert detect_open_request(text) is None


def test_only_web_addresses():
    assert normalize_url("file:///C:/Windows/system32") is None
    assert normalize_url("javascript:alert(1)") is None
    assert normalize_url("youtube.com") == "https://youtube.com"


def test_open_url_refuses_non_web(monkeypatch):
    opened = []
    monkeypatch.setattr(
        abrir_web.webbrowser, "open", lambda u, new=0: opened.append(u) or True
    )
    assert abrir_web.open_url("file:///C:/x.exe") is False
    assert abrir_web.open_url("youtube.com") is True
    assert opened == ["https://youtube.com"]


def test_tool_opens_known_site(monkeypatch):
    opened = []
    monkeypatch.setattr(
        abrir_web.webbrowser, "open", lambda u, new=0: opened.append(u) or True
    )
    result = abrir_web.OpenUrlTool().execute(url="YouTube")
    assert result.success and opened == ["https://www.youtube.com"]


def test_orchestrator_opens_page_and_drops_tools(monkeypatch):
    from openjarvis.agents.orchestrator import OrchestratorAgent

    opened = []
    monkeypatch.setattr(
        abrir_web.webbrowser, "open", lambda u, new=0: opened.append(u) or True
    )
    note = OrchestratorAgent._open_requested_page("Kasi abre YouTube")
    assert opened == ["https://www.youtube.com"]
    assert "Ya abriste" in note
    assert OrchestratorAgent._open_requested_page("hola, ¿cómo estás?") is None
