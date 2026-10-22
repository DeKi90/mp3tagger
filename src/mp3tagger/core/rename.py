"""Renaming (and sorting into folders) files from their tags: a pure plan first, then an
all-or-nothing execution."""

import contextlib
import os
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from mp3tagger.core.models import TagSet
from mp3tagger.core.patterns import PatternError, compile_format, format_tags

MAX_PATH_BYTES = 1000  # well below the limits of common file systems
JUNK_FILES = frozenset({".DS_Store", "Thumbs.db"})  # do not keep an emptied folder alive


class RenameError(OSError):
    """Renaming failed. The message says what happened to the files."""


@dataclass(frozen=True)
class RenamePlan:
    source: Path
    target: Path | None = None  # None when the new name could not be built
    status: Literal["rename", "unchanged", "error"] = "unchanged"
    message: str = ""  # the problem for "error"; a hint such as "empty: artist" otherwise


def _key(path: Path) -> tuple[Path, str]:
    # Case-insensitive: "A.mp3" and "a.mp3" are the same file on common (macOS, Windows) systems.
    return path.parent, path.name.casefold()


def _error(draft: RenamePlan, message: str) -> RenamePlan:
    return RenamePlan(draft.source, draft.target, "error", message)


def _same_file(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _obstacle(target: Path) -> str | None:
    """Why the folders of `target` cannot be created: a file is where a folder should be."""
    for ancestor in target.parents:
        if ancestor.exists():
            return None if ancestor.is_dir() else f"{ancestor.name} is a file, not a folder"
    return None


def plan_renames(
    items: Sequence[tuple[Path, TagSet]],
    pattern: str,
    base: Path | None = None,
    allowed: Callable[[Path], bool] | None = None,
) -> list[RenamePlan]:
    """Work out the new location of each file. Nothing is touched on disk.

    A pattern without ``/`` only renames: the file stays in its folder. A pattern with ``/``
    sorts the files into folders below `base` (the open folder), which are created as needed;
    `allowed` says whether a folder may be used at all (e.g. inside the music folders).

    Raises PatternError if the pattern itself is invalid; problems with single files (an empty
    name, a name already taken, two files getting the same name) are reported per file as
    "error".
    """
    compiled = compile_format(pattern, for_filename=True)
    if compiled.has_folders and base is None:
        raise PatternError("Open a folder first: folders in the pattern are created below it")
    drafts: list[RenamePlan] = []
    for path, tags in items:
        try:
            formatted = format_tags(compiled, tags)
        except PatternError as exc:
            drafts.append(RenamePlan(path, None, "error", str(exc)))
            continue
        *folders, name = formatted.parts
        # Without folders in the pattern the file stays where it is; with them it is sorted below
        # the open folder, wherever it is now.
        anchor = base if compiled.has_folders else path.parent
        assert anchor is not None  # folder patterns were refused above without a base
        target = anchor.joinpath(*folders, name + path.suffix)
        hint = f"empty: {', '.join(formatted.empty_fields)}" if formatted.empty_fields else ""
        problem = None
        if len(str(target).encode()) > MAX_PATH_BYTES:
            problem = "The path would be too long"
        elif compiled.has_folders and allowed is not None and not allowed(target.parent):
            problem = "That folder is outside the music folders"
        elif compiled.has_folders:
            problem = _obstacle(target)
        if problem:
            drafts.append(RenamePlan(path, target, "error", problem))
            continue
        status = "unchanged" if target == path else "rename"
        drafts.append(RenamePlan(path, target, status, hint))

    taken = Counter(_key(d.target) for d in drafts if d.target is not None and d.status != "error")
    leaving = {_key(d.source) for d in drafts if d.status == "rename"}  # names that become free
    plans = []
    for draft in drafts:
        if draft.status != "rename" or draft.target is None:
            plans.append(draft)
        elif taken[_key(draft.target)] > 1:
            plans.append(_error(draft, "Same name as another file"))
        elif (
            draft.target.exists()
            and not _same_file(draft.target, draft.source)  # only the case of the name changes
            and _key(draft.target) not in leaving
        ):
            plans.append(_error(draft, "A file with this name exists"))
        else:
            plans.append(draft)
    return plans


def apply_renames(plans: Sequence[RenamePlan]) -> dict[Path, Path]:
    """Carry out the "rename" plans. Returns {old path: new path}.

    All or nothing: files first move to temporary names (in their own folder), so swaps, chains
    (a->b, b->c) and case-only changes work, then to their final names, creating folders as
    needed. If any step fails, the steps already done are undone, folders created meanwhile are
    removed again, and RenameError is raised. Blocking; call from a worker thread.
    """
    todo = [p for p in plans if p.status == "rename" and p.target is not None]
    done: list[tuple[Path, Path]] = []  # (from, to) of every completed move
    created: list[Path] = []  # folders made by this call, outermost first
    temporary: dict[RenamePlan, Path] = {}
    try:
        for plan in todo:
            temp = plan.source.with_name(f".{uuid.uuid4().hex}.mp3tagger-rename")
            plan.source.rename(temp)
            done.append((plan.source, temp))
            temporary[plan] = temp
        for plan in todo:
            assert plan.target is not None
            if plan.target.exists():  # appeared since planning; a plain rename would overwrite it
                raise FileExistsError(f"{plan.target.name} already exists")
            missing = [p for p in reversed(plan.target.parents) if not p.exists()]
            plan.target.parent.mkdir(parents=True, exist_ok=True)
            created.extend(missing)
            temporary[plan].rename(plan.target)
            done.append((temporary[plan], plan.target))
    except OSError as exc:
        stuck = []
        for origin, moved in reversed(done):
            try:
                moved.rename(origin)
            except OSError:
                stuck.append(moved.name)
        for folder in reversed(created):
            with contextlib.suppress(OSError):
                folder.rmdir()  # only succeeds while empty
        outcome = "No files were renamed."
        if stuck:
            outcome = f"Some files could not be put back and may have odd names: {', '.join(stuck)}"
        raise RenameError(f"Renaming failed ({exc.strerror or exc}). {outcome}") from exc
    return {plan.source: plan.target for plan in todo if plan.target is not None}


def remove_empty_folders(folders: Iterable[Path], root: Path) -> list[Path]:
    """Remove the given folders, and their parents up to (not including) `root`, as far as they
    are empty (apart from Finder/Explorer leftovers like .DS_Store). Returns what was removed.

    Meant for folders files were just moved out of. Never touches `root` or anything outside it.
    """
    removed: list[Path] = []
    for folder in sorted(set(folders), key=lambda f: len(f.parts), reverse=True):
        while folder != root and root in folder.parents:
            try:
                entries = list(folder.iterdir())
                if any(e.name not in JUNK_FILES or not e.is_file() for e in entries):
                    break  # something real is still in there
                for junk in entries:
                    junk.unlink()
                folder.rmdir()
            except OSError:
                break
            removed.append(folder)
            folder = folder.parent
    return removed
