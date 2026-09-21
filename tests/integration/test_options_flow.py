"""Integration tests — the options ("Configure") flow.

Runs on the real HA flow engine via pytest-homeassistant-custom-component,
so the assertions cover what the framework actually does with the schema
rather than what ``_show_init_form`` intended: voluptuous default
substitution, the ``{**options, **user_input}`` merge, and the
update-listener reload that a changed override triggers.

The flow is single-step (``init``); there is no second step to route to.
``async_create_entry`` either ends it (options saved) or the handler
re-shows ``init`` with ``errors`` + ``description_placeholders``.

Three of the form's fields are not settings, and are asserted as such:

- ``override_parse_status_display`` / ``latest_field_inventory_display``
  are read-only displays — popped server-side, never persisted.
- ``run_inventory_scan_now`` is a trigger — it fires the
  ``run_field_inventory`` service and is then dropped.

The real ``async_setup_entry`` is blocked for the form-level tests; the
reload tests load the entry for real (with the coordinator's websocket
start and the platform forwards patched out) because the update listener
that performs the reload is only registered by a successful setup.
"""

from __future__ import annotations

import sys
from pathlib import Path

# conftest.py adds these, but pytest's collection order can bite —
# import-time path inserts are the safe belt-and-braces.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_VENDORED_LIB = _REPO_ROOT / "custom_components" / "blaueis_midea" / "lib"
if str(_VENDORED_LIB) not in sys.path:
    sys.path.insert(0, str(_VENDORED_LIB))

from typing import Any  # noqa: E402
from unittest.mock import AsyncMock, patch  # noqa: E402

import pytest  # noqa: E402
import voluptuous as vol  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402

from custom_components.blaueis_midea.const import (  # noqa: E402
    CONF_DISPLAY_BUZZER_MODE,
    CONF_FMF_CONFIGURED,
    CONF_FMF_ENABLED,
    CONF_FMF_GUARD_TEMP_MAX,
    CONF_FMF_GUARD_TEMP_MIN,
    CONF_FMF_SAFETY_TIMEOUT,
    CONF_FMF_SENSOR,
    CONF_GLOSSARY_OVERRIDES,
    CONF_HALF_DEGREE_STEPS,
    DOMAIN,
)

pytestmark = pytest.mark.asyncio

# Read-only display fields: rendered for information, dropped on save.
STATUS_DISPLAY = "override_parse_status_display"
INVENTORY_DISPLAY = "latest_field_inventory_display"
SCAN_TRIGGER = "run_inventory_scan_now"

# Valid override — flips a real glossary field to 'excluded'. Mirrors the
# minimal case in tests/unit/test_glossary_override_preflight.py.
VALID_OVERRIDE = """
fields:
  control:
    screen_display:
      feature_available: excluded
"""

# Unparseable YAML — a value position opened by a second ':' inside a
# flow mapping. Rejected by the YAML loader itself, so the error carries
# a line/column.
INVALID_OVERRIDE = "fields: {control: {screen_display: : }}\n"

# Parses fine, but the merged glossary then violates the schema.
SCHEMA_VIOLATING_OVERRIDE = "fields:\n  control:\n    screen_display:\n      feature_available: not_a_valid_tier\n"

# The Follow Me source field is an EntitySelector, which validates what
# it is given. The entity need not exist — only the id and the domain
# are checked — but it may not be empty: with no sensor configured the
# key is left out instead; see test_save_without_a_follow_me_sensor.
SENSOR_ENTITY = "sensor.living_room_temperature"


@pytest.fixture
def mock_setup_entry():
    """Block the real async_setup_entry behind entry creation/reload.

    Same rationale as in test_config_flow.py: the real setup does a
    glossary load, a scrypt stretch and a live websocket connect.
    """
    with patch("custom_components.blaueis_midea.async_setup_entry", return_value=True) as mock:
        yield mock


def _schema_defaults(data_schema: vol.Schema) -> dict[str, Any]:
    """Map every schema key to the default the form renders for it.

    ``vol.Optional.default`` is a zero-arg factory, or ``vol.UNDEFINED``
    when the marker carries no default.
    """
    defaults: dict[str, Any] = {}
    for key in data_schema.schema:
        default = getattr(key, "default", vol.UNDEFINED)
        if default is not vol.UNDEFINED:
            defaults[str(key)] = default()
    return defaults


