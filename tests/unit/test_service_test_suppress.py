"""``blaueis_midea.test_suppress`` service handler.

Verifies the registration is idempotent, the handler fans out across
loaded config entries, and clamping happens at the libmidea layer
(the service forwards duration verbatim — caps live in ``Device``).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def hass_with_entries():
    """Fake hass with two loaded entries (each runtime_data is a coord)."""
    hass = MagicMock()
    coord1 = SimpleNamespace(
        device=SimpleNamespace(set_test_suppression=MagicMock(return_value=60.0))
    )
    coord2 = SimpleNamespace(
        device=SimpleNamespace(set_test_suppression=MagicMock(return_value=60.0))
    )
    entry1 = SimpleNamespace(title="Atelier", runtime_data=coord1)
    entry2 = SimpleNamespace(title="Studio", runtime_data=coord2)
    hass.config_entries.async_entries.return_value = [entry1, entry2]
    hass.services.has_service.return_value = False
    return hass, coord1, coord2


@pytest.mark.asyncio
async def test_register_then_handler_fans_out(hass_with_entries):
    from custom_components.blaueis_midea._test_suppress import (
        async_setup_test_suppress,
    )

    hass, coord1, coord2 = hass_with_entries
    await async_setup_test_suppress(hass)

    # Service was registered exactly once.
    hass.services.async_register.assert_called_once()
    args, kwargs = hass.services.async_register.call_args
    name, handler = args[1], args[2]
    assert name == "test_suppress"

    # Invoke the registered handler with a fake ServiceCall.
    call = SimpleNamespace(data={"duration": 60.0})
    await handler(call)

    coord1.device.set_test_suppression.assert_called_once_with(60.0)
    coord2.device.set_test_suppression.assert_called_once_with(60.0)


@pytest.mark.asyncio
async def test_register_idempotent_when_already_registered(hass_with_entries):
    from custom_components.blaueis_midea._test_suppress import (
        async_setup_test_suppress,
    )

    hass, _, _ = hass_with_entries
    hass.services.has_service.return_value = True
    await async_setup_test_suppress(hass)
    hass.services.async_register.assert_not_called()


@pytest.mark.asyncio
async def test_handler_no_entries_warns_and_returns():
    from custom_components.blaueis_midea._test_suppress import (
        async_setup_test_suppress,
    )

    hass = MagicMock()
    hass.services.has_service.return_value = False
    hass.config_entries.async_entries.return_value = []
    await async_setup_test_suppress(hass)
    handler = hass.services.async_register.call_args[0][2]
    # Should not raise, just no-op via warning log.
    await handler(SimpleNamespace(data={"duration": 30.0}))


@pytest.mark.asyncio
async def test_handler_skips_entries_without_runtime_data():
    from custom_components.blaueis_midea._test_suppress import (
        async_setup_test_suppress,
    )

    hass = MagicMock()
    hass.services.has_service.return_value = False
    entry_loaded = SimpleNamespace(
        title="Atelier",
        runtime_data=SimpleNamespace(
            device=SimpleNamespace(set_test_suppression=MagicMock(return_value=60.0))
        ),
    )
    entry_unloaded = SimpleNamespace(title="Stale", runtime_data=None)
    hass.config_entries.async_entries.return_value = [
        entry_loaded,
        entry_unloaded,
    ]

    await async_setup_test_suppress(hass)
    handler = hass.services.async_register.call_args[0][2]
    await handler(SimpleNamespace(data={"duration": 30.0}))

    entry_loaded.runtime_data.device.set_test_suppression.assert_called_once_with(30.0)
    # The unloaded entry has runtime_data=None — handler must skip
    # without raising.
