import pytest

from mp3tagger.services.fs import PathOutsideRootsError, Sandbox


@pytest.fixture
def sandbox(tmp_path):
    root = tmp_path / "music"
    (root / "rock").mkdir(parents=True)
    (root / "jazz").mkdir()
    (root / ".trash").mkdir()
    (root / "file.txt").write_text("x")
    (tmp_path / "secret").mkdir()
    return Sandbox((root,))


def test_resolve_inside_root(sandbox):
    root = sandbox.roots[0]
    assert sandbox.resolve(root) == root
    assert sandbox.resolve(root / "rock") == root / "rock"


def test_resolve_rejects_outside_and_traversal(sandbox):
    root = sandbox.roots[0]
    with pytest.raises(PathOutsideRootsError):
        sandbox.resolve(root.parent / "secret")
    with pytest.raises(PathOutsideRootsError):
        sandbox.resolve(root / ".." / "secret")


def test_resolve_rejects_prefix_sibling(sandbox, tmp_path):
    (tmp_path / "music-evil").mkdir()
    with pytest.raises(PathOutsideRootsError):
        sandbox.resolve(tmp_path / "music-evil")


def test_resolve_rejects_symlink_escaping_root(sandbox):
    root = sandbox.roots[0]
    (root / "link").symlink_to(root.parent / "secret")
    with pytest.raises(PathOutsideRootsError):
        sandbox.resolve(root / "link")


def test_list_dir_lists_visible_subdirs_only(sandbox):
    root = sandbox.roots[0]
    listing = sandbox.list_dir(root)
    assert listing.subdirs == (root / "jazz", root / "rock")
    assert listing.parent is None


def test_list_dir_skips_escaping_symlinks_and_has_parent(sandbox):
    root = sandbox.roots[0]
    (root / "link").symlink_to(root.parent / "secret")
    assert root / "link" not in sandbox.list_dir(root).subdirs
    assert sandbox.list_dir(root / "rock").parent == root


def test_list_dir_on_file_raises(sandbox):
    with pytest.raises(NotADirectoryError):
        sandbox.list_dir(sandbox.roots[0] / "file.txt")
