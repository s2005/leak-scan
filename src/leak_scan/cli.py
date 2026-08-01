"""Command-line interface for leak-scan."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from leak_scan import __version__
from leak_scan.config import DEFAULT_CONFIG_NAMES, ConfigError, find_config, load_config
from leak_scan.gitrepo import GitError
from leak_scan.report import render_json, render_text
from leak_scan.scanner import ScanError, scan_repo

logger = logging.getLogger(__name__)

LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]
FORMATS = ["text", "json"]


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
        "--repo",
        required=True,
        help="Path to the git repository or exported tree to scan. Required.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to the scanner configuration file. Default: search the current "
        "working directory then --repo for one of "
        f"{', '.join(DEFAULT_CONFIG_NAMES)}.",
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
        logger.error("not a directory: %s", repo)
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
        result = scan_repo(repo, config, categories=categories)
    except (GitError, ScanError) as exc:
        logger.error("%s", exc)
        return 2

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
