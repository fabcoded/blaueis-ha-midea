"""Ingress-hook protocol for active-driving features.

Hooks register themselves on the coordinator via
``coord.register_ingress_hook(hook)`` and get their ``on_ingress(coord)``
method called once after every device-state update.

Hooks are fire-and-forget at the coordinator level — they do not return
a value and cannot suppress one another. Each hook is responsible for
its own re-entrancy guard (drop or queue), its own error handling
contract (exceptions bubble to the coordinator which logs and continues),
and its own timer/state management.

Hooks that need to emit outbound frames must go through the device's
public write methods (``device.set``, ``device.toggle_display``, …).
Those methods acquire the per-device ``write_lock`` internally, so
hook-originated writes automatically serialise with user-initiated
writes from HA entities and with writes from other hooks.

See the display-buzzer enforcer (``display_buzzer_enforcer.py``) for
the first consumer. See the architecture doc for the canonical pattern
and the planned Follow Me refactor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .coordinator import BlaueisMideaCoordinator


class IngressHook(Protocol):
    """Subscribes to every device-state update on a coordinator.

    ``on_ingress`` is called with the coordinator after every
    Device-originated state change (any ``rsp_*`` that mutated a field).
    Implementations read state via ``coord.device.read(...)`` and may
    emit frames via ``coord.device.set(...)`` etc.

    Exceptions raised by ``on_ingress`` are caught by the coordinator
    and logged; they do not affect other hooks or the coordinator's
    own state machine.
    """

    async def on_ingress(self, coord: "BlaueisMideaCoordinator") -> None:
        ...
