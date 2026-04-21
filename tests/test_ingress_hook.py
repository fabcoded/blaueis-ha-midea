"""Tests for the ingress-hook surface on BlaueisMideaCoordinator.

Covers:
- register / unregister — idempotent, safe-if-missing.
- _run_ingress_hooks fires every registered hook.
- Hooks run concurrently (not sequentially).
- Exception in one hook does not suppress others.
- Empty hook list is a no-op.
- _on_device_state_change schedules the hook dispatch.
- coord.write_lock proxies to device.write_lock.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from custom_components.blaueis_midea.coordinator import BlaueisMideaCoordinator


# ── Test harness ──────────────────────────────────────────────────────


def _make_coord() -> BlaueisMideaCoordinator:
    """Construct a coordinator with a hass whose loop is the test's
    running asyncio loop. The Device inside is real but never started —
    its WebSocket remains None so any accidental network call raises."""
    hass = MagicMock()
    hass.loop = asyncio.get_event_loop()
    coord = BlaueisMideaCoordinator(
        hass=hass,
        host="127.0.0.1",
        port=8765,
        psk="0" * 32,
    )
    return coord


class RecordingHook:
    """Ingress hook that records how often on_ingress is called and can
    optionally sleep or raise."""

    def __init__(self, name: str = "h", sleep: float = 0.0, raise_exc: Exception | None = None):
        self.name = name
        self.calls = 0
        self.sleep = sleep
        self.raise_exc = raise_exc
        self.call_timestamps: list[float] = []

    async def on_ingress(self, coord: BlaueisMideaCoordinator) -> None:
        self.calls += 1
        self.call_timestamps.append(asyncio.get_event_loop().time())
        if self.sleep:
            await asyncio.sleep(self.sleep)
        if self.raise_exc is not None:
            raise self.raise_exc


# ── Registration semantics ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_adds_hook():
    coord = _make_coord()
    h = RecordingHook()
    coord.register_ingress_hook(h)
    assert h in coord._ingress_hooks


@pytest.mark.asyncio
async def test_register_is_idempotent():
    coord = _make_coord()
    h = RecordingHook()
    coord.register_ingress_hook(h)
    coord.register_ingress_hook(h)
    coord.register_ingress_hook(h)
    assert coord._ingress_hooks.count(h) == 1


@pytest.mark.asyncio
async def test_unregister_removes_hook():
    coord = _make_coord()
    h = RecordingHook()
    coord.register_ingress_hook(h)
    coord.unregister_ingress_hook(h)
    assert h not in coord._ingress_hooks


@pytest.mark.asyncio
async def test_unregister_safe_if_not_registered():
    coord = _make_coord()
    h = RecordingHook()
    # Should not raise
    coord.unregister_ingress_hook(h)


# ── Dispatch semantics ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_ingress_hooks_fires_all():
    coord = _make_coord()
    h1 = RecordingHook(name="h1")
    h2 = RecordingHook(name="h2")
    h3 = RecordingHook(name="h3")
    coord.register_ingress_hook(h1)
    coord.register_ingress_hook(h2)
    coord.register_ingress_hook(h3)

    await coord._run_ingress_hooks()

    assert h1.calls == 1
    assert h2.calls == 1
    assert h3.calls == 1


@pytest.mark.asyncio
async def test_run_ingress_hooks_empty_noop():
    coord = _make_coord()
    # No registered hooks — should complete immediately, no errors.
    await coord._run_ingress_hooks()


@pytest.mark.asyncio
async def test_hooks_run_concurrently_not_sequentially():
    """Three hooks each sleeping 100 ms should complete in ~100 ms when
    run concurrently, not ~300 ms."""
    coord = _make_coord()
    for i in range(3):
        coord.register_ingress_hook(RecordingHook(name=f"h{i}", sleep=0.1))

    loop = asyncio.get_event_loop()
    t0 = loop.time()
    await coord._run_ingress_hooks()
    elapsed = loop.time() - t0
    assert elapsed < 0.25, f"expected concurrent (<250ms), got {elapsed*1000:.0f}ms"


@pytest.mark.asyncio
async def test_exception_in_one_hook_isolated_from_others():
    coord = _make_coord()
    h_good = RecordingHook(name="good")
    h_bad = RecordingHook(name="bad", raise_exc=RuntimeError("oops"))
    h_also_good = RecordingHook(name="also_good")

    coord.register_ingress_hook(h_good)
    coord.register_ingress_hook(h_bad)
    coord.register_ingress_hook(h_also_good)

    # Should not raise at the coordinator level
    await coord._run_ingress_hooks()

    assert h_good.calls == 1
    assert h_bad.calls == 1      # called — it's the hook's internal failure
    assert h_also_good.calls == 1


@pytest.mark.asyncio
async def test_register_during_dispatch_does_not_affect_current_batch():
    """The snapshot-of-hooks-at-start semantic: a hook that registers a
    new hook during dispatch does not cause that new hook to fire in the
    same batch."""
    coord = _make_coord()
    fired_late: list[bool] = []
    late_hook = RecordingHook(name="late")

    class SelfRegisteringHook:
        def __init__(self):
            self.calls = 0

        async def on_ingress(self, coord):
            self.calls += 1
            coord.register_ingress_hook(late_hook)
            fired_late.append(late_hook in coord._ingress_hooks)

    self_reg = SelfRegisteringHook()
    coord.register_ingress_hook(self_reg)

    await coord._run_ingress_hooks()
    # self_reg fired once; late_hook only fires on the NEXT dispatch.
    assert self_reg.calls == 1
    assert late_hook.calls == 0

    await coord._run_ingress_hooks()
    assert self_reg.calls == 2
    assert late_hook.calls == 1


# ── Trigger from _on_device_state_change ──────────────────────────────


@pytest.mark.asyncio
async def test_state_change_schedules_hook_dispatch():
    coord = _make_coord()
    h = RecordingHook()
    coord.register_ingress_hook(h)

    # Fire the device-state-change callback directly.
    coord._on_device_state_change("power", True, False)
    # It schedules a task — give it a cycle to run.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert h.calls == 1


@pytest.mark.asyncio
async def test_state_change_with_no_hooks_does_not_crash():
    coord = _make_coord()
    # No hooks registered.
    coord._on_device_state_change("power", True, False)
    # No task scheduled, no crash.
    await asyncio.sleep(0)


# ── write_lock proxy ──────────────────────────────────────────────────


def test_write_lock_proxies_to_device():
    coord = _make_coord()
    assert coord.write_lock is coord.device.write_lock
