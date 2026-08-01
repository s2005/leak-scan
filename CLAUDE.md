# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Scan a git-tracked tree for content that must not be published

**Tech stack:** Python 3.13+, uv, hatchling, pytest, ruff, mypy

## Essential Commands

```bash
uv sync                      # install dependencies
uv run leak-scan --help
uv run pytest                # all tests
uv run pytest -m unit        # unit tests only
uv run pytest --cov          # tests with coverage
uv run ruff check --fix .    # lint and autofix
uv run ruff format .         # format
uv run mypy                  # type check
```

## Architecture

- `src/leak_scan/cli.py` - argparse setup and the `main()` entry point. `main()` returns an exit code
  and never calls `sys.exit()`. `run(args)` holds the actual control flow, kept separate for testing.
- `src/leak_scan/__main__.py` - enables `python -m leak_scan`.
- `src/leak_scan/models.py` - frozen dataclasses for the parsed config and scan results
  (`Rule`, `AllowRules`, `Category`, `ScanConfig`, `Hit`, `ScanResult`). No I/O, no regex compilation.
- `src/leak_scan/config.py` - loads and validates the YAML/JSON configuration file into a `ScanConfig`
  (`find_config`, `load_config`, `parse_config`) and raises `ConfigError` on anything invalid.
- `src/leak_scan/gitrepo.py` - wraps `git ls-files -z` to list tracked files; raises `GitError`.
- `src/leak_scan/scanner.py` - applies the configured rules and allowlists to tracked files
  (`scan_line`, `scan_file`, `scan_repo`).
- `src/leak_scan/report.py` - renders a `ScanResult` as text or JSON (`render_text`, `render_json`).
- `tests/` - pytest suite mirroring the module layout. Fixtures live in `tests/conftest.py`.

## Conventions

- CLI arguments are always named (`--input`), never positional.
- No emoji or non-ASCII characters anywhere in source - they break Windows console encoding.
- Never suppress a linter error inline. Fix it, or change the config in `pyproject.toml` with a stated reason.
- Never modify `.env`. Document new variables in `.env.example`.
- Every new or changed CLI flag must be reflected in the README CLI reference table in the same change.
- Patterns, labels, categories and allowlists are never hardcoded in source - they are always loaded
  from a config file (see `leak-scan.example.yaml`). The real working config lives in an untracked
  `leak-scan.yaml` because it necessarily contains the site-specific literals being hunted for.
- No real personal name, employer, handle, host or path literal may ever enter a tracked file
  (source, tests, docs, or example configs). Use invented placeholders instead.
