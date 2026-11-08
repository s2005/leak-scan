"""Git plumbing used to enumerate a repository's tracked files."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    """Raised when the git executable cannot be run, or fails."""


class NotAGitRepoError(GitError):
    """Raised when the scan root is not inside a git repository."""


def tracked_files(repo: Path) -> list[str]:
    """Return the repository's tracked paths, relative to its root.

    Only files reported by ``git ls-files`` are ever read by the scanner, so
    ignored and untracked files are never inspected.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=repo,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitError("git executable not found; install git and ensure it is on PATH") from exc

    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace").strip()
        if "not a git repository" in stderr:
            raise NotAGitRepoError(f"git ls-files failed in {repo}: {stderr}")
        raise GitError(f"git ls-files failed in {repo}: {stderr}")

    raw = result.stdout.decode("utf-8", "replace")
    return [entry for entry in raw.split("\0") if entry]
