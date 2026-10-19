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
)


def parse(pattern: str, path: str) -> dict[str, str] | None:
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


def test_folder_levels():
    pattern = "%artist%/%album%/%track% - %title%"
    assert parse(pattern, "/music/Band/LP/01 - Song.mp3") == {
        "artist": "Band",
        "album": "LP",
        "track": "01",
        "title": "Song",
    }
    assert parse(pattern, "/Song.mp3") is None  # not enough folders
    assert parse(pattern, "/music/Band/LP/NoTrack.mp3") is None


def test_backslash_also_separates_folders_and_literal_folder_names_must_match():
    assert parse("Music\\%artist%\\%title%", "/x/Music/Band/Song.mp3") == {
        "artist": "Band",
        "title": "Song",
    }
    assert parse("Music/%artist%/%title%", "/x/Other/Band/Song.mp3") is None


def test_same_field_in_two_folder_levels_must_agree():
    assert parse("%artist%/%artist% - %title%", "/m/X/X - T.mp3") == {"artist": "X", "title": "T"}
    assert parse("%artist%/%artist% - %title%", "/m/X/Y - T.mp3") is None


def test_parse_paths_returns_a_result_per_path_in_order():
    paths = [Path("/m/A - 1.mp3"), Path("/m/bad.mp3"), Path("/m/B - 2.mp3")]
    result = parse_paths(paths, "%artist% - %title%")
    assert [r for _, r in result] == [
        {"artist": "A", "title": "1"},
        None,
        {"artist": "B", "title": "2"},
    ]


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


def test_file_names_cannot_contain_folder_separators_in_the_pattern():
    with pytest.raises(PatternError, match="cannot contain"):
        compile_format("%artist%/%title%", for_filename=True)
    with pytest.raises(PatternError, match="cannot contain"):
        compile_format("%artist%\\%title%", for_filename=True)
    compile_format("%artist%/%title%", for_filename=False)  # fine for tag values


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
