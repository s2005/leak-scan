"""Scan a git-tracked tree for content that must not be published."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("leak-scan")
except PackageNotFoundError:  # pragma: no cover - source checkout without install
    __version__ = "0.0.0.dev0"

__all__ = ["__version__"]
