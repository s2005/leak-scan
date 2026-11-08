"""Data model for scan configuration and results.

Deliberately free of I/O and regex-compilation logic: this module only
describes the shapes produced by ``leak_scan.config`` and consumed by
``leak_scan.scanner`` and ``leak_scan.report``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

type SkipReason = Literal["path_allow", "binary_suffix", "null_byte", "symlink"]


@dataclass(frozen=True)
class Rule:
    """A single compiled pattern within a category."""

    label: str
    regex: re.Pattern[str]


@dataclass(frozen=True)
class AllowRules:
    """Suppression rules applied to the hits of one category."""

    context: tuple[re.Pattern[str], ...] = ()
    values: frozenset[str] = frozenset()
    value_patterns: tuple[re.Pattern[str], ...] = ()
    min_value_length: int = 0
    require_letter_and_digit: bool = False


@dataclass(frozen=True)
class Category:
    """A named group of rules that shares one allowlist."""

    name: str
    description: str
    rules: tuple[Rule, ...]
    allow: AllowRules


@dataclass(frozen=True)
class ScanConfig:
    """A fully parsed and compiled scanner configuration."""

    categories: tuple[Category, ...]
    path_allow: tuple[re.Pattern[str], ...] = ()
    binary_suffixes: frozenset[str] = frozenset()

    @property
    def category_names(self) -> tuple[str, ...]:
        """Return the configured category names, in config order."""
        return tuple(category.name for category in self.categories)


@dataclass(frozen=True)
class Selection:
    """Which candidate files a scan is restricted to.

    ``folders`` holds normalised ``/``-separated prefixes relative to the scan
    root (the empty string means the whole root). ``includes`` and ``excludes``
    hold glob patterns. The stages apply in that order: folders, includes,
    then excludes.
    """

    folders: tuple[str, ...] = ()
    includes: tuple[str, ...] = ()
    excludes: tuple[str, ...] = ()

    @property
    def active(self) -> bool:
        """Return True when any folder, include or exclude was given."""
        return bool(self.folders or self.includes or self.excludes)


@dataclass(frozen=True)
class Hit:
    """A single surviving pattern match."""

    path: str
    lineno: int
    category: str
    label: str
    line: str


@dataclass(frozen=True)
class FileScanResult:
    """Hits or an intentional skip produced while processing one tracked file."""

    hits: tuple[Hit, ...] = ()
    skip_reason: SkipReason | None = None


@dataclass(frozen=True)
class SkippedFile:
    """A tracked file intentionally excluded from text scanning."""

    path: str
    reason: SkipReason


@dataclass(frozen=True)
class ScanResult:
    """The outcome of scanning a repository."""

    hits: tuple[Hit, ...]
    tracked_files: int
    scanned_files: int
    skips: tuple[SkippedFile, ...]

    def __post_init__(self) -> None:
        """Reject ambiguous accounting in manually constructed results."""
        if self.tracked_files != self.scanned_files + len(self.skips):
            raise ValueError("tracked files must equal scanned files plus skipped files")

    @property
    def skipped_files(self) -> int:
        """Return the number of intentionally skipped tracked files."""
        return len(self.skips)

    def counts(self) -> dict[str, int]:
        """Return the number of hits per category."""
        counts: dict[str, int] = {}
        for hit in self.hits:
            counts[hit.category] = counts.get(hit.category, 0) + 1
        return counts

    def files_by_category(self) -> dict[str, set[str]]:
        """Return the set of distinct hit paths per category."""
        files: dict[str, set[str]] = {}
        for hit in self.hits:
            files.setdefault(hit.category, set()).add(hit.path)
        return files
