import os
from pathlib import Path

from mp3tagger.config import Config


def test_defaults(monkeypatch):
    for name in ("MP3TAGGER_ROOTS", "MP3TAGGER_HOST", "MP3TAGGER_PORT"):
        monkeypatch.delenv(name, raising=False)
    config = Config.from_env()
    assert config.roots == (Path.home() / "Music",)
    assert (config.host, config.port) == ("127.0.0.1", 8080)


def test_env_override(monkeypatch, tmp_path):
    other = tmp_path / "other"
    monkeypatch.setenv("MP3TAGGER_ROOTS", os.pathsep.join([str(tmp_path), str(other)]))
    monkeypatch.setenv("MP3TAGGER_HOST", "0.0.0.0")
    monkeypatch.setenv("MP3TAGGER_PORT", "9000")
    config = Config.from_env()
    assert config.roots == (tmp_path.resolve(), other.resolve())
    assert (config.host, config.port) == ("0.0.0.0", 9000)
