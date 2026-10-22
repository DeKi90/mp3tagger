from pathlib import Path

import pytest

from mp3tagger.core.models import TagSet
from mp3tagger.core.patterns import (
    PatternError,
    compile_format,
    compile_parse_pattern,
    format_tags,
    parse_path,
    parse_paths,
    relative_path,
)


def parse(pattern: str, path: str) -> dict[str, str] | None:
    """Read `path`, which is relative to the open folder (as parse_paths computes it)."""
    return parse_path(compile_parse_pattern(pattern), Path(path))


# --- reading ---------------------------------------------------------------------------------


def test_artist_dash_title():
    assert parse("%artist% - %title%", "/m/Beatles - Help.mp3") == {
        "artist": "Beatles",
        "title": "Help",
    }


def test_extension_is_ignored_whatever_it_is():
    assert parse("%title%", "/m/Song.MP3") == {"title": "Song"}
    assert parse("%title%", "/m/My.Song.mp3") == {"title": "My.Song"}  # only the last suffix


def test_first_separator_wins_so_the_rest_belongs_to_the_last_field():
    assert parse("%track% - %title%", "/m/01 - Song - Live.mp3") == {
        "track": "01",
        "title": "Song - Live",
    }


def test_no_match_is_none():
    assert parse("%artist% - %title%", "/m/NoSeparator.mp3") is None


def test_surrounding_whitespace_is_stripped():
    assert parse("%artist%-%title%", "/m/ Beatles  -  Help .mp3") == {
        "artist": "Beatles",
        "title": "Help",
    }


def test_literal_text_is_matched_exactly_and_regex_characters_are_safe():
    assert parse("(%year%) %title% [live].*", "/m/(1999) Song [live].*.mp3") == {
        "year": "1999",
        "title": "Song",
    }
    assert parse("(%year%) %title%", "/m/1999 Song.mp3") is None


def test_ignore_matches_without_storing():
    assert parse("%ignore% - %title%", "/m/Whatever - Help.mp3") == {"title": "Help"}
    assert parse("%ignore% %ignore% %title%", "/m/a b Help.mp3") == {"title": "Help"}


def test_repeated_field_must_have_the_same_value():
    assert parse("%artist% - %artist% live", "/m/X - X live.mp3") == {"artist": "X"}
    assert parse("%artist% - %artist% live", "/m/X - Y live.mp3") is None


def test_albumartist_alias_and_case_insensitive_names():
    assert parse("%AlbumArtist% - %Title%", "/m/V - T.mp3") == {"album_artist": "V", "title": "T"}
    assert parse("%album_artist%", "/m/V.mp3") == {"album_artist": "V"}


def test_width_in_a_reading_pattern_is_accepted_and_ignored():
    assert parse("%track:2% %title%", "/m/3 Song.mp3") == {"track": "3", "title": "Song"}


def test_folder_levels_are_read_from_the_path_below_the_open_folder():
    pattern = "%artist%/%album%/%track% - %title%"
    assert parse(pattern, "Band/LP/01 - Song.mp3") == {
        "artist": "Band",
        "album": "LP",
        "track": "01",
        "title": "Song",
    }
    assert parse(pattern, "Song.mp3") is None  # not enough folders
    assert parse(pattern, "LP/01 - Song.mp3") is None
    assert parse(pattern, "Band/LP/NoTrack.mp3") is None


def test_a_pattern_with_folders_must_account_for_every_level():
    pattern = "%artist%/%album%/%title%"
    assert parse(pattern, "Band/LP/Song.mp3") == {"artist": "Band", "album": "LP", "title": "Song"}
    assert parse(pattern, "Band/LP/Disc 1/Song.mp3") is None  # one level too deep: no guessing


def test_a_pattern_without_folders_reads_the_file_name_wherever_the_file_is():
    assert parse("%artist% - %title%", "Band/LP/Disc 1/X - Y.mp3") == {"artist": "X", "title": "Y"}
    assert parse("%artist% - %title%", "X - Y.mp3") == {"artist": "X", "title": "Y"}


def test_backslash_also_separates_folders_and_literal_folder_names_must_match():
    assert parse("Music\\%artist%\\%title%", "Music/Band/Song.mp3") == {
        "artist": "Band",
        "title": "Song",
    }
    assert parse("Music/%artist%/%title%", "Other/Band/Song.mp3") is None


def test_same_field_in_two_folder_levels_must_agree():
    assert parse("%artist%/%artist% - %title%", "X/X - T.mp3") == {"artist": "X", "title": "T"}
    assert parse("%artist%/%artist% - %title%", "X/Y - T.mp3") is None


