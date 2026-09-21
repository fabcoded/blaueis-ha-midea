"""Integration tests — entity unique_ids and device identifiers keyed on the
config-entry id, and the in-place migration from the ``host:port`` form.

Runs on the real HA config-entry engine via
pytest-homeassistant-custom-component. Only the gateway connection is
patched (``BlaueisMideaCoordinator.async_start``); the platforms load for
real, so the entity and device registries hold exactly what a fresh install
would write. With no gateway, no caps are discovered: the always-present
entities (climate, gateway health sensors) and both devices are what shows up.

The migration tests seed the registries the way an install from before the
change left them (``{host}_{port}_`` unique_ids, ``{host}:{port}_ac`` /
``_gw`` devices) and then run the real setup.
"""

from __future__ import annotations

import sys
from pathlib import Path

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
from homeassistant.helpers import device_registry as dr  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402

import custom_components.blaueis_midea as integration  # noqa: E402
from custom_components.blaueis_midea.const import DOMAIN  # noqa: E402

pytestmark = pytest.mark.asyncio

_START = "custom_components.blaueis_midea.coordinator.BlaueisMideaCoordinator.async_start"
_SWEEP = "custom_components.blaueis_midea._cleanup_orphaned_field_entities"

OLD_PREFIX = "127.0.0.1_8765_"  # {host}_{port}_ of the mock entry
OLD_DEVICE = "127.0.0.1:8765"  # {host}:{port} of the mock entry's devices


async def _setup(hass: HomeAssistant, entry, start=None) -> None:
    if hass.config_entries.async_get_entry(entry.entry_id) is None:
        entry.add_to_hass(hass)
    with patch(_START, start or AsyncMock()):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


def _entities(hass: HomeAssistant, entry) -> list[er.RegistryEntry]:
    return er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)


def _identifiers(hass: HomeAssistant, entry) -> set[str]:
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    return {ident for d in devices for dom, ident in d.identifiers if dom == DOMAIN}


async def test_fresh_install_keys_everything_on_the_entry_id(hass: HomeAssistant, mock_config_entry) -> None:
    await _setup(hass, mock_config_entry)

    entities = _entities(hass, mock_config_entry)
    uids = {e.unique_id for e in entities}
    assert f"{mock_config_entry.entry_id}_climate" in uids
    assert f"{mock_config_entry.entry_id}_gw_cpu_percent" in uids
    assert all(uid.startswith(f"{mock_config_entry.entry_id}_") for uid in uids)
    assert not any("127.0.0.1" in uid for uid in uids)
    assert _identifiers(hass, mock_config_entry) == {
        f"{mock_config_entry.entry_id}_ac",
        f"{mock_config_entry.entry_id}_gw",
    }


# ── host:port → entry-id migration ─────────────────────────────────────


def _new(entry, suffix: str) -> str:
    return f"{entry.entry_id}_{suffix}"


def _seed_device(hass: HomeAssistant, entry, ident: str, name: str) -> dr.DeviceEntry:
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, ident)}, name=name
    )


def _seed_entity(
    hass: HomeAssistant, entry, domain: str, uid: str, object_id: str, device: dr.DeviceEntry | None = None
) -> er.RegistryEntry:
    return er.async_get(hass).async_get_or_create(
        domain,
        DOMAIN,
        uid,
        config_entry=entry,
        device_id=device.id if device else None,
        suggested_object_id=object_id,
    )


def _seed_old_install(hass: HomeAssistant, entry) -> dict:
    """The registries as a pre-migration install left them, with user
    customisations on the entities and devices."""
    entry.add_to_hass(hass)
    reg = er.async_get(hass)
    ac = _seed_device(hass, entry, f"{OLD_DEVICE}_ac", "Midea AC")
    gw = _seed_device(hass, entry, f"{OLD_DEVICE}_gw", "Blaueis Gateway")
    dr.async_get(hass).async_update_device(ac.id, name_by_user="Atelier AC")
    climate = _seed_entity(hass, entry, "climate", f"{OLD_PREFIX}climate", "atelier_ac", ac)
    cpu = _seed_entity(hass, entry, "sensor", f"{OLD_PREFIX}gw_cpu_percent", "gateway_cpu", gw)
    reg.async_update_entity(climate.entity_id, name="My AC")
    reg.async_update_entity(cpu.entity_id, hidden_by=er.RegistryEntryHider.USER)
    reg.async_update_entity_options(cpu.entity_id, "conversation", {"should_expose": False})
    return {"ac": ac, "gw": gw, "climate": climate, "cpu": cpu}


