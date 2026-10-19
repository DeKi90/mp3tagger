"""Bulk text transforms of tag values: case conversion and find/replace."""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from mp3tagger.core.models import TagSet

CaseStyle = Literal["upper", "lower", "title", "sentence"]

# Lower-cased in title case (except as first or last word). English only: titles in other
# languages follow other rules, so this is switchable.
SMALL_WORDS = frozenset(
    {"a", "an", "and", "as", "at", "but", "by", "for", "in", "nor"}
    | {"of", "on", "or", "per", "the", "to", "up", "via", "vs"}
)
_WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")  # letters/digits, with inner apostrophes
_SENTENCE_START = re.compile(r"(^\s*|[.!?]\s+)([^\W\d_])")


class TransformError(ValueError):
    """The transform is not valid. The message is meant to be shown to the user."""


def _capitalize(word: str) -> str:
    return word[:1].upper() + word[1:].lower()


def convert_case(value: str, style: CaseStyle, *, keep_small_words: bool = True) -> str:
    """Change the case of `value`. Separators, digits and punctuation are left alone."""
    if style == "upper":
        return value.upper()
    if style == "lower":
        return value.lower()
    if style == "sentence":
        return _SENTENCE_START.sub(lambda m: m.group(1) + m.group(2).upper(), value.lower())
    if style != "title":
        raise TransformError(f"Unknown case style {style!r}")
    words = list(_WORD.finditer(value))
    last = len(words) - 1
    pieces, position = [], 0
    for index, match in enumerate(words):
        word = match.group()
        small = keep_small_words and word.lower() in SMALL_WORDS and 0 < index < last
        pieces.append(value[position : match.start()])
        pieces.append(word.lower() if small else _capitalize(word))
        position = match.end()
    pieces.append(value[position:])
    return "".join(pieces)


@dataclass(frozen=True)
class FindReplace:
    find: str
    replace: str = ""
    regex: bool = False  # `find` is a regular expression; `replace` may use \1 or \g<name>
    match_case: bool = False
    whole_field: bool = False  # the find text must match the entire value, not just a part


@dataclass(frozen=True)
class Replaced:
    value: str
    count: int  # number of replacements made


def compile_find_replace(spec: FindReplace) -> Callable[[str], Replaced]:
    """Prepare `spec` for use. Raises TransformError for an invalid search or replacement."""
    if not spec.find:
        raise TransformError("Enter the text to find")
    flags = 0 if spec.match_case else re.IGNORECASE
    if not spec.regex:
        pattern = re.compile(re.escape(spec.find), flags)
        literal = spec.replace  # no escape processing: a backslash is just a backslash

        def expand(_match: re.Match[str]) -> str:
            return literal

    else:
        try:
            pattern = re.compile(spec.find, flags)
            pattern.sub(spec.replace, "")  # reveals a bad group reference in the replacement
        except (re.error, IndexError) as exc:  # IndexError: an unknown \g<name> in the replacement
            raise TransformError(f"Invalid regular expression: {exc}") from exc
        template = spec.replace

        def expand(match: re.Match[str]) -> str:
            return match.expand(template)

    def apply(value: str) -> Replaced:
        try:
            if spec.whole_field:
                match = pattern.fullmatch(value)
                return Replaced(expand(match), 1) if match else Replaced(value, 0)
            new, count = pattern.subn(expand, value)
        except (re.error, IndexError) as exc:
            raise TransformError(f"Invalid replacement: {exc}") from exc
        return Replaced(new, count)

    return apply


@dataclass(frozen=True)
class FieldChange:
    path: Path
    field: str
    old: str
    new: str


def plan_field_changes(
    items: Sequence[tuple[Path, TagSet]], fields: Sequence[str], func: Callable[[str], str]
) -> list[FieldChange]:
    """Apply `func` to each chosen field of each file. Only real changes are returned."""
    changes = []
    for path, tags in items:
        for field in fields:
            old = getattr(tags, field)
            new = func(old)
            if new != old:
                changes.append(FieldChange(path, field, old, new))
    return changes


def changes_by_path(changes: Sequence[FieldChange]) -> Mapping[Path, dict[str, str]]:
    result: dict[Path, dict[str, str]] = {}
    for change in changes:
        result.setdefault(change.path, {})[change.field] = change.new
    return result
