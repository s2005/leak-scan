---
name: leak-scan
description: Scan a git-tracked tree for content that must not be published - author identity, employer affiliation, machine-specific paths, dangling task-tree pointers and credentials. Use before publishing or open-sourcing a repository, when preparing a history-free export, when asked to check a repo for leaks or personal data, or when running the publication gate on an exported tree.
---

# leak-scan

Run the `leak-scan` scanner over a repository or an exported publication tree
and act on the result.

The scanner reads only what `git ls-files` reports, so ignored and untracked
files are never scanned. Every pattern comes from a config file - nothing is
hardcoded in the tool.

It scans current working-tree bytes only. It does not inspect Git history,
reflogs, unreachable objects, external Git LFS payloads, or content inside
archives, documents, images, and other binary containers. Configured binary
suffixes and null-byte files are intentionally skipped and reported.

## Prerequisites

The tool lives in the `leak_scan` project. Either install it once:

```bash
uv tool install --from <path-to>/leak_scan leak-scan
```

or run it from a checkout with `uv run leak-scan ...`.

Confirm the installed tool and discover its named options without providing
any scan inputs:

```bash
leak-scan --version
leak-scan --help
```

`--version` prints exactly `leak-scan 0.0.1`. The help output includes the
same `leak-scan 0.0.1` banner. Both commands exit without requiring `--repo`
or a config file.

It needs a config file. The committed `leak-scan.example.yaml` is sanitised and
matches nothing useful on its own - the working config is an untracked
`leak-scan.yaml` holding the real literals. If the operator has no working
config yet, copy the example and fill in the identity and employer categories
before the first run.

## Scanning a working repository

```bash
leak-scan --repo <path-to-repo> --config <path-to>/leak-scan.yaml
```

Exit codes: `0` clean, `1` at least one hit, `2` usage or environment error.
Exit `1` is the normal "found something" signal, not a crash - read the output.

Useful narrowing while working through an inventory:

```bash
leak-scan --repo . --config <cfg> --quiet                 # summary only
leak-scan --repo . --config <cfg> --category identity     # one category
leak-scan --repo . --config <cfg> --format json           # machine-readable
leak-scan --repo . --config <cfg> --show-matches          # intentional local raw view
```

## The publication gate

Run the scan against the **exported** tree, not the working repository - the
export is the artifact that actually gets published.

```bash
mkdir -p <fresh-dir>
git archive HEAD | tar -x -C <fresh-dir>

cd <fresh-dir>
git init -b main
git add .

leak-scan --repo . --config <path-to>/leak-scan.yaml
```

`git archive` serializes exactly the tracked set, so private local files cannot
ride along even by accident. This is history-free only when the export is
committed to a new repository and that new repository is published.

Two caveats that produce misleading results if skipped:

1. The scan reads what `git ls-files` reports. In a fresh directory it must run
   **after** `git init` and `git add .`, or it finds no files and reports a
   clean tree.
2. Every surviving hit blocks publication. Fix unnecessary public text, or use
   only a narrow reviewed context or value allow rule for an intentional
   fixture. Never treat a whole-file or whole-path exemption as clean.

## Existing repository history

Pushing an existing repository publishes the reachable history of the refs
being pushed. Before that publication, run an independent history scanner over
every reachable ref with full redaction. For example, with Gitleaks installed:

```bash
gitleaks git --redact=100 --log-opts=--all .
```

The current-tree gate and history scan cover different surfaces. Neither
checks unreachable local objects or external Git LFS storage. If a working
tree contains only a Git LFS pointer, `leak-scan` scans only that pointer and
does not fetch the payload.

## Reading the output

One redacted line per hit by default:

```text
path/to/file.py:42: [identity] author handle: <redacted>
```

The summary distinguishes tracked files, text files actually scanned, and
intentional skips. JSON also includes every skipped path with a stable
`path_allow`, `binary_suffix`, or `null_byte` reason.

Use `--show-matches` only for an intentional local investigation. It restores
raw matching source lines in text and JSON, which can copy detected values
into terminal logs or saved reports. `--quiet` always omits per-hit rows,
including when `--show-matches` is also supplied.

Work category by category rather than file by file - hits of one category
usually share one root cause and one fix.

## Fixing hits, not exempting them

**Fix the hit at the source. Do not add a path exemption.** `path_allow` is
empty by design; every entry in it is a hole that silently persists.

When something genuinely must stay, the fix is a targeted `allow` rule inside
the relevant category - a `context` regex for a generic path form, or a
`values` / `value_patterns` entry for a placeholder credential - never a whole
file waved through.

## Never commit the working config

The working `leak-scan.yaml` contains the very literals it searches for.
Committing it republishes exactly what the scrub removed, and the scanner would
flag its own config on the next run. The same applies to any test or fixture
that embeds a real literal to assert the scanner catches it - use invented
values (`acme-corp`, `jdoe`) instead.

Verify before committing anywhere:

```bash
git check-ignore -v leak-scan.yaml
git status --porcelain          # must not list it
```

## Extending the pattern set

Add a rule to the appropriate category in the working config when a new class
of leak appears. After any edit, re-run against a known-dirty tree and confirm
the expected inventory still appears. A scanner that reports nothing has two
possible causes - a clean tree, or a broken pattern - and they are
indistinguishable from the output alone.
