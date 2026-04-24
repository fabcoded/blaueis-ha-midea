"""Unit tests for BlaueisMideaDisplayBuzzerModeSelect — the quad-option
display/buzzer selector.

Covers:
- ``current_option`` resolution from stored policy + live state.
- ``async_select_option`` behaviour for each of the four options:
  - ``on``/``off``: stores ``non_enforced`` policy, fires one toggle
    only when state ≠ target.
  - ``forced_on``/``forced_off``: stores matching policy, kicks the
    enforcer.
- Invalid option raises.

All HA mocks come from conftest. Coordinator, entry, and device are
MagicMock/AsyncMock-backed — no real websocket or B5 plumbing.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.blaueis_midea.const import (
    CONF_DISPLAY_BUZZER_MODE,
    DISPLAY_BUZZER_OPTION_FORCED_OFF,
    DISPLAY_BUZZER_OPTION_FORCED_ON,
    DISPLAY_BUZZER_OPTION_OFF,
    DISPLAY_BUZZER_OPTION_ON,
    DISPLAY_BUZZER_POLICY_FORCED_OFF,
    DISPLAY_BUZZER_POLICY_FORCED_ON,
    DISPLAY_BUZZER_POLICY_NON_ENFORCED,
)
from custom_components.blaueis_midea.select import (
    BlaueisMideaDisplayBuzzerModeSelect,
)


def _make_entity(
    *,
    stored_policy: str = DISPLAY_BUZZER_POLICY_NON_ENFORCED,
    observed_display: str | None = None,
    cap_available: bool = True,
):
    """Build an entity with the pipes hooked up to inspectable mocks."""
    hass = MagicMock()
    hass.loop = MagicMock()
    hass.loop.create_task = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()

    entry = MagicMock()
    entry.options = {CONF_DISPLAY_BUZZER_MODE: stored_policy}

    coord = MagicMock()
    coord.host = "127.0.0.1"
    coord.port = 8765
    coord.connected = True
    coord.device = MagicMock()
    coord.device.available_fields = (
        {"screen_display": {}} if cap_available else {}
    )

    def _read(field: str):
        if field in ("screen_display", "screen_display_now"):
            return observed_display
        return None

    coord.device.read.side_effect = _read
    coord.device.toggle_display = AsyncMock()

    entity = BlaueisMideaDisplayBuzzerModeSelect(hass, entry, coord)
    # Skip async_added_to_hass (it builds an enforcer with real asyncio).
    entity.async_write_ha_state = MagicMock()
    return entity, hass, entry, coord


# ── current_option ────────────────────────────────────────────────────


def test_current_option_forced_on_returns_forced_on():
    entity, *_ = _make_entity(stored_policy=DISPLAY_BUZZER_POLICY_FORCED_ON)
    assert entity.current_option == DISPLAY_BUZZER_OPTION_FORCED_ON


def test_current_option_forced_off_returns_forced_off():
    entity, *_ = _make_entity(stored_policy=DISPLAY_BUZZER_POLICY_FORCED_OFF)
    assert entity.current_option == DISPLAY_BUZZER_OPTION_FORCED_OFF


def test_current_option_non_enforced_mirrors_live_on():
    entity, *_ = _make_entity(
        stored_policy=DISPLAY_BUZZER_POLICY_NON_ENFORCED,
        observed_display="on",
    )
    assert entity.current_option == DISPLAY_BUZZER_OPTION_ON


def test_current_option_non_enforced_mirrors_live_off():
    entity, *_ = _make_entity(
        stored_policy=DISPLAY_BUZZER_POLICY_NON_ENFORCED,
        observed_display="off",
    )
    assert entity.current_option == DISPLAY_BUZZER_OPTION_OFF


def test_current_option_non_enforced_unknown_returns_none():
    entity, *_ = _make_entity(
        stored_policy=DISPLAY_BUZZER_POLICY_NON_ENFORCED,
        observed_display=None,
    )
    assert entity.current_option is None


def test_current_option_unknown_policy_falls_back_to_non_enforced():
    """Guards against a malformed config entry: if the stored policy key
    is unknown, treat it as non_enforced so the UI never shows an
    invalid option (and the user can recover by picking something)."""
    entity, *_ = _make_entity(
        stored_policy="garbage_value",
        observed_display="on",
    )
    assert entity.current_option == DISPLAY_BUZZER_OPTION_ON


# ── async_select_option ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_select_on_with_state_off_fires_toggle():
    entity, hass, entry, coord = _make_entity(
        stored_policy=DISPLAY_BUZZER_POLICY_NON_ENFORCED,
        observed_display="off",
    )
    await entity.async_select_option(DISPLAY_BUZZER_OPTION_ON)

    coord.device.toggle_display.assert_awaited_once()
    # Policy didn't change (was non_enforced), no config entry write.
    hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_select_on_with_state_on_is_noop():
    entity, hass, entry, coord = _make_entity(
        stored_policy=DISPLAY_BUZZER_POLICY_NON_ENFORCED,
        observed_display="on",
    )
    await entity.async_select_option(DISPLAY_BUZZER_OPTION_ON)

    coord.device.toggle_display.assert_not_awaited()
    hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_select_off_with_state_on_fires_toggle():
    entity, hass, entry, coord = _make_entity(
        stored_policy=DISPLAY_BUZZER_POLICY_NON_ENFORCED,
        observed_display="on",
    )
    await entity.async_select_option(DISPLAY_BUZZER_OPTION_OFF)

    coord.device.toggle_display.assert_awaited_once()


@pytest.mark.asyncio
async def test_select_off_with_state_off_is_noop():
    entity, hass, entry, coord = _make_entity(
        stored_policy=DISPLAY_BUZZER_POLICY_NON_ENFORCED,
        observed_display="off",
    )
    await entity.async_select_option(DISPLAY_BUZZER_OPTION_OFF)

    coord.device.toggle_display.assert_not_awaited()


@pytest.mark.asyncio
async def test_select_on_when_previously_forced_resets_policy():
    """Picking on/off from forced_* resets policy to non_enforced."""
    entity, hass, entry, coord = _make_entity(
        stored_policy=DISPLAY_BUZZER_POLICY_FORCED_ON,
        observed_display="on",
    )
    await entity.async_select_option(DISPLAY_BUZZER_OPTION_ON)

    hass.config_entries.async_update_entry.assert_called_once()
    call_opts = hass.config_entries.async_update_entry.call_args.kwargs["options"]
    assert call_opts[CONF_DISPLAY_BUZZER_MODE] == DISPLAY_BUZZER_POLICY_NON_ENFORCED
    # State already matches — no toggle.
    coord.device.toggle_display.assert_not_awaited()


@pytest.mark.asyncio
async def test_select_forced_on_writes_policy_no_direct_toggle():
    """Picking forced_* writes the stored policy. The toggle (if any)
    comes from the enforcer's evaluate loop, not the select entity."""
    entity, hass, entry, coord = _make_entity(
        stored_policy=DISPLAY_BUZZER_POLICY_NON_ENFORCED,
        observed_display="off",
    )
    await entity.async_select_option(DISPLAY_BUZZER_OPTION_FORCED_ON)

    hass.config_entries.async_update_entry.assert_called_once()
    call_opts = hass.config_entries.async_update_entry.call_args.kwargs["options"]
    assert call_opts[CONF_DISPLAY_BUZZER_MODE] == DISPLAY_BUZZER_POLICY_FORCED_ON
    # Select entity does NOT send toggle for forced_*; enforcer does.
    coord.device.toggle_display.assert_not_awaited()