def test_relative_path_is_taken_below_the_base_or_falls_back_to_the_name():
    assert relative_path(Path("/m/Band/LP/a.mp3"), Path("/m")) == Path("Band/LP/a.mp3")
    assert relative_path(Path("/m/a.mp3"), Path("/m")) == Path("a.mp3")
    assert relative_path(Path("/elsewhere/a.mp3"), Path("/m")) == Path("a.mp3")
    assert relative_path(Path("/m/Band/a.mp3"), None) == Path("a.mp3")


def test_parse_paths_returns_a_result_per_path_in_order():
    paths = [Path("/m/A - 1.mp3"), Path("/m/bad.mp3"), Path("/m/B - 2.mp3")]
    result = parse_paths(paths, "%artist% - %title%", Path("/m"))
    assert [r for _, r in result] == [
        {"artist": "A", "title": "1"},
        None,
        {"artist": "B", "title": "2"},
    ]


def test_parse_paths_reads_folders_relative_to_the_base():
    paths = [Path("/lib/Band/LP/01 - Song.mp3"), Path("/lib/Band/01 - Loose.mp3")]
    result = parse_paths(paths, "%artist%/%album%/%track% - %title%", Path("/lib"))
    assert result[0][1] == {"artist": "Band", "album": "LP", "track": "01", "title": "Song"}
    assert result[1][1] is None  # only one folder below the open folder
    # Opened one level deeper, the same files read differently: the base decides.
    deeper = parse_paths([paths[0]], "%album%/%track% - %title%", Path("/lib/Band"))
    assert deeper[0][1] == {"album": "LP", "track": "01", "title": "Song"}


@pytest.mark.parametrize(
    ("pattern", "message"),
    [
        ("", "empty"),
        ("   ", "empty"),
        ("just text", "no field"),
        ("%titel%", "Unknown field %titel%"),
        ("%artist% - %nope%", "Unknown field %nope%"),
        ("%ignore%", "no field"),
    ],
)
def test_invalid_reading_patterns(pattern, message):
    with pytest.raises(PatternError, match=message):
        compile_parse_pattern(pattern)


def test_unknown_field_error_lists_the_available_ones():
    with pytest.raises(PatternError, match=r"%title%.*%composer%"):
        compile_parse_pattern("%wrong%")


def test_lone_percent_signs_are_literal():
    assert parse("100% %title%", "/m/100% Pure.mp3") == {"title": "Pure"}


# --- writing ---------------------------------------------------------------------------------

TAGS = TagSet(title="Help!", artist="The Beatles", album="Help", track="3/12", year="1965")


def fmt(pattern: str, tags: TagSet = TAGS, *, filename: bool = False):
    return format_tags(compile_format(pattern, for_filename=filename), tags)


def test_format_plain_text():
    assert fmt("%artist% - %album%").text == "The Beatles - Help"


def test_format_zero_pads_numbers_only():
    assert fmt("%track:2%", TagSet(track="3")).text == "03"
    assert fmt("%track:3%", TagSet(track="12")).text == "012"
    assert fmt("%title:5%", TagSet(title="abc")).text == "abc"  # not numeric: unchanged
    assert fmt("%track:2%", TagSet(track="123")).text == "123"  # never truncates


def test_track_and_disc_totals_are_dropped_in_file_names_but_kept_otherwise():
    assert fmt("%track:2% %title%", filename=True).text == "03 Help!"
    assert fmt("%track%", filename=False).text == "3/12"
    assert fmt("%disc%", TagSet(disc="1/2"), filename=True).text == "1"


def test_file_names_replace_illegal_characters_in_values_only():
    tags = TagSet(title='AC/DC: "Live"?', artist="A|B")
    assert fmt("%artist% - %title%", tags, filename=True).text == "A_B - AC_DC_ _Live__"
    assert fmt("%title%", tags, filename=False).text == 'AC/DC: "Live"?'


def test_folders_in_a_file_name_pattern_give_one_part_per_level():
    tags = TagSet(artist="The Beatles", album="Help", track="3/12", title="Help!")
    result = fmt("%artist%/%album%/%track:2% - %title%", tags, filename=True)
    assert result.parts == ("The Beatles", "Help", "03 - Help!")
    assert result.text == "The Beatles/Help/03 - Help!"
    assert fmt("%artist% - %title%", tags, filename=True).parts == ("The Beatles - Help!",)


