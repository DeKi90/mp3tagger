from mp3tagger.core.library import scan_folder


def test_scan_non_recursive_ignores_other_files_and_subfolders(make_mp3, tmp_path):
    make_mp3(tmp_path / "b.mp3", title="B")
    make_mp3(tmp_path / "a.MP3", title="A")
    make_mp3(tmp_path / "sub" / "c.mp3", title="C")
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / ".hidden.mp3").write_bytes(b"")
    tracks = scan_folder(tmp_path)
    assert [t.filename for t in tracks] == ["a.MP3", "b.mp3"]


def test_scan_recursive(make_mp3, tmp_path):
    make_mp3(tmp_path / "a.mp3")
    make_mp3(tmp_path / "sub" / "deeper" / "c.mp3")
    tracks = scan_folder(tmp_path, recursive=True)
    assert [t.path.relative_to(tmp_path).as_posix() for t in tracks] == [
        "a.mp3",
        "sub/deeper/c.mp3",
    ]


def test_scan_keeps_broken_files_with_error(make_mp3, tmp_path):
    make_mp3(tmp_path / "ok.mp3", title="Ok")
    (tmp_path / "bad.mp3").write_bytes(b"junk")
    tracks = {t.filename: t for t in scan_folder(tmp_path)}
    assert tracks["ok.mp3"].error is None
    assert tracks["bad.mp3"].error


def test_scan_reports_progress(make_mp3, tmp_path):
    for name in "abc":
        make_mp3(tmp_path / f"{name}.mp3")
    calls = []
    scan_folder(tmp_path, progress=lambda done, total: calls.append((done, total)))
    assert calls == [(1, 3), (2, 3), (3, 3)]
