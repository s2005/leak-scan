"""Rendering scan results as human-readable text or machine-readable JSON."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from leak_scan.models import ScanConfig, ScanResult

MAX_LINE = 160
REDACTED = "<redacted>"


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

    lines.append("")
    lines.append(
        f"Scanned {result.scanned_files} of {result.tracked_files} tracked files in {repo}; "
        f"skipped {result.skipped_files}"
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
        "tracked_files": result.tracked_files,
        "scanned_files": result.scanned_files,
        "skipped_files": result.skipped_files,
        "skips": [
            {"path": skip.path, "reason": skip.reason}
            for skip in sorted(result.skips, key=lambda item: (item.path, item.reason))
        ],
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
