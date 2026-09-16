"""Load, validate, and compile leak-scan configuration files.

The scanner never hardcodes the site-specific literals it searches for;
every pattern, label, category and allowlist comes from a config file
following the schema validated here. See ``leak-scan.example.yaml`` for a
fully documented sample.
"""

from __future__ import annotations

import json
import re
from collections.abc import Hashable
from pathlib import Path
from typing import Any

import yaml

from leak_scan.models import AllowRules, Category, Rule, ScanConfig

CONFIG_VERSION = 1

DEFAULT_CONFIG_NAMES = ("leak-scan.yaml", "leak-scan.yml", "leak-scan.json")

TOP_LEVEL_KEYS = frozenset({"version", "categories", "path_allow", "binary_suffixes"})
CATEGORY_KEYS = frozenset({"name", "description", "rules", "allow"})
RULE_KEYS = frozenset({"label", "pattern", "ignore_case"})
ALLOW_KEYS = frozenset(
    {
        "context",
        "values",
        "value_patterns",
        "min_value_length",
        "require_letter_and_digit",
    }
)

DEFAULT_BINARY_SUFFIXES = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".pdf",
    ".zip",
    ".gz",
    ".jar",
    ".xlsx",
    ".class",
    ".so",
    ".dll",
    ".exe",
)


class ConfigError(ValueError):
    """Raised when a scanner configuration is missing, malformed, or invalid."""


_MERGE_TAG = "tag:yaml.org,2002:merge"


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""

    def construct_mapping(
        self, node: yaml.nodes.MappingNode, deep: bool = False
    ) -> dict[Hashable, Any]:
        if isinstance(node, yaml.nodes.MappingNode):
            seen: set[Hashable] = set()
            for key_node, _value_node in node.value:
                # Keys brought in through a merge are flattened by super() below and
                # must not be counted here, so an explicit key may override one.
                if key_node.tag == _MERGE_TAG:
                    continue
                key = self.construct_object(key_node, deep=deep)
                # Unhashable keys are left for the parent, which raises the
                # proper YAML "unhashable key" error instead of a raw TypeError.
                if not isinstance(key, Hashable):
                    continue
                if key in seen:
                    raise yaml.constructor.ConstructorError(
                        "while constructing a mapping",
                        node.start_mark,
                        f"duplicate key {key!r}",
                        key_node.start_mark,
                    )
                seen.add(key)
        return super().construct_mapping(node, deep=deep)


def find_config(*directories: Path) -> Path | None:
    """Return the first default-named config file found among directories.

    Each directory is searched for ``DEFAULT_CONFIG_NAMES`` in order, and the
    directories are tried in the order given. Returns ``None`` when no
    directory contains any of the default names.
    """
    for directory in directories:
        for name in DEFAULT_CONFIG_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def load_config(path: Path) -> ScanConfig:
    """Read a YAML or JSON configuration file from disk and compile it."""
    suffix = path.suffix.lower()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from exc

    data: object
    if suffix == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"invalid JSON in {path}: {exc}") from exc
    elif suffix in (".yaml", ".yml"):
        try:
            data = yaml.load(text, Loader=_UniqueKeyLoader)
        except yaml.YAMLError as exc:
            raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    else:
        raise ConfigError(f"unsupported config file extension {path.suffix!r}: {path}")

    return parse_config(data, source=str(path))


