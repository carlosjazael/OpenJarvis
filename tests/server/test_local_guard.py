"""Web pages must not be able to drive the local server."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient

from openjarvis.server.local_guard import (
    LocalGuardMiddleware,
    blocked_reason,
    is_loopback,
)


def _client(local_only=True):
    app = FastAPI()

    @app.post("/v1/chat/completions")
    def chat():
        return {"ok": True}

    app.add_middleware(
        LocalGuardMiddleware,
        allowed_origins=["http://localhost:5173"],
        local_only=local_only,
    )
    return TestClient(app, base_url="http://127.0.0.1:8000")


def test_local_program_without_origin_is_allowed():
    assert _client().post("/v1/chat/completions", json={}).status_code == 200


def test_other_web_site_is_refused():
    r = _client().post(
        "/v1/chat/completions",
        content='{"messages":[]}',
        headers={"Origin": "https://evil.example", "Content-Type": "text/plain"},
    )
    assert r.status_code == 403


def test_allowed_and_same_origin_pass():
    c = _client()
    assert (
        c.post(
            "/v1/chat/completions", json={}, headers={"Origin": "http://localhost:5173"}
        ).status_code
        == 200
    )
    assert (
        c.post(
            "/v1/chat/completions", json={}, headers={"Origin": "http://127.0.0.1:8000"}
        ).status_code
        == 200
    )


def test_null_origin_is_refused():
    assert (
        _client()
        .post("/v1/chat/completions", json={}, headers={"Origin": "null"})
        .status_code
        == 403
    )


def test_dns_rebinding_host_is_refused():
    r = _client().post(
        "/v1/chat/completions", json={}, headers={"Host": "evil.example:8000"}
    )
    assert r.status_code == 403


def test_lan_server_keeps_working_for_lan_host():
    r = _client(local_only=False).post(
        "/v1/chat/completions", json={}, headers={"Host": "192.168.1.5:8000"}
    )
    assert r.status_code == 200


@pytest.mark.parametrize(
    ("method", "site", "blocked"),
    [
        ("POST", "cross-site", True),
        ("GET", "cross-site", False),
        ("POST", "none", False),
    ],
)
def test_sec_fetch_site(method, site, blocked):
    reason = blocked_reason(
        method=method,
        host="127.0.0.1:8000",
        origin=None,
        sec_fetch_site=site,
        allowed_origins=[],
        local_only=True,
    )
    assert bool(reason) is blocked


def test_is_loopback():
    assert is_loopback("127.0.0.1") and is_loopback("localhost") and is_loopback("::1")
    assert not is_loopback("0.0.0.0")


def test_websocket_from_other_site_is_refused():
    from starlette.websockets import WebSocketDisconnect

    app = FastAPI()

    @app.websocket("/ws")
    async def ws(socket: WebSocket):
        await socket.accept()
        await socket.send_text("hola")
        await socket.close()

    app.add_middleware(LocalGuardMiddleware, allowed_origins=[], local_only=True)
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    local = {"Host": "127.0.0.1:8000"}
    with client.websocket_connect("/ws", headers=local) as s:
        assert s.receive_text() == "hola"
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "/ws", headers={"Origin": "https://evil.example"}
        ) as s:
            s.receive_text()


def test_oauth_error_page_escapes_html():
    import html

    payload = "<script>alert(1)</script>"
    assert "<script>" not in html.escape(payload)
