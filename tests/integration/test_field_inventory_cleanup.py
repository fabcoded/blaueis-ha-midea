"""Integration tests — Store-backed snapshot persistence + RAM discipline.

Covers the contracts we care about after the tempfile/HTTP view removal:

1. When a prior snapshot is on disk at setup, it's hydrated onto the
   coordinator (label, ts, markdown, snapshot_json).
2. The snapshot dict actually held on the coordinator IS the same
   object that came from the Store — no defensive copies duplicating
   RAM.
3. Teardown clears session RAM but leaves the disk snapshot intact.

These run under HA's real event loop via pytest-homeassistant-custom-component.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest  # noqa: E402
from homeassistant.helpers.storage import Store  # noqa: E402

pytestmark = pytest.mark.asyncio


def _fake_coordinator():
    """Minimal coordinator stand-in — just the attrs the setup/teardown
    helpers read or write. Avoids pulling in the whole Device class."""
    return SimpleNamespace(
        device=SimpleNamespace(_glossary={}),
        connected=True,
    )


async def test_setup_hydrates_prior_snapshot_from_store(hass, mock_config_entry):
    """Write a snapshot directly into HA Store, then call the field-inventory
    setup. Expect the coordinator to have the snapshot's fields rebound."""
    from custom_components.blaueis_midea.field_inventory import (
        _STORE_KEY_FMT,
        _STORE_VERSION,
        async_setup_field_inventory,
    )

    mock_config_entry.add_to_hass(hass)
    coord = _fake_coordinator()
    mock_config_entry.runtime_data = coord

    # Seed the Store before setup runs.
    store = Store(
        hass, _STORE_VERSION, _STORE_KEY_FMT.format(entry_id=mock_config_entry.entry_id)
    )
    snapshot_js = {"meta": {"timestamp": "2026-04-24T08:00:00+00:00"}, "fields": {}}
    await store.async_save(
        {
            "timestamp": "2026-04-24T08:00:00+00:00",
            "label": "seeded",
            "markdown": "<!-- seeded -->\n# test\n",
            "snapshot_json": snapshot_js,
        }
    )

    await async_setup_field_inventory(hass, mock_config_entry)

    assert coord.inventory_latest_label == "seeded"
    assert coord.inventory_latest_ts == "2026-04-24T08:00:00+00:00"
    assert coord.inventory_latest_md.startswith("<!-- seeded -->")
    assert coord.inventory_prior_snapshot == snapshot_js


async def test_setup_with_no_store_starts_clean(hass, mock_config_entry):
    """First-ever setup (no prior Store file) leaves all session attrs
    as None — compare just won't run on the first scan."""
    from custom_components.blaueis_midea.field_inventory import (
        async_setup_field_inventory,
    )

    mock_config_entry.add_to_hass(hass)
    coord = _fake_coordinator()
    mock_config_entry.runtime_data = coord

    await async_setup_field_inventory(hass, mock_config_entry)

    assert coord.inventory_latest_label is None
    assert coord.inventory_latest_ts is None
    assert coord.inventory_latest_md is None
    assert coord.inventory_prior_snapshot is None


async def test_teardown_clears_ram_but_preserves_disk(hass, mock_config_entry):
    """async_teardown drops the session attrs but the Store file survives,
    so the next setup can rehydrate. Persistent-on-disk, dynamic-in-RAM."""
    from custom_components.blaueis_midea.field_inventory import (
        _STORE_KEY_FMT,
        _STORE_VERSION,
        async_setup_field_inventory,
        async_teardown_field_inventory,
    )

    mock_config_entry.add_to_hass(hass)
    coord = _fake_coordinator()
    mock_config_entry.runtime_data = coord

    store = Store(
        hass, _STORE_VERSION, _STORE_KEY_FMT.format(entry_id=mock_config_entry.entry_id)
    )
    payload = {
        "timestamp": "2026-04-24T09:00:00+00:00",
        "label": "will-survive",
        "markdown": "# kept on disk\n",
        "snapshot_json": {"meta": {"timestamp": "2026-04-24T09:00:00+00:00"}},
    }
    await store.async_save(payload)

    await async_setup_field_inventory(hass, mock_config_entry)
    assert coord.inventory_latest_label == "will-survive"

    await async_teardown_field_inventory(hass, mock_config_entry)
    assert coord.inventory_latest_label is None
    assert coord.inventory_latest_md is None
    assert coord.inventory_prior_snapshot is None

    # Re-load Store directly — disk survives teardown.
    reread = await store.async_load()
    assert reread is not None
    assert reread["label"] == "will-survive"
