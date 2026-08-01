"""Tests for the leak-scan command-line interface."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from leak_scan import __version__
from leak_scan.cli import build_parser, main
from leak_scan.report import REDACTED

from .conftest import GitRepo


@pytest.mark.unit
def test_parser_requires_repo() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args([])
    assert exc.value.code == 2


@pytest.mark.unit
def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ == "0.0.1"
    captured = capsys.readouterr()
    assert captured.out == "leak-scan 0.0.1\n"
    assert captured.err == ""


@pytest.mark.unit
def test_help_lists_every_named_option(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    help_text = captured.out
    assert "leak-scan 0.0.1" in help_text
    assert captured.err == ""
    for option in (
        "--repo",
        "--config",
        "--category",
        "--quiet",
        "--show-matches",
        "--format",
        "--log-level",
        "--version",
        "--help",
    ):
        assert option in help_text


@pytest.mark.unit
def test_repo_not_a_directory_exits_2(tmp_path: Path, config_file: Path) -> None:
    missing = tmp_path / "does-not-exist"
    exit_code = main(["--repo", str(missing), "--config", str(config_file)])
    assert exit_code == 2


@pytest.mark.unit
def test_config_path_not_found_exits_2(git_repo: GitRepo, tmp_path: Path) -> None:
    missing_config = tmp_path / "no-such-config.yaml"
    exit_code = main(["--repo", str(git_repo.path), "--config", str(missing_config)])
    assert exit_code == 2


@pytest.mark.unit
def test_missing_config_exits_2(
    git_repo: GitRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty_cwd = tmp_path / "empty-cwd"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)
    exit_code = main(["--repo", str(git_repo.path)])
    assert exit_code == 2


@pytest.mark.unit
def test_unknown_category_exits_2(git_repo: GitRepo, config_file: Path) -> None:
    exit_code = main(
        [
            "--repo",
            str(git_repo.path),
            "--config",
            str(config_file),
            "--category",
            "no-such-category",
        ]
    )
    assert exit_code == 2


@pytest.mark.unit
def test_unknown_category_error_lists_valid_names(
    git_repo: GitRepo, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(
        [
            "--repo",
            str(git_repo.path),
            "--config",
            str(config_file),
            "--category",
            "no-such-category",
        ]
    )
    err = capsys.readouterr().err
    assert "identity" in err
    assert "machine" in err
    assert "credential" in err


@pytest.mark.unit
def test_clean_tree_exits_0(tmp_path: Path, config_file: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git executable not found")

    repo = tmp_path / "clean-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    (repo / "clean.txt").write_text("nothing interesting here\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)

    exit_code = main(["--repo", str(repo), "--config", str(config_file)])
    assert exit_code == 0


@pytest.mark.unit
def test_planted_leak_tree_exits_1(git_repo: GitRepo, config_file: Path) -> None:
    exit_code = main(["--repo", str(git_repo.path), "--config", str(config_file)])
    assert exit_code == 1


@pytest.mark.unit
def test_default_output_redacts_planted_value(
    git_repo: GitRepo, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["--repo", str(git_repo.path), "--config", str(config_file)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert REDACTED in out
    assert "hunter2ok" not in out


@pytest.mark.unit
def test_show_matches_prints_planted_value(
    git_repo: GitRepo, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "--repo",
            str(git_repo.path),
            "--config",
            str(config_file),
            "--show-matches",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "hunter2ok" in out


@pytest.mark.unit
def test_unreadable_tracked_file_exits_2_without_printing_content(
    git_repo: GitRepo,
    config_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    planted_content = "invented content that must stay private"
    missing = git_repo.write("missing.txt", f"{planted_content}\n")
    missing.unlink()

    exit_code = main(["--repo", str(git_repo.path), "--config", str(config_file)])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "missing.txt" in captured.err
    assert planted_content not in captured.out
    assert planted_content not in captured.err


@pytest.mark.unit
def test_quiet_flag_suppresses_hit_lines(
    git_repo: GitRepo, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "--repo",
            str(git_repo.path),
            "--config",
            str(config_file),
            "--quiet",
            "--show-matches",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "jdoe" not in out
    assert "Scanned" in out


@pytest.mark.unit
def test_json_format_output(
    git_repo: GitRepo, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        ["--repo", str(git_repo.path), "--config", str(config_file), "--format", "json"]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    payload = json.loads(out)
    assert payload["total"] >= 1
    assert payload["hits"][0]["text"] == REDACTED


@pytest.mark.unit
def test_json_show_matches_prints_planted_value(
    git_repo: GitRepo, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "--repo",
            str(git_repo.path),
            "--config",
            str(config_file),
            "--format",
            "json",
            "--show-matches",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert any(hit["text"] == "password: hunter2ok" for hit in payload["hits"])


@pytest.mark.unit
def test_json_quiet_omits_hit_rows(
    git_repo: GitRepo, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "--repo",
            str(git_repo.path),
            "--config",
            str(config_file),
            "--format",
            "json",
            "--quiet",
            "--show-matches",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["total"] >= 1
    assert payload["hits"] == []
