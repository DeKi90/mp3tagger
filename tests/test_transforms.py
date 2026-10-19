from pathlib import Path

import pytest

from mp3tagger.core.models import TagSet
from mp3tagger.core.transforms import (
    FindReplace,
    TransformError,
    changes_by_path,
    compile_find_replace,
    convert_case,
    plan_field_changes,
)

# --- case ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Hello World", "HELLO WORLD"),
        ("ünïcode straße", "ÜNÏCODE STRASSE"),
        ("", ""),
        ("123 - 45", "123 - 45"),
    ],
)
def test_upper(value, expected):
    assert convert_case(value, "upper") == expected


def test_lower():
    assert convert_case("Hello WORLD ÄÖ", "lower") == "hello world äö"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("the lord of the rings", "The Lord of the Rings"),
        ("a day in the life", "A Day in the Life"),
        ("SHOUTING TITLE HERE", "Shouting Title Here"),
        ("what are you waiting for", "What Are You Waiting For"),  # last word is capitalised
        ("of mice and men", "Of Mice and Men"),  # first word is capitalised
        ("don't stop me now", "Don't Stop Me Now"),
        ("it’s a long way", "It’s a Long Way"),
        ("rock-n-roll (live) [remastered]", "Rock-N-Roll (Live) [Remastered]"),
        ("under_score words", "Under_Score Words"),
        ("ac/dc - back in black", "Ac/Dc - Back in Black"),
        ("  padded   spaces  ", "  Padded   Spaces  "),
        ("track 01 of 12", "Track 01 of 12"),
        ("", ""),
        ("---", "---"),
        ("x", "X"),
    ],
)
def test_title_case(value, expected):
    assert convert_case(value, "title") == expected


def test_title_case_can_capitalise_small_words_too():
    assert convert_case("the lord of the rings", "title", keep_small_words=False) == (
        "The Lord Of The Rings"
    )


def test_title_case_non_english_text_is_just_capitalised():
    assert convert_case("karlsson vom dach", "title") == "Karlsson Vom Dach"
    assert convert_case("élan vital", "title") == "Élan Vital"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("HELLO WORLD", "Hello world"),
        ("hello. how ARE you? fine! thanks", "Hello. How are you? Fine! Thanks"),
        ("  leading space", "  Leading space"),
        ("123 abc", "123 abc"),  # does not start with a letter: nothing to capitalise
        ("e.g. this", "E.g. This"),  # known limit: abbreviations look like sentence ends
        ("", ""),
    ],
)
def test_sentence_case(value, expected):
    assert convert_case(value, "sentence") == expected


def test_unknown_style_is_an_error():
    with pytest.raises(TransformError):
        convert_case("x", "weird")  # type: ignore[arg-type]


# --- find / replace --------------------------------------------------------------------------


def run(spec: FindReplace, value: str):
    return compile_find_replace(spec)(value)


def test_plain_replace_all_occurrences_case_insensitive_by_default():
    result = run(FindReplace("the", "THE"), "The cat and the hat")
    assert (result.value, result.count) == ("THE cat and THE hat", 2)


def test_match_case():
    result = run(FindReplace("the", "X", match_case=True), "The cat and the hat")
    assert (result.value, result.count) == ("The cat and X hat", 1)


def test_plain_text_is_literal_not_regex_and_backslashes_are_literal():
    assert run(FindReplace("a.b", "-"), "a.b axb").value == "- axb"
    assert run(FindReplace("(feat.)", ""), "Song (feat.) X").value == "Song  X"
    assert run(FindReplace("x", r"\1\n"), "axb").value == r"a\1\nb"


def test_no_match_returns_the_value_unchanged():
    result = run(FindReplace("zzz", "y"), "abc")
    assert (result.value, result.count) == ("abc", 0)


def test_replace_with_nothing_removes_the_text():
    assert run(FindReplace(" (Live)", ""), "Song (Live)").value == "Song"


def test_regex_with_numbered_and_named_groups():
    assert run(FindReplace(r"(\w+), (\w+)", r"\2 \1", regex=True), "Doe, John").value == "John Doe"
    named = FindReplace(r"(?P<a>\d+)-(?P<b>\d+)", r"\g<b>-\g<a>", regex=True)
    assert run(named, "10-20").value == "20-10"


def test_regex_anchors_and_flags():
    assert run(FindReplace(r"^the\s+", "", regex=True), "The Beatles").value == "Beatles"
    assert run(FindReplace(r"\s+$", "", regex=True), "x   ").value == "x"
    assert run(FindReplace(r"^the\s+", "", regex=True, match_case=True), "The X").count == 0
    assert run(FindReplace(r"[aeiou]", "_", regex=True), "banana").value == "b_n_n_"


def test_regex_unicode_and_case_insensitivity():
    assert run(FindReplace("ÄÖ", "ae", regex=True), "äö").value == "ae"
    assert run(FindReplace("straße", "x"), "STRASSE straße").value == "STRASSE x"


def test_whole_field_plain():
    spec = FindReplace("rock", "Rock", whole_field=True)
    assert run(spec, "ROCK").value == "Rock"
    assert run(spec, "rock music").count == 0  # only a complete match counts


def test_whole_field_regex_with_groups():
    spec = FindReplace(r"(\d+)/(\d+)", r"\1", regex=True, whole_field=True)
    assert run(spec, "3/12").value == "3"
    assert run(spec, "disc 3/12").count == 0


def test_empty_find_text_is_refused_in_both_modes():
    with pytest.raises(TransformError, match="Enter the text"):
        compile_find_replace(FindReplace(""))
    with pytest.raises(TransformError, match="Enter the text"):
        compile_find_replace(FindReplace("", regex=True))


def test_invalid_regex_is_reported():
    with pytest.raises(TransformError, match="Invalid regular expression"):
        compile_find_replace(FindReplace("(unclosed", regex=True))


def test_invalid_group_reference_in_the_replacement_is_reported_up_front():
    with pytest.raises(TransformError, match="Invalid regular expression"):
        compile_find_replace(FindReplace(r"(a)", r"\2", regex=True))
    with pytest.raises(TransformError):
        compile_find_replace(FindReplace(r"(a)", r"\g<nope>", regex=True))


def test_empty_matches_are_handled_without_looping():
    assert run(FindReplace(r"x*", "-", regex=True), "abc").value == "-a-b-c-"


# --- planning --------------------------------------------------------------------------------

A, B = Path("/m/a.mp3"), Path("/m/b.mp3")


def test_plan_field_changes_returns_only_real_changes_of_the_chosen_fields():
    items = [
        (A, TagSet(title="hello", artist="X", album="already Fine")),
        (B, TagSet(title="HELLO", artist="y")),
    ]
    changes = plan_field_changes(items, ["title", "artist"], lambda v: v.upper())
    assert [(c.path, c.field, c.old, c.new) for c in changes] == [
        (A, "title", "hello", "HELLO"),
        (B, "artist", "y", "Y"),
    ]  # B's title is unchanged; album was not chosen


def test_changes_by_path_groups_fields():
    items = [(A, TagSet(title="a", artist="b")), (B, TagSet(title="c"))]
    grouped = changes_by_path(plan_field_changes(items, ["title", "artist"], str.upper))
    assert grouped == {A: {"title": "A", "artist": "B"}, B: {"title": "C"}}
