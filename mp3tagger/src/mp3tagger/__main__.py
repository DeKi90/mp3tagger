"""Entry point: `poetry run mp3tagger` or `python -m mp3tagger`."""

from nicegui import app, ui

from mp3tagger.config import Config
from mp3tagger.serving import IngressPrefix, add_health_route
from mp3tagger.ui.app import build_app


def main(config: Config | None = None) -> None:
    config = config or Config.from_env()
    build_app(config)
    app.add_middleware(IngressPrefix)  # works below a proxy path, e.g. Home Assistant's ingress
    add_health_route(app)
    ui.run(host=config.host, port=config.port, title="MP3 tagger", reload=False, show=False)


if __name__ in {"__main__", "__mp_main__"}:
    main()