def _expect_mapping(data: object, context: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ConfigError(f"{context} must be a mapping, got {type(data).__name__}")
    return data


def _expect_list(value: object, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise ConfigError(f"{context} must be a list, got {type(value).__name__}")
    return value


def _expect_str(value: object, context: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{context} must be a string, got {type(value).__name__}")
    return value


def _expect_bool(value: object, context: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{context} must be a boolean, got {type(value).__name__}")
    return value


def _expect_int(value: object, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"{context} must be an integer, got {type(value).__name__}")
    return value


def _expect_non_empty_str(value: object, context: str) -> str:
    text = _expect_str(value, context)
    if not text.strip():
        raise ConfigError(f"{context} must not be empty")
    return text


def _reject_unknown_keys(mapping: dict[str, Any], *, allowed: frozenset[str], context: str) -> None:
    unknown = sorted((key for key in mapping if key not in allowed), key=repr)
    if not unknown:
        return
    rendered = ", ".join(repr(key) for key in unknown)
    noun = "key" if len(unknown) == 1 else "keys"
    raise ConfigError(f"{context}: unknown {noun} {rendered}")


def _compile_pattern(pattern: str, *, flags: int, context: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern, flags)
    except re.error as exc:
        raise ConfigError(f"{context}: invalid regex {pattern!r}: {exc}") from exc


def _parse_allow(data: object, *, category_name: str) -> AllowRules:
    if data is None:
        return AllowRules()
    mapping = _expect_mapping(data, f"category {category_name!r}: 'allow'")
    _reject_unknown_keys(
        mapping,
        allowed=ALLOW_KEYS,
        context=f"category {category_name!r}: 'allow'",
    )

    context_list = _expect_list(
        mapping.get("context", []), f"category {category_name!r}: allow.context"
    )
    context = tuple(
        _compile_pattern(
            _expect_non_empty_str(pattern, f"category {category_name!r}: allow.context entry"),
            flags=re.IGNORECASE,
            context=f"category {category_name!r}: allow.context",
        )
        for pattern in context_list
    )

    values_list = _expect_list(
        mapping.get("values", []), f"category {category_name!r}: allow.values"
    )
    values = frozenset(
        _expect_str(value, f"category {category_name!r}: allow.values entry").strip().lower()
        for value in values_list
    )

    value_patterns_list = _expect_list(
        mapping.get("value_patterns", []), f"category {category_name!r}: allow.value_patterns"
    )
    value_patterns = tuple(
        _compile_pattern(
            _expect_non_empty_str(
                pattern, f"category {category_name!r}: allow.value_patterns entry"
            ),
            flags=0,
            context=f"category {category_name!r}: allow.value_patterns",
        )
        for pattern in value_patterns_list
    )

    min_value_length = _expect_int(
        mapping.get("min_value_length", 0),
        f"category {category_name!r}: allow.min_value_length",
    )
    if min_value_length < 0:
        raise ConfigError(
            f"category {category_name!r}: allow.min_value_length must not be negative"
        )
    require_letter_and_digit = _expect_bool(
        mapping.get("require_letter_and_digit", False),
        f"category {category_name!r}: allow.require_letter_and_digit",
    )

    return AllowRules(
        context=context,
        values=values,
        value_patterns=value_patterns,
        min_value_length=min_value_length,
        require_letter_and_digit=require_letter_and_digit,
    )


def _parse_rule(data: object, *, category_name: str, index: int) -> Rule:
    mapping = _expect_mapping(data, f"category {category_name!r}: rule #{index + 1}")
    _reject_unknown_keys(
        mapping,
        allowed=RULE_KEYS,
        context=f"category {category_name!r}: rule #{index + 1}",
    )

    if "label" not in mapping:
        raise ConfigError(f"category {category_name!r}: rule #{index + 1} is missing 'label'")
    label = _expect_non_empty_str(
        mapping["label"], f"category {category_name!r}: rule #{index + 1} 'label'"
    )

    if "pattern" not in mapping:
        raise ConfigError(f"category {category_name!r}: rule {label!r} is missing 'pattern'")
    pattern = _expect_non_empty_str(
        mapping["pattern"], f"category {category_name!r}: rule {label!r} 'pattern'"
    )

    ignore_case = _expect_bool(
        mapping.get("ignore_case", True),
        f"category {category_name!r}: rule {label!r} 'ignore_case'",
    )
    flags = re.IGNORECASE if ignore_case else 0
    regex = _compile_pattern(
        pattern,
        flags=flags,
        context=f"category {category_name!r}, rule {label!r}, pattern {pattern!r}",
    )
    return Rule(label=label, regex=regex)


def _parse_category(data: object, *, index: int) -> Category:
    mapping = _expect_mapping(data, f"category #{index + 1}")
    _reject_unknown_keys(
        mapping,
        allowed=CATEGORY_KEYS,
        context=f"category #{index + 1}",
    )

    if "name" not in mapping:
        raise ConfigError(f"category #{index + 1} is missing 'name'")
    name = _expect_non_empty_str(mapping["name"], f"category #{index + 1} 'name'")

    description = _expect_str(mapping.get("description", ""), f"category {name!r}: 'description'")

    rules_raw = mapping.get("rules")
    if not rules_raw:
        raise ConfigError(f"category {name!r} must define a non-empty 'rules' list")
    rules_list = _expect_list(rules_raw, f"category {name!r}: 'rules'")
    if not rules_list:
        raise ConfigError(f"category {name!r} must define a non-empty 'rules' list")
    rules = tuple(
        _parse_rule(rule, category_name=name, index=rule_index)
        for rule_index, rule in enumerate(rules_list)
    )

    allow = _parse_allow(mapping.get("allow"), category_name=name)

    return Category(name=name, description=description, rules=rules, allow=allow)


def parse_config(data: object, source: str) -> ScanConfig:
    """Validate and compile a raw config document into a ``ScanConfig``.

    Kept separate from ``load_config`` so tests can exercise validation
    without touching disk.
    """
    mapping = _expect_mapping(data, source)
    _reject_unknown_keys(mapping, allowed=TOP_LEVEL_KEYS, context=source)

    version = mapping.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version != CONFIG_VERSION:
        raise ConfigError(f"{source}: 'version' must equal {CONFIG_VERSION}, got {version!r}")

    categories_raw = mapping.get("categories")
    if not categories_raw:
        raise ConfigError(f"{source}: 'categories' must be a non-empty list")
    categories_list = _expect_list(categories_raw, f"{source}: 'categories'")
    if not categories_list:
        raise ConfigError(f"{source}: 'categories' must be a non-empty list")

    categories = tuple(
        _parse_category(category, index=index) for index, category in enumerate(categories_list)
    )

    seen: set[str] = set()
    for category in categories:
        if category.name in seen:
            raise ConfigError(f"{source}: duplicate category name {category.name!r}")
        seen.add(category.name)

    path_allow_list = _expect_list(mapping.get("path_allow", []), f"{source}: 'path_allow'")
    path_allow = tuple(
        _compile_pattern(
            _expect_non_empty_str(pattern, f"{source}: path_allow entry"),
            flags=re.IGNORECASE,
            context=f"{source}: path_allow",
        )
        for pattern in path_allow_list
    )

    binary_suffixes_list = _expect_list(
        mapping.get("binary_suffixes", list(DEFAULT_BINARY_SUFFIXES)),
        f"{source}: 'binary_suffixes'",
    )
    binary_suffixes = frozenset(
        _expect_str(suffix, f"{source}: binary_suffixes entry").lower()
        for suffix in binary_suffixes_list
    )

    return ScanConfig(categories=categories, path_allow=path_allow, binary_suffixes=binary_suffixes)
