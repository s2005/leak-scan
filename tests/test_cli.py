"""Tests for the leak-scan command-line interface."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from leak_scan import __version__
from leak_scan.cli import build_parser, main
from leak_scan.files import WalkError
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
        "--no-git",
        "--folder",
        "--include",
        "--exclude",
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


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    """Run main() and return (exit code, stdout, stderr)."""
    capsys.readouterr()
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.mark.unit
def test_non_git_folder_without_no_git_exits_2_with_hint(
    plain_dir: Path, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, err = _run(capsys, "--repo", str(plain_dir), "--config", str(config_file))
    assert code == 2
    assert "not a git repository" in err
    assert "--no-git" in err


@pytest.mark.unit
def test_no_git_scans_plain_folder_and_exits_1_on_hit(
    plain_dir: Path,
    config_file: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(repo: Path) -> list[str]:
        raise AssertionError("git must not be invoked with --no-git")

    monkeypatch.setattr("leak_scan.scanner.tracked_files", fail_if_called)
    code, out, _ = _run(capsys, "--no-git", "--repo", str(plain_dir), "--config", str(config_file))
    assert code == 1
    assert "leaky.txt:2: [identity]" in out
    assert "Scanned 2 of 2 files in" in out
    assert "Selection:" not in out


@pytest.mark.unit
def test_no_git_clean_plain_folder_exits_0(
    tmp_path: Path, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "clean-folder"
    folder.mkdir()
    (folder / "clean.txt").write_text("nothing interesting here\n", encoding="utf-8")
    code, _, _ = _run(capsys, "--no-git", "--repo", str(folder), "--config", str(config_file))
    assert code == 0


@pytest.mark.unit
def test_no_git_empty_folder_exits_0_with_warning(
    tmp_path: Path, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "empty-folder"
    folder.mkdir()
    code, _, err = _run(capsys, "--no-git", "--repo", str(folder), "--config", str(config_file))
    assert code == 0
    assert "WARNING" in err
    assert "no files found" in err


@pytest.mark.unit
def test_selection_options_narrow_a_plain_folder(
    plain_dir: Path, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (plain_dir / "notes.md").write_text("jdoe\n", encoding="utf-8")
    base = ("--no-git", "--repo", str(plain_dir), "--config", str(config_file))
    code, out, _ = _run(capsys, *base, "--include", "*.md")
    assert code == 1
    assert "notes.md:1:" in out
    assert "leaky.txt:" not in out
    assert "Selection: folders=-; include=*.md; exclude=-; removed 2 file(s)" in out

    code, out, _ = _run(capsys, *base, "--include", "*.txt", "--exclude", "leaky.*")
    assert code == 0
    assert "Scanned 1 of 1 files" in out


@pytest.mark.unit
def test_selection_line_is_kept_under_quiet(
    plain_dir: Path, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = _run(
        capsys,
        "--no-git",
        "--repo",
        str(plain_dir),
        "--config",
        str(config_file),
        "--quiet",
        "--exclude",
        "clean.txt",
    )
    assert code == 1
    assert "Selection: folders=-; include=-; exclude=clean.txt; removed 1 file(s)" in out
    assert "leaky.txt:" not in out


@pytest.mark.unit
def test_folder_option_restricts_to_subtree(
    plain_dir: Path, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (plain_dir / "sub").mkdir()
    (plain_dir / "sub" / "inner.txt").write_text("jdoe\n", encoding="utf-8")
    code, out, _ = _run(
        capsys,
        "--no-git",
        "--repo",
        str(plain_dir),
        "--config",
        str(config_file),
        "--folder",
        "sub",
    )
    assert code == 1
    assert "sub/inner.txt:1:" in out
    assert "leaky.txt:" not in out
    assert "Selection: folders=sub; include=-; exclude=-; removed 2 file(s)" in out


@pytest.mark.unit
def test_selection_works_in_git_mode(
    git_repo: GitRepo, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = _run(
        capsys,
        "--repo",
        str(git_repo.path),
        "--config",
        str(config_file),
        "--exclude",
        "leaky.txt",
    )
    assert code == 0
    assert "Scanned 1 of 1 tracked files" in out
    assert "Selection: folders=-; include=-; exclude=leaky.txt; removed 1 file(s)" in out


@pytest.mark.unit
def test_git_mode_output_without_options_is_unchanged(
    git_repo: GitRepo, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = _run(capsys, "--repo", str(git_repo.path), "--config", str(config_file))
    assert code == 1
    assert "Scanned 2 of 2 tracked files in" in out
    assert "Selection:" not in out


@pytest.mark.unit
def test_json_output_carries_source_and_selection(
    plain_dir: Path, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = _run(
        capsys,
        "--no-git",
        "--repo",
        str(plain_dir),
        "--config",
        str(config_file),
        "--format",
        "json",
        "--include",
        "*.txt",
    )
    assert code == 1
    payload = json.loads(out)
    assert payload["source"] == "files"
    assert payload["selection"]["include"] == ["*.txt"]
    assert payload["selection"]["removed_files"] == 0


@pytest.mark.unit
@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--folder", "missing"),
        ("--folder", "clean.txt"),
        ("--folder", ".."),
        ("--include", ""),
        ("--include", "/abs"),
        ("--include", "a/../b"),
        ("--include", "a\\b"),
        ("--exclude", ""),
        ("--exclude", "/abs"),
        ("--exclude", "a/../b"),
        ("--exclude", "a\\b"),
    ],
)
def test_invalid_selection_value_exits_2_naming_it(
    plain_dir: Path,
    config_file: Path,
    capsys: pytest.CaptureFixture[str],
    flag: str,
    value: str,
) -> None:
    code, out, err = _run(
        capsys, "--no-git", "--repo", str(plain_dir), "--config", str(config_file), flag, value
    )
    assert code == 2
    assert out == ""
    assert flag in err
    if value:
        assert repr(value) in err or value in err


@pytest.mark.unit
@pytest.mark.parametrize("no_git", [False, True])
def test_selection_matching_nothing_exits_2(
    git_repo: GitRepo, config_file: Path, capsys: pytest.CaptureFixture[str], no_git: bool
) -> None:
    argv = ["--repo", str(git_repo.path), "--config", str(config_file), "--include", "*.nomatch"]
    if no_git:
        argv.append("--no-git")
    code, out, err = _run(capsys, *argv)
    assert code == 2
    assert out == ""
    assert "selection matched no files" in err


@pytest.mark.unit
def test_unreadable_directory_during_walk_exits_2(
    plain_dir: Path,
    config_file: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_walk(root: Path) -> tuple[list[str], list[str]]:
        raise WalkError("cannot list directory 'sub'")

    monkeypatch.setattr("leak_scan.scanner.walk_files", broken_walk)
    code, _, err = _run(capsys, "--no-git", "--repo", str(plain_dir), "--config", str(config_file))
    assert code == 2
    assert "cannot list directory" in err
