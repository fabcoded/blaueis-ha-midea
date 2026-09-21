"""Integration tests — ``async_setup_entry``, ``async_unload_entry`` and the
field-rename unique_id migration.

Runs on the real HA config-entry engine via
pytest-homeassistant-custom-component. The gateway connection is patched at
``BlaueisMideaCoordinator.async_start`` (the websocket connect) and the
platform forwards are patched out, so setup exercises everything the
integration itself does around them: PSK stretch, migrations, debug ring,
coordinator construction, Follow Me auto-start, field-inventory hydration,
update listener. The migration is also driven directly against the real
entity registry.
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

import logging  # noqa: E402
from unittest.mock import AsyncMock, patch  # noqa: E402

import pytest  # noqa: E402
from homeassistant.config_entries import ConfigEntryState  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402

import custom_components.blaueis_midea as integration  # noqa: E402
from custom_components.blaueis_midea.const import (  # noqa: E402
    CONF_FMF_CONFIGURED,
    CONF_FMF_ENABLED,
    CONF_FMF_SENSOR,
    CONF_GLOSSARY_OVERRIDES,
    DOMAIN,
)
from custom_components.blaueis_midea.coordinator import BlaueisMideaCoordinator  # noqa: E402

pytestmark = pytest.mark.asyncio

_START = "custom_components.blaueis_midea.coordinator.BlaueisMideaCoordinator.async_start"
_STOP = "custom_components.blaueis_midea.coordinator.BlaueisMideaCoordinator.async_stop"
_DEVICE_STOP = "blaueis.client.device.Device.stop"
_FM_START = "custom_components.blaueis_midea.follow_me.BlauiesFollowMeManager.async_start"
_SWEEP = "custom_components.blaueis_midea._cleanup_orphaned_field_entities"

PREFIX = "127.0.0.1_8765_"
SENSOR_ENTITY = "sensor.living_room_temperature"


def _ring_handlers(logger: str = "blaueis_midea") -> list[logging.Handler]:
    from blaueis.core.debug_ring import DebugRing

    return [h for h in logging.getLogger(logger).handlers if isinstance(h, DebugRing)]


async def _setup(hass: HomeAssistant, entry, **options) -> AsyncMock:
    """Register ``entry`` (with ``options`` merged in) and set it up against a
    reachable gateway. Returns the patched platform-forward mock."""
    if hass.config_entries.async_get_entry(entry.entry_id) is None:
        entry.add_to_hass(hass)
    if options:
        hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    forward = AsyncMock()
    with patch(_START, AsyncMock()), patch.object(hass.config_entries, "async_forward_entry_setups", forward):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return forward


@pytest.fixture(autouse=True)
def _detach_debug_rings():
    """The debug ring hangs off process-global loggers, and other test
    modules leave theirs behind (see the leak xfail below) — detach every
    ring before and after each test so handler counts start at zero."""

    def _detach() -> None:
        for name in integration._RING_LOGGERS:
            for h in _ring_handlers(name):
                logging.getLogger(name).removeHandler(h)

    _detach()
    yield
    _detach()


# ── async_setup_entry ──────────────────────────────────────────────────


async def test_setup_loads_entry_with_a_coordinator(hass: HomeAssistant, mock_config_entry) -> None:
    forward = await _setup(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    coord = mock_config_entry.runtime_data
    assert isinstance(coord, BlaueisMideaCoordinator)
    assert (coord.host, coord.port) == ("127.0.0.1", 8765)
    # The PSK reaches the coordinator already stretched (bytes), not as text.
    assert isinstance(coord._psk, bytes)
    assert coord._applied_override_yaml == ""
    forward.assert_awaited_once_with(mock_config_entry, integration.PLATFORMS)
    assert len(_ring_handlers()) == 1


async def test_setup_snapshots_the_applied_override(hass: HomeAssistant, mock_config_entry) -> None:
    yaml_text = "fields:\n  control:\n    screen_display:\n      feature_available: excluded\n"
    await _setup(hass, mock_config_entry, **{CONF_GLOSSARY_OVERRIDES: yaml_text})

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.runtime_data._applied_override_yaml == yaml_text


async def test_setup_survives_an_unparseable_stored_override(hass: HomeAssistant, mock_config_entry) -> None:
    """A hand-edited, broken override is logged and ignored — the entry
    still loads rather than failing setup."""
    await _setup(hass, mock_config_entry, **{CONF_GLOSSARY_OVERRIDES: "fields: {control: : }\n"})

    assert mock_config_entry.state is ConfigEntryState.LOADED


async def test_setup_unreachable_gateway_retries_and_stops_the_device(hass: HomeAssistant, mock_config_entry) -> None:
    mock_config_entry.add_to_hass(hass)
    device_stop = AsyncMock()
    with patch(_START, AsyncMock(side_effect=OSError("refused"))), patch(_DEVICE_STOP, device_stop):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    device_stop.assert_awaited()


@pytest.mark.xfail(
    strict=True,
    reason="Bug: a failed setup never detaches its debug ring, every retry stacks another (up to 5 MB each).",
)
async def test_failed_setup_does_not_leak_a_debug_ring(hass: HomeAssistant, mock_config_entry) -> None:
    """The ring is installed before the gateway connect and only removed by
    async_unload_entry, which HA never calls for a setup that raised."""
    mock_config_entry.add_to_hass(hass)
    with patch(_START, AsyncMock(side_effect=OSError("refused"))):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        for _ in range(2):
            await hass.config_entries.async_reload(mock_config_entry.entry_id)
            await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    assert _ring_handlers() == []


async def test_setup_autostarts_follow_me_when_configured_and_enabled(hass: HomeAssistant, mock_config_entry) -> None:
    fm_start = AsyncMock()
    with patch(_FM_START, fm_start):
        await _setup(
            hass,
            mock_config_entry,
            **{CONF_FMF_CONFIGURED: True, CONF_FMF_ENABLED: True, CONF_FMF_SENSOR: SENSOR_ENTITY},
        )

    assert mock_config_entry.state is ConfigEntryState.LOADED
    fm_start.assert_awaited_once_with(SENSOR_ENTITY)


@pytest.mark.parametrize(
    "options",
    [
        {CONF_FMF_CONFIGURED: True, CONF_FMF_ENABLED: False, CONF_FMF_SENSOR: SENSOR_ENTITY},
        {CONF_FMF_CONFIGURED: True, CONF_FMF_ENABLED: True},  # no sensor
        # Enabled without Configured is normalised away before auto-start.
        {CONF_FMF_CONFIGURED: False, CONF_FMF_ENABLED: True, CONF_FMF_SENSOR: SENSOR_ENTITY},
    ],
)
async def test_setup_does_not_autostart_follow_me_otherwise(hass: HomeAssistant, mock_config_entry, options) -> None:
    fm_start = AsyncMock()
    with patch(_FM_START, fm_start):
        await _setup(hass, mock_config_entry, **options)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    fm_start.assert_not_awaited()


async def test_follow_me_autostart_failure_does_not_fail_setup(hass: HomeAssistant, mock_config_entry) -> None:
    with patch(_FM_START, AsyncMock(side_effect=RuntimeError("sensor gone"))):
        await _setup(
            hass,
            mock_config_entry,
            **{CONF_FMF_CONFIGURED: True, CONF_FMF_ENABLED: True, CONF_FMF_SENSOR: SENSOR_ENTITY},
        )

    assert mock_config_entry.state is ConfigEntryState.LOADED


# ── async_unload_entry ─────────────────────────────────────────────────


async def test_unload_stops_the_coordinator_and_releases_state(hass: HomeAssistant, mock_config_entry) -> None:
    await _setup(hass, mock_config_entry)
    assert len(_ring_handlers()) == 1

    stop = AsyncMock()
    with (
        patch.object(hass.config_entries, "async_unload_platforms", AsyncMock(return_value=True)) as unload_platforms,
        patch(_STOP, stop),
        patch("blaueis.core.codec.invalidate_glossary_cache") as invalidate,
    ):
        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    unload_platforms.assert_awaited_once_with(mock_config_entry, integration.PLATFORMS)
    stop.assert_awaited_once()
    invalidate.assert_called_once()
    assert _ring_handlers() == []


async def test_unload_keeps_running_when_platforms_refuse(hass: HomeAssistant, mock_config_entry) -> None:
    await _setup(hass, mock_config_entry)

    stop = AsyncMock()
    with (
        patch.object(hass.config_entries, "async_unload_platforms", AsyncMock(return_value=False)),
        patch(_STOP, stop),
    ):
        assert not await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED  # HA keeps it loaded on a False unload
    stop.assert_not_awaited()
    assert len(_ring_handlers()) == 1


async def test_setup_unload_setup_cycle(hass: HomeAssistant, mock_config_entry) -> None:
    """A reload is unload + setup; the second setup must start from clean
    state (one ring, a fresh coordinator)."""
    await _setup(hass, mock_config_entry)
    first = mock_config_entry.runtime_data

    with (
        patch(_START, AsyncMock()),
        patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()),
        patch.object(hass.config_entries, "async_unload_platforms", AsyncMock(return_value=True)),
    ):
        assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.runtime_data is not first
    assert len(_ring_handlers()) == 1


# ── Field-rename unique_id migration ───────────────────────────────────


def _register(hass: HomeAssistant, entry, domain: str, suffix: str, object_id: str) -> er.RegistryEntry:
    return er.async_get(hass).async_get_or_create(
        domain,
        DOMAIN,
        f"{PREFIX}{suffix}",
        config_entry=entry,
        suggested_object_id=object_id,
    )


def _uid_of(hass: HomeAssistant, entity_id: str) -> str:
    return er.async_get(hass).async_get(entity_id).unique_id


@pytest.mark.parametrize(("old", "new"), sorted(integration._FIELD_RENAMES.items()))
async def test_every_rename_rewrites_the_unique_id_in_place(
    hass: HomeAssistant, mock_config_entry, old: str, new: str
) -> None:
    mock_config_entry.add_to_hass(hass)
    ent = _register(hass, mock_config_entry, "sensor", old, f"ac_{old}")

    integration._migrate_renamed_unique_ids(hass, mock_config_entry)

    # Same entity_id (history, dashboards, automations keep working).
    assert _uid_of(hass, ent.entity_id) == f"{PREFIX}{new}"


async def test_migration_leaves_other_entries_and_current_names_alone(hass: HomeAssistant, mock_config_entry) -> None:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    other = MockConfigEntry(domain=DOMAIN, data=dict(mock_config_entry.data), unique_id="other")
    mock_config_entry.add_to_hass(hass)
    other.add_to_hass(hass)
    foreign = _register(hass, other, "sensor", "ptc_heater", "other_ptc_heater")
    current = _register(hass, mock_config_entry, "sensor", "power_total_kwh", "ac_power_total_kwh")
    unrelated = _register(hass, mock_config_entry, "sensor", "indoor_temperature", "ac_indoor")

    integration._migrate_renamed_unique_ids(hass, mock_config_entry)

    assert _uid_of(hass, foreign.entity_id) == f"{PREFIX}ptc_heater"
    assert _uid_of(hass, current.entity_id) == f"{PREFIX}power_total_kwh"
    assert _uid_of(hass, unrelated.entity_id) == f"{PREFIX}indoor_temperature"


async def test_migration_is_idempotent_and_does_not_chain(hass: HomeAssistant, mock_config_entry) -> None:
    """Runs on every setup. A second run changes nothing — in particular the
    breezeless → breeze_away rename must not be carried further."""
    mock_config_entry.add_to_hass(hass)
    ent = _register(hass, mock_config_entry, "switch", "breezeless", "ac_breeze")

    integration._migrate_renamed_unique_ids(hass, mock_config_entry)
    integration._migrate_renamed_unique_ids(hass, mock_config_entry)

    assert _uid_of(hass, ent.entity_id) == f"{PREFIX}breeze_away"


async def test_rename_targets_are_not_themselves_renamed() -> None:
    """Guard the no-chaining property for the whole table: no rename's
    target is another rename's source."""
    assert not set(integration._FIELD_RENAMES.values()) & set(integration._FIELD_RENAMES)


