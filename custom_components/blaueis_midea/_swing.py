"""Per-axis swing / vane-position mapping — pure, HA-free logic.

The climate entity folds oscillation ("swing") and the fixed vane positions
into one enum per axis (``swing_mode`` = vertical, ``swing_horizontal_mode`` =
horizontal). On the hardware the two are mutually exclusive, so we send only
the touched field; the firmware enforces the exclusion and clears the sibling.

These functions take the device's ``available_fields`` (a mapping; only keys
are read) and a ``read(field) -> raw`` callable, so they're trivially testable
without Home Assistant.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .const import POS_LABELS, SWING_AXES, SWING_OFF, SWING_ON, SWING_ON_RAW

_RAWS = (1, 25, 50, 75, 100)


def axis_options(axis: str, available_fields: Mapping[str, Any]) -> list[str]:
    """Option list for an axis, built from its caps:
    ``["off"]`` + ``["swing"]`` if the swing field is available
    + the position labels if the angle field is available.
    """
    f = SWING_AXES[axis]
    opts = [SWING_OFF]
    if f["swing"] in available_fields:
        opts.append(SWING_ON)
    if f["angle"] in available_fields:
        opts += [POS_LABELS[axis][r] for r in _RAWS]
    return opts


def axis_mode(
    axis: str,
    available_fields: Mapping[str, Any],
    read: Callable[[str], Any],
) -> str:
    """Current option for an axis: swing wins, else a fixed position, else off.

    Returns the option string. If the angle reads an off-grid raw (shouldn't
    occur — the firmware rejects those), falls back to ``"off"``.
    """
    f = SWING_AXES[axis]
    if f["swing"] in available_fields and read(f["swing"]) not in (None, 0, False):
        return SWING_ON
    if f["angle"] in available_fields:
        a = read(f["angle"])
        if a in POS_LABELS[axis]:
            return POS_LABELS[axis][a]
    return SWING_OFF


def axis_set_changes(
    axis: str,
    option: str,
    available_fields: Mapping[str, Any],
    read: Callable[[str], Any],
) -> dict[str, int] | None:
    """The SINGLE-field ``{field: raw}`` write for selecting ``option`` on an
    axis, or ``None`` if the option isn't supported by this unit's caps.

    Never returns more than one field — the firmware clears the mutually
    exclusive sibling. ``"off"`` clears whichever mode is currently active.
    """
    f = SWING_AXES[axis]
    label_to_raw = {label: raw for raw, label in POS_LABELS[axis].items()}

    if option == SWING_ON and f["swing"] in available_fields:
        return {f["swing"]: SWING_ON_RAW}
    if option in label_to_raw and f["angle"] in available_fields:
        return {f["angle"]: label_to_raw[option]}
    if option == SWING_OFF:
        # Clear whichever mode is active — still exactly one field.
        if f["swing"] in available_fields and read(f["swing"]) not in (None, 0, False):
            return {f["swing"]: 0}
        if f["angle"] in available_fields:
            return {f["angle"]: 0}
        return {f["swing"]: 0}
    return None