def _form_input(**overrides: Any) -> dict[str, Any]:
    """Every field the form asks for, the way a real client submits it.

    docs/ai_automation.md §4.3 "Field omissions matter": an omitted
    Optional key is replaced by its (stored-value) default, so a client
    that submits a partial dict re-submits stale state without meaning
    to. Tests that want that trap ask for it explicitly.
    """
    payload: dict[str, Any] = {
        CONF_FMF_CONFIGURED: False,
        CONF_FMF_ENABLED: False,
        CONF_FMF_SENSOR: SENSOR_ENTITY,
        CONF_FMF_GUARD_TEMP_MIN: -15.0,
        CONF_FMF_GUARD_TEMP_MAX: 40.0,
        CONF_FMF_SAFETY_TIMEOUT: 300,
        CONF_HALF_DEGREE_STEPS: True,
        CONF_GLOSSARY_OVERRIDES: "",
        STATUS_DISPLAY: "",
        SCAN_TRIGGER: False,
        INVENTORY_DISPLAY: "",
    }
    payload.update(overrides)
    return payload


def _store_options(hass: HomeAssistant, entry, **options: Any) -> None:
    """Register the entry with hass and seed entry.options on top of the
    fixture's. ``options`` is write-protected on a real ConfigEntry, so
    this goes through the manager like production code does."""
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})


async def _open_options(hass: HomeAssistant, entry) -> dict:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    return result


# ── Form rendering ──────────────────────────────────────────────────────


async def test_options_form_renders_stored_values(hass: HomeAssistant, mock_config_entry) -> None:
    """The form opens on `init` and defaults every field to what is stored."""
    _store_options(
        hass,
        mock_config_entry,
        **{
            CONF_FMF_CONFIGURED: True,
            CONF_FMF_ENABLED: True,
            CONF_FMF_SENSOR: SENSOR_ENTITY,
            CONF_FMF_GUARD_TEMP_MIN: -5.0,
            CONF_FMF_GUARD_TEMP_MAX: 33.0,
            CONF_FMF_SAFETY_TIMEOUT: 900,
            CONF_HALF_DEGREE_STEPS: False,
        },
    )

    result = await _open_options(hass, mock_config_entry)
    defaults = _schema_defaults(result["data_schema"])

    assert defaults[CONF_FMF_CONFIGURED] is True
    assert defaults[CONF_FMF_ENABLED] is True
    assert defaults[CONF_FMF_SENSOR] == SENSOR_ENTITY
    assert defaults[CONF_FMF_GUARD_TEMP_MIN] == -5.0
    assert defaults[CONF_FMF_GUARD_TEMP_MAX] == 33.0
    assert defaults[CONF_FMF_SAFETY_TIMEOUT] == 900
    assert defaults[CONF_HALF_DEGREE_STEPS] is False
    # Every placeholder the strings.json description references must be
    # supplied even on the happy path (gotchas §5), or the form never
    # opens at all.
    assert result["description_placeholders"] == {"override_error": ""}
    assert result["errors"] == {}


async def test_display_buzzer_field_is_cap_gated(hass: HomeAssistant, mock_config_entry) -> None:
    """No coordinator (entry not loaded) → no `screen_display` cap → the
    policy field is omitted from the schema entirely (gotchas §3: a
    single-option SelectSelector would deadlock the form instead)."""
    mock_config_entry.add_to_hass(hass)

    result = await _open_options(hass, mock_config_entry)
    assert CONF_DISPLAY_BUZZER_MODE not in _schema_defaults(result["data_schema"])


@pytest.mark.parametrize(
    ("stored_yaml", "expected_status"),
    [
        # Only whitespace-empty text means "no override configured" and
        # blanks the line. A comments-only block is non-empty text that
        # happens to parse to nothing — it reports "parse ok", not "".
        ("", ""),
        ("   \n\t\n", ""),
        ("# nothing but a comment\n", "parse ok"),
        (VALID_OVERRIDE, "parse ok"),
        (INVALID_OVERRIDE, "parse failed (check log)"),
    ],
)
async def test_parse_status_display_reflects_stored_yaml(
    hass: HomeAssistant,
    mock_config_entry,
    stored_yaml: str,
    expected_status: str,
) -> None:
    """The read-only status line is recomputed from the *stored* YAML on
    every render — including stored YAML that no longer parses (which
    __init__ ignores at runtime rather than failing setup)."""
    _store_options(hass, mock_config_entry, **{CONF_GLOSSARY_OVERRIDES: stored_yaml})

    result = await _open_options(hass, mock_config_entry)
    assert _schema_defaults(result["data_schema"])[STATUS_DISPLAY] == expected_status