@pytest.mark.xfail(
    strict=True,
    reason="Bug: when the renamed unique_id already exists, async_update_entity raises and setup fails.",
)
async def test_migration_tolerates_an_existing_target(hass: HomeAssistant, mock_config_entry) -> None:
    """Both the old and the new unique_id registered (e.g. the new-name
    entity was created before the rename entry landed): the migration must
    not crash setup. Leaving the old entity for the orphan sweep is fine."""
    mock_config_entry.add_to_hass(hass)
    _register(hass, mock_config_entry, "sensor", "total_power_kwh", "ac_old_energy")
    _register(hass, mock_config_entry, "sensor", "power_total_kwh", "ac_new_energy")

    integration._migrate_renamed_unique_ids(hass, mock_config_entry)


async def test_setup_runs_the_migration(hass: HomeAssistant, mock_config_entry) -> None:
    """The migration is wired into async_setup_entry (the orphan sweep that
    follows it is patched out: with no caps discovered it would remove the
    migrated entity, which is correct but not what this test is about)."""
    mock_config_entry.add_to_hass(hass)
    ent = _register(hass, mock_config_entry, "sensor", "realtime_power_kw", "ac_power")

    with patch(_SWEEP):
        await _setup(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert _uid_of(hass, ent.entity_id) == f"{PREFIX}power_realtime_kw"
