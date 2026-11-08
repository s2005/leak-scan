"""Choosing which candidate files a scan covers.

The selection is a pure function of relative paths, so it applies the same way
whether the paths came from ``git ls-files`` or from a directory walk. Stages
run in a fixed order: folders restrict where to look, includes keep what
matches, excludes then remove from that result.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path, PurePosixPath

from leak_scan.models import Selection


class SelectionError(ValueError):
    """Raised when a folder or pattern is invalid, or a selection matches no files."""


def _normalise_folder(repo: Path, folder: str) -> str:
    """Return the ``/``-separated prefix of ``folder`` relative to ``repo``."""
    if not folder:
        raise SelectionError("--folder must not be empty")
    root = repo.resolve()
    target = (root / folder).resolve()
    if not target.is_relative_to(root):
        raise SelectionError(f"--folder {folder!r} is outside the scan root {root}")
    if not target.is_dir():
        raise SelectionError(f"--folder {folder!r} is not a directory under {root}")
    prefix = target.relative_to(root).as_posix()
    return "" if prefix == "." else prefix


def _check_pattern(option: str, pattern: str) -> str:
    """Return ``pattern`` unchanged when it is a usable glob, else raise."""
    if not pattern:
        raise SelectionError(f"{option} pattern must not be empty")
    if "\\" in pattern:
        raise SelectionError(f"{option} pattern {pattern!r} contains a backslash; use '/'")
    if pattern.startswith("/"):
        raise SelectionError(f"{option} pattern {pattern!r} must be relative, not absolute")
    if ".." in pattern.split("/"):
        raise SelectionError(f"{option} pattern {pattern!r} must not contain a '..' segment")
    return pattern


def build_selection(
    repo: Path,
    folders: Sequence[str] = (),
    includes: Sequence[str] = (),
    excludes: Sequence[str] = (),
) -> Selection:
    """Validate the raw option values and return a ``Selection``."""
    return Selection(
        folders=tuple(_normalise_folder(repo, folder) for folder in folders),
        includes=tuple(_check_pattern("--include", pattern) for pattern in includes),
        excludes=tuple(_check_pattern("--exclude", pattern) for pattern in excludes),
    )


def _in_folders(path: str, folders: tuple[str, ...]) -> bool:
    """True when ``path`` lies under at least one folder prefix."""
    return any(not folder or path == folder or path.startswith(folder + "/") for folder in folders)


def _matches(path: str, pattern: str) -> bool:
    """Glob match; a pattern without ``/`` is matched against the file name only."""
    subject = PurePosixPath(path)
    if "/" not in pattern:
        subject = PurePosixPath(subject.name)
    return subject.full_match(pattern, case_sensitive=True)


def apply_selection(paths: Iterable[str], selection: Selection) -> list[str]:
    """Return the paths that survive folders, then includes, then excludes."""
    kept: list[str] = []
    for path in paths:
        if selection.folders and not _in_folders(path, selection.folders):
            continue
        if selection.includes and not any(_matches(path, pat) for pat in selection.includes):
            continue
        if any(_matches(path, pat) for pat in selection.excludes):
            continue
        kept.append(path)
    return kept