async def test_old_install_migrates_in_place(hass: HomeAssistant, mock_config_entry) -> None:
    seeded = _seed_old_install(hass, mock_config_entry)

    await _setup(hass, mock_config_entry)

    reg = er.async_get(hass)
    climate = reg.async_get(seeded["climate"].entity_id)
    cpu = reg.async_get(seeded["cpu"].entity_id)
    # Same entity_ids — history, dashboards and automations keep working —
    # now carrying the entry-id unique_ids, with the user's settings intact.
    assert climate.unique_id == _new(mock_config_entry, "climate")
    assert cpu.unique_id == _new(mock_config_entry, "gw_cpu_percent")
    assert climate.name == "My AC"
    assert cpu.hidden_by is er.RegistryEntryHider.USER
    assert cpu.options["conversation"] == {"should_expose": False}
    # The platforms found the migrated entities instead of creating a second set.
    uids = [e.unique_id for e in _entities(hass, mock_config_entry)]
    assert uids.count(_new(mock_config_entry, "climate")) == 1
    assert not [uid for uid in uids if uid.startswith(OLD_PREFIX)]
    # Both devices retained (same device ids, user name kept), re-keyed.
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), mock_config_entry.entry_id)
    assert {d.id for d in devices} == {seeded["ac"].id, seeded["gw"].id}
    assert _identifiers(hass, mock_config_entry) == {_new(mock_config_entry, "ac"), _new(mock_config_entry, "gw")}
    assert dr.async_get(hass).async_get(seeded["ac"].id).name_by_user == "Atelier AC"
    assert climate.device_id == seeded["ac"].id
    assert cpu.device_id == seeded["gw"].id


async def test_migration_rerun_is_a_no_op(hass: HomeAssistant, mock_config_entry, caplog) -> None:
    _seed_old_install(hass, mock_config_entry)
    integration._migrate_to_entry_id_prefix(hass, mock_config_entry)
    ents_before = {e.entity_id: e for e in _entities(hass, mock_config_entry)}
    devs_before = dr.async_entries_for_config_entry(dr.async_get(hass), mock_config_entry.entry_id)

    caplog.clear()
    with caplog.at_level(logging.INFO):
        integration._migrate_to_entry_id_prefix(hass, mock_config_entry)

    assert {e.entity_id: e for e in _entities(hass, mock_config_entry)} == ents_before
    assert dr.async_entries_for_config_entry(dr.async_get(hass), mock_config_entry.entry_id) == devs_before
    assert "unique_id migration" not in caplog.text


async def test_migration_on_a_fresh_install_is_a_no_op(hass: HomeAssistant, mock_config_entry, caplog) -> None:
    await _setup(hass, mock_config_entry)
    ents_before = {e.entity_id: e for e in _entities(hass, mock_config_entry)}

    with caplog.at_level(logging.INFO):
        integration._migrate_to_entry_id_prefix(hass, mock_config_entry)

    assert {e.entity_id: e for e in _entities(hass, mock_config_entry)} == ents_before
    assert "unique_id migration" not in caplog.text


async def test_migration_leaves_other_entries_alone(hass: HomeAssistant, mock_config_entry) -> None:
    """Another entry pointed at the same address (so the same old prefix)
    is migrated by its own setup, never by this entry's."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    other = MockConfigEntry(domain=DOMAIN, data=dict(mock_config_entry.data), unique_id="other")
    mock_config_entry.add_to_hass(hass)
    other.add_to_hass(hass)
    foreign = _seed_entity(hass, other, "sensor", f"{OLD_PREFIX}indoor_temperature", "other_temp")

    integration._migrate_to_entry_id_prefix(hass, mock_config_entry)

    assert er.async_get(hass).async_get(foreign.entity_id).unique_id == f"{OLD_PREFIX}indoor_temperature"


async def test_migration_collision_keeps_the_entry_id_holder(hass: HomeAssistant, mock_config_entry, caplog) -> None:
    """Old and new ids both registered — e.g. an older version ran again
    after the migration and re-created its own set: the entity and device
    that already carry the entry-id key win, the stale ones go, the stale
    device's entities move over first, and nothing raises."""
    seeded = _seed_old_install(hass, mock_config_entry)
    new_ac = _seed_device(hass, mock_config_entry, _new(mock_config_entry, "ac"), "Midea AC")
    kept = _seed_entity(hass, mock_config_entry, "climate", _new(mock_config_entry, "climate"), "ac_kept", new_ac)
    # An entity on the stale device that does not collide, so it survives.
    extra = _seed_entity(hass, mock_config_entry, "sensor", f"{OLD_PREFIX}gw_ram_used_mb", "ac_extra", seeded["ac"])

    with caplog.at_level(logging.WARNING):
        integration._migrate_to_entry_id_prefix(hass, mock_config_entry)
        await hass.async_block_till_done()

    reg = er.async_get(hass)
    assert reg.async_get(seeded["climate"].entity_id) is None
    assert reg.async_get(kept.entity_id).unique_id == _new(mock_config_entry, "climate")
    assert dr.async_get(hass).async_get(seeded["ac"].id) is None
    assert reg.async_get(extra.entity_id).device_id == new_ac.id
    assert reg.async_get(extra.entity_id).unique_id == _new(mock_config_entry, "gw_ram_used_mb")
    # The gateway device had no counterpart and was re-keyed in place.
    assert _identifiers(hass, mock_config_entry) == {_new(mock_config_entry, "ac"), _new(mock_config_entry, "gw")}
    assert len([r for r in caplog.records if "stale duplicate" in r.message]) == 2  # one entity, one device


