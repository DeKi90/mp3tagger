"""Merged view of several tracks' tags, for batch editing."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from mp3tagger.core.models import FIELD_NAMES, CoverArt, TagSet

# Shown in fields whose values differ between the selected tracks. Editing such a field sets it
# on all of them; leaving the text as is (or typing it back) keeps every track's own value.
KEEP = "<keep>"


@dataclass(frozen=True)
class MergedTags:
    values: dict[str, str]  # field -> the common value, or KEEP where the tracks differ
    mixed: frozenset[str]  # fields whose values differ

    def get(self, field: str) -> str:
        return self.values[field]


def merge_tags(tags: Sequence[TagSet]) -> MergedTags:
    """Merge the tags of one or more tracks. Raises ValueError for an empty sequence."""
    if not tags:
        raise ValueError("Nothing to merge")
    values: dict[str, str] = {}
    mixed: set[str] = set()
    for field in FIELD_NAMES:
        distinct = {getattr(t, field) for t in tags}
        if len(distinct) == 1:
            values[field] = distinct.pop()
        else:
            values[field] = KEEP
            mixed.add(field)
    return MergedTags(values, frozenset(mixed))


@dataclass(frozen=True)
class ShownCover:
    """The cover displayed for a track: its embedded picture or, failing that, a folder image."""

    cover: CoverArt
    folder_file: str | None = None  # name of the image file if it is the folder image


@dataclass(frozen=True)
class MergedCover:
    state: Literal["none", "single", "mixed"]  # no cover / one common cover / covers differ
    shown: ShownCover | None = None  # set for "single"

    @property
    def cover(self) -> CoverArt | None:
        return self.shown.cover if self.shown else None


def merge_covers(covers: Sequence[ShownCover | None]) -> MergedCover:
    """Merge the covers of one or more tracks. Raises ValueError for an empty sequence.

    The same picture embedded in one file and found as a folder image for another counts as
    different: acting on it would not do the same thing to both.
    """
    if not covers:
        raise ValueError("Nothing to merge")
    first = covers[0]
    if any(c != first for c in covers):
        return MergedCover("mixed")
    return MergedCover("none") if first is None else MergedCover("single", first)
