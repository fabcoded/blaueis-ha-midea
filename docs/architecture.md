# Architecture notes — active-driving features

This doc captures two orthogonal mechanisms the integration uses when a
feature needs to **actively drive** the AC (send frames in response to
observed state), rather than just reactively react to user actions.

Today there is one consumer of this architecture: the Display & Buzzer
mode enforcer (see `display_buzzer_mode.md`). The Follow Me manager
uses an older pattern that could be refactored onto this one later.

## 1. `IngressHook` — state-update subscription

**File:** `custom_components/blaueis_midea/_ingress_hook.py`

A `Protocol` that a feature implements to receive a callback after every
AC state update (any `rsp_*` that mutated a field in the status
database).

```python
class IngressHook(Protocol):
    async def on_ingress(self, coord: BlaueisMideaCoordinator) -> None:
        ...
```

Hooks are registered on the coordinator:

```python
coord.register_ingress_hook(hook)     # idempotent
coord.unregister_ingress_hook(hook)   # safe if not registered
```

Typical lifecycle: an HA entity (the "owner") creates the hook instance
in `async_added_to_hass`, registers it, and unregisters + closes it in
`async_will_remove_from_hass`.

### Dispatch model

After every `Device._on_device_state_change`:

```python
asyncio.create_task(self._run_ingress_hooks())

async def _run_ingress_hooks(self):
    hooks = list(self._ingress_hooks)   # snapshot
    await asyncio.gather(
        *(h.on_ingress(self) for h in hooks),
        return_exceptions=True,
    )
    # log any exceptions; don't let one hook affect another
```

Key properties:

- **Concurrent**: all hooks run simultaneously via `asyncio.gather`. A slow
  hook can't block a fast one.
- **Isolated errors**: exceptions from one hook are caught + logged via
  `return_exceptions=True`. Others still run.
- **Snapshot at start**: hooks that register/unregister during dispatch
  don't affect the current batch — new hooks fire on the *next* ingress.
- **Fire-and-forget at the coordinator level**: no return value, no way
  for one hook to suppress others.
- **Per-coordinator**: each device has its own hook list. HA can host
  multiple AC entries, each with independent hooks.

### Re-entrancy is the hook's problem

Because every ingress fires every hook, rapid back-to-back ingresses
could re-enter a hook while its previous call is still running. The
coordinator does not guard against this — each hook owns its own
re-entrancy strategy. The Display-Buzzer enforcer uses drop-on-busy:

```python
async def on_ingress(self, coord):
    if self._evaluating.locked():
        return                    # previous evaluate still running; drop
    async with self._evaluating:
        await self._evaluate()
```

Alternative strategies (queue, coalesce) are valid; pick per the hook's
semantics.

## 2. `Device.write_lock` — integration-level write serialiser

**File:** `blaueis-libmidea/.../client/device.py`

An `asyncio.Lock` owned by the `Device`, acquired by every outbound-write
method on the device. This guarantees at most one
integration-originated frame is "in flight" per device at any time,
even when multiple concurrent callers (HA entities, Follow Me, ingress
hooks) want to emit.

```python
class Device:
    def __init__(self, ...):
        ...
        self._write_lock = asyncio.Lock()

    @property
    def write_lock(self) -> asyncio.Lock:
        return self._write_lock

    async def set(self, **changes):
        async with self._write_lock:
            return await self._db.command(changes, send_fn=...)

    async def toggle_display(self):
        async with self._write_lock:
            await self._client.send_frame(...)

    async def send_silent_poll(self):
        async with self._write_lock:
            await self._client.send_frame(...)
```

### Why we need it *in addition to* the gateway's TX queue

The gateway (`blaueis-gateway/uart_protocol.py`) already has an
`asyncio.Queue(maxsize=16)` that serialises wire bytes. But that queue
is fed by **every** connected client (HA + the scanner + anything else
with a WS session). Our writes may interleave with other clients' at
the gateway.

The per-device `write_lock` sits *above* the gateway queue and gives us
**integration-level** ordering:

| Race | Without `write_lock` | With `write_lock` |
|---|---|---|
| Hook toggle while user louver-set | Order nondeterministic | Hook completes, then user's set fires |
| Two hooks write simultaneously | Gateway byte-order, integration-side nondeterministic | FIFO by asyncio wait order |
| Hook retry during user write | Retry jumps ahead | Retry waits for user |

Python 3.10+ `asyncio.Lock` is FIFO on wait order. No priority scheme;
first-await-first-served.

### Scope: per-call serialisation only

The lock guards **single** outbound method calls. It is intentionally
non-reentrant. Do **not** hold `device.write_lock` across multiple
method calls:

```python
# WRONG — deadlocks. The inner .set() tries to re-acquire.
async with coord.write_lock:
    await coord.device.toggle_display()
    await coord.device.set(wind_swing_ud_angle=50)
```

If a future feature needs to bundle a multi-frame sequence atomically
against other writers (e.g. toggle-off → writes → toggle-on for a
silent-louver sequence), add a dedicated method on `Device` that takes
the lock once internally and emits all frames under it. Don't expose the
lock for external bundling — that's a footgun waiting to deadlock the
event loop.

## 3. Example — Display & Buzzer enforcer

The enforcer is the first consumer of the `IngressHook` protocol. Brief
summary (full detail in `display_buzzer_mode.md`):

- `select.display_buzzer_mode` entity owns the enforcer's lifecycle.
- On entity add, the enforcer registers as an ingress hook.
- `on_ingress` → `_evaluate` reads mode + observed display state, and
  optionally sends a toggle.
- Toggle sends go through `coord.device.toggle_display()` which takes
  `device.write_lock` internally.
- Timers (`cooldown`, `retry`, `safety`) live inside the enforcer and
  fire on `asyncio.get_running_loop().call_later`.
- Drop-on-busy re-entrancy guard (`self._evaluating: asyncio.Lock`).
- Capability gate applied both at setup time (select entity only
  created if `screen_display` in `available_fields`) and inside
  `_evaluate` (defensive `get_cap_available` callback).

## 4. Known non-issues

- **"Two hooks fighting for the same field"** — the coordinator doesn't
  detect this. Two hooks both writing the same field would simply serialise
  their writes, but semantically they'd stomp on each other. Solve this
  at the feature-design level (don't write two enforcers that target
  the same field), not in the hook framework.
- **"Hook raises repeatedly"** — logged every time via
  `_LOGGER.exception`, no rate limit. If a hook is buggy, the logs will
  show it. Don't add backoff here; fix the hook.
- **"Ingress fires while HA is shutting down"** — the owning entity
  unregisters in `async_will_remove_from_hass`, and the enforcer's
  `close()` cancels its timers. Any in-flight `on_ingress` task
  completes normally; subsequent ingresses find an empty hook list.

## 5. Candidates for this pattern (not yet refactored)

- **Follow Me** (`follow_me.py`) actively drives `follow_me=True/False`
  based on an external sensor and the AC's readback. It uses its own
  timer loop instead of `on_ingress`. Refactoring onto `IngressHook`
  would remove the custom keepalive timer (30 s tick) in favour of
  reacting to each `rsp_0xC0` — tighter closed-loop and less duplicated
  timer infrastructure. Not in scope of the current work.
