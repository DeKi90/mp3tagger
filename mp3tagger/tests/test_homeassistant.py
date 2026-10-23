import json
from pathlib import Path

import pytest

from mp3tagger import homeassistant
from mp3tagger.config import Config
from mp3tagger.homeassistant import (
    INGRESS_PORT,
    config_from_options,
    existing_folders,
    load_options,
)


def test_the_options_become_the_configuration():
    config = config_from_options(
        {
            "music_folders": ["/media/music", "/share/audio"],
            "contact": "me@example.org",
            "cover_country": "at",
        }
    )
    assert config.roots == (Path("/media/music"), Path("/share/audio"))
    assert (config.contact, config.cover_country) == ("me@example.org", "at")


def test_the_server_listens_where_home_assistant_expects_it():
    config = config_from_options({})
    assert config.port == INGRESS_PORT == 8099  # the ingress_port in config.yaml
    assert config.host == "0.0.0.0"  # reachable from the proxy, not just from inside


def test_defaults_when_options_are_empty_or_missing_values():
    config = config_from_options({"music_folders": [], "contact": None, "cover_country": ""})
    assert config.roots == (Path("/media"),)
    assert config.contact == "" and config.cover_country == Config().cover_country


def test_options_are_read_from_the_json_file(tmp_path):
    path = tmp_path / "options.json"
    path.write_text(json.dumps({"music_folders": ["/media"], "cover_country": "de"}))
    assert load_options(path) == {"music_folders": ["/media"], "cover_country": "de"}


def test_no_options_file_means_no_options(tmp_path):
    assert load_options(tmp_path / "missing.json") == {}


def test_only_folders_that_exist_are_used(tmp_path):
    real = tmp_path / "music"
    real.mkdir()
    config = config_from_options({"music_folders": [str(real), str(tmp_path / "gone")]})
    assert existing_folders(config) == (real,)


def test_main_starts_the_server_with_the_usable_folders(tmp_path, monkeypatch, capsys):
    real = tmp_path / "music"
    real.mkdir()
    options = tmp_path / "options.json"
    options.write_text(
        json.dumps({"music_folders": [str(real), str(tmp_path / "gone")], "contact": "x"})
    )
    monkeypatch.setattr(homeassistant, "OPTIONS_PATH", options)
    monkeypatch.setattr(
        homeassistant, "load_options", lambda path=options: json.loads(path.read_text())
    )
    started = []
    monkeypatch.setattr("mp3tagger.__main__.main", lambda config=None: started.append(config))
    homeassistant.main()
    (config,) = started
    assert config.roots == (real,) and config.port == 8099 and config.contact == "x"
    assert "gone does not exist" in capsys.readouterr().err


def test_main_refuses_to_start_without_any_music_folder(tmp_path, monkeypatch):
    options = tmp_path / "options.json"
    options.write_text(json.dumps({"music_folders": [str(tmp_path / "gone")]}))
    monkeypatch.setattr(
        homeassistant, "load_options", lambda path=options: json.loads(path.read_text())
    )
    started = []
    monkeypatch.setattr("mp3tagger.__main__.main", lambda config=None: started.append(config))
    with pytest.raises(SystemExit) as exit_info:
        homeassistant.main()
    assert "None of the music folders exist" in str(exit_info.value) and started == []
