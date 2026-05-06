"""Tests for the HA-side glossary-override preflight (G3).

Covers:
- empty / whitespace / YAML null → no-override path returns (None, [], [])
- valid override → returns (parsed, affected_paths, warnings)
- invalid YAML → GlossaryOverrideError with line/col
- non-dict top level → GlossaryOverrideError
- schema-violating merged result → GlossaryOverrideError with JSON pointer
- meta block stripped → warning surfaced, override still applied
"""

from __future__ import annotations

import pytest

from custom_components.blaueis_midea._glossary_override import (
    GlossaryOverrideError,
    validate_and_parse_overrides,
)


# ── Empty / null inputs ────────────────────────────────────────────────


def test_none_input():
    parsed, affected, warnings = validate_and_parse_overrides(None)
    assert parsed is None
    assert affected == []
    assert warnings == []


def test_empty_string():
    parsed, affected, warnings = validate_and_parse_overrides("")
    assert parsed is None


def test_whitespace_only():
    parsed, affected, warnings = validate_and_parse_overrides("   \n\t  \n")
    assert parsed is None


def test_yaml_null_only():
    parsed, _, _ = validate_and_parse_overrides("~")
    assert parsed is None


def test_yaml_comments_only():
    parsed, _, _ = validate_and_parse_overrides("# this is just a comment\n")
    assert parsed is None


# ── Valid overrides ────────────────────────────────────────────────────


def test_valid_screen_display_override():
    yaml_text = """
fields:
  control:
    screen_display:
      feature_available: excluded
"""
    parsed, affected, warnings = validate_and_parse_overrides(yaml_text)
    assert parsed is not None
    assert parsed["fields"]["control"]["screen_display"]["feature_available"] == "excluded"
    assert (
        "fields.control.screen_display.feature_available" in affected
    )
    assert warnings == []


def test_meta_block_stripped_with_warning():
    yaml_text = """
meta:
  version: 99.0.0
fields:
  control:
    screen_display:
      feature_available: excluded
"""
    parsed, affected, warnings = validate_and_parse_overrides(yaml_text)
    # Override applied; meta warning surfaced.
    assert parsed is not None
    assert "meta" in parsed  # parsed retains original input
    assert len(warnings) == 1
    assert "meta" in warnings[0].lower()


# ── Parse errors ───────────────────────────────────────────────────────


def test_invalid_yaml_returns_line_col():
    yaml_text = """
fields:
  control:
    screen_display:
      feature_available:
        bad: [unclosed
"""
    with pytest.raises(GlossaryOverrideError) as exc:
        validate_and_parse_overrides(yaml_text)
    msg = str(exc.value)
    assert "line" in msg.lower() or "syntax" in msg.lower()


def test_top_level_list_rejected():
    yaml_text = "- a\n- b\n"
    with pytest.raises(GlossaryOverrideError) as exc:
        validate_and_parse_overrides(yaml_text)
    assert "mapping" in str(exc.value).lower() or "dict" in str(exc.value).lower()


def test_top_level_scalar_rejected():
    yaml_text = "hello"
    with pytest.raises(GlossaryOverrideError):
        validate_and_parse_overrides(yaml_text)


# ── Schema violation ───────────────────────────────────────────────────


def test_invalid_feature_available_value_rejected():
    """`feature_available` must be one of the schema enum
    (always/readable/capability/never). 'maybe' is not."""
    yaml_text = """
fields:
  control:
    screen_display:
      feature_available: maybe
"""
    with pytest.raises(GlossaryOverrideError) as exc:
        validate_and_parse_overrides(yaml_text)
    msg = str(exc.value)
    # Should mention the schema location and what was wrong.
    assert "feature_available" in msg
    assert (
        "schema" in msg.lower() or "validation" in msg.lower() or "enum" in msg.lower()
    )
