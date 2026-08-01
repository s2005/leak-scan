"""Allow running the package with `python -m leak_scan`."""

from leak_scan.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
