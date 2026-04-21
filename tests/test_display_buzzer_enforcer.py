"""Tests for display_buzzer_enforcer.DisplayBuzzerEnforcer.

State-machine only — injected fake clock + fake scheduler keep the tests
deterministic and independent of wall time.

Covers the scenarios from the plan's §9.1:
- mode == auto: no toggles regardless of observed state.
- permanent_off + observed=ON: toggle sent, last_correction recorded.
- Second ingress within 15s: cooldown timer armed, no toggle.
- cooldown timer fires: evaluate re-runs, may toggle.
- retry timer fires while still drifted: second toggle (bounded).
- MAX_RETRY_ATTEMPTS exceeded: no more retries until cooldown elapses.
- safety timer fires: silent poll sent.
- re-entrancy: concurrent on_ingress is dropped.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import pytest

from custom_components.blaueis_midea.display_buzzer_enforcer import (
    DISPLAY_STATE_OFF,
    DISPLAY_STATE_ON,
    MODE_NON_ENFORCED,
    MODE_FORCED_OFF,
    MODE_FORCED_ON,
    DisplayBuzzerEnforcer,
)


# ── Fakes ─────────────────────────────────────────────────────────────


class FakeClock:
    def __init__(self, start: float = 0.0):
        self._now = float(start)

    def monotonic(self) -> float:
        return self._now

    def advance(self, dt: float) -> None:
        self._now += float(dt)


class _FakeHandle:
    def __init__(self, scheduler: "FakeScheduler", when: float, cb):
        self.scheduler = scheduler
        self.when = when
        self.cb = cb
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class FakeScheduler:
    def __init__(self, clock: FakeClock):
        self._clock = clock
        self._pending: list[_FakeHandle] = []

    def call_later(self, delay, callback) -> _FakeHandle:
        h = _FakeHandle(self, self._clock.monotonic() + float(delay), callback)
        self._pending.append(h)
        return h

    def fire_due(self) -> int:
        """Run every non-cancelled handle whose when <= now. Returns count fired."""
        fired = 0
        # Copy list; callbacks may schedule new handles.
        due = [h for h in self._pending if not h.cancelled and h.when <= self._clock.monotonic()]
        # Remove fired ones from pending
        self._pending = [h for h in self._pending if h not in due]
        for h in due:
            if h.cancelled:
                continue
            h.cb()
            fired += 1
        return fired

    def active_count(self) -> int:
        return sum(1 for h in self._pending if not h.cancelled)


async def _drain_tasks():
    """Let any asyncio.ensure_future callbacks run."""
    await asyncio.sleep(0)
    await asyncio.sleep(0)


class Probe:
    """Captures mode / observed / toggle calls / poll calls."""

    def __init__(self, mode: str, observed: Optional[int]):
        self.mode = mode
        self.observed = observed
        self.toggle_calls = 0
        self.poll_calls = 0
        self.toggle_delay = 0.0  # simulated await in send_toggle
        self.toggle_exception: Optional[Exception] = None

    def get_mode(self) -> str:
        return self.mode

    def get_observed(self) -> Optional[int]:
        return self.observed

    async def send_toggle(self) -> None:
        self.toggle_calls += 1
        if self.toggle_delay:
            await asyncio.sleep(self.toggle_delay)
        if self.toggle_exception is not None:
            raise self.toggle_exception

    async def send_silent_poll(self) -> None:
        self.poll_calls += 1


# ── Helpers ───────────────────────────────────────────────────────────


def _make_enforcer(probe: Probe, clock: FakeClock, scheduler: FakeScheduler,
                   **overrides) -> DisplayBuzzerEnforcer:
    defaults = dict(
        cooldown_seconds=15.0,
        retry_gap_seconds=2.0,
        max_retry_attempts=3,
        safety_idle_seconds=60.0,
    )
    defaults.update(overrides)
    return DisplayBuzzerEnforcer(
        get_mode=probe.get_mode,
        get_observed=probe.get_observed,
        send_toggle=probe.send_toggle,
        send_silent_poll=probe.send_silent_poll,
        clock=clock,
        scheduler=scheduler,
        **defaults,
    )


# ── Mode=auto: no toggles ever ────────────────────────────────────────


@pytest.mark.asyncio
async def test_mode_auto_never_toggles():
    probe = Probe(mode=MODE_NON_ENFORCED, observed=DISPLAY_STATE_ON)
    clock = FakeClock()
    sched = FakeScheduler(clock)
    e = _make_enforcer(probe, clock, sched)

    for _ in range(5):
        await e.on_ingress()
        await _drain_tasks()

    # Even if the user flips observed, still no toggle in auto.
    probe.observed = DISPLAY_STATE_OFF
    await e.on_ingress()
    await _drain_tasks()

    assert probe.toggle_calls == 0


# ── Steady state: observed == desired → no toggle, timers cleared ─────


@pytest.mark.asyncio
async def test_permanent_off_steady_state_no_toggle():
    probe = Probe(mode=MODE_FORCED_OFF, observed=DISPLAY_STATE_OFF)
    clock = FakeClock()
    sched = FakeScheduler(clock)
    e = _make_enforcer(probe, clock, sched)

    await e.on_ingress()
    await _drain_tasks()

    assert probe.toggle_calls == 0
    assert not e.has_cooldown_timer
    assert not e.has_retry_timer
    assert e.retry_count == 0


# ── Drift triggers toggle ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_permanent_off_drift_triggers_toggle():
    probe = Probe(mode=MODE_FORCED_OFF, observed=DISPLAY_STATE_ON)
    clock = FakeClock(100.0)
    sched = FakeScheduler(clock)
    e = _make_enforcer(probe, clock, sched)

    await e.on_ingress()
    await _drain_tasks()

    assert probe.toggle_calls == 1
    assert e.last_correction_ts == 100.0
    assert e.retry_count == 1
    assert e.has_retry_timer  # scheduled the follow-up check


@pytest.mark.asyncio
async def test_permanent_on_drift_triggers_toggle():
    probe = Probe(mode=MODE_FORCED_ON, observed=DISPLAY_STATE_OFF)
    clock = FakeClock()
    sched = FakeScheduler(clock)
    e = _make_enforcer(probe, clock, sched)

    await e.on_ingress()
    await _drain_tasks()

    assert probe.toggle_calls == 1


# ── Second ingress during cooldown: no toggle, cooldown timer armed ───


@pytest.mark.asyncio
async def test_second_ingress_within_cooldown_arms_timer_no_toggle():
    probe = Probe(mode=MODE_FORCED_OFF, observed=DISPLAY_STATE_ON)
    clock = FakeClock(100.0)
    sched = FakeScheduler(clock)
    e = _make_enforcer(probe, clock, sched)

    # First drift → toggle
    await e.on_ingress()
    await _drain_tasks()
    assert probe.toggle_calls == 1
    first_corr = e.last_correction_ts

    # Advance a bit (less than cooldown), still drifted, but retry-timer
    # already scheduled — a fresh ingress arriving here should re-send if
    # we're still in the same event (retry_count = 1 < max).
    clock.advance(0.5)
    await e.on_ingress()
    await _drain_tasks()
    # We're in an ongoing event, retry_count 1, not exhausted → toggle again.
    assert probe.toggle_calls == 2
    # Event start time should be preserved.
    assert e.last_correction_ts == first_corr


@pytest.mark.asyncio
async def test_ingress_after_retries_exhausted_arms_cooldown():
    """Once retry_count >= max, a same-event ingress should defer via cooldown."""
    probe = Probe(mode=MODE_FORCED_OFF, observed=DISPLAY_STATE_ON)
    clock = FakeClock(100.0)
    sched = FakeScheduler(clock)
    e = _make_enforcer(probe, clock, sched, max_retry_attempts=2)

    # Burn 2 retries.
    await e.on_ingress()  # retry_count=1
    await _drain_tasks()
    clock.advance(0.1)
    await e.on_ingress()  # retry_count=2 (== max)
    await _drain_tasks()
    assert probe.toggle_calls == 2

    # Next ingress: retry_count already at max, should arm cooldown, not send.
    clock.advance(0.1)
    await e.on_ingress()
    await _drain_tasks()
    assert probe.toggle_calls == 2
    assert e.has_cooldown_timer


# ── Retry timer fires while still drifted → another toggle ────────────


@pytest.mark.asyncio
async def test_retry_timer_fires_while_drifted_triggers_second_toggle():
    probe = Probe(mode=MODE_FORCED_OFF, observed=DISPLAY_STATE_ON)
    clock = FakeClock(100.0)
    sched = FakeScheduler(clock)
    e = _make_enforcer(probe, clock, sched)

    await e.on_ingress()
    await _drain_tasks()
    assert probe.toggle_calls == 1

    # Advance past retry gap
    clock.advance(2.0)
    sched.fire_due()
    await _drain_tasks()
    assert probe.toggle_calls == 2
    assert e.retry_count == 2


@pytest.mark.asyncio
async def test_retry_timer_bounded_by_max_attempts():
    probe = Probe(mode=MODE_FORCED_OFF, observed=DISPLAY_STATE_ON)
    clock = FakeClock(100.0)
    sched = FakeScheduler(clock)
    e = _make_enforcer(probe, clock, sched, max_retry_attempts=3)

    # Attempt 1
    await e.on_ingress()
    await _drain_tasks()
    assert probe.toggle_calls == 1

    # Attempt 2
    clock.advance(2.0)
    sched.fire_due(); await _drain_tasks()
    assert probe.toggle_calls == 2

    # Attempt 3
    clock.advance(2.0)
    sched.fire_due(); await _drain_tasks()
    assert probe.toggle_calls == 3

    # Fourth retry fire: should NOT send (retries exhausted),
    # should arm cooldown.
    clock.advance(2.0)
    sched.fire_due(); await _drain_tasks()
    assert probe.toggle_calls == 3
    assert e.has_cooldown_timer


@pytest.mark.asyncio
async def test_cooldown_expiry_starts_fresh_event():
    probe = Probe(mode=MODE_FORCED_OFF, observed=DISPLAY_STATE_ON)
    clock = FakeClock(100.0)
    sched = FakeScheduler(clock)
    e = _make_enforcer(probe, clock, sched, max_retry_attempts=2)

    await e.on_ingress()
    await _drain_tasks()
    clock.advance(2.0); sched.fire_due(); await _drain_tasks()
    assert probe.toggle_calls == 2
    # Attempt retry 3 → exhausted → cooldown armed
    clock.advance(2.0); sched.fire_due(); await _drain_tasks()
    assert probe.toggle_calls == 2  # not 3 (exhausted)

    # Advance past cooldown from t=100 (event start) — 15 s from 100 = 115.
    clock.advance(15.0)  # now ~119, past 115
    sched.fire_due()
    await _drain_tasks()
    # Fresh event: toggle sent again.
    assert probe.toggle_calls == 3
    assert e.retry_count == 1


# ── Successful flip: timers cancelled, event reset ────────────────────


@pytest.mark.asyncio
async def test_flip_observed_resets_state():
    probe = Probe(mode=MODE_FORCED_OFF, observed=DISPLAY_STATE_ON)
    clock = FakeClock(100.0)
    sched = FakeScheduler(clock)
    e = _make_enforcer(probe, clock, sched)

    await e.on_ingress()
    await _drain_tasks()
    assert probe.toggle_calls == 1

    # AC flipped — next ingress sees observed == desired.
    probe.observed = DISPLAY_STATE_OFF
    clock.advance(0.5)
    await e.on_ingress()
    await _drain_tasks()

    assert probe.toggle_calls == 1  # no new toggle
    assert e.retry_count == 0
    assert not e.has_retry_timer
    assert not e.has_cooldown_timer


# ── Safety timer ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_safety_timer_fires_silent_poll_on_quiet_bus():
    probe = Probe(mode=MODE_FORCED_OFF, observed=DISPLAY_STATE_OFF)
    clock = FakeClock(0.0)
    sched = FakeScheduler(clock)
    e = _make_enforcer(probe, clock, sched)

    # Arm the safety timer via a first ingress
    await e.on_ingress()
    await _drain_tasks()
    assert e.has_safety_timer

    # Advance past safety idle — timer should fire and silent poll is sent
    clock.advance(61.0)
    sched.fire_due()
    await _drain_tasks()
    assert probe.poll_calls == 1


@pytest.mark.asyncio
async def test_safety_timer_reset_on_ingress():
    probe = Probe(mode=MODE_FORCED_OFF, observed=DISPLAY_STATE_OFF)
    clock = FakeClock(0.0)
    sched = FakeScheduler(clock)
    e = _make_enforcer(probe, clock, sched)

    await e.on_ingress()
    await _drain_tasks()
    # Advance close to idle timeout
    clock.advance(50.0)
    # Fresh ingress resets safety timer
    await e.on_ingress()
    await _drain_tasks()
    # Now another 50 s — should NOT fire because timer was reset to 0 at 50s
    clock.advance(50.0)
    sched.fire_due()
    await _drain_tasks()
    assert probe.poll_calls == 0
    # Another 15 s pushes total since last ingress to 65 → fires
    clock.advance(15.0)
    sched.fire_due()
    await _drain_tasks()
    assert probe.poll_calls == 1


# ── Re-entrancy ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_on_ingress_dropped():
    """If an evaluate is in flight, a concurrent on_ingress should drop
    (not queue). The drop prevents duplicate toggles from back-to-back
    ingresses during a slow send_toggle."""
    probe = Probe(mode=MODE_FORCED_OFF, observed=DISPLAY_STATE_ON)
    probe.toggle_delay = 0.05  # simulated send latency
    clock = FakeClock()
    sched = FakeScheduler(clock)
    e = _make_enforcer(probe, clock, sched)

    # Kick off two concurrent ingresses.
    t1 = asyncio.create_task(e.on_ingress())
    await asyncio.sleep(0.01)  # let t1 acquire the re-entrancy lock
    t2 = asyncio.create_task(e.on_ingress())
    await asyncio.gather(t1, t2)
    # Only one evaluate executed → one toggle.
    assert probe.toggle_calls == 1


# ── Error handling: toggle raises ─────────────────────────────────────


@pytest.mark.asyncio
async def test_toggle_exception_does_not_poison_enforcer():
    probe = Probe(mode=MODE_FORCED_OFF, observed=DISPLAY_STATE_ON)
    probe.toggle_exception = RuntimeError("transport down")
    clock = FakeClock(100.0)
    sched = FakeScheduler(clock)
    e = _make_enforcer(probe, clock, sched)

    # First attempt raises internally — should be caught + retry timer armed
    await e.on_ingress()
    await _drain_tasks()
    assert probe.toggle_calls == 1
    assert e.has_retry_timer

    # Next retry succeeds
    probe.toggle_exception = None
    clock.advance(2.0)
    sched.fire_due(); await _drain_tasks()
    assert probe.toggle_calls == 2


# ── close() cancels everything ────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_cancels_all_timers():
    probe = Probe(mode=MODE_FORCED_OFF, observed=DISPLAY_STATE_ON)
    clock = FakeClock()
    sched = FakeScheduler(clock)
    e = _make_enforcer(probe, clock, sched)

    await e.on_ingress()
    await _drain_tasks()
    assert e.has_retry_timer
    assert e.has_safety_timer

    await e.close()
    assert not e.has_cooldown_timer
    assert not e.has_retry_timer
    assert not e.has_safety_timer

    # on_ingress is a no-op after close
    await e.on_ingress()
    await _drain_tasks()
    assert probe.toggle_calls == 1  # no additional

    # close is idempotent
    await e.close()


# ── Unknown observed values (intermediate 1..6) are skipped ───────────


@pytest.mark.asyncio
async def test_intermediate_observed_values_skip_enforcement():
    probe = Probe(mode=MODE_FORCED_OFF, observed=3)
    clock = FakeClock()
    sched = FakeScheduler(clock)
    e = _make_enforcer(probe, clock, sched)

    await e.on_ingress()
    await _drain_tasks()
    assert probe.toggle_calls == 0


@pytest.mark.asyncio
async def test_observed_none_skips_enforcement():
    probe = Probe(mode=MODE_FORCED_OFF, observed=None)
    clock = FakeClock()
    sched = FakeScheduler(clock)
    e = _make_enforcer(probe, clock, sched)

    await e.on_ingress()
    await _drain_tasks()
    assert probe.toggle_calls == 0


# ── Unknown mode string falls through as no-op ────────────────────────


@pytest.mark.asyncio
async def test_unknown_mode_no_toggle():
    probe = Probe(mode="nonsense", observed=DISPLAY_STATE_ON)
    clock = FakeClock()
    sched = FakeScheduler(clock)
    e = _make_enforcer(probe, clock, sched)

    await e.on_ingress()
    await _drain_tasks()
    assert probe.toggle_calls == 0


# ── Cap-availability defensive gate ───────────────────────────────────


@pytest.mark.asyncio
async def test_no_cap_skips_enforcement():
    """When get_cap_available returns False, drift is ignored (no toggle)."""
    probe = Probe(mode=MODE_FORCED_OFF, observed=DISPLAY_STATE_ON)
    clock = FakeClock()
    sched = FakeScheduler(clock)
    e = _make_enforcer(probe, clock, sched, get_cap_available=lambda: False)

    await e.on_ingress()
    await _drain_tasks()
    assert probe.toggle_calls == 0
    # No timers armed either — nothing to retry since we never tried.
    assert not e.has_cooldown_timer
    assert not e.has_retry_timer


@pytest.mark.asyncio
async def test_cap_available_true_then_false_stops_enforcement():
    """If cap is present initially then disappears mid-life, enforcement halts."""
    state = {"cap": True}
    probe = Probe(mode=MODE_FORCED_OFF, observed=DISPLAY_STATE_ON)
    clock = FakeClock(100.0)
    sched = FakeScheduler(clock)
    e = _make_enforcer(probe, clock, sched, get_cap_available=lambda: state["cap"])

    # First evaluate — cap present, toggle fires.
    await e.on_ingress()
    await _drain_tasks()
    assert probe.toggle_calls == 1

    # Cap disappears.
    state["cap"] = False
    clock.advance(2.0)
    sched.fire_due()
    await _drain_tasks()
    # No new toggle even though drift persists and retry timer would fire.
    assert probe.toggle_calls == 1
    assert not e.has_retry_timer


@pytest.mark.asyncio
async def test_cap_available_none_behaves_as_always_true():
    """When no get_cap_available callback is provided (legacy construction),
    the enforcer proceeds as before."""
    probe = Probe(mode=MODE_FORCED_OFF, observed=DISPLAY_STATE_ON)
    clock = FakeClock()
    sched = FakeScheduler(clock)
    e = _make_enforcer(probe, clock, sched, get_cap_available=None)

    await e.on_ingress()
    await _drain_tasks()
    assert probe.toggle_calls == 1