async def test_scan_trigger_always_renders_unticked(hass: HomeAssistant, mock_config_entry) -> None:
    """`run_inventory_scan_now` is a trigger, not a setting: it renders
    False even if a previous save somehow put True in options, so a plain
    re-save never re-fires a scan."""
    _store_options(hass, mock_config_entry, **{SCAN_TRIGGER: True})

    result = await _open_options(hass, mock_config_entry)
    assert _schema_defaults(result["data_schema"])[SCAN_TRIGGER] is False


# ── Saving ──────────────────────────────────────────────────────────────


async def test_valid_override_saves(hass: HomeAssistant, mock_config_entry, mock_setup_entry) -> None:
    """A valid override ends the flow and lands verbatim in entry.options."""
    mock_config_entry.add_to_hass(hass)

    result = await _open_options(hass, mock_config_entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _form_input(**{CONF_GLOSSARY_OVERRIDES: VALID_OVERRIDE, CONF_FMF_SAFETY_TIMEOUT: 600}),
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_GLOSSARY_OVERRIDES] == VALID_OVERRIDE
    assert mock_config_entry.options[CONF_FMF_SAFETY_TIMEOUT] == 600


async def test_save_without_a_follow_me_sensor(hass: HomeAssistant, mock_config_entry, mock_setup_entry) -> None:
    """A fresh entry has no `follow_me_function_sensor`. The field then
    renders with no default (EntitySelector rejects "", so a "" default
    would fail every submit), an untouched field is absent from the
    submission, and the rest of the dialog saves. The stored options keep
    their shape: still no sensor key.
    """
    mock_config_entry.add_to_hass(hass)
    assert CONF_FMF_SENSOR not in mock_config_entry.options

    result = await _open_options(hass, mock_config_entry)
    assert CONF_FMF_SENSOR in {str(k) for k in result["data_schema"].schema}
    assert CONF_FMF_SENSOR not in _schema_defaults(result["data_schema"])

    payload = _form_input(**{CONF_FMF_SAFETY_TIMEOUT: 900})
    payload.pop(CONF_FMF_SENSOR)
    result = await hass.config_entries.options.async_configure(result["flow_id"], payload)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_FMF_SAFETY_TIMEOUT] == 900
    assert CONF_FMF_SENSOR not in mock_config_entry.options


async def test_follow_me_sensor_can_be_picked_on_a_fresh_entry(
    hass: HomeAssistant, mock_config_entry, mock_setup_entry
) -> None:
    """Dropping the default must not drop the field: a sensor can still be
    chosen on an entry that had none."""
    mock_config_entry.add_to_hass(hass)

    result = await _open_options(hass, mock_config_entry)
    result = await hass.config_entries.options.async_configure(result["flow_id"], _form_input())
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_FMF_SENSOR] == SENSOR_ENTITY


