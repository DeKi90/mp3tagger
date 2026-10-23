"""Running as a Home Assistant app: the options the user set in Home Assistant are in
``/data/options.json``; the web UI is served on the ingress port."""

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from mp3tagger.config import Config

OPTIONS_PATH = Path("/data/options.json")
INGRESS_PORT = 8099  # must match ingress_port in config.yaml
DEFAULT_FOLDERS = ("/media",)


def load_options(path: Path = OPTIONS_PATH) -> dict[str, Any]:
    """The app's options, or none at all outside Home Assistant."""
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def config_from_options(options: Mapping[str, Any]) -> Config:
    """The configuration for the options Home Assistant gives the app."""
    folders = options.get("music_folders") or list(DEFAULT_FOLDERS)
    return Config(
        roots=tuple(Path(folder) for folder in folders),
        host="0.0.0.0",  # reachable by the ingress proxy (and the optional host port)
        port=INGRESS_PORT,
        contact=str(options.get("contact") or ""),
        cover_country=str(options.get("cover_country") or Config().cover_country),
    )


def existing_folders(config: Config) -> tuple[Path, ...]:
    return tuple(root for root in config.roots if root.is_dir())


def main() -> None:
    config = config_from_options(load_options())
    usable = existing_folders(config)
    for root in config.roots:
        if root not in usable:
            print(f"Music folder {root} does not exist: it is ignored.", file=sys.stderr)
    if not usable:
        folders = ", ".join(str(r) for r in config.roots)
        sys.exit(
            f"None of the music folders exist ({folders}). Check the app's Music folders option "
            "and that /media or /share holds your music."
        )
    from mp3tagger.__main__ import main as serve

    serve(Config(usable, config.host, config.port, config.contact, config.cover_country))


if __name__ == "__main__":
    main()
