"""Helpers for driving the page with NiceGUI's simulated user (no browser)."""

import asyncio
from pathlib import Path

from nicegui import ui
from nicegui.testing import User
from nicegui.testing.user_interaction import UserInteraction

from mp3tagger.config import Config
from mp3tagger.ui.app import build_app
from mp3tagger.ui.file_grid import FileGrid


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
    """Open `subfolder` of the music root. "Include subfolders" is ticked by default, so it is
    unticked here unless `recursive`."""
    build_app(Config(roots=(music_root,)))
    await user.open("/")
    if not recursive:
        user.find("Include subfolders").click()
    user.find("Open folder…").click()
    await asyncio.sleep(0.1)
    click_folder_entry(user, subfolder)
    click_in_dialog(user, ui.button, "Open")
    await user.should_see(kind=ui.label, content=" files · ", retries=100)  # scan finished


def grid_rows(user: User) -> list[dict]:
    (grid,) = (e for e in user.client.elements.values() if isinstance(e, ui.aggrid))
    return grid.options["rowData"]


async def select(user: User, monkeypatch, *paths: Path) -> None:
    """Simulate selecting rows. The simulated user has no browser, so fake the grid query."""

    async def selected_paths(_self) -> list[Path]:
        return list(paths)

    monkeypatch.setattr(FileGrid, "selected_paths", selected_paths)
    (grid,) = (e for e in user.client.elements.values() if isinstance(e, ui.aggrid))
    UserInteraction(user, {grid}, None).trigger("selectionChanged")
    await asyncio.sleep(0.1)


def field(user: User, label: str) -> ui.input:
    (element,) = (
        e
        for e in user.client.elements.values()
        if isinstance(e, ui.input) and e.props.get("label") == label
    )
    return element


def type_into(user: User, label: str, text: str) -> None:
    field(user, label).set_value(text)


def button(user: User, text: str) -> ui.button:
    (element,) = (
        e
        for e in user.client.elements.values()
        if isinstance(e, ui.button) and e.props.get("label", "").startswith(text)
    )
    return element


async def click(user: User, text: str) -> None:
    """Click a toolbar/panel button and give its (possibly async) handler time to finish."""
    UserInteraction(user, {button(user, text)}, text).click()
    await asyncio.sleep(0.05)


def row_for(user: User, path: Path) -> dict:
    return next(r for r in grid_rows(user) if r["id"] == str(path))
