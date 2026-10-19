"""Format strings such as "%artist% - %title%", used to read tags from file names and to build
file names (or other tag values) from tags.

Placeholders are the tag field names (``%albumartist%`` is accepted for ``%album_artist%``),
optionally with a zero-padding width: ``%track:2%`` turns 3 into 03. When reading, ``%ignore%``
matches a part of the name without storing it.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from mp3tagger.core.models import FIELD_NAMES, TagSet

IGNORE = "ignore"
ALIASES = {"albumartist": "album_artist"}
_TOKEN = re.compile(r"%([A-Za-z_]+)(?::(\d+))?%")
_ILLEGAL_IN_FILE_NAME = re.compile(r'[\x00-\x1f/\\:*?"<>|]')
MAX_FILE_NAME_BYTES = 255


class PatternError(ValueError):
    """The pattern is not valid. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class Placeholder:
    field: str  # a tag field name, or IGNORE
    width: int = 0


Token = str | Placeholder


def tokenize(pattern: str) -> list[Token]:
    tokens: list[Token] = []
    position = 0
    for match in _TOKEN.finditer(pattern):
        if match.start() > position:
            tokens.append(pattern[position : match.start()])
        name = match.group(1).lower()
        name = ALIASES.get(name, name)
        if name != IGNORE and name not in FIELD_NAMES:
            raise PatternError(f"Unknown field %{match.group(1)}%. Fields: {_field_list()}")
        tokens.append(Placeholder(name, int(match.group(2) or 0)))
        position = match.end()
    if position < len(pattern):
        tokens.append(pattern[position:])
    return tokens


def _field_list() -> str:
    return ", ".join(f"%{name}%" for name in FIELD_NAMES)


# --- reading: file name -> tags ------------------------------------------------------------


@dataclass(frozen=True)
class ParsePattern:
    components: tuple[re.Pattern[str], ...]  # one per path component, outermost folder first
    fields: tuple[str, ...]  # the tag fields the pattern fills, in order


def compile_parse_pattern(pattern: str) -> ParsePattern:
    """Compile a pattern for reading file names. ``/`` separates folder levels."""
    if not pattern.strip():
        raise PatternError("The pattern is empty")
    components: list[re.Pattern[str]] = []
    fields: list[str] = []
    for part in pattern.replace("\\", "/").split("/"):
        regex, seen = "", set()
        for token in tokenize(part):
            if isinstance(token, str):
                regex += re.escape(token)
            elif token.field == IGNORE:
                regex += ".+?"
            elif token.field in seen:  # a repeated field must have the same value
                regex += f"(?P={token.field})"
            else:
                seen.add(token.field)
                regex += f"(?P<{token.field}>.+?)"
                if token.field not in fields:
                    fields.append(token.field)
        components.append(re.compile(f"^{regex}$", re.DOTALL))
    if not fields:
        raise PatternError("The pattern contains no field such as %title%")
    return ParsePattern(tuple(components), tuple(fields))


def parse_path(compiled: ParsePattern, path: Path) -> dict[str, str] | None:
    """The tag values `path` encodes, or None if it does not match. The extension is ignored."""
    depth = len(compiled.components)
    names = [*path.parent.parts[-(depth - 1) :], path.stem] if depth > 1 else [path.stem]
    if len(names) < depth:
        return None
    values: dict[str, str] = {}
    for regex, name in zip(compiled.components, names, strict=True):
        match = regex.match(name)
        if match is None:
            return None
        for field, value in match.groupdict().items():
            value = value.strip()
            if values.setdefault(field, value) != value:
                return None
    return values


def parse_paths(paths: Sequence[Path], pattern: str) -> list[tuple[Path, dict[str, str] | None]]:
    """Apply `pattern` to every path. Raises PatternError for an invalid pattern."""
    compiled = compile_parse_pattern(pattern)
    return [(path, parse_path(compiled, path)) for path in paths]


# --- writing: tags -> text -----------------------------------------------------------------


@dataclass(frozen=True)
class FormatPattern:
    tokens: tuple[Token, ...]
    for_filename: bool


def compile_format(pattern: str, *, for_filename: bool = False) -> FormatPattern:
    """Compile a pattern for building text from tags. With `for_filename` the result is a file
    name: values are made safe, and the pattern may not contain a folder separator."""
    if not pattern.strip():
        raise PatternError("The pattern is empty")
    tokens = tokenize(pattern)
    if not any(isinstance(t, Placeholder) for t in tokens):
        raise PatternError("The pattern contains no field such as %title%")
    if any(isinstance(t, Placeholder) and t.field == IGNORE for t in tokens):
        raise PatternError("%ignore% only makes sense when reading file names")
    if for_filename and any(isinstance(t, str) and ("/" in t or "\\" in t) for t in tokens):
        raise PatternError("A file name cannot contain / or \\")
    return FormatPattern(tuple(tokens), for_filename)


@dataclass(frozen=True)
class Formatted:
    text: str
    empty_fields: tuple[str, ...]  # fields used by the pattern that have no value


def format_tags(compiled: FormatPattern, tags: TagSet) -> Formatted:
    """Build the text for `tags`. Raises PatternError if a file name would come out empty."""
    parts: list[str] = []
    empty: list[str] = []
    for token in compiled.tokens:
        if isinstance(token, str):
            parts.append(token)
            continue
        value = getattr(tags, token.field)
        if compiled.for_filename and token.field in ("track", "disc"):
            value = value.partition("/")[0]  # "3/12" -> "3"
        if not value:
            empty.append(token.field)
        if token.width and value.isdigit():
            value = value.zfill(token.width)
        parts.append(_ILLEGAL_IN_FILE_NAME.sub("_", value) if compiled.for_filename else value)
    text = "".join(parts)
    if compiled.for_filename:
        text = text.strip(" ").rstrip(". ")
        if text.startswith("."):
            text = "_" + text[1:]  # a leading dot would hide the file from the file list
        if not text:
            raise PatternError("The file name would be empty")
        if len(text.encode()) > MAX_FILE_NAME_BYTES:
            raise PatternError("The file name would be too long")
    return Formatted(text, tuple(dict.fromkeys(empty)))


def format_values(
    items: Sequence[tuple[Path, TagSet]], pattern: str
) -> list[tuple[Path, Formatted]]:
    """Build the text for each file's tags (to copy into another tag field).

    Raises PatternError for an invalid pattern.
    """
    compiled = compile_format(pattern)
    return [(path, format_tags(compiled, tags)) for path, tags in items]
