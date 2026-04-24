"""Shared fixtures for blaueis-ha-midea tests.

Mocks homeassistant modules so integration code can be imported
without a full HA installation.
"""

import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

# Mock homeassistant modules before any integration code is imported.
# This must happen at module level, before fixtures or test collection
# triggers imports of custom_components.blaueis_midea.*.
_HA_MODULES = [
    "homeassistant",
    "homeassistant.components",
    "homeassistant.components.select",
    "homeassistant.components.switch",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.entity",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.event",
    "homeassistant.helpers.selector",
    "voluptuous",
]
for _mod in _HA_MODULES:
    sys.modules.setdefault(_mod, MagicMock())

# HomeAssistantError must be a real exception class (MagicMock can't be raised)
class _HomeAssistantError(Exception):
    pass

sys.modules["homeassistant.exceptions"].HomeAssistantError = _HomeAssistantError


# Entity base classes must be real `object` subclasses so @property decorators
# on our subclass aren't shadowed by MagicMock attribute auto-creation.
class _RealSelectEntity:
    _attr_options: list = []


class _RealSwitchEntity:
    pass


sys.modules["homeassistant.components.select"].SelectEntity = _RealSelectEntity
sys.modules["homeassistant.components.switch"].SwitchEntity = _RealSwitchEntity


class FakeState:
    """Mimics homeassistant.core.State for sensor readings."""

    def __init__(self, value, unit="°C", last_updated=None):
        self.state = str(value)
        self.attributes = {"unit_of_measurement": unit} if unit else {}
        self.last_updated = last_updated or datetime.now(timezone.utc)


class FakeHass:
    """Minimal hass stub for Follow Me Manager."""

    def __init__(self):
        self._states: dict[str, FakeState] = {}

    @property
    def states(self):
        return self

    def get(self, entity_id):
        return self._states.get(entity_id)

    def set_sensor(self, entity_id, value, unit="°C", last_updated=None):
        self._states[entity_id] = FakeState(value, unit, last_updated)


class FakeDevice:
    """Minimal Device stub."""

    def __init__(self):
        self._shadow = None
        self._fields: dict = {}
        self.set = AsyncMock()

    def set_follow_me_shadow(self, celsius):
        self._shadow = {"celsius": celsius}

    def clear_follow_me_shadow(self):
        self._shadow = None

    @property
    def follow_me_shadow_active(self):
        return self._shadow is not None

    def read(self, field_name):
        return self._fields.get(field_name)


class FakeCoordinator:
    """Minimal coordinator stub."""

    def __init__(self):
        self.device = FakeDevice()
        self._connected = True

    @property
    def connected(self):
        return self._connected


@pytest.fixture
def hass():
    return FakeHass()


@pytest.fixture
def coordinator():
    return FakeCoordinator()


@pytest.fixture
def manager(hass, coordinator):
    from custom_components.blaueis_midea.follow_me import BlauiesFollowMeManager

    return BlauiesFollowMeManager(hass, coordinator)
