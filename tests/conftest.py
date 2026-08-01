"""Shared pytest fixtures for leak-scan.

Every literal used here is invented for the test suite (acme-corp, jdoe,
etc.) - never a real personal, employer, host or path literal. Embedding
real ones in the tests would recreate exactly the self-defeating trap the
tool itself exists to catch.
"""

from __future__ import annotations

import copy
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from leak_scan.config import parse_config
from leak_scan.models import ScanConfig

CONFIG_DATA: dict[str, Any] = {
    "version": 1,
    "path_allow": [],
    "binary_suffixes": [".png", ".bin"],
    "categories": [
        {
            "name": "identity",
            "description": "Invented author identity markers.",
            "rules": [
                {"label": "author handle", "pattern": r"jdoe"},
                {"label": "employer name", "pattern": r"acme-corp"},
            ],
        },
        {
            "name": "machine",
            "description": "Invented machine path markers.",
            "rules": [
                {
                    "label": "unix home directory path",
                    "pattern": r"/home/[A-Za-z0-9_.-]+/",
                },
            ],
            "allow": {
                # A generic home-directory *form* names no real machine and
                # must not be flagged.
                "context": [r"/home/(?:user|youruser|runner|me)/"],
            },
        },
        {
            "name": "credential",
            "description": "Invented credential assignment marker.",
            "rules": [
                {
                    "label": "credential assignment",
                    "pattern": (
                        r"(?:password|token)\s*[:=]\s*"
                        r"(?P<value>[\"'`]?[^\s\"'`,;()]+[\"'`]?)"
                    ),
                },
            ],
            "allow": {
                "values": ["changeme", "placeholder"],
                "value_patterns": [r"^\$\{.*\}$"],
                "min_value_length": 6,
                "require_letter_and_digit": True,
            },
        },
    ],
}


@pytest.fixture
def config_data() -> dict[str, Any]:
    """Return a small valid config dict covering identity/machine/credential shapes."""
    return copy.deepcopy(CONFIG_DATA)


@pytest.fixture
def config_file(tmp_path: Path, config_data: dict[str, Any]) -> Path:
    """Write config_data as a YAML file and return its path."""
    path = tmp_path / "leak-scan.yaml"
    path.write_text(yaml.safe_dump(config_data, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def scan_config(config_data: dict[str, Any]) -> ScanConfig:
    """Return config_data parsed into a ScanConfig."""
    return parse_config(config_data, source="<config_data fixture>")


@dataclass
class GitRepo:
    """A scratch git repository used by scanner and CLI tests."""

    path: Path

    def write(self, relpath: str, content: str) -> Path:
        """Write (or overwrite) a tracked file and re-stage the whole tree."""
        target = self.path / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.path, check=True, capture_output=True)
        return target


@pytest.fixture
def git_repo(tmp_path: Path) -> GitRepo:
    """Create a scratch git repository seeded with a clean file and planted hits."""
    if shutil.which("git") is None:
        pytest.skip("git executable not found")

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_path, check=True, capture_output=True)

    repo = GitRepo(path=repo_path)
    repo.write("clean.txt", "nothing interesting here\n")
    repo.write("leaky.txt", "password: hunter2ok\njdoe was here\n")
    return repo