async def test_invalid_override_reshows_form_with_error(
    hass: HomeAssistant, mock_config_entry, mock_setup_entry
) -> None:
    """Unparseable YAML aborts the save: the form comes back with the
    field error and the parser's message in `override_error`, and nothing
    is written to entry.options."""
    mock_config_entry.add_to_hass(hass)
    stored_before = dict(mock_config_entry.options)

    result = await _open_options(hass, mock_config_entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _form_input(**{CONF_GLOSSARY_OVERRIDES: INVALID_OVERRIDE}),
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert result["errors"] == {CONF_GLOSSARY_OVERRIDES: "invalid_override"}
    override_error = result["description_placeholders"]["override_error"]
    assert "YAML syntax error" in override_error
    assert "line" in override_error
    assert dict(mock_config_entry.options) == stored_before


async def test_schema_rejection_reshows_form_with_pointer(
    hass: HomeAssistant, mock_config_entry, mock_setup_entry
) -> None:
    """YAML that parses but violates the glossary schema is rejected the
    same way, with the path of the offending leaf in the message."""
    mock_config_entry.add_to_hass(hass)

    result = await _open_options(hass, mock_config_entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _form_input(**{CONF_GLOSSARY_OVERRIDES: SCHEMA_VIOLATING_OVERRIDE}),
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_GLOSSARY_OVERRIDES: "invalid_override"}
    override_error = result["description_placeholders"]["override_error"]
    assert "Schema validation failed at" in override_error
    assert "screen_display" in override_error


async def test_form_recovers_after_rejection(hass: HomeAssistant, mock_config_entry, mock_setup_entry) -> None:
    """The re-shown form is live: a corrected submit on the same flow_id
    still saves."""
    mock_config_entry.add_to_hass(hass)

    result = await _open_options(hass, mock_config_entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _form_input(**{CONF_GLOSSARY_OVERRIDES: INVALID_OVERRIDE}),
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _form_input(**{CONF_GLOSSARY_OVERRIDES: VALID_OVERRIDE}),
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_GLOSSARY_OVERRIDES] == VALID_OVERRIDE


# ── Read-only / trigger fields are not settings ─────────────────────────


async def test_readonly_display_fields_are_dropped_server_side(
    hass: HomeAssistant, mock_config_entry, mock_setup_entry
) -> None:
    """Whatever the client submits for the two display fields is popped
    before the merge — neither key ever reaches entry.options."""
    mock_config_entry.add_to_hass(hass)

    result = await _open_options(hass, mock_config_entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _form_input(
            **{
                STATUS_DISPLAY: "parse ok — edited by hand",
                INVENTORY_DISPLAY: "pasted nonsense",
            }
        ),
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert STATUS_DISPLAY not in mock_config_entry.options
    assert INVENTORY_DISPLAY not in mock_config_entry.options


async def test_scan_trigger_fires_service_and_is_not_persisted(
    hass: HomeAssistant, mock_config_entry, mock_setup_entry
) -> None:
    """Ticking the trigger calls blaueis_midea.run_field_inventory with a
    generated label, and the tick itself is dropped rather than stored (a
    persisted True could never be unticked — gotchas §4)."""
    mock_config_entry.add_to_hass(hass)
    calls: list[dict] = []

    async def _record(call) -> None:
        calls.append(dict(call.data))

    hass.services.async_register(DOMAIN, "run_field_inventory", _record)

    result = await _open_options(hass, mock_config_entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _form_input(**{SCAN_TRIGGER: True}),
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(calls) == 1
    assert calls[0]["label"].startswith("configure-")
    assert SCAN_TRIGGER not in mock_config_entry.options


async def test_unticked_scan_trigger_fires_nothing(hass: HomeAssistant, mock_config_entry, mock_setup_entry) -> None:
    """An ordinary save does not queue a scan."""
    mock_config_entry.add_to_hass(hass)
    calls: list[dict] = []

    async def _record(call) -> None:
        calls.append(dict(call.data))

    hass.services.async_register(DOMAIN, "run_field_inventory", _record)

    result = await _open_options(hass, mock_config_entry)
    result = await hass.config_entries.options.async_configure(result["flow_id"], _form_input())
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert calls == []


# ── Field omissions / stale state ───────────────────────────────────────


async def test_options_not_in_the_form_survive_a_save(hass: HomeAssistant, mock_config_entry, mock_setup_entry) -> None:
    """gotchas §1: async_create_entry REPLACES options, so the handler
    merges. A cap-hidden `display_buzzer_mode` policy must survive a save
    made for an unrelated field."""
    _store_options(hass, mock_config_entry, **{CONF_DISPLAY_BUZZER_MODE: "forced_off"})

    result = await _open_options(hass, mock_config_entry)
    assert CONF_DISPLAY_BUZZER_MODE not in _schema_defaults(result["data_schema"])

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _form_input(**{CONF_FMF_CONFIGURED: True})
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_DISPLAY_BUZZER_MODE] == "forced_off"
    assert mock_config_entry.options[CONF_FMF_CONFIGURED] is True


async def test_explicit_empty_clears_a_stored_override(
    hass: HomeAssistant, mock_config_entry, mock_setup_entry
) -> None:
    """gotchas §2: the override field defaults to the stored value, so it
    is clearable only because that default is never a non-empty
    placeholder. Submitting "" must stick, not be substituted back."""
    _store_options(hass, mock_config_entry, **{CONF_GLOSSARY_OVERRIDES: VALID_OVERRIDE})

    result = await _open_options(hass, mock_config_entry)
    assert _schema_defaults(result["data_schema"])[CONF_GLOSSARY_OVERRIDES] == VALID_OVERRIDE

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _form_input(**{CONF_GLOSSARY_OVERRIDES: ""})
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_GLOSSARY_OVERRIDES] == ""


async def test_omitted_field_is_replaced_by_its_rendered_default(
    hass: HomeAssistant, mock_config_entry, mock_setup_entry
) -> None:
    """docs/ai_automation.md §4.3 "Field omissions matter", pinned as a
    contract: an omitted Optional key is NOT left alone — voluptuous
    substitutes the default the form rendered, which is the stored value.

    So a client that drops `glossary_overrides_yaml` from its payload
    re-submits the stored YAML instead of clearing it, and one that drops
    a Follow Me field re-submits the stored setting. Nothing stale gets
    resurrected here — the round-trip is value-preserving — but that only
    holds because the rendered defaults ARE the stored values, which is
    why the documented recipe says to echo back every field from
    `data_schema` rather than rely on it.

    The two fields whose rendered default is deliberately NOT the stored
    value (the trigger, and the displays) are the ones popped server-side,
    so an omission cannot write a stale value through them either.
    """
    _store_options(
        hass,
        mock_config_entry,
        **{
            CONF_GLOSSARY_OVERRIDES: VALID_OVERRIDE,
            CONF_FMF_SAFETY_TIMEOUT: 1200,
        },
    )

    result = await _open_options(hass, mock_config_entry)
    partial = _form_input()
    partial.pop(CONF_GLOSSARY_OVERRIDES)
    partial.pop(CONF_FMF_SAFETY_TIMEOUT)
    partial.pop(STATUS_DISPLAY)
    partial.pop(SCAN_TRIGGER)
    partial.pop(INVENTORY_DISPLAY)

    result = await hass.config_entries.options.async_configure(result["flow_id"], partial)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_GLOSSARY_OVERRIDES] == VALID_OVERRIDE
    assert mock_config_entry.options[CONF_FMF_SAFETY_TIMEOUT] == 1200
    assert SCAN_TRIGGER not in mock_config_entry.options
    assert STATUS_DISPLAY not in mock_config_entry.options
    assert INVENTORY_DISPLAY not in mock_config_entry.options


