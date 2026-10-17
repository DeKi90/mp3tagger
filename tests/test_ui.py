"""UI smoke tests using NiceGUI's simulated user (no browser)."""

import asyncio

import pytest
from nicegui import ui
from nicegui.testing import User
from nicegui.testing.user_interaction import UserInteraction

from mp3tagger.config import Config
from mp3tagger.ui.app import build_app

pytest_plugins = ["nicegui.testing.user_plugin"]


@pytest.fixture
def music_root(make_mp3, tmp_path):
    root = tmp_path / "music"
    make_mp3(root / "rock" / "b.mp3", title="Beta", artist="Band", year="2001", track="2")
    make_mp3(root / "rock" / "a.mp3", title="Alpha", artist="Band", year="2000", track="1")
    make_mp3(root / "rock" / "deep" / "c.mp3", title="Gamma")
    (root / "empty").mkdir()
    return root


def click_in_dialog(user: User, kind: type[ui.element], text: str) -> None:
    """The simulated user cannot see into the dialog's scroll area; look elements up directly."""
    matches = {
        e
        for e in user.client.elements.values()
        if isinstance(e, kind) and text in (e.props.get("label"), getattr(e, "text", None))
    }
    assert matches, f"no {kind.__name__} {text!r} found"
    UserInteraction(user, matches, text).click()


def click_folder_entry(user: User, name: str) -> None:
    (label,) = (
        e for e in user.client.elements.values() if isinstance(e, ui.item_label) and e.text == name
    )
    item = label
    while not isinstance(item, ui.item):  # the click handler sits on the enclosing ui.item
        item = item.parent_slot.parent
    UserInteraction(user, {item}, name).click()


async def open_folder(user: User, music_root, subfolder: str, *, recursive: bool = False) -> None:
    build_app(Config(roots=(music_root,)))
    await user.open("/")
    if recursive:
        user.find("Include subfolders").click()
    user.find("Open folder…").click()
    await asyncio.sleep(0.1)
    click_folder_entry(user, subfolder)
    click_in_dialog(user, ui.button, "Open")
    await user.should_see(kind=ui.label, content=" files · ", retries=100)  # scan finished


def grid_rows(user: User) -> list[dict]:
    (grid,) = (e for e in user.client.elements.values() if isinstance(e, ui.aggrid))
    return grid.options["rowData"]


async def test_open_folder_populates_grid(user: User, music_root):
    await open_folder(user, music_root, "rock")
    rows = grid_rows(user)
    assert [r["title"] for r in rows] == ["Alpha", "Beta"]
    assert rows[0]["filename"] == "a.mp3"
    assert 1.0 < rows[0]["duration"] < 1.1  # raw seconds, formatted client-side
    assert rows[0]["bitrate"] == 128_000
    await user.should_see("2 files · 0 selected")


async def test_include_subfolders(user: User, music_root):
    await open_folder(user, music_root, "rock", recursive=True)
    assert sorted(r["filename"] for r in grid_rows(user)) == ["a.mp3", "b.mp3", "c.mp3"]


async def test_empty_folder_warns(user: User, music_root):
    await open_folder(user, music_root, "empty")
    await user.should_see("No MP3 files found")
    assert grid_rows(user) == []
