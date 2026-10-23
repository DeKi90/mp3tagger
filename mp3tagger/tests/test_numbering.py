from pathlib import Path

import pytest

from mp3tagger.core.numbering import number_tracks

A, B, C = Path("/m/x/a.mp3"), Path("/m/x/b.mp3"), Path("/m/x/c.mp3")
D, E = Path("/m/y/d.mp3"), Path("/m/y/e.mp3")


def test_numbers_in_the_given_order():
    assert number_tracks([C, A, B]) == {C: "1", A: "2", B: "3"}


def test_start_value_and_zero_padding():
    assert number_tracks([A, B], start=9, width=2) == {A: "09", B: "10"}
    assert number_tracks([A], start=0) == {A: "0"}


def test_total_is_appended():
    assert number_tracks([A, B, C], total=True) == {A: "1/3", B: "2/3", C: "3/3"}
    assert number_tracks([A, B], total=True, width=2) == {A: "01/02", B: "02/02"}


def test_one_sequence_across_folders_by_default():
    assert number_tracks([A, B, D, E]) == {A: "1", B: "2", D: "3", E: "4"}


def test_restart_in_every_folder_with_per_folder_totals():
    result = number_tracks([A, D, B, E, C], restart_per_folder=True, total=True)
    assert result == {A: "1/3", B: "2/3", C: "3/3", D: "1/2", E: "2/2"}


def test_start_applies_to_every_folder_when_restarting():
    assert number_tracks([A, D], start=5, restart_per_folder=True) == {A: "5", D: "5"}


def test_nothing_and_invalid_start():
    assert number_tracks([]) == {}
    with pytest.raises(ValueError):
        number_tracks([A], start=-1)
