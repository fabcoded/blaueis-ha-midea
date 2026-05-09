"""HA-side preflight for glossary overrides — parse, merge, validate.

This module is the gatekeeper for user-supplied YAML overrides entered
via the Configure dialog. It does three things:

1. Parses the YAML text → a Python dict (or returns "no override" for
   empty / whitespace-only / explicit-null input).
2. Strips protected keys (``meta``) via ``apply_override``.
3. Validates the **merged result** (base glossary + user override)
   against ``glossary_schema.json``. Validating the merged result —
   not the partial override alone — is the cleanest way to enforce
   schema invariants that span keys (e.g. required fields on a cap
   value).

On any failure the caller gets a single ``GlossaryOverrideError`` with
a human-readable message that names the location of the problem
(YAML line/col for parse errors, JSON-pointer path for schema errors).
This is what surfaces as a form error in the config flow.

Used by config_flow.py (G4) on save and by __init__.py (G5) on entry
load.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from blaueis.core.codec import load_glossary
from blaueis.core.glossary_override import OverrideMessage, apply_override

_LOGGER = logging.getLogger(__name__)

# Path to the schema, vendored alongside the glossary.
_SCHEMA_PATH = (
    Path(__file__).parent / "lib" / "blaueis" / "core" / "data" / "glossary_schema.json"
)


class GlossaryOverrideError(ValueError):
    """Raised by ``validate_and_parse_overrides`` for any user-recoverable
    failure: YAML parse error, non-dict top level, or schema rejection.

    The message is intended to be shown directly to the user in the
    config-flow form. It does NOT carry a traceback — the cause is
    described in plain text (e.g. ``YAML syntax error at line 4: ...``
    or ``Schema rejected at fields.X.feature_available: ...``).
    """


# ── Schema (loaded at module init) ─────────────────────────────────────
# Loaded eagerly so the I/O happens during HA's executor-threaded import
# of the integration package — never inside the event loop. A lazy load
# triggered HA's blocking-call detector at async_setup_entry time.
# The schema file is bundled with the integration and never mutates, so
# there's no benefit to deferring.

_SCHEMA: dict = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


# ── Public API ─────────────────────────────────────────────────────────


def validate_and_parse_overrides(
    yaml_text: str | None,
) -> tuple[dict | None, list[str], list[OverrideMessage]]:
    """Parse + validate an override YAML string.

    Returns ``(parsed_override, affected_paths, messages)``:

    - ``parsed_override``: the dict that should be passed to
      ``Device(glossary_overrides=...)``, or ``None`` if no override
      is configured (empty / whitespace / YAML null).
    - ``affected_paths``: dotted leaf paths of leaves that the merge
      would change in the merged glossary. Used by G12 for the
      "N fields affected" message and G9 for the merged view markers.
    - ``messages``: structured ``OverrideMessage`` records from the
      override merge — protected-key strips plus per-field exclusion
      gating outcomes (``excluded_accepted`` / ``excluded_caveat`` /
      ``excluded_rejected``). The integration renders these as the
      user-facing status block. See ``docs/exclusion_reasons.md``.

    Raises ``GlossaryOverrideError`` for anything the user can fix:

    - YAML parse errors (with line/col).
    - Top-level not a dict (e.g. user pasted a list).
    - Schema validation failure (with JSON-pointer path).
    """
    # Empty / null → no override.
    if yaml_text is None:
        return None, [], []
    stripped = yaml_text.strip()
    if not stripped:
        return None, [], []

    # Parse YAML.
    try:
        parsed: Any = yaml.safe_load(stripped)
    except yaml.YAMLError as e:
        raise GlossaryOverrideError(_format_yaml_error(e)) from None

    if parsed is None:
        # YAML "~" or comments-only → no override.
        return None, [], []
    if not isinstance(parsed, dict):
        raise GlossaryOverrideError(
            f"Override must be a YAML mapping (dict) at the top level. "
            f"Got {type(parsed).__name__}."
        )

    # Merge against base glossary, then validate the merged result.
    # IMPORTANT: we only flag errors that the OVERRIDE introduces. The
    # on-disk glossary may itself have pre-existing schema-vs-data
    # divergences (e.g. fields with `_migration` audit blocks the schema
    # doesn't yet describe); those are not the user's problem and must
    # not block their override. We compute the baseline errors first
    # and reject only schema violations that did not exist before the
    # override was applied.
    base = load_glossary()
    merged, affected, messages = apply_override(base, parsed)

    schema = _SCHEMA
    validator = Draft202012Validator(schema)
    base_signatures = {_error_signature(e) for e in validator.iter_errors(base)}
    new_errors = [
        e
        for e in validator.iter_errors(merged)
        if _error_signature(e) not in base_signatures
    ]
    new_errors.sort(key=lambda e: list(e.absolute_path))
    if new_errors:
        first = new_errors[0]
        path = ".".join(str(p) for p in first.absolute_path) or "<root>"
        msg = f"Schema validation failed at {path}: {first.message}"
        if len(new_errors) > 1:
            msg += (
                f"\n(plus {len(new_errors) - 1} more validation error(s) "
                f"caused by this override)"
            )
        raise GlossaryOverrideError(msg)

    return parsed, affected, messages


# ── Helpers ────────────────────────────────────────────────────────────


def _error_signature(err: ValidationError) -> tuple:
    """A hashable identity for a schema ValidationError, used to dedupe
    errors that already exist in the un-overridden base glossary.

    The path tuple + message is stable across runs and tight enough that
    two errors with the same path-and-message are practically the same
    issue. Not perfect (two distinct issues could collide on identical
    messages), but close enough for filtering purposes.
    """
    return (tuple(err.absolute_path), err.message)


def _format_yaml_error(err: yaml.YAMLError) -> str:
    """Render a YAML parse error with line/column when available."""
    if hasattr(err, "problem_mark") and err.problem_mark is not None:
        mark = err.problem_mark
        return (
            f"YAML syntax error at line {mark.line + 1}, "
            f"column {mark.column + 1}: {err.problem or 'invalid YAML'}"
        )
    return f"YAML syntax error: {err}"
