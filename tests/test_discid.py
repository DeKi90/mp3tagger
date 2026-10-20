import pytest

from mp3tagger.core.discid import InvalidTocError, Toc, parse_mcdi


def wmp(text: str) -> bytes:
    """An MCDI frame as Windows Media Player writes it: UTF-16 text plus a terminator."""
    return text.encode("utf-16-le") + b"\x00\x00"


# Real tables of contents from audiobook CDs, with the Disc IDs MusicBrainz knows them by (each
# one was looked up and found the matching release, so these vectors are verified).
KARLSSON = ("6+96+926A+13B91+1A876+23885+2D8DB+34008", "QFMiaZBX.YfwImg_6WzFSe0L.I4-")
PUMUCKL = ("2+96+1DC94+3A640", "AZfHkpq3HJPvDW8Pp0GoAHeqhtg-")


@pytest.mark.parametrize(("text", "disc_id"), [KARLSSON, PUMUCKL])
def test_disc_id_matches_the_one_musicbrainz_knows(text, disc_id):
    assert parse_mcdi(wmp(text)).disc_id() == disc_id


def test_parsed_values():
    toc = parse_mcdi(wmp(KARLSSON[0]))
    assert toc.first_track == 1 and toc.last_track == 6 and toc.track_count == 6
    assert toc.offsets == (0x96, 0x926A, 0x13B91, 0x1A876, 0x23885, 0x2D8DB)
    assert toc.leadout == 0x34008
    assert round(toc.seconds) == 2838  # 47:18, the sum of the six tracks


def test_toc_string_for_fuzzy_lookups():
    toc = parse_mcdi(wmp("2+96+1DC94+3A640"))
    assert toc.musicbrainz_toc() == "1+2+239168+150+122004"


def test_text_form_is_accepted_with_or_without_terminator_and_in_lower_case():
    assert parse_mcdi("2+96+1dc94+3a640".encode("utf-16-le")).disc_id() == PUMUCKL[1]


def test_track_count_is_hexadecimal():
    offsets = "+".join(f"{150 + i * 1000:X}" for i in range(17))
    toc = parse_mcdi(wmp(f"11+{offsets}+{150 + 17 * 1000:X}"))  # 0x11 = 17 tracks
    assert toc.track_count == 17


def binary_toc(toc: Toc, *, msf: bool) -> bytes:
    """The same table of contents as the ID3 spec's binary dump."""

    def address(frames: int) -> bytes:
        if msf:
            return bytes([0, frames // 75 // 60, frames // 75 % 60, frames % 75])
        return (frames - 150).to_bytes(4, "big")

    rows = [
        bytes([0, 0x14, number, 0]) + address(offset)
        for number, offset in enumerate(toc.offsets, start=toc.first_track)
    ]
    rows.append(bytes([0, 0x14, 0xAA, 0]) + address(toc.leadout))
    length = 2 + 8 * len(rows)
    return length.to_bytes(2, "big") + bytes([toc.first_track, toc.last_track]) + b"".join(rows)


@pytest.mark.parametrize("msf", [True, False])
@pytest.mark.parametrize(("text", "disc_id"), [KARLSSON, PUMUCKL])
def test_binary_form_gives_the_same_disc_id_as_the_text_form(text, disc_id, msf):
    text_toc = parse_mcdi(wmp(text))
    binary = parse_mcdi(binary_toc(text_toc, msf=msf))
    assert binary == text_toc
    assert binary.disc_id() == disc_id


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"garbage",
        wmp("hello"),
        wmp("2+96+1DC94"),  # one number short
        wmp("2+96+1DC94+3A640+5"),  # one too many
        wmp("2+10+1DC94+3A640"),  # first track before the lead-in
        wmp("2+1DC94+96+3A640"),  # not increasing
        wmp("2+96+1DC94+1DC94"),  # lead-out not after the last track
        wmp("0+96"),
        b"\x00" * 20,
    ],
)
def test_invalid_data_is_rejected(data):
    with pytest.raises(InvalidTocError):
        parse_mcdi(data)


def test_binary_with_wrong_row_count_or_missing_lead_out_is_rejected():
    good = binary_toc(parse_mcdi(wmp(PUMUCKL[0])), msf=True)
    with pytest.raises(InvalidTocError):
        parse_mcdi(good[:-8])  # lead-out row cut off
    broken = bytearray(good)
    broken[3] = 5  # claims five tracks
    with pytest.raises(InvalidTocError):
        parse_mcdi(bytes(broken))


def test_a_disc_not_starting_at_track_one_uses_its_track_numbers():
    toc = Toc(3, (150, 5000, 9000), 12000)
    assert (toc.first_track, toc.last_track) == (3, 5)
    assert toc.musicbrainz_toc() == "3+5+12000+150+5000+9000"
    assert toc.disc_id() != Toc(1, (150, 5000, 9000), 12000).disc_id()
