"""Integration test for the display/buzzer feature wiring.

Scope: prove that a device-originated state change flows through
BlaueisMideaCoordinator.register_ingress_hook → _run_ingress_hooks →
DisplayBuzzerEnforcer.on_ingress → send_toggle callback.

Unit tests cover the enforcer state machine (test_display_buzzer_enforcer.py)
and the coordinator hook surface in isolation (test_ingress_hook.py). This
file covers the JOIN — the interface contract between the coordinator and
the enforcer (Protocol conformance, coord arg pass-through, re-entrancy
guard playing nicely with coordinator-scheduled tasks).

Caught during authoring: enforcer's ``on_ingress(self)`` was missing the
``coord`` positional arg that ``coordinator._run_ingress_hooks`` passes.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from custom_components.blaueis_midea.coordinator import BlaueisMideaCoordinator
from custom_components.blaueis_midea.display_buzzer_enforcer import (
    DISPLAY_STATE_OFF,
    DISPLAY_STATE_ON,
    MODE_FORCED_OFF,
    MODE_FORCED_ON,
    DisplayBuzzerEnforcer,
)


class FakeClock:
    def __init__(self):
        self._t = 0.0

    def monotonic(self) -> float:
        return self._t

    def advance(self, dt: float) -> None:
        self._t += float(dt)


class _FakeHandle:
    def __init__(self, when, cb):
        self.when = when
        self.cb = cb
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class FakeScheduler:
    def __init__(self, clock: FakeClock):
        self._clock = clock
        self._pending: list[_FakeHandle] = []

    def call_later(self, delay, callback):
        h = _FakeHandle(self._clock.monotonic() + float(delay), callback)
        self._pending.append(h)
        return h

    def fire_due(self) -> int:
        fired = 0
        due = [h for h in self._pending
               if not h.cancelled and h.when <= self._clock.monotonic()]
        self._pending = [h for h in self._pending if h not in due]
        for h in due:
            h.cb()
            fired += 1
        return fired


def _make_coord() -> BlaueisMideaCoordinator:
    """Real coordinator with a MagicMock hass. Its loop is the test's
    asyncio loop so `hass.loop.create_task` schedules on this loop."""
    hass = MagicMock()
    hass.loop = asyncio.get_event_loop()
    return BlaueisMideaCoordinator(
        hass=hass, host="127.0.0.1", port=8765, psk="0" * 32,
    )


async def _drain() -> None:
    for _ in range(4):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_state_change_drives_enforcer_toggle_end_to_end():
    """A device state change → coord dispatch → enforcer evaluate → toggle."""
    coord = _make_coord()

    mode = MODE_FORCED_OFF
    observed = DISPLAY_STATE_ON  # drift from desired
    toggle_calls: list[None] = []

    async def send_toggle():
        toggle_calls.append(None)
        # After the correction we "observe" the flip so a second ingress
        # reaches steady state instead of stacking retries.
        nonlocal observed
        observed = DISPLAY_STATE_OFF

    async def send_poll():
        pass

    clock = FakeClock()
    scheduler = FakeScheduler(clock)

    enforcer = DisplayBuzzerEnforcer(
        get_mode=lambda: mode,
        get_observed=lambda: observed,
        send_toggle=send_toggle,
        send_silent_poll=send_poll,
        get_cap_available=lambda: True,
        clock=clock,
        scheduler=scheduler,
    )
    coord.register_ingress_hook(enforcer)

    # Simulate the Device firing a state change (this is what
    # Device._on_device_state_change delivers after parsing rsp_0xC0).
    coord._on_device_state_change("screen_display", "on", None)
    await _drain()

    assert len(toggle_calls) == 1, "toggle should fire on first drift"

    # Retry timer was armed; advance clock + fire; observed now matches,
    # evaluate should see steady state and not re-toggle.
    clock.advance(3.0)
    scheduler.fire_due()
    await _drain()
    assert len(toggle_calls) == 1, "no second toggle — steady state reached"

    await enforcer.close()


@pytest.mark.asyncio
async def test_enforcer_accepts_coord_positional_arg():
    """Regression: the enforcer must accept ``on_ingress(coord)`` — the
    coordinator's ``_run_ingress_hooks`` passes ``self`` positionally.
    Before the fix this raised ``TypeError: on_ingress() takes 1 positional
    argument but 2 were given`` on every state change."""
    coord = _make_coord()
    clock = FakeClock()
    scheduler = FakeScheduler(clock)

    enforcer = DisplayBuzzerEnforcer(
        get_mode=lambda: MODE_FORCED_ON,
        get_observed=lambda: DISPLAY_STATE_ON,  # matches — no toggle
        send_toggle=lambda: None,  # not awaited (evaluate returns before send)
        send_silent_poll=lambda: None,
        clock=clock,
        scheduler=scheduler,
    )
    coord.register_ingress_hook(enforcer)

    # Direct exercise of the coordinator's hook-dispatch path.
    await coord._run_ingress_hooks()
    # If we got here without TypeError, the protocol conformance holds.

    await enforcer.close()


@pytest.mark.asyncio
async def test_cap_loss_midsession_stops_toggles():
    """If the screen_display cap disappears after the enforcer is live,
    further state changes do not produce toggles."""
    coord = _make_coord()

    cap_available = True
    toggle_calls: list[None] = []

    async def send_toggle():
        toggle_calls.append(None)

    async def send_poll():
        pass

    clock = FakeClock()
    scheduler = FakeScheduler(clock)

    enforcer = DisplayBuzzerEnforcer(
        get_mode=lambda: MODE_FORCED_OFF,
        get_observed=lambda: DISPLAY_STATE_ON,
        send_toggle=send_toggle,
        send_silent_poll=send_poll,
        get_cap_available=lambda: cap_available,
        clock=clock,
        scheduler=scheduler,
    )
    coord.register_ingress_hook(enforcer)

    # Cap goes away BEFORE any ingress.
    cap_available = False
    coord._on_device_state_change("screen_display", "on", None)
    await _drain()

    assert toggle_calls == [], "no toggle once cap is gone"

    await enforcer.close()
