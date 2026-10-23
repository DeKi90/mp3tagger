import pytest

from mp3tagger.ui.tag_panel import year_input_ok


@pytest.mark.parametrize("value", [None, "", "2024", "2024-05", "2024-05-01", "<keep>"])
def test_acceptable_year_inputs(value):
    assert year_input_ok(value)


@pytest.mark.parametrize("value", ["abcd", "99", "2024-13", "<keep", "keep", "2024/05/01"])
def test_unacceptable_year_inputs(value):
    assert not year_input_ok(value)
