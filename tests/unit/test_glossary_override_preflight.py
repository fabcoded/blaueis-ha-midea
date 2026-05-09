"""Tests for the HA-side glossary-override preflight (G3).

Covers:
- empty / whitespace / YAML null → no-override path returns (None, [], [])
- valid override → returns (parsed, affected_paths, messages)
- invalid YAML → GlossaryOverrideError with line/col
- non-dict top level → GlossaryOverrideError
- schema-violating merged result → GlossaryOverrideError with JSON pointer
- meta block stripped → OverrideMessage emitted, override still applied
"""

from __future__ import annotations

import pytest

from custom_components.blaueis_midea._glossary_override import (
    GlossaryOverrideError,
    validate_and_parse_overrides,
)


# ── Empty / null inputs ────────────────────────────────────────────────


def test_none_input():
    parsed, affected, messages = validate_and_parse_overrides(None)
    assert parsed is None
    assert affected == []
    assert messages == []


def test_empty_string():
    parsed, affected, messages = validate_and_parse_overrides("")
    assert parsed is None


def test_whitespace_only():
    parsed, affected, messages = validate_and_parse_overrides("   \n\t  \n")
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
    parsed, affected, messages = validate_and_parse_overrides(yaml_text)
    assert parsed is not None
    assert (
        parsed["fields"]["control"]["screen_display"]["feature_available"] == "excluded"
    )
    assert "fields.control.screen_display.feature_available" in affected
    # screen_display is not currently 'excluded' in base, so no exclusion-
    # gating message. The override merely changes its tier; nothing gets
    # gated. Empty messages list is the expected outcome here.
    assert messages == []


def test_meta_block_stripped_with_warning():
    yaml_text = """
meta:
  version: 99.0.0
fields:
  control:
    screen_display:
      feature_available: excluded
"""
    parsed, affected, messages = validate_and_parse_overrides(yaml_text)
    # Override applied; meta strip surfaced as a structured OverrideMessage.
    assert parsed is not None
    assert "meta" in parsed  # parsed retains original input
    assert len(messages) == 1
    msg = messages[0]
    assert msg.code == "protected_key"
    assert msg.severity == "warning"
    assert msg.field is None
    assert "meta" in msg.message.lower()


def test_excluded_timer_field_caveat_path():
    """Override on power_off_timer (excluded for unnecessary_automation +
    never_tested_write) → caveat — present in messages, patch still applied."""
    yaml_text = """
fields:
  control:
    power_off_timer:
      feature_available: always
"""
    parsed, affected, messages = validate_and_parse_overrides(yaml_text)
    assert parsed is not None
    # Patch passes through (caveat does not strip).
    assert "fields.control.power_off_timer.feature_available" in affected
    # Exactly one exclusion-gating message for the timer field.
    timer_msgs = [m for m in messages if m.field == "fields.control.power_off_timer"]
    assert len(timer_msgs) == 1
    msg = timer_msgs[0]
    assert msg.code == "excluded_caveat"
    assert msg.severity == "warning"
    assert "never_tested_write" in msg.reasons
    assert "unnecessary_automation" in msg.reasons


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


# ── Parse-status display string (config_flow helper) ───────────────────


def test_parse_status_empty_yaml():
    from custom_components.blaueis_midea.config_flow import (
        _compute_override_parse_status,
    )

    assert _compute_override_parse_status("") == ""
    assert _compute_override_parse_status("   \n  \t") == ""
    assert _compute_override_parse_status(None) == ""  # type: ignore[arg-type]


def test_parse_status_clean_override():
    """Override on a non-excluded field with no caveats → parse ok."""
    from custom_components.blaueis_midea.config_flow import (
        _compute_override_parse_status,
    )

    yaml_text = (
        "fields:\n"
        "  control:\n"
        "    screen_display:\n"
        "      feature_available: excluded\n"
        "      excluded_reasons:\n"
        "      - unnecessary_automation\n"
    )
    assert _compute_override_parse_status(yaml_text) == "parse ok"


def test_parse_status_with_warning_on_timer_override():
    """Override on power_off_timer triggers caveat → status shows warning."""
    from custom_components.blaueis_midea.config_flow import (
        _compute_override_parse_status,
    )

    yaml_text = (
        "fields:\n  control:\n    power_off_timer:\n      feature_available: always\n"
    )
    assert _compute_override_parse_status(yaml_text) == "parse with warning (check log)"


def test_parse_status_failed_on_invalid_yaml():
    from custom_components.blaueis_midea.config_flow import (
        _compute_override_parse_status,
    )

    bad = "fields:\n  control:\n    bad: [unclosed\n"
    assert _compute_override_parse_status(bad) == "parse failed (check log)"


def test_parse_status_failed_on_schema_violation():
    """A schema-rejecting override (unknown enum value) → parse failed."""
    from custom_components.blaueis_midea.config_flow import (
        _compute_override_parse_status,
    )

    yaml_text = (
        "fields:\n"
        "  control:\n"
        "    screen_display:\n"
        "      feature_available: bogus_enum_value\n"
    )
    assert _compute_override_parse_status(yaml_text) == "parse failed (check log)"
