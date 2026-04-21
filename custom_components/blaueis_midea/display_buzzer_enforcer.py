"""Display-LED buzzer enforcer — state machine only.

This module has NO Home Assistant imports and NO coordinator imports.
It is the pure state machine for maintaining an AC's display-LED latch
in one of three modes (``auto`` / ``permanent_on`` / ``permanent_off``).
Phase 3 wires it into the coordinator via the ingress-hook surface.

Background: on this SKU the firmware's display-LED latch exposed at
``rsp_0xC0 body[14]`` bits[6:4] globally gates the indoor-unit buzzer
(see ``blaueis-research/internal-tests/findings/07_display_and_buzzer.md``
§4.8, confirmed 2026-04-20). Keeping the latch at ``0x70`` (OFF) silences
``cmd_0xb0`` property writes; keeping it at ``0x00`` (ON) restores the
audible feedback. The enforcer re-issues a ``cmd_0x41 body[1]=0x61``
toggle when observed state drifts from the declared mode.

Design principles:
- Driven by three events: ``on_ingress()`` (every rsp_* update), the
  ``cooldown`` timer, the ``retry`` timer, plus a ``safety`` timer that
  triggers a silent poll when the AC has gone quiet. All three timer
  fires ultimately call ``_evaluate()``.
- Re-entrancy guard per enforcer via an ``asyncio.Lock`` — back-to-back
  ingresses while a previous evaluation is still running are dropped
  (next ingress will re-evaluate).
- Correction events are rate-limited to one toggle-plus-retries per
  ``COOLDOWN_SECONDS``; retries within one event are bounded by
  ``MAX_RETRY_ATTEMPTS`` with ``RETRY_GAP_SECONDS`` between attempts.
- Clock and scheduler are injected — tests supply deterministic fakes.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable, Optional, Protocol

# ── Public constants ───────────────────────────────────────────────────

# Stored-policy values (see ``const.DISPLAY_BUZZER_POLICIES``). Mirrored
# here so this module has no HA-specific imports — the enforcer is pure
# state-machine and takes the policy via the ``get_mode`` callback.
MODE_NON_ENFORCED = "non_enforced"
MODE_FORCED_ON = "forced_on"
MODE_FORCED_OFF = "forced_off"

ALL_MODES = (MODE_NON_ENFORCED, MODE_FORCED_ON, MODE_FORCED_OFF)

# Wire-value contract: the ``observed`` callback returns the 3-bit value
# extracted from ``rsp_0xC0 body[14]`` bits[6:4]. Only values observed in
# the 2026-04-19 capture are ``0`` (display ON) and ``7`` (display OFF).
# Intermediate values 1..6 are treated as unknown — we do not enforce against
# them.
DISPLAY_STATE_ON = 0
DISPLAY_STATE_OFF = 7

# Default timing — overridable per-instance for tests or SKU tuning.
DEFAULT_COOLDOWN_SECONDS = 15.0
DEFAULT_RETRY_GAP_SECONDS = 2.0
DEFAULT_MAX_RETRY_ATTEMPTS = 3
DEFAULT_SAFETY_IDLE_SECONDS = 60.0


# ── Injected-dependency protocols ──────────────────────────────────────


class Cancellable(Protocol):
    def cancel(self) -> None: ...


class Scheduler(Protocol):
    """Schedules a callback to run after ``delay`` seconds.

    Implementations must call the callback on the asyncio event loop
    (so the enforcer's coroutine-dispatch logic is single-threaded)."""

    def call_later(
        self, delay: float, callback: Callable[[], None]
    ) -> Cancellable: ...


class Clock(Protocol):
    def monotonic(self) -> float: ...


# ── Default implementations (production) ───────────────────────────────


class _RealClock:
    def monotonic(self) -> float:
        return time.monotonic()


class _AsyncioScheduler:
    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        self._loop = loop

    def _loop_or_running(self) -> asyncio.AbstractEventLoop:
        return self._loop or asyncio.get_running_loop()

    def call_later(
        self, delay: float, callback: Callable[[], None]
    ) -> Cancellable:
        return self._loop_or_running().call_later(delay, callback)


# ── Enforcer ───────────────────────────────────────────────────────────


class DisplayBuzzerEnforcer:
    """State machine for the display-buzzer mode enforcement.

    Parameters (all callable; enforcer does not hold references to
    HA entities or the coordinator directly):

    get_mode:
        Returns one of ``MODE_NON_ENFORCED`` / ``MODE_FORCED_ON`` /
        ``MODE_FORCED_OFF``. Queried on every evaluate.
    get_observed:
        Returns the 3-bit display-state value (0..7) or ``None`` if the
        value has not been observed yet. Values outside {0, 7} are
        treated as "unknown" and skip enforcement.
    send_toggle:
        Async callable that emits one ``cmd_0x41 body[1]=0x61`` relative
        toggle. Returns when the frame has been queued to the gateway
        (not necessarily when the AC has processed it).
    send_silent_poll:
        Async callable that emits one ``cmd_0x41 body[1]=0x81`` silent
        status poll. Used by the safety timer to force an ingress when
        the AC has gone quiet.
    """

    def __init__(
        self,
        *,
        get_mode: Callable[[], str],
        get_observed: Callable[[], Optional[int]],
        send_toggle: Callable[[], Awaitable[None]],
        send_silent_poll: Callable[[], Awaitable[None]],
        get_cap_available: Optional[Callable[[], bool]] = None,
        clock: Optional[Clock] = None,
        scheduler: Optional[Scheduler] = None,
        logger: Optional[logging.Logger] = None,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        retry_gap_seconds: float = DEFAULT_RETRY_GAP_SECONDS,
        max_retry_attempts: int = DEFAULT_MAX_RETRY_ATTEMPTS,
        safety_idle_seconds: float = DEFAULT_SAFETY_IDLE_SECONDS,
    ):
        self._get_mode = get_mode
        self._get_observed = get_observed
        self._send_toggle = send_toggle
        self._send_silent_poll = send_silent_poll
        # Optional defensive runtime check: if the cap disappears from
        # `available_fields` after the enforcer was created, bail out of
        # evaluate. Usually the entity-level gate at setup time prevents
        # the enforcer from ever being instantiated without the cap, but
        # this callback protects against late B5 re-advertisements or
        # glossary changes.
        self._get_cap_available = get_cap_available
        self._clock: Clock = clock or _RealClock()
        self._scheduler: Scheduler = scheduler or _AsyncioScheduler()
        self._log = logger or logging.getLogger(__name__)

        self._cooldown_seconds = float(cooldown_seconds)
        self._retry_gap_seconds = float(retry_gap_seconds)
        self._max_retry_attempts = int(max_retry_attempts)
        self._safety_idle_seconds = float(safety_idle_seconds)

        # State
        self._last_correction_ts: Optional[float] = None
        self._retry_count: int = 0
        self._cooldown_handle: Optional[Cancellable] = None
        self._retry_handle: Optional[Cancellable] = None
        self._safety_handle: Optional[Cancellable] = None

        # Re-entrancy guard — drops concurrent evaluates rather than queuing.
        self._evaluating = asyncio.Lock()

        self._closed = False
        # Latches the "cap went away" WARNING to once per transition, so a
        # misbehaving firmware that keeps toggling the cap doesn't flood
        # the logs. Reset when the cap returns.
        self._cap_loss_logged = False

    # ── Public surface ────────────────────────────────────────────────

    async def on_ingress(self, coord: object = None) -> None:
        """Called by the ingress-hook wrapper on every rsp_* update.

        Drops the call if a previous evaluate is still running.

        ``coord`` is accepted for ``IngressHook`` protocol conformance
        (the coordinator passes itself as arg) but is unused — the
        enforcer is pure state driven through callbacks.
        """
        del coord
        if self._closed:
            return
        if self._evaluating.locked():
            return
        async with self._evaluating:
            self._reset_safety_timer()
            await self._evaluate()

    async def close(self) -> None:
        """Cancel all armed timers. Safe to call repeatedly."""
        self._closed = True
        self._cancel(self._cooldown_handle)
        self._cooldown_handle = None
        self._cancel(self._retry_handle)
        self._retry_handle = None
        self._cancel(self._safety_handle)
        self._safety_handle = None

    # Introspection hooks for tests — NOT part of the runtime contract.
    @property
    def retry_count(self) -> int:
        return self._retry_count

    @property
    def last_correction_ts(self) -> Optional[float]:
        return self._last_correction_ts

    @property
    def has_cooldown_timer(self) -> bool:
        return self._cooldown_handle is not None

    @property
    def has_retry_timer(self) -> bool:
        return self._retry_handle is not None

    @property
    def has_safety_timer(self) -> bool:
        return self._safety_handle is not None

    # ── Core evaluate ─────────────────────────────────────────────────

    async def _evaluate(self) -> None:
        if self._closed:
            return

        # Defensive cap-availability check. When the entity-level setup
        # gate did its job, this callback always returns True; but if
        # the cap disappears from `available_fields` (late B5, glossary
        # change, etc.) we stop enforcing rather than spamming toggles
        # against a feature the firmware no longer advertises.
        if self._get_cap_available is not None and not self._get_cap_available():
            if not self._cap_loss_logged:
                self._log.warning(
                    "screen_display cap no longer advertised — "
                    "stopping display/buzzer enforcement"
                )
                self._cap_loss_logged = True
            self._cancel(self._cooldown_handle)
            self._cooldown_handle = None
            self._cancel(self._retry_handle)
            self._retry_handle = None
            self._retry_count = 0
            return
        if self._cap_loss_logged:
            self._log.info("screen_display cap advertised again — resuming enforcement")
            self._cap_loss_logged = False

        mode = self._get_mode()
        if mode == MODE_NON_ENFORCED:
            # No enforcement. Cancel any pending correction timers (safety
            # timer is independent and keeps running so we still notice the
            # AC going silent).
            self._cancel(self._cooldown_handle)
            self._cooldown_handle = None
            self._cancel(self._retry_handle)
            self._retry_handle = None
            self._retry_count = 0
            return

        if mode not in (MODE_FORCED_ON, MODE_FORCED_OFF):
            self._log.warning("unknown mode %r — treating as non-enforced", mode)
            return

        observed = self._get_observed()
        if observed is None:
            return  # state not known yet
        if observed not in (DISPLAY_STATE_ON, DISPLAY_STATE_OFF):
            # Intermediate 1..6 — never seen on our SKU. Be conservative:
            # don't enforce against an unknown state.
            self._log.debug(
                "observed display-state %d is intermediate — skipping", observed
            )
            return

        desired = (
            DISPLAY_STATE_ON if mode == MODE_FORCED_ON else DISPLAY_STATE_OFF
        )

        if observed == desired:
            # Reached steady state — clear the correction timers and event.
            self._cancel(self._cooldown_handle)
            self._cooldown_handle = None
            self._cancel(self._retry_handle)
            self._retry_handle = None
            self._retry_count = 0
            return

        # ── Drift ─────────────────────────────────────────────────────
        now = self._clock.monotonic()
        last = self._last_correction_ts

        # Entry-point guard: is this the start of a new correction event?
        if last is None or (now - last) >= self._cooldown_seconds:
            # New event — reset retry count. Last is either None or far
            # enough in the past that cooldown has elapsed.
            self._retry_count = 0

        # If we've exhausted retries in the current event, wait the rest
        # of the cooldown.
        if self._retry_count >= self._max_retry_attempts:
            if last is not None:
                wait = (last + self._cooldown_seconds) - now
                if wait > 0:
                    self._arm_cooldown_timer(wait)
                    return
            # cooldown expired mid-evaluate — fall through to a fresh event
            self._retry_count = 0

        # Still in cooldown window without having exhausted retries means
        # we're inside an ongoing event (retry in progress). That path is
        # normal — proceed to send.
        #
        # Out of cooldown with retry_count 0 means first attempt of a new
        # event — also proceed.
        if self._retry_count == 0 and last is not None and (now - last) < self._cooldown_seconds:
            # First attempt of an event, still inside cooldown window
            # (last event was the most recent correction). Defer.
            wait = (last + self._cooldown_seconds) - now
            self._arm_cooldown_timer(wait)
            return

        # Emit toggle.
        if self._retry_count == 0:
            self._last_correction_ts = now  # mark event start
        self._retry_count += 1
        try:
            await self._send_toggle()
        except Exception:
            self._log.exception("send_toggle failed")
        finally:
            # Even on send failure, arm the retry timer — maybe transport
            # recovers, or the next ingress will have updated info.
            self._arm_retry_timer()

    # ── Timers ────────────────────────────────────────────────────────

    def _arm_cooldown_timer(self, delay: float) -> None:
        if self._closed:
            return
        self._cancel(self._cooldown_handle)
        self._cooldown_handle = self._scheduler.call_later(
            max(0.0, delay), self._on_cooldown_timer
        )

    def _arm_retry_timer(self) -> None:
        if self._closed:
            return
        self._cancel(self._retry_handle)
        self._retry_handle = self._scheduler.call_later(
            self._retry_gap_seconds, self._on_retry_timer
        )

    def _reset_safety_timer(self) -> None:
        if self._closed:
            return
        self._cancel(self._safety_handle)
        self._safety_handle = self._scheduler.call_later(
            self._safety_idle_seconds, self._on_safety_timer
        )

    def _on_cooldown_timer(self) -> None:
        self._cooldown_handle = None
        asyncio.ensure_future(self._fire_evaluate())

    def _on_retry_timer(self) -> None:
        self._retry_handle = None
        asyncio.ensure_future(self._fire_evaluate())

    def _on_safety_timer(self) -> None:
        self._safety_handle = None
        asyncio.ensure_future(self._fire_safety_poll())

    async def _fire_evaluate(self) -> None:
        # Timer-driven evaluate — share the same re-entrancy guard as
        # ingress-driven, but do NOT reset the safety timer (the safety
        # timer is only re-armed on actual ingress events).
        if self._closed:
            return
        if self._evaluating.locked():
            return
        async with self._evaluating:
            await self._evaluate()

    async def _fire_safety_poll(self) -> None:
        """Safety timer fired — AC has been silent for safety_idle_seconds.
        Send a silent status poll to provoke an ingress. No evaluate until
        the ingress arrives and re-triggers the loop."""
        if self._closed:
            return
        try:
            await self._send_silent_poll()
        except Exception:
            self._log.exception("send_silent_poll failed")
        # Re-arm the safety timer even if the poll failed — next firing
        # will try again. A successful poll should produce an ingress
        # which will re-arm via _reset_safety_timer().
        if not self._closed:
            self._safety_handle = self._scheduler.call_later(
                self._safety_idle_seconds, self._on_safety_timer
            )

    @staticmethod
    def _cancel(handle: Optional[Cancellable]) -> None:
        if handle is not None:
            try:
                handle.cancel()
            except Exception:
                pass
