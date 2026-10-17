"""Merged view of several tracks' tags, for batch editing."""

from collections.abc import Sequence
from dataclasses import dataclass

from mp3tagger.core.models import FIELD_NAMES, TagSet

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
