"""Tests for leak_scan.report."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from leak_scan.models import (
    AllowRules,
    Category,
    Hit,
    Rule,
    ScanConfig,
    ScanResult,
    SkippedFile,
)
from leak_scan.report import MAX_LINE, REDACTED, render_json, render_text


def _build_config() -> ScanConfig:
    identity = Category(
        name="identity",
        description="",
        rules=(Rule(label="author handle", regex=re.compile("jdoe")),),
        allow=AllowRules(),
    )
    machine = Category(
        name="machine",
        description="",
        rules=(Rule(label="drive-rooted path", regex=re.compile(r"C:\\Users")),),
        allow=AllowRules(),
    )
    return ScanConfig(categories=(identity, machine))


def _build_result() -> ScanResult:
    hits = (
        Hit(
            path="leaky.txt",
            lineno=2,
            category="identity",
            label="author handle",
            line="jdoe was here",
        ),
        Hit(
            path="leaky.txt",
            lineno=5,
            category="machine",
            label="drive-rooted path",
            line=r"C:\Users\jdoe",
        ),
    )
    return ScanResult(
        hits=hits,
        tracked_files=4,
        scanned_files=3,
        skips=(SkippedFile(path="logo.png", reason="binary_suffix"),),
    )


@pytest.mark.unit
def test_render_text_redacts_hit_lines_by_default() -> None:
    config = _build_config()
    result = _build_result()
    text = render_text(
        result,
        config,
        repo=Path("/repo"),
        quiet=False,
        show_matches=False,
        categories=None,
    )
    lines = text.splitlines()
    assert lines[0] == f"leaky.txt:2: [identity] author handle: {REDACTED}"
    assert lines[1] == f"leaky.txt:5: [machine] drive-rooted path: {REDACTED}"
    assert "jdoe" not in text


@pytest.mark.unit
def test_render_text_show_matches_includes_raw_lines() -> None:
    text = render_text(
        _build_result(),
        _build_config(),
        repo=Path("/repo"),
        quiet=False,
        show_matches=True,
        categories=None,
    )
    assert "author handle: jdoe was here" in text
    assert r"drive-rooted path: C:\Users\jdoe" in text


@pytest.mark.unit
def test_render_text_summary_and_totals() -> None:
    config = _build_config()
    result = _build_result()
    text = render_text(
        result,
        config,
        repo=Path("/repo"),
        quiet=False,
        show_matches=False,
        categories=None,
    )
    assert "Scanned 3 of 4 tracked files in" in text
    assert "skipped 1" in text
    assert "identity" in text
    assert "machine" in text
    assert "TOTAL" in text
    assert text.rstrip().endswith("2 hit(s)")


@pytest.mark.unit
def test_render_text_quiet_omits_hit_lines() -> None:
    config = _build_config()
    result = _build_result()
    text = render_text(
        result,
        config,
        repo=Path("/repo"),
        quiet=True,
        show_matches=True,
        categories=None,
    )
    assert "author handle" not in text
    assert "jdoe" not in text
    assert "Scanned 3 of 4 tracked files" in text


@pytest.mark.unit
def test_render_text_category_filter() -> None:
    # render_text's `categories` restricts the per-category summary rows; the
    # per-hit dump lines are expected to already be pre-filtered by the
    # caller (scan_repo applies the same filter to result.hits before this
    # is ever called from the CLI).
    config = _build_config()
    identity_hit = Hit(
        path="leaky.txt",
        lineno=2,
        category="identity",
        label="author handle",
        line="jdoe was here",
    )
    result = ScanResult(hits=(identity_hit,), tracked_files=3, scanned_files=3, skips=())
    text = render_text(
        result,
        config,
        repo=Path("/repo"),
        quiet=False,
        show_matches=False,
        categories=["identity"],
    )
    summary_lines = [line for line in text.splitlines() if line.startswith(("identity", "machine"))]
    assert any(line.startswith("identity") for line in summary_lines)
    assert not any(line.startswith("machine") for line in summary_lines)


@pytest.mark.unit
def test_render_text_truncates_long_lines() -> None:
    long_line = "x" * (MAX_LINE + 50)
    hit = Hit(path="big.txt", lineno=1, category="identity", label="author handle", line=long_line)
    result = ScanResult(hits=(hit,), tracked_files=1, scanned_files=1, skips=())
    config = _build_config()
    text = render_text(
        result,
        config,
        repo=Path("/repo"),
        quiet=False,
        show_matches=True,
        categories=None,
    )
    first_line = text.splitlines()[0]
    printed_text = first_line.split(": ")[-1]
    assert len(printed_text) == MAX_LINE


@pytest.mark.unit
def test_render_json_shape() -> None:
    result = _build_result()
    payload = json.loads(render_json(result, repo=Path("/repo"), quiet=False, show_matches=False))
    assert payload["repo"] == str(Path("/repo"))
    assert payload["tracked_files"] == 4
    assert payload["scanned_files"] == 3
    assert payload["skipped_files"] == 1
    assert payload["skips"] == [{"path": "logo.png", "reason": "binary_suffix"}]
    assert payload["total"] == 2
    assert payload["counts"] == {"identity": 1, "machine": 1}
    assert payload["hits"][0] == {
        "path": "leaky.txt",
        "line": 2,
        "category": "identity",
        "label": "author handle",
        "text": REDACTED,
    }


@pytest.mark.unit
def test_render_json_show_matches_includes_raw_lines() -> None:
    payload = json.loads(
        render_json(_build_result(), repo=Path("/repo"), quiet=False, show_matches=True)
    )
    assert payload["hits"][0]["text"] == "jdoe was here"


@pytest.mark.unit
def test_render_json_quiet_omits_hit_rows_even_when_showing_matches() -> None:
    payload = json.loads(
        render_json(_build_result(), repo=Path("/repo"), quiet=True, show_matches=True)
    )
    assert payload["total"] == 2
    assert payload["hits"] == []


@pytest.mark.unit
def test_render_json_counts_keys_are_sorted() -> None:
    result = _build_result()
    raw = render_json(result, repo=Path("/repo"), quiet=False, show_matches=False)
    # json.dumps with our dict already inserted in sorted order; assert the
    # serialized text reflects alphabetical category ordering.
    identity_pos = raw.index('"identity"')
    machine_pos = raw.index('"machine"')
    assert identity_pos < machine_pos