def test_backslash_also_separates_levels_when_writing_file_names():
    tags = TagSet(artist="A", title="T")
    assert fmt("%artist%\\%title%", tags, filename=True).parts == ("A", "T")


def test_a_slash_inside_a_value_never_creates_a_level():
    tags = TagSet(artist="AC/DC", album="Back\\In Black", title="T")
    result = fmt("%artist%/%album%/%title%", tags, filename=True)
    assert result.parts == ("AC_DC", "Back_In Black", "T")


def test_tag_values_cannot_climb_out_of_the_folder():
    tags = TagSet(artist="..", album=".", title="T")
    with pytest.raises(PatternError, match="folder name would be empty"):
        fmt("%artist%/%title%", tags, filename=True)
    with pytest.raises(PatternError, match="folder name would be empty"):
        fmt("%album%/%title%", tags, filename=True)


def test_every_level_is_trimmed_and_never_hidden():
    tags = TagSet(artist=" X. ", album=".hidden", title="T")
    assert fmt("%artist%/%album%/%title%", tags, filename=True).parts == ("X", "_hidden", "T")


def test_an_empty_level_is_an_error_naming_what_is_missing():
    tags = TagSet(artist="A", title="T")  # no album
    with pytest.raises(PatternError, match="A folder name would be empty"):
        fmt("%artist%/%album%/%title%", tags, filename=True)
    with pytest.raises(PatternError, match="The file name would be empty"):
        fmt("%artist%/%album%", tags, filename=True)


def test_overlong_folder_names_are_refused():
    with pytest.raises(PatternError, match="folder name would be too long"):
        fmt("%album%/%title%", TagSet(album="x" * 300, title="T"), filename=True)


@pytest.mark.parametrize(
    ("pattern", "message"),
    [
        ("../%title%", r"cannot be \. or \.\."),
        ("./%title%", r"cannot be \. or \.\."),
        ("%artist%/../%title%", r"cannot be \. or \.\."),
        ("/%title%", "is empty"),
        ("%title%/", "is empty"),
        ("%artist%//%title%", "is empty"),
    ],
)
def test_invalid_folder_patterns_are_refused_up_front(pattern, message):
    with pytest.raises(PatternError, match=message):
        compile_format(pattern, for_filename=True)


def test_folders_are_not_special_when_building_other_tag_values():
    tags = TagSet(artist="A", title="T")
    result = fmt("%artist%/%title%", tags, filename=False)
    assert result.parts == ("A/T",) and result.text == "A/T"
    compile_format("../%title%")  # nothing to guard: it is only text


def test_file_names_are_trimmed_and_never_hidden():
    assert fmt("  %title%. ", filename=True).text == "Help!"
    assert fmt("%album%", TagSet(album=".hidden"), filename=True).text == "_hidden"


def test_empty_and_overlong_file_names_are_errors():
    with pytest.raises(PatternError, match="empty"):
        fmt("%artist%", TagSet(), filename=True)
    with pytest.raises(PatternError, match="too long"):
        fmt("%title%", TagSet(title="x" * 300), filename=True)
    with pytest.raises(PatternError, match="too long"):
        fmt("%title%", TagSet(title="ä" * 150), filename=True)  # counted in bytes


def test_empty_fields_are_reported_once_each():
    result = fmt("%artist% - %album% - %artist%", TagSet(title="t"))
    assert result.empty_fields == ("artist", "album")
    assert fmt("%title%", TagSet(title="t")).empty_fields == ()


def test_format_with_empty_field_still_produces_text_for_tag_values():
    assert fmt("%artist% - %title%", TagSet(title="t")).text == " - t"


@pytest.mark.parametrize(
    ("pattern", "message"),
    [("", "empty"), ("text only", "no field"), ("%ignore% %title%", "ignore"), ("%x%", "Unknown")],
)
def test_invalid_writing_patterns(pattern, message):
    with pytest.raises(PatternError, match=message):
        compile_format(pattern)


def test_format_values_for_copying_between_fields():
    from mp3tagger.core.patterns import format_values

    items = [
        (Path("/m/a.mp3"), TagSet(artist="A", title="T")),
        (Path("/m/b.mp3"), TagSet(title="U")),
    ]
    result = format_values(items, "%artist% - %title%")
    assert [(p.name, f.text, f.empty_fields) for p, f in result] == [
        ("a.mp3", "A - T", ()),
        ("b.mp3", " - U", ("artist",)),
    ]
    with pytest.raises(PatternError):
        format_values(items, "%nope%")
