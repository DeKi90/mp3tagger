"""Root-confined filesystem access. All user-supplied paths must go through here."""

from dataclasses import dataclass
from pathlib import Path


class PathOutsideRootsError(ValueError):
    pass


@dataclass(frozen=True)
class Directory:
    path: Path
    parent: Path | None  # None when the parent would be outside the roots
    subdirs: tuple[Path, ...]


class Sandbox:
    def __init__(self, roots: tuple[Path, ...]) -> None:
        self.roots = tuple(r.resolve() for r in roots)

    def resolve(self, path: str | Path) -> Path:
        """Resolve `path` (following symlinks) and ensure it lies within a root."""
        resolved = Path(path).expanduser().resolve()
        if not any(resolved == r or resolved.is_relative_to(r) for r in self.roots):
            raise PathOutsideRootsError(f"{path} is outside the allowed music roots")
        return resolved

    def list_dir(self, path: str | Path) -> Directory:
        folder = self.resolve(path)
        if not folder.is_dir():
            raise NotADirectoryError(str(folder))
        parent = folder.parent if folder not in self.roots else None
        subdirs = []
        for child in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
            if child.name.startswith(".") or not child.is_dir():
                continue
            try:
                subdirs.append(self.resolve(child))  # skips symlinks that leave the roots
            except PathOutsideRootsError:
                continue
        return Directory(path=folder, parent=parent, subdirs=tuple(subdirs))
