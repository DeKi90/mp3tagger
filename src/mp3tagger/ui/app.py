"""NiceGUI page layout and wiring."""

from nicegui import ui

from mp3tagger.config import Config


def build_app(config: Config) -> None:
    @ui.page("/")
    def index() -> None:
        ui.label("MP3 tagger").classes("text-h5")
        ui.label("Music roots: " + ", ".join(str(r) for r in config.roots))
