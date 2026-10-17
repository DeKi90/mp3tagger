"""Entry point: `poetry run mp3tagger` or `python -m mp3tagger`."""

from nicegui import ui

from mp3tagger.config import Config
from mp3tagger.ui.app import build_app


def main() -> None:
    config = Config.from_env()
    build_app(config)
    ui.run(host=config.host, port=config.port, title="MP3 tagger", reload=False, show=False)


if __name__ in {"__main__", "__mp_main__"}:
    main()
