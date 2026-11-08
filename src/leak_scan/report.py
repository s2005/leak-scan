"""Rendering scan results as human-readable text or machine-readable JSON."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from leak_scan.models import ScanConfig, ScanResult

MAX_LINE = 160
REDACTED = "<redacted>"


def _join(values: Sequence[str]) -> str:
    """Comma-join selection values for display; ``-`` when empty, ``.`` for the root."""
    if not values:
        return "-"
    return ", ".join(value or "." for value in values)


def render_text(
    result: ScanResult,
    config: ScanConfig,
    *,
    repo: Path,
    quiet: bool,
    show_matches: bool,
    categories: Sequence[str] | None,
) -> str:
    """Render a scan result as the tool's human-readable report."""
    category_filter = set(categories) if categories else None
    lines: list[str] = []

    if not quiet:
        for hit in result.hits:
            text = hit.line[:MAX_LINE] if show_matches else REDACTED
            lines.append(f"{hit.path}:{hit.lineno}: [{hit.category}] {hit.label}: {text}")

    noun = "tracked files" if result.source == "repo" else "files"
    lines.append("")
    lines.append(
        f"Scanned {result.scanned_files} of {result.tracked_files} {noun} in {repo}; "
        f"skipped {result.skipped_files}"
    )
    if result.selection.active:
        selection = result.selection
        lines.append(
            f"Selection: folders={_join(selection.folders)}; "
            f"include={_join(selection.includes)}; exclude={_join(selection.excludes)}; "
            f"removed {result.removed_files} file(s)"
        )
    lines.append("-" * 60)

    counts = result.counts()
    files_by_category = result.files_by_category()
    for category in config.categories:
        if category_filter is not None and category.name not in category_filter:
            continue
        hits = counts.get(category.name, 0)
        files_hit = len(files_by_category.get(category.name, ()))
        lines.append(f"{category.name:<12} {hits:>5} hit(s) in {files_hit:>4} file(s)")
    lines.append("-" * 60)
    lines.append(f"{'TOTAL':<12} {len(result.hits):>5} hit(s)")

    return "\n".join(lines)


def render_json(result: ScanResult, *, repo: Path, quiet: bool, show_matches: bool) -> str:
    """Render a scan result as a deterministic JSON document."""
    counts = result.counts()
    payload = {
        "repo": str(repo),
        "source": result.source,
        "tracked_files": result.tracked_files,
        "scanned_files": result.scanned_files,
        "skipped_files": result.skipped_files,
        "skips": [
            {"path": skip.path, "reason": skip.reason}
            for skip in sorted(result.skips, key=lambda item: (item.path, item.reason))
        ],
        "selection": {
            "folders": [folder or "." for folder in result.selection.folders],
            "include": list(result.selection.includes),
            "exclude": list(result.selection.excludes),
            "removed_files": result.removed_files,
        },
        "total": len(result.hits),
        "counts": {name: counts[name] for name in sorted(counts)},
        "hits": [
            {
                "path": hit.path,
                "line": hit.lineno,
                "category": hit.category,
                "label": hit.label,
                "text": hit.line if show_matches else REDACTED,
            }
            for hit in (() if quiet else result.hits)
        ],
    }
    return json.dumps(payload, indent=2)
