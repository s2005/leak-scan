"""Command-line interface for leak-scan."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from leak_scan import __version__
from leak_scan.config import DEFAULT_CONFIG_NAMES, ConfigError, find_config, load_config
from leak_scan.files import WalkError
from leak_scan.gitrepo import GitError, NotAGitRepoError
from leak_scan.models import Source
from leak_scan.report import render_json, render_text
from leak_scan.scanner import ScanError, scan_repo
from leak_scan.selection import SelectionError, build_selection

logger = logging.getLogger(__name__)

LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]
FORMATS = ["text", "json"]
MODES = ["repo", "dir"]


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser. Kept separate so tests can inspect it."""
    parser = argparse.ArgumentParser(
        prog="leak-scan",
        description=(
            f"leak-scan {__version__} - "
            "Scan a git-tracked tree for content that must not be published."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--root",
        "--repo",
        dest="repo",
        metavar="PATH",
        required=True,
        help="Path to scan: the git repository in --mode repo, a plain folder in "
        "--mode dir. --repo is an alias. Required.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to the scanner configuration file. Default: search the current "
        "working directory then --root for one of "
        f"{', '.join(DEFAULT_CONFIG_NAMES)}.",
    )
    parser.add_argument(
        "--mode",
        choices=MODES,
        default="repo",
        help="Where the file list comes from. repo: the files git tracks "
        "(git ls-files). dir: every file found by walking --root, so a folder that "
        "is not a git repository can be scanned; never reads .git entries, follows "
        "symlinks or consults .gitignore. Default: repo.",
    )
    parser.add_argument(
        "--folder",
        action="append",
        default=None,
        metavar="DIR",
        help="Scan only this directory, relative to --root. Repeatable. "
        "Default: the whole of --root.",
    )
    parser.add_argument(
        "--include",
        action="append",
        default=None,
        metavar="GLOB",
        help="Keep only files whose path relative to --root matches this glob; a "
        "pattern without '/' matches the file name at any depth, '**' spans "
        "directories, matching is case-sensitive. Repeatable. Applied after --folder "
        "and before --exclude. Default: keep every file.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=None,
        metavar="GLOB",
        help="Remove files matching this glob (same syntax as --include) from the "
        "result of --folder and --include. Repeatable. Default: remove nothing.",
    )
    parser.add_argument(
        "--category",
        default=None,
        help="Limit output to a single configured category. Default: all categories.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Print only the per-category summary, not each hit. Default: False.",
    )
    parser.add_argument(
        "--show-matches",
        action="store_true",
        help="Print raw matching source lines. Default: redact matching text.",
    )
    parser.add_argument(
        "--format",
        choices=FORMATS,
        default="text",
        help="Output format. Default: text.",
    )
    parser.add_argument(
        "--log-level",
        choices=LOG_LEVELS,
        default="INFO",
        help="Application log level. Default: INFO.",
    )
    return parser


def setup_logging(level: str) -> None:
    """Configure root logging for the run.

    Uses force=True so each call replaces any handler installed by a
    previous run in the same process (relevant for the test suite, where
    main() is invoked many times; a real CLI invocation only calls this
    once).
    """
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        force=True,
    )


def run(args: argparse.Namespace) -> int:
    """Execute a scan according to the parsed arguments.

    Returns the process exit code: 0 when no hits were found, 1 when at
    least one hit survived, 2 on a usage or environment error.
    """
    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        logger.error("scan root is not a directory: %s", repo)
        return 2

    config_path: Path | None
    if args.config:
        config_path = Path(args.config).resolve()
        if not config_path.is_file():
            logger.error("config file not found: %s", config_path)
            return 2
    else:
        config_path = find_config(Path.cwd(), repo)
        if config_path is None:
            logger.error(
                "no config file found; looked for %s in %s and %s",
                ", ".join(DEFAULT_CONFIG_NAMES),
                Path.cwd(),
                repo,
            )
            return 2

    try:
        config = load_config(config_path)
    except ConfigError as exc:
        logger.error("%s", exc)
        return 2

    categories: list[str] | None = None
    if args.category:
        if args.category not in config.category_names:
            valid = ", ".join(config.category_names)
            logger.error("unknown category %r; valid categories: %s", args.category, valid)
            return 2
        categories = [args.category]

    try:
        selection = build_selection(
            repo,
            folders=args.folder or [],
            includes=args.include or [],
            excludes=args.exclude or [],
        )
    except SelectionError as exc:
        logger.error("%s", exc)
        return 2

    source: Source = args.mode
    try:
        result = scan_repo(repo, config, categories=categories, source=source, selection=selection)
    except NotAGitRepoError as exc:
        logger.error("%s", exc)
        logger.error("to scan a folder that is not a git repository, use --mode dir")
        return 2
    except (GitError, ScanError, WalkError, SelectionError) as exc:
        logger.error("%s", exc)
        return 2

    if source == "dir" and not selection.active and result.tracked_files == 0:
        logger.warning("no files found under %s; nothing was scanned", repo)

    if args.format == "json":
        output = render_json(
            result,
            repo=repo,
            quiet=args.quiet,
            show_matches=args.show_matches,
        )
    else:
        output = render_text(
            result,
            config,
            repo=repo,
            quiet=args.quiet,
            show_matches=args.show_matches,
            categories=categories,
        )
    print(output)

    return 1 if result.hits else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns an exit code instead of calling sys.exit()."""
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(args.log_level)

    try:
        return run(args)
    except KeyboardInterrupt:
        logger.error("interrupted")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