# ── Reload on a changed override ────────────────────────────────────────


async def test_changed_override_reloads_the_entry(hass: HomeAssistant, mock_config_entry) -> None:
    """Saving a *different* override makes the update listener reload the
    entry — the patched glossary view lives on Device and is rebuilt only
    by a full setup. Needs a genuinely loaded entry: the listener is
    registered by async_setup_entry."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.blaueis_midea.coordinator.BlaueisMideaCoordinator.async_start",
            AsyncMock(),
        ),
        patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        with patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload:
            result = await _open_options(hass, mock_config_entry)
            result = await hass.config_entries.options.async_configure(
                result["flow_id"], _form_input(**{CONF_GLOSSARY_OVERRIDES: VALID_OVERRIDE})
            )
            await hass.async_block_till_done()

            assert result["type"] is FlowResultType.CREATE_ENTRY
            reload.assert_awaited_once_with(mock_config_entry.entry_id)


async def test_unchanged_override_does_not_reload(hass: HomeAssistant, mock_config_entry) -> None:
    """A save that leaves the override text alone reconciles in place —
    reloading on every Configure submit would drop and recreate every
    entity for nothing."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.blaueis_midea.coordinator.BlaueisMideaCoordinator.async_start",
            AsyncMock(),
        ),
        patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        with patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload:
            result = await _open_options(hass, mock_config_entry)
            result = await hass.config_entries.options.async_configure(
                result["flow_id"], _form_input(**{CONF_HALF_DEGREE_STEPS: False})
            )
            await hass.async_block_till_done()

            assert result["type"] is FlowResultType.CREATE_ENTRY
            assert mock_config_entry.options[CONF_HALF_DEGREE_STEPS] is False
            reload.assert_not_awaited()
