"""Tests for doing things on the PC by voice (songs, favorites, programs, files)."""

from __future__ import annotations

import pytest

from openjarvis.tools import abrir_pc, abrir_web
from openjarvis.tools.abrir_pc import (
    LocalCatalog,
    Program,
    index_files,
    match_score,
    resolve_request,
)


class FakeCatalog(LocalCatalog):
    def bookmarks(self):
        return [
            ("SAT - Portal de trámites", "https://www.sat.gob.mx/portal"),
            ("BBVA México banca en línea", "https://www.bbva.mx"),
        ]

    def programs(self):
        return [
            Program("Excel", path=r"C:\menu\Excel.lnk"),
            Program("AutoCAD 2024 - Español", path=r"C:\menu\AutoCAD.lnk"),
            Program("WhatsApp", app_id="5319275A.WhatsAppDesktop!App"),
            Program("Spotify", app_id="SpotifyAB.SpotifyMusic!Spotify"),
        ]

    def files(self):
        return [
            (
                "Presupuesto obra Chilpancingo.xlsx",
                r"C:\Docs\Presupuesto obra Chilpancingo.xlsx",
                False,
            ),
            ("notas.txt", r"C:\Desktop\notas.txt", False),
            ("Facturas", r"C:\Docs\Facturas", True),
        ]


@pytest.fixture
def opened(monkeypatch):
    calls = []
    monkeypatch.setattr(
        abrir_web.webbrowser, "open", lambda u, new=0: calls.append(("web", u)) or True
    )
    monkeypatch.setattr(
        abrir_pc, "_start_file", lambda p: calls.append(("file", p)) or True
    )
    monkeypatch.setattr(
        abrir_pc, "_start_program", lambda p: calls.append(("program", p.name)) or True
    )
    monkeypatch.setattr(
        abrir_pc,
        "first_youtube_video",
        lambda q: "https://www.youtube.com/watch?v=abcdefghijk",
    )
    return calls


def run(text):
    action = resolve_request(text, FakeCatalog())
    return action, (action.run() if action else None)


@pytest.mark.parametrize(
    "text",
    [
        "Kasi, pon Hotel California de los Eagles",
        "reproduce la canción Bohemian Rhapsody",
        "quiero escuchar Luis Miguel",
        "pon canciones de navidad en YouTube",
    ],
)
def test_plays_song(opened, text):
    action, reply = run(text)
    assert action.kind == "song"
    assert opened == [("web", "https://www.youtube.com/watch?v=abcdefghijk")]
    assert "YouTube" in reply


def test_song_query_drops_filler(opened):
    action, _ = run("pon la canción de Hotel California")
    assert action.label == "Hotel California"


@pytest.mark.parametrize(
    "text", ["pon atención", "pon una alarma a las 7", "hola, ¿cómo estás?"]
)
def test_not_actions(opened, text):
    assert resolve_request(text, FakeCatalog()) is None
    assert opened == []


def test_programs(opened):
    assert run("abre Excel")[0].kind == "program"
    assert run("Kasi abre autocad")[0].label.startswith("AutoCAD")
    assert run("abre el programa whatsapp")[0].label == "WhatsApp"
    assert run("abre Spotify")[0].kind == "program"  # the app beats the website
    assert [c[1] for c in opened] == [
        "Excel",
        "AutoCAD 2024 - Español",
        "WhatsApp",
        "Spotify",
    ]


def test_favorites(opened):
    action, reply = run("abre mi favorito del SAT")
    assert opened == [("web", "https://www.sat.gob.mx/portal")]
    action, _ = run("abre bbva")
    assert opened[-1] == ("web", "https://www.bbva.mx")


def test_missing_favorite_says_so(opened):
    _action, reply = run("abre mi favorito de Netflix")
    assert "No encontré" in reply and opened == []


def test_files(opened):
    _a, reply = run("abre el archivo del presupuesto de chilpancingo")
    assert opened == [("file", r"C:\Docs\Presupuesto obra Chilpancingo.xlsx")]
    run("abre el presupuesto de la obra de Chilpancingo")
    assert len(opened) == 2
    run("abre la carpeta de facturas")
    assert opened[-1] == ("file", r"C:\Docs\Facturas")
    _a, reply = run("abre el archivo de vacaciones")
    assert "No encontré" in reply


def test_known_sites_and_urls_still_work(opened):
    run("abre YouTube")
    run("abre sat.gob.mx")
    assert opened == [("web", "https://www.youtube.com"), ("web", "https://sat.gob.mx")]


def test_unknown_thing_is_left_to_the_model(opened):
    assert resolve_request("abre la puerta", FakeCatalog()) is None


def test_local_can_be_disabled(opened):
    assert resolve_request("abre Excel", FakeCatalog(), local=False) is None


def test_match_score():
    assert match_score("autocad", "AutoCAD 2024 - Español") == 1
    assert match_score("excel", "Word") == 0


def test_index_never_lists_programs_or_scripts(tmp_path):
    (tmp_path / "plano.dwg").write_text("x")
    (tmp_path / "virus.exe").write_text("x")
    (tmp_path / "script.bat").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "foto.jpg").write_text("x")
    names = {n for n, _p, _d in index_files([tmp_path])}
    assert names == {"plano.dwg", "sub", "foto.jpg"}


def test_orchestrator_does_it_without_the_model(opened, monkeypatch):
    from openjarvis.agents.orchestrator import OrchestratorAgent

    monkeypatch.setattr(abrir_pc, "_default_catalog", lambda: FakeCatalog())

    class NoEngine:
        def generate(self, *a, **k):
            raise AssertionError("the model must not be called")

    agent = OrchestratorAgent(NoEngine(), "m", open_web=True)
    result = agent.run("pon Hotel California")
    assert "Hotel California" in result.content
    assert opened == [("web", "https://www.youtube.com/watch?v=abcdefghijk")]