async def test_merge_moves_only_this_entrys_entities(hass: HomeAssistant, mock_config_entry) -> None:
    """The stale device also carries another config entry's entity: only this
    entry's entities move to the kept device, the foreign one stays put."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    seeded = _seed_old_install(hass, mock_config_entry)
    other = MockConfigEntry(domain=DOMAIN, data=dict(mock_config_entry.data), unique_id="other")
    other.add_to_hass(hass)
    _seed_device(hass, other, f"{OLD_DEVICE}_ac", "Midea AC")  # links the stale device to `other` too
    new_ac = _seed_device(hass, mock_config_entry, _new(mock_config_entry, "ac"), "Midea AC")
    own = _seed_entity(hass, mock_config_entry, "sensor", f"{OLD_PREFIX}gw_ram_used_mb", "ac_own", seeded["ac"])
    foreign = _seed_entity(hass, other, "sensor", "other_only", "other_only", seeded["ac"])

    integration._migrate_to_entry_id_prefix(hass, mock_config_entry)

    reg = er.async_get(hass)
    assert reg.async_get(own.entity_id).device_id == new_ac.id
    assert reg.async_get(foreign.entity_id).device_id == seeded["ac"].id
    assert reg.async_get(foreign.entity_id).unique_id == "other_only"


async def test_field_renames_still_apply_after_the_prefix_migration(hass: HomeAssistant, mock_config_entry) -> None:
    """An old-prefix entity with an old field name comes out with both the
    entry-id prefix and the new name (orphan sweep patched out: no caps
    are discovered, so it would remove the field entity)."""
    mock_config_entry.add_to_hass(hass)
    ent = _seed_entity(hass, mock_config_entry, "sensor", f"{OLD_PREFIX}total_power_kwh", "ac_energy")

    with patch(_SWEEP):
        await _setup(hass, mock_config_entry)

    assert er.async_get(hass).async_get(ent.entity_id).unique_id == _new(mock_config_entry, "power_total_kwh")


async def test_orphan_sweep_works_on_migrated_ids(hass: HomeAssistant, mock_config_entry) -> None:
    """The sweep matches the entry-id prefix: migrated entities it must
    remove — a climate-exclusive field's standalone select, a field deleted
    from the glossary — are removed; the migrated climate entity stays."""
    seeded = _seed_old_install(hass, mock_config_entry)
    exclusive = _seed_entity(hass, mock_config_entry, "select", f"{OLD_PREFIX}louver_swing_vertical", "ac_louver")
    deleted = _seed_entity(hass, mock_config_entry, "binary_sensor", f"{OLD_PREFIX}run_status", "ac_run_status")

    await _setup(hass, mock_config_entry)

    reg = er.async_get(hass)
    assert reg.async_get(exclusive.entity_id) is None
    assert reg.async_get(deleted.entity_id) is None
    assert reg.async_get(seeded["climate"].entity_id) is not None


# ── sw_version: the gateway device's, not the AC's ─────────────────────


def _device(hass: HomeAssistant, entry, kind: str) -> dr.DeviceEntry:
    return dr.async_get(hass).async_get_device(identifiers={(DOMAIN, _new(entry, kind))})


async def test_only_the_gateway_device_reports_a_sw_version(hass: HomeAssistant, mock_config_entry) -> None:
    async def _connect(coordinator) -> None:
        # What the real connect learns from the gateway's version reply.
        coordinator.device.gateway_info["version"] = "v0.1.0"

    await _setup(hass, mock_config_entry, start=_connect)

    assert _device(hass, mock_config_entry, "ac").sw_version is None
    assert _device(hass, mock_config_entry, "gw").sw_version == "v0.1.0"


async def test_a_stored_ac_sw_version_is_cleared(hass: HomeAssistant, mock_config_entry) -> None:
    seeded = _seed_old_install(hass, mock_config_entry)
    dr.async_get(hass).async_update_device(seeded["ac"].id, sw_version="v0.0.9")

    await _setup(hass, mock_config_entry)

    assert _device(hass, mock_config_entry, "ac").sw_version is None
    assert _device(hass, mock_config_entry, "gw").sw_version is not None
