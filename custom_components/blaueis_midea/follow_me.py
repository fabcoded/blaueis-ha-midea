"""Follow Me Function — state machine that couples an HA temperature sensor
to the AC's Follow Me / I Feel function.

Two-layer architecture:

  Layer 1 — DATA PLANE (Device poll loop, every ~15s):
    Shadow register armed → _build_query_frame returns Follow Me frame
    (body[1]=0x81 body[4]=0x01 body[5]=T*2+50).
    Shadow cleared → standard status query (body[4]=0x03).

  Layer 2 — CONTROL PLANE (this manager, event-driven):
    0x40 SET follow_me=True  on activation, recovery, AC disagrees (30s tick).
    0x40 SET follow_me=False on deactivation, sensor lost/stale/OOR (30s tick).

State machine: IDLE → ENGAGED ↔ TEMP-DISABLED → DISENGAGING → IDLE.

Naming:
  follow_me           — the AC's protocol bit (binary_sensor, read-only)
  Follow Me Function  — this state machine (switch, manager, config)
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from homeassistant.helpers.event import async_track_time_interval

from .const import CONF_FMF_GUARD_TEMP_MAX, CONF_FMF_GUARD_TEMP_MIN, CONF_FMF_SAFETY_TIMEOUT

if TYPE_CHECKING:
    from .coordinator import BlaueisMideaCoordinator

_LOGGER = logging.getLogger(__name__)


class BlauiesFollowMeManager:
    """Arms the Device's Follow Me shadow register and sends hello/end
    frames reactively based on AC C0 readback."""

    KEEPALIVE_INTERVAL = 30

    def __init__(self, hass, coordinator: BlaueisMideaCoordinator) -> None:
        self.hass = hass
        self._coord = coordinator
        self._active = False
        self._stopping = False
        self._temp_disabled = False
        self._cancel_timer = None
        self._source_entity_id: str | None = None
        self._guard_temp_min: float = -15.0
        self._guard_temp_max: float = 40.0
        self._safety_timeout: int = 300

    @property
    def active(self) -> bool:
        return self._active

    @property
    def source_entity_id(self) -> str | None:
        return self._source_entity_id

    def configure_guards(self, options: dict) -> None:
        self._guard_temp_min = options.get(CONF_FMF_GUARD_TEMP_MIN, -15.0)
        self._guard_temp_max = options.get(CONF_FMF_GUARD_TEMP_MAX, 40.0)
        self._safety_timeout = options.get(CONF_FMF_SAFETY_TIMEOUT, 300)

    async def async_start(self, source_entity_id: str) -> None:
        if self._active or self._stopping:
            await self.async_stop()

        self._source_entity_id = source_entity_id
        self._active = True
        self._stopping = False
        self._temp_disabled = False

        temp = self._read_source_temp()
        if temp is not None:
            self._coord.device.set_follow_me_shadow(temp)

        await self._coord.device.set(follow_me=True)

        self._cancel_timer = async_track_time_interval(
            self.hass, self._tick, timedelta(seconds=self.KEEPALIVE_INTERVAL)
        )
        _LOGGER.info(
            "Follow Me Function started, source=%s",
            source_entity_id,
        )

    async def async_stop(self) -> None:
        was_active = self._active
        self._active = False

        self._coord.device.clear_follow_me_shadow()

        try:
            await self._coord.device.set(follow_me=False)
        except Exception:
            _LOGGER.debug("follow_me=false send failed on stop")

        if was_active and self._cancel_timer:
            self._stopping = True
            _LOGGER.info("Follow Me Function disengaging")
        else:
            self._kill_timer()
            self._stopping = False
            _LOGGER.info("Follow Me Function stopped")

    async def _tick(self, _now=None) -> None:
        if self._stopping:
            await self._tick_stopping()
            return
        if not self._active or not self._coord.connected:
            return

        temp = self._read_source_temp()
        if temp is None:
            if not self._temp_disabled:
                self._temp_disabled = True
                _LOGGER.error(
                    "Follow Me Function: sensor lost/out-of-range/stale, temporarily disabling"
                )
                self._coord.device.clear_follow_me_shadow()
                try:
                    await self._coord.device.set(follow_me=False)
                except Exception:
                    pass
            return

        if self._temp_disabled:
            self._temp_disabled = False
            _LOGGER.info("Follow Me Function: sensor recovered, re-enabling")

        self._coord.device.set_follow_me_shadow(temp)

        ac_fm = self._coord.device.read("follow_me")
        if not ac_fm:
            _LOGGER.error("AC does not confirm follow_me, re-sending hello")
            try:
                await self._coord.device.set(follow_me=True)
            except Exception:
                _LOGGER.debug("follow_me hello resend failed")

    async def _tick_stopping(self) -> None:
        if not self._coord.connected:
            return

        ac_fm = self._coord.device.read("follow_me")
        if not ac_fm:
            _LOGGER.info("Follow Me Function confirmed off by AC")
            self._kill_timer()
            self._stopping = False
            return

        _LOGGER.error("AC still reports follow_me after end, re-sending")
        try:
            await self._coord.device.set(follow_me=False)
        except Exception:
            _LOGGER.debug("follow_me=false resend failed")

    def _kill_timer(self) -> None:
        if self._cancel_timer:
            self._cancel_timer()
            self._cancel_timer = None

    def _read_source_temp(self) -> float | None:
        """Read source sensor, convert to Celsius, check guards, clamp to [0, 50]."""
        if not self._source_entity_id:
            return None
        state = self.hass.states.get(self._source_entity_id)
        if not state or state.state in ("unavailable", "unknown", "None"):
            return None

        age = (datetime.now(timezone.utc) - state.last_updated).total_seconds()
        if age > self._safety_timeout:
            _LOGGER.debug("Source sensor stale (%.0fs > %ds)", age, self._safety_timeout)
            return None

        try:
            temp = float(state.state)
        except (ValueError, TypeError):
            _LOGGER.debug(
                "Source sensor %s non-numeric: %s",
                self._source_entity_id, state.state,
            )
            return None
        if math.isnan(temp) or math.isinf(temp):
            return None

        unit = state.attributes.get("unit_of_measurement", "")
        if unit in ("\u00b0F", "F"):
            temp = (temp - 32) * 5 / 9

        if temp < self._guard_temp_min or temp > self._guard_temp_max:
            _LOGGER.debug(
                "Source temp %.1f\u00b0C outside guards [%.0f, %.0f]",
                temp, self._guard_temp_min, self._guard_temp_max,
            )
            return None

        temp = max(0.0, min(50.0, temp))
        return temp
