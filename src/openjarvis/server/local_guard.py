"""Keep web pages from talking to the local Kasandra server.

A server on ``127.0.0.1`` is still reachable *from the user's own browser*:
any web page can try to ``POST`` to it (CSRF), or use DNS rebinding to make
the browser treat ``evil.example`` as ``127.0.0.1``.  With voice actions that
open programs and files, that must not work.  This middleware:

* rejects requests whose ``Origin`` is a web page that isn't allowed
  (programs such as the desktop clock send no ``Origin`` and are unaffected);
* rejects ``Sec-Fetch-Site: cross-site`` requests that change things;
* when the server only listens on loopback, rejects any ``Host`` that isn't
  ``localhost``/``127.0.0.1``/``::1`` (DNS rebinding).
"""

from __future__ import annotations

from typing import Iterable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _hostname(host_header: str) -> str:
    host = (host_header or "").strip().lower()
    if host.startswith("["):  # [::1]:8000
        return host[1:].split("]", 1)[0]
    if host.count(":") > 1:  # bare IPv6
        return host
    return host.rsplit(":", 1)[0] if ":" in host else host


def blocked_reason(
    *,
    method: str,
    host: str,
    origin: Optional[str],
    sec_fetch_site: Optional[str],
    allowed_origins: Iterable[str],
    local_only: bool,
) -> Optional[str]:
    """Why this request must be refused, or None when it is fine."""
    method = (method or "").upper()
    if local_only and _hostname(host) not in LOOPBACK_HOSTS:
        return "host not allowed"
    if origin:
        allowed = {o.rstrip("/").lower() for o in allowed_origins}
        same_origin = {f"http://{host}".lower(), f"https://{host}".lower()}
        o = origin.rstrip("/").lower()
        if o not in allowed and o not in same_origin:
            return "origin not allowed"
    elif (sec_fetch_site or "").lower() == "cross-site" and method not in _SAFE_METHODS:
        return "cross-site request"
    return None


class LocalGuardMiddleware(BaseHTTPMiddleware):
    """Refuse browser requests from other web sites (see module docstring)."""

    def __init__(self, app, allowed_origins=(), local_only: bool = True) -> None:  # noqa: ANN001
        super().__init__(app)
        self._origins = list(allowed_origins or [])
        self._local_only = local_only

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        reason = blocked_reason(
            method=request.method,
            host=request.headers.get("host", ""),
            origin=request.headers.get("origin"),
            sec_fetch_site=request.headers.get("sec-fetch-site"),
            allowed_origins=self._origins,
            local_only=self._local_only,
        )
        if reason:
            return JSONResponse({"detail": f"Forbidden: {reason}"}, status_code=403)
        return await call_next(request)


def is_loopback(host: str) -> bool:
    return _hostname(host) in LOOPBACK_HOSTS or host in ("",)


__all__ = ["LocalGuardMiddleware", "blocked_reason", "is_loopback"]
