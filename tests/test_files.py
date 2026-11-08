"""Tests for leak_scan.files."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from leak_scan.files import WalkError, walk_files


def _make_tree(root: Path) -> None:
    (root / "a.txt").write_text("a", encoding="utf-8")
    (root / "sub" / "deep").mkdir(parents=True)
    (root / "sub" / "b.txt").write_text("b", encoding="utf-8")
    (root / "sub" / "deep" / "c.txt").write_text("c", encoding="utf-8")


@pytest.mark.unit
def test_walk_lists_files_sorted_with_posix_separators(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    files, links = walk_files(tmp_path)
    assert files == ["a.txt", "sub/b.txt", "sub/deep/c.txt"]
    assert links == []


@pytest.mark.unit
def test_walk_empty_directory(tmp_path: Path) -> None:
    assert walk_files(tmp_path) == ([], [])


@pytest.mark.unit
def test_walk_skips_git_directory_at_any_depth(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x", encoding="utf-8")
    (tmp_path / "sub" / ".git").mkdir()
    (tmp_path / "sub" / ".git" / "HEAD").write_text("x", encoding="utf-8")
    files, _ = walk_files(tmp_path)
    assert files == ["a.txt", "sub/b.txt", "sub/deep/c.txt"]


@pytest.mark.unit
def test_walk_skips_git_file(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    (tmp_path / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    files, _ = walk_files(tmp_path)
    assert ".git" not in files


@pytest.mark.unit
def test_walk_does_not_ignore_gitignored_files(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("x", encoding="utf-8")
    files, _ = walk_files(tmp_path)
    assert files == [".gitignore", "ignored.txt"]


@pytest.mark.unit
def test_walk_lists_symlinks_without_following(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("s", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    (root / "real.txt").write_text("r", encoding="utf-8")
    try:
        (root / "link.txt").symlink_to(outside / "secret.txt")
        (root / "linkdir").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks cannot be created on this platform")
    files, links = walk_files(root)
    assert files == ["real.txt"]
    assert links == ["link.txt", "linkdir"]


@pytest.mark.unit
@pytest.mark.skipif(sys.platform != "win32", reason="directory junctions exist only on Windows")
def test_walk_lists_junction_without_following(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "x.txt").write_text("x", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(root / "junc"), str(target)],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("cannot create a junction here")
    files, links = walk_files(root)
    assert files == []
    assert links == ["junc"]


@pytest.mark.unit
def test_walk_treats_islink_entries_as_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_tree(tmp_path)
    real_islink = os.path.islink

    def fake_islink(path: str | os.PathLike[str]) -> bool:
        return Path(path).name in {"b.txt", "deep"} or real_islink(path)

    monkeypatch.setattr("leak_scan.files.os.path.islink", fake_islink)
    files, links = walk_files(tmp_path)
    assert files == ["a.txt"]
    assert links == ["sub/b.txt", "sub/deep"]


@pytest.mark.unit
def test_walk_raises_on_unreadable_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_tree(tmp_path)

    def failing_walk(top: Path, **kwargs: object) -> Iterator[tuple[str, list[str], list[str]]]:
        onerror = kwargs["onerror"]
        assert callable(onerror)
        onerror(PermissionError(13, "Permission denied", str(top / "sub")))
        return iter(())

    monkeypatch.setattr("leak_scan.files.os.walk", failing_walk)
    with pytest.raises(WalkError, match="sub"):
        walk_files(tmp_path)
