"""What is needed to run behind a reverse proxy such as Home Assistant's ingress."""

import re

from fastapi import FastAPI
from starlette.types import ASGIApp, Receive, Scope, Send

_INGRESS_HEADER = b"x-ingress-path"
_FORWARDED_PREFIX = b"x-forwarded-prefix"
_PATH_CHARACTERS = re.compile(rb"^/[A-Za-z0-9/_\-.~%]*$")


def is_plain_path(prefix: bytes) -> bool:
    """Whether `prefix` is an absolute path on this server and nothing else: no scheme, no host
    (``//host`` would turn the asset URLs built from it into links to another site), no empty
    or ``.``/``..`` segments."""
    if not _PATH_CHARACTERS.match(prefix):
        return False
    segments = prefix.rstrip(b"/").split(b"/")[1:]
    return all(segment not in (b"", b".", b"..") for segment in segments)


class IngressPrefix:
    """Home Assistant's ingress proxy serves the app below a path such as
    ``/api/hassio_ingress/<token>`` and says so in ``X-Ingress-Path``. NiceGUI builds its asset
    and websocket URLs from ``X-Forwarded-Prefix``, so pass the one on as the other."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            headers = scope["headers"]
            prefix = next((v for k, v in headers if k == _INGRESS_HEADER), None)
            if prefix is not None and is_plain_path(prefix):
                kept = [(k, v) for k, v in headers if k != _FORWARDED_PREFIX]
                scope = {**scope, "headers": [*kept, (_FORWARDED_PREFIX, prefix.rstrip(b"/"))]}
        await self.app(scope, receive, send)


def add_health_route(app: FastAPI, path: str = "/healthz") -> None:
    """A cheap liveness check for container health checks (no UI page is built for it)."""

    @app.get(path, include_in_schema=False)
    def health() -> dict[str, str]:
        return {"status": "ok"}
