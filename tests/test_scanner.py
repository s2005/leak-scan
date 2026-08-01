"""Tests for leak_scan.scanner."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from leak_scan.models import AllowRules, Category, Rule, ScanConfig, ScanResult, SkippedFile
from leak_scan.scanner import ScanError, scan_file, scan_line, scan_repo

from .conftest import GitRepo


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
