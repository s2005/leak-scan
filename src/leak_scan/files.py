"""Directory walk used to enumerate files when the folder is not a git repository."""

from __future__ import annotations

import os
from pathlib import Path

GIT_ENTRY = ".git"


class WalkError(RuntimeError):
    """Raised when a directory cannot be listed during the walk."""


def _is_link(path: str) -> bool:
    """True for a symlink, or on Windows a directory junction."""
    return os.path.islink(path) or os.path.isjunction(path)


def _raise_walk_error(error: OSError) -> None:
    """``os.walk`` error callback: never treat an unreadable directory as empty."""
    raise WalkError(f"cannot list directory {error.filename!r}: {error.strerror}") from error


def walk_files(root: Path) -> tuple[list[str], list[str]]:
    """Return ``(files, links)`` found under ``root``.

    Both lists hold sorted ``/``-separated paths relative to ``root``. ``links``
    holds every symlink or junction, to a file or to a directory; none is
    followed, so nothing outside ``root`` is ever opened. Entries named
    ``.git`` (directory or file) are neither listed nor descended into.
    ``.gitignore`` is not consulted.
    """
    files: list[str] = []
    links: list[str] = []
    for current, dirnames, filenames in os.walk(
        root, topdown=True, onerror=_raise_walk_error, followlinks=False
    ):
        base = Path(current)
        dirnames[:] = [name for name in dirnames if name != GIT_ENTRY]
        kept_dirs: list[str] = []
        for name in dirnames:
            if _is_link(os.path.join(current, name)):
                links.append((base / name).relative_to(root).as_posix())
            else:
                kept_dirs.append(name)
        dirnames[:] = kept_dirs
        for name in filenames:
            if name == GIT_ENTRY:
                continue
            relpath = (base / name).relative_to(root).as_posix()
            if _is_link(os.path.join(current, name)):
                links.append(relpath)
            else:
                files.append(relpath)
    return sorted(files), sorted(links)
