"""Tests for leak_scan.config."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from leak_scan.config import (
    DEFAULT_CONFIG_NAMES,
    ConfigError,
    find_config,
    load_config,
    parse_config,
)
from leak_scan.models import ScanConfig

EXAMPLE_YAML = Path(__file__).resolve().parents[1] / "leak-scan.example.yaml"
EXAMPLE_JSON = Path(__file__).resolve().parents[1] / "leak-scan.example.json"


def _normalize(config: ScanConfig) -> tuple[object, ...]:
    """Project a ScanConfig into a comparable, pattern-text-based tuple.

    re.Pattern objects compiled separately never compare equal via `==` even
    with identical text and flags, so equivalence tests compare this
    projection instead of the dataclasses directly.
    """
    categories = tuple(
        (
            category.name,
            category.description,
            tuple((rule.label, rule.regex.pattern, rule.regex.flags) for rule in category.rules),
            tuple(pattern.pattern for pattern in category.allow.context),
            frozenset(category.allow.values),
            tuple(pattern.pattern for pattern in category.allow.value_patterns),
            category.allow.min_value_length,
            category.allow.require_letter_and_digit,
        )
        for category in config.categories
    )
    path_allow = tuple(pattern.pattern for pattern in config.path_allow)
    return categories, path_allow, frozenset(config.binary_suffixes)


@pytest.mark.unit
def test_round_trip_yaml(tmp_path: Path, config_data: dict[str, Any]) -> None:
    path = tmp_path / "leak-scan.yaml"
    path.write_text(yaml.safe_dump(config_data), encoding="utf-8")
    config = load_config(path)
    assert config.category_names == ("identity", "machine", "credential")


@pytest.mark.unit
def test_round_trip_json(tmp_path: Path, config_data: dict[str, Any]) -> None:
    path = tmp_path / "leak-scan.json"
    path.write_text(json.dumps(config_data), encoding="utf-8")
    config = load_config(path)
    assert config.category_names == ("identity", "machine", "credential")


@pytest.mark.unit
def test_round_trip_yaml_and_json_are_equivalent(
    tmp_path: Path, config_data: dict[str, Any]
) -> None:
    yaml_path = tmp_path / "leak-scan.yaml"
    json_path = tmp_path / "leak-scan.json"
    yaml_path.write_text(yaml.safe_dump(config_data), encoding="utf-8")
    json_path.write_text(json.dumps(config_data), encoding="utf-8")

    assert _normalize(load_config(yaml_path)) == _normalize(load_config(json_path))


@pytest.mark.unit
def test_example_configs_are_equivalent() -> None:
    yaml_config = load_config(EXAMPLE_YAML)
    json_config = load_config(EXAMPLE_JSON)
    assert _normalize(yaml_config) == _normalize(json_config)


@pytest.mark.unit
def test_example_configs_have_no_default_binary_suffix_gap() -> None:
    # Sanity check that the examples actually loaded a non-trivial config.
    yaml_config = load_config(EXAMPLE_YAML)
    assert "credential" in yaml_config.category_names
    assert "machine" in yaml_config.category_names
    assert "docs_tasks" in yaml_config.category_names
    assert ".png" in yaml_config.binary_suffixes


@pytest.mark.unit
def test_unsupported_extension_raises(tmp_path: Path) -> None:
    path = tmp_path / "leak-scan.toml"
    path.write_text("version = 1", encoding="utf-8")
    with pytest.raises(ConfigError, match="unsupported config file extension"):
        load_config(path)


@pytest.mark.unit
def test_invalid_yaml_raises(tmp_path: Path) -> None:
    path = tmp_path / "leak-scan.yaml"
    path.write_text("version: [1, 2\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(path)


@pytest.mark.unit
def test_duplicate_yaml_key_raises(tmp_path: Path) -> None:
    path = tmp_path / "leak-scan.yaml"
    path.write_text("version: 1\nversion: 2\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"duplicate key ['\"]version['\"]"):
        load_config(path)


@pytest.mark.unit
def test_duplicate_yaml_key_in_nested_mapping_raises(tmp_path: Path) -> None:
    path = tmp_path / "leak-scan.yaml"
    path.write_text(
        "version: 1\n"
        "categories:\n"
        "  - name: widget\n"
        "    name: gadget\n"
        "    rules:\n"
        "      - label: widget-token\n"
        "        pattern: 'widget-[0-9]+'\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=r"duplicate key ['\"]name['\"]"):
        load_config(path)


@pytest.mark.unit
def test_unhashable_yaml_key_raises_config_error(tmp_path: Path) -> None:
    path = tmp_path / "leak-scan.yaml"
    path.write_text("? [a, b]\n: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(path)


@pytest.mark.unit
def test_yaml_merge_key_loads(tmp_path: Path) -> None:
    path = tmp_path / "leak-scan.yaml"
    path.write_text(
        "version: 1\n"
        "categories:\n"
        "  - name: widget\n"
        "    rules:\n"
        "      - label: widget-token\n"
        "        pattern: 'widget-[0-9]+'\n"
        "    allow: &shared_allow\n"
        "      values: ['placeholder-widget']\n"
        "  - name: gadget\n"
        "    rules:\n"
        "      - label: gadget-token\n"
        "        pattern: 'gadget-[0-9]+'\n"
        "    allow:\n"
        "      <<: *shared_allow\n",
        encoding="utf-8",
    )
    config = load_config(path)
    gadget = next(category for category in config.categories if category.name == "gadget")
    assert "placeholder-widget" in gadget.allow.values


@pytest.mark.unit
def test_yaml_explicit_key_overrides_merged_key(tmp_path: Path) -> None:
    path = tmp_path / "leak-scan.yaml"
    path.write_text(
        "version: 1\n"
        "categories:\n"
        "  - name: widget\n"
        "    rules:\n"
        "      - label: widget-token\n"
        "        pattern: 'widget-[0-9]+'\n"
        "    allow: &shared_allow\n"
        "      values: ['placeholder-widget']\n"
        "  - name: gadget\n"
        "    rules:\n"
        "      - label: gadget-token\n"
        "        pattern: 'gadget-[0-9]+'\n"
        "    allow:\n"
        "      <<: *shared_allow\n"
        "      values: ['placeholder-gadget']\n",
        encoding="utf-8",
    )
    config = load_config(path)
    gadget = next(category for category in config.categories if category.name == "gadget")
    assert set(gadget.allow.values) == {"placeholder-gadget"}


@pytest.mark.unit
def test_duplicate_key_in_inline_merge_source_raises(tmp_path: Path) -> None:
    path = tmp_path / "leak-scan.yaml"
    path.write_text(
        "version: 1\n"
        "categories:\n"
        "  - name: widget\n"
        "    rules:\n"
        "      - label: widget-token\n"
        "        pattern: 'widget-[0-9]+'\n"
        "    allow:\n"
        "      <<: {values: ['placeholder-first'], values: ['placeholder-second']}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=r"duplicate key ['\"]values['\"]"):
        load_config(path)


@pytest.mark.unit
def test_duplicate_key_in_merge_source_sequence_raises(tmp_path: Path) -> None:
    path = tmp_path / "leak-scan.yaml"
    path.write_text(
        "version: 1\n"
        "categories:\n"
        "  - name: widget\n"
        "    rules:\n"
        "      - label: widget-token\n"
        "        pattern: 'widget-[0-9]+'\n"
        "    allow:\n"
        "      <<: [{values: ['placeholder-first'], values: ['placeholder-second']}]\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=r"duplicate key ['\"]values['\"]"):
        load_config(path)


@pytest.mark.unit
def test_yaml_override_of_nested_merge_key_on_reused_anchor_loads(tmp_path: Path) -> None:
    path = tmp_path / "leak-scan.yaml"
    path.write_text(
        "version: 1\n"
        "categories:\n"
        "  - name: widget\n"
        "    rules:\n"
        "      - label: widget-token\n"
        "        pattern: 'widget-[0-9]+'\n"
        "    allow: &shared_allow\n"
        "      <<: {values: ['placeholder-base']}\n"
        "      values: ['placeholder-widget']\n"
        "  - name: gadget\n"
        "    rules:\n"
        "      - label: gadget-token\n"
        "        pattern: 'gadget-[0-9]+'\n"
        "    allow:\n"
        "      <<: *shared_allow\n",
        encoding="utf-8",
    )
    config = load_config(path)
    gadget = next(category for category in config.categories if category.name == "gadget")
    assert set(gadget.allow.values) == {"placeholder-widget"}


@pytest.mark.unit
def test_same_key_in_two_merge_sources_loads(tmp_path: Path) -> None:
    path = tmp_path / "leak-scan.yaml"
    path.write_text(
        "version: 1\n"
        "categories:\n"
        "  - name: widget\n"
        "    rules:\n"
        "      - label: widget-token\n"
        "        pattern: 'widget-[0-9]+'\n"
        "    allow:\n"
        "      <<: [{values: ['placeholder-first']}, {values: ['placeholder-second']}]\n",
        encoding="utf-8",
    )
    config = load_config(path)
    widget = next(category for category in config.categories if category.name == "widget")
    assert set(widget.allow.values) == {"placeholder-first"}


@pytest.mark.unit
def test_repeated_merge_key_raises(tmp_path: Path) -> None:
    path = tmp_path / "leak-scan.yaml"
    path.write_text(
        "version: 1\n"
        "categories:\n"
        "  - name: widget\n"
        "    rules:\n"
        "      - label: widget-token\n"
        "        pattern: 'widget-[0-9]+'\n"
        "    allow:\n"
        "      <<: {values: ['placeholder-first']}\n"
        "      <<: {values: ['placeholder-second']}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=r"duplicate key ['\"]<<['\"]"):
        load_config(path)


@pytest.mark.unit
def test_quoted_merge_key_is_an_ordinary_key(tmp_path: Path) -> None:
    path = tmp_path / "leak-scan.yaml"
    path.write_text(
        "version: 1\n"
        "categories:\n"
        "  - name: widget\n"
        "    rules:\n"
        "      - label: widget-token\n"
        "        pattern: 'widget-[0-9]+'\n"
        "    allow:\n"
        "      <<: {values: ['placeholder-first']}\n"
        "      '<<': {values: ['placeholder-second']}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="unknown key") as excinfo:
        load_config(path)
    assert "duplicate" not in str(excinfo.value)


@pytest.mark.unit
def test_invalid_json_raises(tmp_path: Path) -> None:
    path = tmp_path / "leak-scan.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid JSON"):
        load_config(path)


@pytest.mark.unit
def test_missing_version_raises(config_data: dict[str, Any]) -> None:
    del config_data["version"]
    with pytest.raises(ConfigError, match="version"):
        parse_config(config_data, source="<test>")


@pytest.mark.unit
def test_unknown_top_level_key_raises(config_data: dict[str, Any]) -> None:
    config_data["unexpected"] = True
    with pytest.raises(ConfigError, match=r"<test>: unknown key 'unexpected'"):
        parse_config(config_data, source="<test>")


@pytest.mark.unit
def test_unknown_category_key_raises(config_data: dict[str, Any]) -> None:
    config_data["categories"][0]["unexpected"] = True
    with pytest.raises(ConfigError, match=r"category #1: unknown key 'unexpected'"):
        parse_config(config_data, source="<test>")


@pytest.mark.unit
def test_unknown_rule_key_raises(config_data: dict[str, Any]) -> None:
    config_data["categories"][0]["rules"][0]["unexpected"] = True
    with pytest.raises(
        ConfigError,
        match=r"category 'identity': rule #1: unknown key 'unexpected'",
    ):
        parse_config(config_data, source="<test>")


@pytest.mark.unit
def test_unknown_allow_key_raises(config_data: dict[str, Any]) -> None:
    config_data["categories"][1]["allow"]["unexpected"] = True
    with pytest.raises(
        ConfigError,
        match=r"category 'machine': 'allow': unknown key 'unexpected'",
    ):
        parse_config(config_data, source="<test>")


@pytest.mark.unit
def test_wrong_version_raises(config_data: dict[str, Any]) -> None:
    config_data["version"] = 2
    with pytest.raises(ConfigError, match="version"):
        parse_config(config_data, source="<test>")


@pytest.mark.unit
def test_missing_categories_raises(config_data: dict[str, Any]) -> None:
    del config_data["categories"]
    with pytest.raises(ConfigError, match="categories"):
        parse_config(config_data, source="<test>")


@pytest.mark.unit
def test_empty_categories_raises(config_data: dict[str, Any]) -> None:
    config_data["categories"] = []
    with pytest.raises(ConfigError, match="categories"):
        parse_config(config_data, source="<test>")


@pytest.mark.unit
def test_empty_category_name_raises(config_data: dict[str, Any]) -> None:
    config_data["categories"][0]["name"] = "  "
    with pytest.raises(ConfigError, match="category #1 'name' must not be empty"):
        parse_config(config_data, source="<test>")


@pytest.mark.unit
def test_missing_rules_raises(config_data: dict[str, Any]) -> None:
    del config_data["categories"][0]["rules"]
    with pytest.raises(ConfigError, match="rules"):
        parse_config(config_data, source="<test>")


@pytest.mark.unit
def test_empty_rules_raises(config_data: dict[str, Any]) -> None:
    config_data["categories"][0]["rules"] = []
    with pytest.raises(ConfigError, match="rules"):
        parse_config(config_data, source="<test>")


@pytest.mark.unit
def test_duplicate_category_name_raises(config_data: dict[str, Any]) -> None:
    config_data["categories"].append(dict(config_data["categories"][0]))
    with pytest.raises(ConfigError, match="duplicate category name"):
        parse_config(config_data, source="<test>")


@pytest.mark.unit
def test_missing_category_name_raises(config_data: dict[str, Any]) -> None:
    del config_data["categories"][0]["name"]
    with pytest.raises(ConfigError, match="missing 'name'"):
        parse_config(config_data, source="<test>")


@pytest.mark.unit
def test_missing_rule_label_raises(config_data: dict[str, Any]) -> None:
    del config_data["categories"][0]["rules"][0]["label"]
    with pytest.raises(ConfigError, match="missing 'label'"):
        parse_config(config_data, source="<test>")


@pytest.mark.unit
def test_empty_rule_label_raises(config_data: dict[str, Any]) -> None:
    config_data["categories"][0]["rules"][0]["label"] = "\t"
    with pytest.raises(ConfigError, match="rule #1 'label' must not be empty"):
        parse_config(config_data, source="<test>")


@pytest.mark.unit
def test_missing_rule_pattern_raises(config_data: dict[str, Any]) -> None:
    del config_data["categories"][0]["rules"][0]["pattern"]
    with pytest.raises(ConfigError, match="missing 'pattern'"):
        parse_config(config_data, source="<test>")


@pytest.mark.unit
def test_empty_rule_pattern_raises(config_data: dict[str, Any]) -> None:
    config_data["categories"][0]["rules"][0]["pattern"] = "\n"
    with pytest.raises(ConfigError, match="'pattern' must not be empty"):
        parse_config(config_data, source="<test>")


@pytest.mark.unit
def test_empty_allow_pattern_raises(config_data: dict[str, Any]) -> None:
    config_data["categories"][1]["allow"]["context"] = [" "]
    with pytest.raises(ConfigError, match=r"allow\.context entry must not be empty"):
        parse_config(config_data, source="<test>")


@pytest.mark.unit
def test_empty_path_allow_pattern_raises(config_data: dict[str, Any]) -> None:
    config_data["path_allow"] = [""]
    with pytest.raises(ConfigError, match="path_allow entry must not be empty"):
        parse_config(config_data, source="<test>")


@pytest.mark.unit
def test_negative_min_value_length_raises(config_data: dict[str, Any]) -> None:
    config_data["categories"][2]["allow"]["min_value_length"] = -1
    with pytest.raises(ConfigError, match="min_value_length must not be negative"):
        parse_config(config_data, source="<test>")


@pytest.mark.unit
def test_wrong_type_for_rules_raises(config_data: dict[str, Any]) -> None:
    config_data["categories"][0]["rules"] = "not-a-list"
    with pytest.raises(ConfigError, match="must be a list"):
        parse_config(config_data, source="<test>")


@pytest.mark.unit
def test_wrong_type_for_ignore_case_raises(config_data: dict[str, Any]) -> None:
    config_data["categories"][0]["rules"][0]["ignore_case"] = "yes"
    with pytest.raises(ConfigError, match="ignore_case"):
        parse_config(config_data, source="<test>")


@pytest.mark.unit
def test_invalid_regex_raises(config_data: dict[str, Any]) -> None:
    config_data["categories"][0]["rules"][0]["pattern"] = "(unclosed"
    with pytest.raises(ConfigError, match="invalid regex"):
        parse_config(config_data, source="<test>")


@pytest.mark.unit
def test_invalid_regex_error_names_category_and_label(config_data: dict[str, Any]) -> None:
    config_data["categories"][0]["rules"][0]["pattern"] = "(unclosed"
    with pytest.raises(ConfigError) as exc_info:
        parse_config(config_data, source="<test>")
    message = str(exc_info.value)
    assert "identity" in message
    assert "author handle" in message
    assert "(unclosed" in message


@pytest.mark.unit
def test_top_level_not_a_mapping_raises() -> None:
    with pytest.raises(ConfigError, match="mapping"):
        parse_config([1, 2, 3], source="<test>")


@pytest.mark.unit
def test_find_config_searches_directories_in_order(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (second / "leak-scan.yaml").write_text("version: 1\n", encoding="utf-8")

    assert find_config(first, second) == second / "leak-scan.yaml"


@pytest.mark.unit
def test_find_config_prefers_first_matching_directory(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "leak-scan.json").write_text("{}", encoding="utf-8")
    (second / "leak-scan.yaml").write_text("version: 1\n", encoding="utf-8")

    assert find_config(first, second) == first / "leak-scan.json"


@pytest.mark.unit
def test_find_config_returns_none_when_nothing_found(tmp_path: Path) -> None:
    assert find_config(tmp_path) is None


@pytest.mark.unit
def test_default_config_names() -> None:
    assert DEFAULT_CONFIG_NAMES == ("leak-scan.yaml", "leak-scan.yml", "leak-scan.json")
