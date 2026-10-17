import pytest

from mp3tagger.core.batch import KEEP, merge_tags
from mp3tagger.core.models import FIELD_NAMES, TagSet


def test_single_track_has_no_mixed_fields():
    tags = TagSet(title="A", artist="X")
    merged = merge_tags([tags])
    assert merged.mixed == frozenset()
    assert merged.values == tags.as_dict()


def test_equal_fields_are_shown_differing_fields_are_keep():
    merged = merge_tags(
        [TagSet(title="A", artist="X", year="2000"), TagSet(title="B", artist="X", year="2001")]
    )
    assert merged.get("artist") == "X"
    assert merged.get("title") == merged.get("year") == KEEP
    assert merged.mixed == {"title", "year"}


def test_empty_vs_set_counts_as_different():
    merged = merge_tags([TagSet(genre="Rock"), TagSet()])
    assert "genre" in merged.mixed


def test_all_empty_is_uniform_empty():
    merged = merge_tags([TagSet(), TagSet(), TagSet()])
    assert merged.mixed == frozenset()
    assert set(merged.values) == set(FIELD_NAMES)
    assert all(v == "" for v in merged.values.values())


def test_merge_of_nothing_is_an_error():
    with pytest.raises(ValueError):
        merge_tags([])
