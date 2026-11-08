"""Tests for leak_scan.selection."""

from __future__ import annotations

from pathlib import Path

import pytest

from leak_scan.models import Selection
from leak_scan.selection import SelectionError, apply_selection, build_selection

PATHS = [
    "README.md",
    "src/a.py",
    "src/pkg/b.py",
    "src/pkg/data.txt",
    "srcx/c.py",
    "tests/test_a.py",
    "docs/guide.md",
]


@pytest.mark.unit
def test_no_options_keeps_everything() -> None:
    assert apply_selection(PATHS, Selection()) == PATHS
    assert Selection().active is False


@pytest.mark.unit
def test_includes_keep_only_matches() -> None:
    selection = Selection(includes=("*.md",))
    assert apply_selection(PATHS, selection) == ["README.md", "docs/guide.md"]


@pytest.mark.unit
def test_excludes_without_includes_remove_matches() -> None:
    selection = Selection(excludes=("tests/**", "*.md"))
    assert apply_selection(PATHS, selection) == [
        "src/a.py",
        "src/pkg/b.py",
        "src/pkg/data.txt",
        "srcx/c.py",
    ]


@pytest.mark.unit
def test_exclude_wins_over_include() -> None:
    selection = Selection(includes=("*.py",), excludes=("tests/**",))
    assert apply_selection(PATHS, selection) == ["src/a.py", "src/pkg/b.py", "srcx/c.py"]


@pytest.mark.unit
def test_file_matching_both_include_and_exclude_is_dropped() -> None:
    selection = Selection(includes=("src/**",), excludes=("*.txt",))
    assert "src/pkg/data.txt" not in apply_selection(PATHS, selection)
    assert "src/a.py" in apply_selection(PATHS, selection)


@pytest.mark.unit
def test_name_only_pattern_matches_at_any_depth() -> None:
    assert apply_selection(["a/b/c.py", "c.py", "c.pyc"], Selection(includes=("*.py",))) == [
        "a/b/c.py",
        "c.py",
    ]


@pytest.mark.unit
def test_pattern_with_slash_matches_whole_path() -> None:
    selection = Selection(includes=("src/*.py",))
    assert apply_selection(PATHS, selection) == ["src/a.py"]
    selection = Selection(includes=("src/**/*.py",))
    assert apply_selection(PATHS, selection) == ["src/a.py", "src/pkg/b.py"]


@pytest.mark.unit
def test_matching_is_case_sensitive() -> None:
    assert apply_selection(["c.py"], Selection(includes=("*.PY",))) == []


@pytest.mark.unit
def test_folder_prefix_respects_directory_boundary() -> None:
    selection = Selection(folders=("src",))
    assert apply_selection(PATHS, selection) == ["src/a.py", "src/pkg/b.py", "src/pkg/data.txt"]


@pytest.mark.unit
def test_several_folders_union_then_includes_and_excludes() -> None:
    selection = Selection(folders=("src", "docs"), includes=("*.py", "*.md"), excludes=("b.py",))
    assert apply_selection(PATHS, selection) == ["src/a.py", "docs/guide.md"]


@pytest.mark.unit
def test_root_folder_means_whole_tree() -> None:
    assert apply_selection(PATHS, Selection(folders=("",))) == PATHS


@pytest.mark.unit
def test_build_selection_normalises_folders(tmp_path: Path) -> None:
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    selection = build_selection(tmp_path, folders=["src/pkg", "./src", "."], includes=["*.py"])
    assert selection.folders == ("src/pkg", "src", "")
    assert selection.includes == ("*.py",)
    assert selection.excludes == ()
    assert selection.active is True


@pytest.mark.unit
def test_build_selection_rejects_missing_folder(tmp_path: Path) -> None:
    with pytest.raises(SelectionError, match="missing"):
        build_selection(tmp_path, folders=["missing"])


@pytest.mark.unit
def test_build_selection_rejects_file_as_folder(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    with pytest.raises(SelectionError, match=r"a\.txt"):
        build_selection(tmp_path, folders=["a.txt"])


@pytest.mark.unit
def test_build_selection_rejects_folder_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(SelectionError, match="outside"):
        build_selection(root, folders=[".."])


@pytest.mark.unit
def test_build_selection_rejects_empty_folder(tmp_path: Path) -> None:
    with pytest.raises(SelectionError, match="empty"):
        build_selection(tmp_path, folders=[""])


@pytest.mark.unit
@pytest.mark.parametrize("pattern", ["", "/abs", "a/../b", "a\\b", "../x"])
@pytest.mark.parametrize("option", ["includes", "excludes"])
def test_build_selection_rejects_bad_patterns(tmp_path: Path, option: str, pattern: str) -> None:
    with pytest.raises(SelectionError):
        build_selection(tmp_path, **{option: [pattern]})


@pytest.mark.unit
def test_bad_pattern_error_names_the_value(tmp_path: Path) -> None:
    with pytest.raises(SelectionError, match=r"a/\.\./b"):
        build_selection(tmp_path, excludes=["a/../b"])
