"""Check device.set() results and raise HomeAssistantError for user-facing rejections."""

from __future__ import annotations

import logging
import re

from homeassistant.exceptions import HomeAssistantError

from .const import CLIMATE_PRESET_FIELDS, MODE_MIDEA_TO_HA

_LOGGER = logging.getLogger(__name__)


def check_set_result(result: dict | None, *, primary_fields: set[str]) -> None:
    """Raise HomeAssistantError if any *primary* field was rejected by the mode gate.

    Non-primary rejections (mutex expansion side-effects) are logged at DEBUG.
    Preflight blocks (stale sibling data) get a generic "try again" message.
    Gracefully no-ops on the old Device return shape (no ``rejected`` key).
    """
    if not result:
        return

    rejected: dict = result.get("rejected", {})
    results: dict = result.get("results", {})

    primary_rejections = {f: r for f, r in rejected.items() if f in primary_fields}
    secondary_rejections = {f: r for f, r in rejected.items() if f not in primary_fields}

    if secondary_rejections:
        _LOGGER.debug("Non-primary fields rejected by mode gate: %s", secondary_rejections)

    if primary_rejections:
        labels = [_humanize_field(f) for f in primary_rejections]
        reasons = [_humanize_rejection(r) for r in primary_rejections.values()]
        unique_reasons = list(dict.fromkeys(reasons))
        msg = f"Cannot set {', '.join(labels)}: {'; '.join(unique_reasons)}"
        raise HomeAssistantError(msg)

    preflight_blocked = _check_preflight(results)
    if preflight_blocked:
        _LOGGER.warning("Command blocked by preflight: %s", preflight_blocked)
        raise HomeAssistantError(
            "Command could not be sent \u2014 device state is stale. "
            "Try again in a few seconds."
        )


def _humanize_field(field_name: str) -> str:
    label = CLIMATE_PRESET_FIELDS.get(field_name)
    if label:
        return label
    return field_name.replace("_", " ").title()


_MODE_RE = re.compile(r"requires mode \[([^\]]+)\], current=(\d+)")


def _humanize_rejection(reason: str) -> str:
    m = _MODE_RE.search(reason)
    if not m:
        return reason
    raw_modes = [s.strip().strip("'\"") for s in m.group(1).split(",")]
    mode_labels = [MODE_MIDEA_TO_HA.get(int(v), v) if v.isdigit() else v for v in raw_modes]
    current_int = int(m.group(2))
    current_label = MODE_MIDEA_TO_HA.get(current_int, str(current_int))
    return (
        f"requires {_join_modes(mode_labels)} mode "
        f"(current mode is {current_label.replace('_', ' ').title()})"
    )


def _join_modes(modes: list[str]) -> str:
    titled = [m.replace("_", " ").title() for m in modes]
    if len(titled) <= 2:
        return " or ".join(titled)
    return ", ".join(titled[:-1]) + ", or " + titled[-1]


def _check_preflight(results: dict) -> list | None:
    for cmd_result in results.values():
        if not isinstance(cmd_result, dict):
            continue
        preflight = cmd_result.get("preflight")
        if preflight and cmd_result.get("body") is None:
            return preflight
    return None
