"""Tests for leak_scan.scanner."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from leak_scan.models import (
    AllowRules,
    Category,
    Rule,
    ScanConfig,
    ScanResult,
    Selection,
    SkippedFile,
    Source,
)
from leak_scan.scanner import ScanError, scan_file, scan_line, scan_repo
from leak_scan.selection import SelectionError

from .conftest import GitRepo

_BASE_FILES = {
    "clean.txt": "nothing interesting here\n",
    "leaky.txt": "password: hunter2ok\njdoe was here\n",
}


@pytest.mark.unit
def test_scan_result_rejects_ambiguous_file_accounting() -> None:
    with pytest.raises(ValueError, match="tracked files must equal scanned files plus skipped"):
        ScanResult(
            hits=(),
            tracked_files=2,
            scanned_files=2,
            skips=(SkippedFile(path="logo.png", reason="binary_suffix"),),
        )


@pytest.mark.unit
def test_scan_line_matches_rule(scan_config: ScanConfig) -> None:
    identity = scan_config.categories[0]
    hits = scan_line("contact jdoe for details", identity)
    assert hits == [("author handle", "contact jdoe for details")]


@pytest.mark.unit
def test_scan_line_context_suppression(scan_config: ScanConfig) -> None:
    machine = scan_config.categories[1]
    # /home/user/ is a generic placeholder home directory that names no real
    # machine, so it sits inside the allowlisted context and is suppressed.
    hits = scan_line("backup lives at /home/user/data", machine)
    assert hits == []


@pytest.mark.unit
def test_scan_line_context_partial_overlap_does_not_suppress() -> None:
    category = Category(
        name="credential",
        description="Invented test category.",
        rules=(Rule(label="test value", regex=re.compile(r"sample-[A-Z]+")),),
        allow=AllowRules(context=(re.compile(r"sample-"),)),
    )
    line = "value: sample-ABC"
    assert scan_line(line, category) == [("test value", line)]


@pytest.mark.unit
def test_scan_line_context_full_containment_suppresses() -> None:
    category = Category(
        name="credential",
        description="Invented test category.",
        rules=(Rule(label="test value", regex=re.compile(r"sample-[A-Z]+")),),
        allow=AllowRules(context=(re.compile(r"value: sample-[A-Z]+"),)),
    )
    assert scan_line("value: sample-ABC", category) == []


@pytest.mark.unit
def test_scan_line_machine_hit_survives_outside_context(scan_config: ScanConfig) -> None:
    machine = scan_config.categories[1]
    line = "backup lives at /home/produser/data"
    hits = scan_line(line, machine)
    assert hits == [("unix home directory path", line)]


@pytest.mark.unit
def test_scan_line_value_suppressed_by_literal(scan_config: ScanConfig) -> None:
    credential = scan_config.categories[2]
    hits = scan_line("token: changeme", credential)
    assert hits == []


@pytest.mark.unit
def test_scan_line_value_suppressed_by_pattern(scan_config: ScanConfig) -> None:
    credential = scan_config.categories[2]
    hits = scan_line("token: ${SECRET_TOKEN}", credential)
    assert hits == []


@pytest.mark.unit
def test_scan_line_value_suppressed_by_min_length(scan_config: ScanConfig) -> None:
    credential = scan_config.categories[2]
    hits = scan_line("token: a1", credential)
    assert hits == []


@pytest.mark.unit
def test_scan_line_value_suppressed_by_letter_and_digit_rule(scan_config: ScanConfig) -> None:
    credential = scan_config.categories[2]
    # long enough, but has no digit at all.
    hits = scan_line("token: onlyletters", credential)
    assert hits == []


@pytest.mark.unit
def test_scan_line_value_survives_when_real_looking(scan_config: ScanConfig) -> None:
    credential = scan_config.categories[2]
    hits = scan_line("token: hunter2ok", credential)
    assert hits == [("credential assignment", "token: hunter2ok")]


@pytest.mark.unit
def test_scan_file_skips_binary_suffix(tmp_path: Path, scan_config: ScanConfig) -> None:
    (tmp_path / "logo.png").write_text("jdoe\n", encoding="utf-8")
    result = scan_file(tmp_path, "logo.png", scan_config)
    assert result.hits == ()
    assert result.skip_reason == "binary_suffix"


@pytest.mark.unit
def test_scan_file_skips_null_byte_content(tmp_path: Path, scan_config: ScanConfig) -> None:
    (tmp_path / "binary.dat").write_bytes(b"jdoe\x00binary")
    result = scan_file(tmp_path, "binary.dat", scan_config)
    assert result.hits == ()
    assert result.skip_reason == "null_byte"


@pytest.mark.unit
def test_scan_file_raises_safe_error_on_oserror(
    tmp_path: Path, scan_config: ScanConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_oserror(_path: Path) -> bytes:
        raise OSError("unsafe system detail")

    monkeypatch.setattr(Path, "read_bytes", raise_oserror)
    with pytest.raises(ScanError) as exc_info:
        scan_file(tmp_path, "does-not-exist.txt", scan_config)

    message = str(exc_info.value)
    assert "does-not-exist.txt" in message
    assert "unsafe system detail" not in message


@pytest.mark.unit
def test_scan_file_reports_hits_with_lineno(tmp_path: Path, scan_config: ScanConfig) -> None:
    (tmp_path / "notes.txt").write_text("clean line\njdoe was here\n", encoding="utf-8")
    result = scan_file(tmp_path, "notes.txt", scan_config)
    assert result.skip_reason is None
    assert len(result.hits) == 1
    hit = result.hits[0]
    assert hit.lineno == 2
    assert hit.category == "identity"
    assert hit.label == "author handle"
    assert hit.line == "jdoe was here"


@pytest.mark.unit
def test_scan_repo_respects_path_allow(scan_config: ScanConfig, git_repo: GitRepo) -> None:
    git_repo.write("vendor/jdoe.txt", "jdoe\n")
    config = ScanConfig(
        categories=scan_config.categories,
        path_allow=(re.compile(r"^vendor/"),),
        binary_suffixes=scan_config.binary_suffixes,
    )
    result = scan_repo(git_repo.path, config)
    assert all(hit.path != "vendor/jdoe.txt" for hit in result.hits)
    assert result.tracked_files == 3
    assert result.scanned_files == 2
    assert result.skipped_files == 1
    assert result.skips[0].path == "vendor/jdoe.txt"
    assert result.skips[0].reason == "path_allow"


@pytest.mark.unit
def test_scan_repo_finds_planted_hits(scan_config: ScanConfig, git_repo: GitRepo) -> None:
    result = scan_repo(git_repo.path, scan_config)
    assert result.source == "repo"
    assert result.tracked_files == 2
    assert result.scanned_files == 2
    assert result.skipped_files == 0
    assert any(hit.path == "leaky.txt" for hit in result.hits)
    assert not any(hit.path == "clean.txt" for hit in result.hits)


@pytest.mark.unit
def test_scan_repo_category_filter(scan_config: ScanConfig, git_repo: GitRepo) -> None:
    unfiltered = scan_repo(git_repo.path, scan_config)
    filtered = scan_repo(git_repo.path, scan_config, categories=["credential"])
    assert all(hit.category == "credential" for hit in filtered.hits)
    assert any(hit.category == "credential" for hit in filtered.hits)
    assert filtered.tracked_files == unfiltered.tracked_files
    assert filtered.scanned_files == unfiltered.scanned_files
    assert filtered.skips == unfiltered.skips


@pytest.mark.unit
def test_scan_repo_records_all_intentional_skip_reasons(
    scan_config: ScanConfig, git_repo: GitRepo
) -> None:
    git_repo.write("vendor/ignored.txt", "jdoe\n")
    git_repo.write("logo.png", "jdoe\n")
    git_repo.write("binary.dat", "jdoe\x00binary")
    config = ScanConfig(
        categories=scan_config.categories,
        path_allow=(re.compile(r"^vendor/"),),
        binary_suffixes=scan_config.binary_suffixes,
    )

    result = scan_repo(git_repo.path, config)

    assert result.tracked_files == 5
    assert result.scanned_files == 2
    assert result.skipped_files == 3
    assert [(skip.path, skip.reason) for skip in result.skips] == [
        ("binary.dat", "null_byte"),
        ("logo.png", "binary_suffix"),
        ("vendor/ignored.txt", "path_allow"),
    ]


@pytest.mark.unit
def test_scan_repo_raises_when_tracked_working_tree_path_is_missing(
    scan_config: ScanConfig, git_repo: GitRepo
) -> None:
    missing = git_repo.write("missing.txt", "invented file content\n")
    missing.unlink()

    with pytest.raises(ScanError, match=r"missing\.txt"):
        scan_repo(git_repo.path, scan_config)


@pytest.mark.unit
def test_scan_repo_files_mode_scans_a_non_git_folder(
    scan_config: ScanConfig, plain_dir: Path
) -> None:
    result = scan_repo(plain_dir, scan_config, source="dir")
    assert result.source == "dir"
    assert result.tracked_files == 2
    assert result.scanned_files == 2
    assert {hit.path for hit in result.hits} == {"leaky.txt"}
    assert result.selection == Selection()
    assert result.removed_files == 0


@pytest.mark.unit
def test_scan_repo_files_mode_scans_gitignored_files(
    scan_config: ScanConfig, plain_dir: Path
) -> None:
    (plain_dir / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (plain_dir / "ignored.txt").write_text("jdoe\n", encoding="utf-8")
    result = scan_repo(plain_dir, scan_config, source="dir")
    assert "ignored.txt" in {hit.path for hit in result.hits}


@pytest.mark.unit
def test_scan_repo_files_mode_never_reads_dot_git(scan_config: ScanConfig, plain_dir: Path) -> None:
    (plain_dir / ".git").mkdir()
    (plain_dir / ".git" / "config").write_text("jdoe\n", encoding="utf-8")
    result = scan_repo(plain_dir, scan_config, source="dir")
    assert all(not hit.path.startswith(".git") for hit in result.hits)
    assert result.tracked_files == 2


@pytest.mark.unit
def test_scan_repo_selection_filters_before_accounting(
    scan_config: ScanConfig, plain_dir: Path
) -> None:
    (plain_dir / "notes.md").write_text("jdoe\n", encoding="utf-8")
    selection = Selection(includes=("*.txt", "*.md"), excludes=("leaky.txt",))
    result = scan_repo(plain_dir, scan_config, source="dir", selection=selection)
    assert result.tracked_files == 2
    assert result.tracked_files == result.scanned_files + result.skipped_files
    assert result.removed_files == 1
    assert result.skips == ()
    assert {hit.path for hit in result.hits} == {"notes.md"}
    assert result.selection == selection


@pytest.mark.unit
def test_scan_repo_git_and_files_modes_select_the_same_paths(
    scan_config: ScanConfig, git_repo: GitRepo, tmp_path: Path
) -> None:
    contents = {
        "src/a.py": "jdoe\n",
        "src/deep/b.py": "jdoe\n",
        "srcx/c.py": "jdoe\n",
        "docs/guide.md": "jdoe\n",
    }
    plain = tmp_path / "copy"
    plain.mkdir()
    for relpath, text in [*contents.items(), *_BASE_FILES.items()]:
        target = plain / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    for relpath, text in contents.items():
        git_repo.write(relpath, text)

    selection = Selection(folders=("src", "docs"), includes=("*.py", "*.md"), excludes=("b.py",))
    from_git = scan_repo(git_repo.path, scan_config, selection=selection)
    from_files = scan_repo(plain, scan_config, source="dir", selection=selection)

    assert {hit.path for hit in from_git.hits} == {"src/a.py", "docs/guide.md"}
    assert {hit.path for hit in from_files.hits} == {hit.path for hit in from_git.hits}
    assert from_files.tracked_files == from_git.tracked_files == 2
    assert from_files.removed_files == from_git.removed_files


@pytest.mark.unit
def test_scan_repo_records_symlinks_as_skips_without_reading(
    scan_config: ScanConfig, plain_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "leak_scan.scanner.walk_files",
        lambda root: (["clean.txt"], ["link.txt", "linkdir"], []),
    )
    result = scan_repo(plain_dir, scan_config, source="dir")
    assert result.tracked_files == 3
    assert result.scanned_files == 1
    assert [(skip.path, skip.reason) for skip in result.skips] == [
        ("link.txt", "symlink"),
        ("linkdir", "symlink"),
    ]


@pytest.mark.unit
def test_scan_repo_symlinks_go_through_the_selection(
    scan_config: ScanConfig, plain_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "leak_scan.scanner.walk_files",
        lambda root: (["clean.txt"], ["link.txt", "linkdir"], []),
    )
    result = scan_repo(
        plain_dir, scan_config, source="dir", selection=Selection(excludes=("link*",))
    )
    assert result.skips == ()
    assert result.removed_files == 2


@pytest.mark.unit
@pytest.mark.parametrize("source", ["repo", "dir"])
def test_scan_repo_empty_active_selection_raises(
    scan_config: ScanConfig, git_repo: GitRepo, source: Source
) -> None:
    selection = Selection(includes=("*.nomatch",))
    with pytest.raises(SelectionError, match="no files"):
        scan_repo(git_repo.path, scan_config, source=source, selection=selection)


@pytest.mark.unit
def test_scan_repo_files_mode_without_selection_allows_empty_folder(
    scan_config: ScanConfig, tmp_path: Path
) -> None:
    result = scan_repo(tmp_path, scan_config, source="dir")
    assert result.tracked_files == 0
    assert result.hits == ()


@pytest.mark.unit
def test_scan_repo_records_special_files_as_skips_without_opening(
    scan_config: ScanConfig, plain_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "leak_scan.scanner.walk_files",
        lambda root: (["clean.txt"], ["link.txt"], ["pipe", "sock"]),
    )
    result = scan_repo(plain_dir, scan_config, source="dir")
    assert result.tracked_files == 4
    assert result.scanned_files == 1
    assert result.tracked_files == result.scanned_files + result.skipped_files
    assert [(skip.path, skip.reason) for skip in result.skips] == [
        ("link.txt", "symlink"),
        ("pipe", "special_file"),
        ("sock", "special_file"),
    ]


@pytest.mark.unit
def test_scan_repo_special_files_go_through_the_selection(
    scan_config: ScanConfig, plain_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "leak_scan.scanner.walk_files",
        lambda root: (["clean.txt"], [], ["pipe", "sock"]),
    )
    result = scan_repo(
        plain_dir, scan_config, source="dir", selection=Selection(excludes=("pipe",))
    )
    assert [skip.path for skip in result.skips] == ["sock"]
    assert result.removed_files == 1
    assert result.tracked_files == 2


@pytest.mark.unit
@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs need a POSIX platform")
def test_scan_repo_dir_mode_completes_with_a_real_fifo(
    scan_config: ScanConfig, plain_dir: Path
) -> None:
    os.mkfifo(plain_dir / "pipe")
    result = scan_repo(plain_dir, scan_config, source="dir")
    assert [(skip.path, skip.reason) for skip in result.skips] == [("pipe", "special_file")]
    assert result.scanned_files == 2
