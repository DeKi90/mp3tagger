import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute

from mp3tagger.serving import IngressPrefix, add_health_route, is_plain_path


def echo_app() -> IngressPrefix:
    """An app that reports the X-Forwarded-Prefix header it received."""

    async def show(request: Request) -> JSONResponse:
        return JSONResponse({"prefix": request.headers.get("x-forwarded-prefix")})

    async def show_ws(websocket) -> None:
        await websocket.accept()
        await websocket.send_json({"prefix": websocket.headers.get("x-forwarded-prefix")})
        await websocket.close()

    from starlette.applications import Starlette

    return IngressPrefix(Starlette(routes=[Route("/", show), WebSocketRoute("/ws", show_ws)]))


def prefix_seen(headers: dict[str, str]) -> str | None:
    return TestClient(echo_app()).get("/", headers=headers).json()["prefix"]


def test_plain_paths_are_recognised():
    for good in (b"/", b"/ingress/abc", b"/api/hassio_ingress/Zx-9_~.v1/", b"/a.b/c"):
        assert is_plain_path(good), good


def test_the_ingress_path_becomes_the_forwarded_prefix():
    assert prefix_seen({"X-Ingress-Path": "/api/hassio_ingress/abc123"}) == (
        "/api/hassio_ingress/abc123"
    )


def test_a_trailing_slash_is_dropped():
    assert prefix_seen({"X-Ingress-Path": "/api/hassio_ingress/abc123/"}) == (
        "/api/hassio_ingress/abc123"
    )


def test_without_the_header_nothing_is_added():
    assert prefix_seen({}) is None


def test_an_existing_forwarded_prefix_is_replaced_not_duplicated():
    seen = prefix_seen({"X-Ingress-Path": "/ingress/x", "X-Forwarded-Prefix": "/other"})
    assert seen == "/ingress/x"


def test_a_forwarded_prefix_without_an_ingress_path_is_left_alone():
    assert prefix_seen({"X-Forwarded-Prefix": "/proxy"}) == "/proxy"  # other proxies still work


@pytest.mark.parametrize(
    "value",
    [
        "http://evil.example/",
        "//evil.example",
        "javascript:alert(1)",
        '/a"><script>',
        "no-slash",
        "/a b",
    ],
)
def test_prefixes_that_are_not_plain_paths_are_ignored(value):
    assert prefix_seen({"X-Ingress-Path": value}) is None


def test_websocket_connections_get_the_prefix_too():
    client = TestClient(echo_app())
    with client.websocket_connect("/ws", headers={"X-Ingress-Path": "/ingress/ws1"}) as ws:
        assert ws.receive_json() == {"prefix": "/ingress/ws1"}


def test_the_health_route_answers_without_building_a_page():
    app = FastAPI()
    add_health_route(app)
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200 and response.json() == {"status": "ok"}
    assert "/healthz" not in TestClient(app).get("/openapi.json").text  # not part of the API docs


def test_the_health_path_can_be_chosen():
    app = FastAPI()
    add_health_route(app, "/up")
    assert TestClient(app).get("/up").status_code == 200
    assert TestClient(app).get("/healthz").status_code == 404
