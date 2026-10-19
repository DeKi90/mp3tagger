"""Renaming files from their tags: a pure plan first, then an all-or-nothing execution."""

import os
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from mp3tagger.core.models import TagSet
from mp3tagger.core.patterns import PatternError, compile_format, format_tags


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


def plan_renames(items: Sequence[tuple[Path, TagSet]], pattern: str) -> list[RenamePlan]:
    """Work out the new name of each file. Nothing is touched on disk.

    Raises PatternError if the pattern itself is invalid; problems with single files (empty name,
    name already taken, two files getting the same name) are reported per file as "error".
    """
    compiled = compile_format(pattern, for_filename=True)
    drafts: list[RenamePlan] = []
    for path, tags in items:
        try:
            formatted = format_tags(compiled, tags)
        except PatternError as exc:
            drafts.append(RenamePlan(path, None, "error", str(exc)))
            continue
        target = path.with_name(formatted.text + path.suffix)
        hint = f"empty: {', '.join(formatted.empty_fields)}" if formatted.empty_fields else ""
        status = "unchanged" if target == path else "rename"
        drafts.append(RenamePlan(path, target, status, hint))

    taken = Counter(_key(d.target) for d in drafts if d.target is not None)
    leaving = {_key(d.source) for d in drafts if d.status == "rename"}  # names that become free
    plans = []
    for draft in drafts:
        if draft.status != "rename" or draft.target is None:
            plans.append(draft)
        elif taken[_key(draft.target)] > 1:
            plans.append(
                RenamePlan(draft.source, draft.target, "error", "Same name as another file")
            )
        elif (
            draft.target.exists()
            and not _same_file(draft.target, draft.source)  # only the case of the name changes
            and _key(draft.target) not in leaving
        ):
            plans.append(
                RenamePlan(draft.source, draft.target, "error", "A file with this name exists")
            )
        else:
            plans.append(draft)
    return plans


def apply_renames(plans: Sequence[RenamePlan]) -> dict[Path, Path]:
    """Carry out the "rename" plans. Returns {old path: new path}.

    All or nothing: files first move to temporary names, so swaps and chains (a->b, b->c) and
    case-only changes work, then to their final names. If any step fails, the steps already done
    are undone and RenameError is raised. Blocking; call from a worker thread.
    """
    todo = [p for p in plans if p.status == "rename" and p.target is not None]
    done: list[tuple[Path, Path]] = []  # (from, to) of every completed move
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
            temporary[plan].rename(plan.target)
            done.append((temporary[plan], plan.target))
    except OSError as exc:
        stuck = []
        for origin, moved in reversed(done):
            try:
                moved.rename(origin)
            except OSError:
                stuck.append(moved.name)
        outcome = "No files were renamed."
        if stuck:
            outcome = f"Some files could not be put back and may have odd names: {', '.join(stuck)}"
        raise RenameError(f"Renaming failed ({exc.strerror or exc}). {outcome}") from exc
    return {plan.source: plan.target for plan in todo if plan.target is not None}
