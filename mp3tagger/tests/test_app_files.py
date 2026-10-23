"""The Home Assistant app files and the Dockerfile must stay consistent with the code."""

import re
from pathlib import Path

import yaml

from mp3tagger import homeassistant
from mp3tagger.config import Config

APP = Path(__file__).resolve().parents[1]  # the app folder: also the Docker build context
REPOSITORY = APP.parent


def load(path: Path):
    return yaml.safe_load(path.read_text())


def test_the_repository_is_declared_for_home_assistant():
    assert load(REPOSITORY / "repository.yaml")["name"]


def test_the_repository_and_the_app_point_to_the_same_https_address():
    url = load(REPOSITORY / "repository.yaml")["url"]
    assert url.startswith("https://")  # Home Assistant cannot clone over ssh
    assert load(APP / "config.yaml")["url"] == url


def test_the_app_declares_what_home_assistant_requires():
    config = load(APP / "config.yaml")
    for key in ("name", "version", "slug", "description", "arch"):
        assert config[key], key
    assert config["slug"] == "mp3tagger"
    assert set(config["arch"]) <= {"aarch64", "amd64"}  # what the Python base image is built for


def test_the_version_matches_the_project():
    project = re.search(r'^version = "(.+)"', (APP / "pyproject.toml").read_text(), re.M)
    assert load(APP / "config.yaml")["version"] == project.group(1)


def test_ingress_uses_the_port_the_code_listens_on():
    config = load(APP / "config.yaml")
    assert config["ingress"] is True
    assert config["ingress_port"] == homeassistant.INGRESS_PORT
    assert f"{homeassistant.INGRESS_PORT}/tcp" in config["ports"]
    assert config["ports"][f"{homeassistant.INGRESS_PORT}/tcp"] is None  # off until chosen
    assert f"[PORT:{homeassistant.INGRESS_PORT}]" in config["watchdog"]
    assert "/healthz" in config["watchdog"]


def test_every_option_has_a_schema_entry_a_default_and_translations():
    config = load(APP / "config.yaml")
    options, schema = config["options"], config["schema"]
    assert set(options) == set(schema)
    for language in ("en", "de"):
        translated = load(APP / "translations" / f"{language}.yaml")["configuration"]
        assert set(translated) == set(options), language
        assert all(t["name"] and t["description"] for t in translated.values()), language


def test_the_defaults_match_what_the_code_assumes():
    options = load(APP / "config.yaml")["options"]
    config = homeassistant.config_from_options(options)
    assert config.roots == tuple(Path(p) for p in homeassistant.DEFAULT_FOLDERS)
    assert config.cover_country == Config().cover_country


def test_music_is_writable_in_the_shared_folders():
    maps = {m["type"]: m for m in load(APP / "config.yaml")["map"]}
    assert maps["media"]["read_only"] is False and maps["share"]["read_only"] is False


def test_the_app_has_its_documentation_and_images():
    for name in ("DOCS.md", "CHANGELOG.md", "icon.png", "logo.png", "Dockerfile", ".dockerignore"):
        assert (APP / name).is_file(), name


def test_the_home_assistant_image_is_the_last_stage_of_the_dockerfile():
    stages = re.findall(r"^FROM .+ AS (\w+)$", (APP / "Dockerfile").read_text(), re.M)
    assert stages[-1] == "homeassistant"  # Home Assistant builds the last stage
    assert "standalone" in stages


def test_the_dockerfile_uses_the_ports_and_commands_of_the_code():
    dockerfile = (APP / "Dockerfile").read_text()
    home_assistant = dockerfile.split("AS homeassistant")[1]
    assert f"EXPOSE {homeassistant.INGRESS_PORT}" in home_assistant
    assert 'CMD ["mp3tagger-ha"]' in home_assistant
    standalone = dockerfile.split("AS standalone")[1].split("AS homeassistant")[0]
    assert 'CMD ["mp3tagger"]' in standalone and "/healthz" in standalone


def test_the_dockerfile_needs_nothing_outside_the_build_context():
    # Home Assistant builds from the app folder alone: COPY sources must be inside it.
    for source in re.findall(
        r"^COPY (?!--from)(\S+(?: \S+)*?) \S+$", (APP / "Dockerfile").read_text(), re.M
    ):
        for part in source.split():
            assert not part.startswith(("..", "/")), part
            assert (APP / part).exists(), part


def test_the_console_scripts_exist():
    scripts = re.search(
        r"\[project\.scripts\](.*?)\n\n", (APP / "pyproject.toml").read_text(), re.S
    ).group(1)
    assert "mp3tagger-ha" in scripts and "mp3tagger =" in scripts
