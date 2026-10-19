from imagery import jpeg, png
from mp3tagger.core.folder_cover import find_folder_cover, load_folder_covers
from mp3tagger.core.images import MAX_COVER_BYTES


def test_finds_cover_jpg(tmp_path):
    (tmp_path / "cover.jpg").write_bytes(jpeg(40, 30))
    found = find_folder_cover(tmp_path)
    assert found.name == "cover.jpg"
    assert (found.cover.mime, found.cover.data) == ("image/jpeg", jpeg(40, 30))


def test_empty_folder_and_missing_folder_have_none(tmp_path):
    assert find_folder_cover(tmp_path) is None
    assert find_folder_cover(tmp_path / "missing") is None


def test_name_match_is_case_insensitive_and_keeps_the_disk_name(tmp_path):
    (tmp_path / "Folder.JPG").write_bytes(jpeg())
    assert find_folder_cover(tmp_path).name == "Folder.JPG"


def test_preference_order(tmp_path):
    for name in ("albumart.png", "front.jpg", "folder.png", "cover.png"):
        (tmp_path / name).write_bytes(png())
    names = []
    while (found := find_folder_cover(tmp_path)) is not None:
        names.append(found.name)
        (tmp_path / found.name).unlink()
    assert names == ["cover.png", "folder.png", "front.jpg", "albumart.png"]


def test_jpg_is_preferred_over_png_of_the_same_name(tmp_path):
    (tmp_path / "cover.png").write_bytes(png())
    (tmp_path / "cover.jpg").write_bytes(jpeg())
    assert find_folder_cover(tmp_path).name == "cover.jpg"


def test_invalid_images_are_skipped_in_favour_of_the_next_candidate(tmp_path):
    (tmp_path / "cover.jpg").write_bytes(b"not an image")
    (tmp_path / "folder.png").write_bytes(png())
    assert find_folder_cover(tmp_path).name == "folder.png"


def test_oversized_images_are_skipped(tmp_path):
    (tmp_path / "cover.png").write_bytes(png() + bytes(MAX_COVER_BYTES))
    assert find_folder_cover(tmp_path) is None


def test_other_files_hidden_files_and_folders_do_not_count(tmp_path):
    (tmp_path / "holiday.jpg").write_bytes(jpeg())
    (tmp_path / ".cover.jpg").write_bytes(jpeg())
    (tmp_path / "cover.jpg").mkdir()  # a folder with that name
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "cover.jpg").write_bytes(jpeg())
    assert find_folder_cover(tmp_path) is None


def test_load_folder_covers_maps_each_folder(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "cover.png").write_bytes(png())
    result = load_folder_covers([tmp_path / "a", tmp_path / "b"])
    assert result[tmp_path / "a"].name == "cover.png" and result[tmp_path / "b"] is None
