"""Translation consistency checks.

Two surfaces are validated:

1. **Field-agnostic chrome** in ``translations/<lang>.json``. The
   keys consumed by ``_preflight.validate_or_raise`` must exist in
   every language file with the same placeholder set, otherwise HA
   silently falls back to the literal key.

2. **Field-level i18n** declared inside the glossary (``label_i18n:``,
   ``description_i18n:``). Per-field declarations must be consistent
   within the field (no mixed-type values, every language string
   non-empty). We do not require parity across fields — adding a
   language one field at a time is the expected migration path.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

INTEGRATION_ROOT = Path(__file__).resolve().parents[2] / "custom_components" / "blaueis_midea"
TRANSLATIONS_DIR = INTEGRATION_ROOT / "translations"
GLOSSARY_PATH = (
    INTEGRATION_ROOT / "lib" / "blaueis" / "core" / "data" / "glossary.yaml"
)

PREFLIGHT_KEYS = {
    "value_out_of_range": {"got", "min", "max", "field"},
    "value_not_in_enum": {"got", "allowed", "field"},
    "field_inactive_in_mode": {"field", "mode"},
}

PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


# ── translations/<lang>.json: chrome layer ───────────────────────────


def _all_lang_files() -> list[Path]:
    return sorted(TRANSLATIONS_DIR.glob("*.json"))


@pytest.mark.parametrize("lang_file", _all_lang_files(), ids=lambda p: p.stem)
def test_preflight_keys_present_in_lang_file(lang_file: Path) -> None:
    """Every preflight translation key exists under ``exceptions:``."""
    data = json.loads(lang_file.read_text(encoding="utf-8"))
    exceptions = data.get("exceptions") or {}
    missing = sorted(set(PREFLIGHT_KEYS) - set(exceptions))
    assert not missing, (
        f"{lang_file.name} missing exception keys: {missing}"
    )


@pytest.mark.parametrize("lang_file", _all_lang_files(), ids=lambda p: p.stem)
def test_preflight_placeholders_match_in_lang_file(lang_file: Path) -> None:
    """Each preflight key's message uses exactly the expected placeholders.

    HA validates the placeholder set across language files at cache build
    — a mismatch silently disables the localised string. Catching it in
    test keeps the production cache populated.
    """
    data = json.loads(lang_file.read_text(encoding="utf-8"))
    exceptions = data.get("exceptions") or {}
    for key, expected in PREFLIGHT_KEYS.items():
        block = exceptions.get(key)
        assert isinstance(block, dict), f"{lang_file.name}:{key} not a block"
        message = block.get("message")
        assert isinstance(message, str) and message, (
            f"{lang_file.name}:{key} has no message"
        )
        actual = set(PLACEHOLDER_RE.findall(message))
        assert actual == expected, (
            f"{lang_file.name}:{key} placeholders {actual} != {expected}"
        )


# ── glossary label_i18n / description_i18n: field-level ──────────────


def _walk_glossary_fields(node, path=()):
    """Yield (path_tuple, field_dict) for every leaf with ``data_type``
    or ``label_i18n``/``description_i18n``."""
    if not isinstance(node, dict):
        return
    if (
        "data_type" in node
        or "label_i18n" in node
        or "description_i18n" in node
    ):
        yield path, node
        return
    for k, v in node.items():
        yield from _walk_glossary_fields(v, path + (k,))


def _load_glossary_fields() -> list[tuple[tuple, dict]]:
    if not GLOSSARY_PATH.exists():
        return []
    raw = yaml.safe_load(GLOSSARY_PATH.read_text(encoding="utf-8"))
    fields = (raw or {}).get("fields") or {}
    return list(_walk_glossary_fields(fields))


def test_glossary_i18n_blocks_are_well_formed() -> None:
    """For every field that declares ``label_i18n`` or ``description_i18n``:

    - The block is a dict.
    - Every key (lang code) maps to a non-empty string.
    - At least one entry exists (an empty block is a config error).
    """
    bad: list[str] = []
    for path, fdef in _load_glossary_fields():
        for blob_name in ("label_i18n", "description_i18n"):
            i18n = fdef.get(blob_name)
            if i18n is None:
                continue
            label = ".".join(path) + f".{blob_name}"
            if not isinstance(i18n, dict) or not i18n:
                bad.append(f"{label}: not a non-empty dict")
                continue
            for lang, val in i18n.items():
                if not isinstance(lang, str) or not lang:
                    bad.append(f"{label}: lang key {lang!r} not a non-empty str")
                if not isinstance(val, str) or not val:
                    bad.append(f"{label}.{lang}: value not a non-empty str")
    assert not bad, "Glossary i18n issues:\n  " + "\n  ".join(bad)


def test_every_glossary_lang_has_translation_file() -> None:
    """If the glossary declares strings in language X, the integration
    must ship a ``translations/X.json`` so HA can resolve the chrome
    pieces (config-flow titles, exception templates) that don't live in
    the glossary."""
    declared: set[str] = set()
    for _, fdef in _load_glossary_fields():
        for blob_name in ("label_i18n", "description_i18n"):
            i18n = fdef.get(blob_name)
            if isinstance(i18n, dict):
                declared.update(k for k in i18n if isinstance(k, str))
    available = {p.stem for p in _all_lang_files()}
    missing = sorted(declared - available)
    assert not missing, (
        f"Glossary declares languages with no translation file: {missing}"
    )
