"""Core scanning logic: reading tracked files and applying configured rules."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from leak_scan.gitrepo import tracked_files
from leak_scan.models import (
    AllowRules,
    Category,
    FileScanResult,
    Hit,
    ScanConfig,
    ScanResult,
    SkippedFile,
)


class ScanError(RuntimeError):
    """Raised when a tracked file cannot be read safely."""

    def __init__(self, relpath: str) -> None:
        super().__init__(f"cannot read tracked file {relpath!r}")
        self.relpath = relpath


def _context_allows(line: str, match: re.Match[str], allow: AllowRules) -> bool:
    """True when the match sits inside one of the category's context allows."""
    for context in allow.context:
        for found in context.finditer(line):
            if found.start() <= match.start() and match.end() <= found.end():
                return True
    return False


def _value_allows(match: re.Match[str], allow: AllowRules) -> bool:
    """True when the rule's named 'value' group is allowlisted.

    Inert for rules whose regex defines no 'value' group.
    """
    groups = match.groupdict()
    if "value" not in groups:
        return False

    stripped = (groups.get("value") or "").strip().strip("\"'`")

    if stripped.lower() in allow.values:
        return True
    for pattern in allow.value_patterns:
        if pattern.match(stripped):
            return True
    if len(stripped) < allow.min_value_length:
        return True
    if allow.require_letter_and_digit:
        has_digit = any(char.isdigit() for char in stripped)
        has_alpha = any(char.isalpha() for char in stripped)
        if not (has_digit and has_alpha):
            return True
    return False


def scan_line(line: str, category: Category) -> list[tuple[str, str]]:
    """Return (label, line) for every hit in a line that survives allowlisting."""
    hits: list[tuple[str, str]] = []
    for rule in category.rules:
        for match in rule.regex.finditer(line):
            if _context_allows(line, match, category.allow):
                continue
            if _value_allows(match, category.allow):
                continue
            hits.append((rule.label, line))
    return hits


def scan_file(repo: Path, relpath: str, config: ScanConfig) -> FileScanResult:
    """Scan a single tracked file for hits.

    Configured binary suffixes and null-byte content produce intentional skip
    results. Read failures raise ``ScanError`` so a tracked file can never be
    silently treated as clean.
    """
    path = repo / relpath
    if path.suffix.lower() in config.binary_suffixes:
        return FileScanResult(skip_reason="binary_suffix")
    try:
        blob = path.read_bytes()
    except OSError as exc:
        raise ScanError(relpath) from exc
    if b"\0" in blob:
        return FileScanResult(skip_reason="null_byte")
    text = blob.decode("utf-8", errors="replace")

    hits: list[Hit] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped_line = line.strip()
        for category in config.categories:
            for label, _ in scan_line(line, category):
                hits.append(
                    Hit(
                        path=relpath,
                        lineno=lineno,
                        category=category.name,
                        label=label,
                        line=stripped_line,
                    )
                )
    return FileScanResult(hits=tuple(hits))


def scan_repo(
    repo: Path, config: ScanConfig, categories: Sequence[str] | None = None
) -> ScanResult:
    """Scan every git-tracked file in ``repo``.

    ``categories``, when given, restricts the returned hits to those category
    names without changing tracked, scanned, or skipped file accounting.
    """
    files = tracked_files(repo)
    category_filter = set(categories) if categories else None

    hits: list[Hit] = []
    skips: list[SkippedFile] = []
    scanned_count = 0
    for relpath in sorted(files):
        if any(allow.search(relpath) for allow in config.path_allow):
            skips.append(SkippedFile(path=relpath, reason="path_allow"))
            continue
        file_result = scan_file(repo, relpath, config)
        if file_result.skip_reason is not None:
            skips.append(SkippedFile(path=relpath, reason=file_result.skip_reason))
            continue
        scanned_count += 1
        for hit in file_result.hits:
            if category_filter is not None and hit.category not in category_filter:
                continue
            hits.append(hit)

    return ScanResult(
        hits=tuple(hits),
        tracked_files=len(files),
        scanned_files=scanned_count,
        skips=tuple(skips),
    )