@pytest.mark.asyncio
async def test_select_forced_off_writes_policy():
    entity, hass, entry, coord = _make_entity(
        stored_policy=DISPLAY_BUZZER_POLICY_NON_ENFORCED,
        observed_display="on",
    )
    await entity.async_select_option(DISPLAY_BUZZER_OPTION_FORCED_OFF)

    hass.config_entries.async_update_entry.assert_called_once()
    call_opts = hass.config_entries.async_update_entry.call_args.kwargs["options"]
    assert call_opts[CONF_DISPLAY_BUZZER_MODE] == DISPLAY_BUZZER_POLICY_FORCED_OFF
    coord.device.toggle_display.assert_not_awaited()


@pytest.mark.asyncio
async def test_select_same_forced_twice_idempotent():
    """forced_on → forced_on: no config write needed (already stored)."""
    entity, hass, entry, coord = _make_entity(
        stored_policy=DISPLAY_BUZZER_POLICY_FORCED_ON,
        observed_display="on",
    )
    await entity.async_select_option(DISPLAY_BUZZER_OPTION_FORCED_ON)
    hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_select_unknown_option_raises():
    from homeassistant.exceptions import HomeAssistantError

    entity, *_ = _make_entity()
    with pytest.raises(HomeAssistantError):
        await entity.async_select_option("gibberish")


@pytest.mark.asyncio
async def test_select_on_with_unknown_state_does_not_toggle():
    """If observed state is None (first ingress hasn't arrived), we
    can't tell if we need to toggle — skip to avoid spurious chirps."""
    entity, hass, entry, coord = _make_entity(
        stored_policy=DISPLAY_BUZZER_POLICY_NON_ENFORCED,
        observed_display=None,
    )
    await entity.async_select_option(DISPLAY_BUZZER_OPTION_ON)
    coord.device.toggle_display.assert_not_awaited()
