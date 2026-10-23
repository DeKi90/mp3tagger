"""Format strings such as "%artist% - %title%", used to read tags from file names and to build
file names (or other tag values) from tags.

Placeholders are the tag field names (``%albumartist%`` is accepted for ``%album_artist%``),
optionally with a zero-padding width: ``%track:2%`` turns 3 into 03. When reading, ``%ignore%``
matches a part of the name without storing it.

A ``/`` in a pattern separates folder levels below the folder that is open in the application:
when writing file names the folders are created there, when reading they are matched against the
path of each file relative to it.
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


def relative_path(path: Path, base: Path | None) -> Path:
    """`path` below `base`; just the file name if it is not below it (or there is no base)."""
    if base is not None:
        try:
            return path.relative_to(base)
        except ValueError:
            pass
    return Path(path.name)


def parse_path(compiled: ParsePattern, relative: Path) -> dict[str, str] | None:
    """The tag values encoded in `relative`, a file's path below the open folder (the extension
    is ignored), or None if it does not match.

    A pattern without ``/`` reads the file name only, wherever the file is. A pattern with ``/``
    must account for every folder level: ``%artist%/%album%/%title%`` matches only files exactly
    two folders down.
    """
    depth = len(compiled.components)
    names = [*relative.parent.parts, relative.stem] if depth > 1 else [relative.stem]
    if len(names) != depth:
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


def parse_paths(
    paths: Sequence[Path], pattern: str, base: Path | None = None
) -> list[tuple[Path, dict[str, str] | None]]:
    """Apply `pattern` to every path, read relative to `base`, the open folder. Raises
    PatternError for an invalid pattern."""
    compiled = compile_parse_pattern(pattern)
    return [(path, parse_path(compiled, relative_path(path, base))) for path in paths]


# --- writing: tags -> text -----------------------------------------------------------------


@dataclass(frozen=True)
class FormatPattern:
    components: tuple[tuple[Token, ...], ...]  # one per path level, the last is the file name
    for_filename: bool

    @property
    def has_folders(self) -> bool:
        return len(self.components) > 1


def _split_levels(tokens: list[Token]) -> list[list[Token]]:
    """Split a pattern into path levels at every ``/`` in its literal text."""
    levels: list[list[Token]] = [[]]
    for token in tokens:
        if isinstance(token, str):
            first, *rest = token.split("/")
            if first:
                levels[-1].append(first)
            for part in rest:
                levels.append([part] if part else [])
        else:
            levels[-1].append(token)
    return levels


def compile_format(pattern: str, *, for_filename: bool = False) -> FormatPattern:
    """Compile a pattern for building text from tags.

    With `for_filename` the result is a path below the open folder: ``/`` (or ``\\``) separates
    folder levels, values are made safe, and no level can be empty, ``.`` or ``..``.
    """
    if not pattern.strip():
        raise PatternError("The pattern is empty")
    tokens = tokenize(pattern.replace("\\", "/") if for_filename else pattern)
    if not any(isinstance(t, Placeholder) for t in tokens):
        raise PatternError("The pattern contains no field such as %title%")
    if any(isinstance(t, Placeholder) and t.field == IGNORE for t in tokens):
        raise PatternError("%ignore% only makes sense when reading file names")
    levels = _split_levels(tokens) if for_filename else [tokens]
    for level in levels:
        if not level:
            raise PatternError("A folder or file name in the pattern is empty (check for //)")
        if all(isinstance(t, str) for t in level) and "".join(map(str, level)).strip() in {
            ".",
            "..",
        }:
            raise PatternError("A folder name cannot be . or ..")
    return FormatPattern(tuple(tuple(level) for level in levels), for_filename)


@dataclass(frozen=True)
class Formatted:
    parts: tuple[str, ...]  # one per path level; just one unless the pattern has folders
    empty_fields: tuple[str, ...]  # fields used by the pattern that have no value

    @property
    def text(self) -> str:
        return "/".join(self.parts)


def _level(tokens: tuple[Token, ...], tags: TagSet, for_filename: bool, empty: list[str]) -> str:
    parts: list[str] = []
    for token in tokens:
        if isinstance(token, str):
            parts.append(token)
            continue
        value = getattr(tags, token.field)
        if for_filename and token.field in ("track", "disc"):
            value = value.partition("/")[0]  # "3/12" -> "3"
        if not value:
            empty.append(token.field)
        if token.width and value.isdigit():
            value = value.zfill(token.width)
        parts.append(_ILLEGAL_IN_FILE_NAME.sub("_", value) if for_filename else value)
    return "".join(parts)


def _safe_name(text: str, is_file: bool) -> str:
    """Make one folder or file name safe, or raise PatternError if nothing usable is left."""
    text = text.strip(" ").rstrip(". ")
    if text.startswith("."):
        text = "_" + text[1:]  # a leading dot would hide it from the file list
    if not text:
        raise PatternError(
            "The file name would be empty" if is_file else "A folder name would be empty"
        )
    if len(text.encode()) > MAX_FILE_NAME_BYTES:
        raise PatternError(
            "The file name would be too long" if is_file else "A folder name would be too long"
        )
    return text


def format_tags(compiled: FormatPattern, tags: TagSet) -> Formatted:
    """Build the text for `tags`. For file names, raises PatternError if a level would come out
    empty or too long."""
    empty: list[str] = []
    parts = [_level(level, tags, compiled.for_filename, empty) for level in compiled.components]
    if compiled.for_filename:
        last = len(parts) - 1
        parts = [_safe_name(text, index == last) for index, text in enumerate(parts)]
    return Formatted(tuple(parts), tuple(dict.fromkeys(empty)))


def format_values(
    items: Sequence[tuple[Path, TagSet]], pattern: str
) -> list[tuple[Path, Formatted]]:
    """Build the text for each file's tags (to copy into another tag field).

    Raises PatternError for an invalid pattern.
    """
    compiled = compile_format(pattern)
    return [(path, format_tags(compiled, tags)) for path, tags in items]
