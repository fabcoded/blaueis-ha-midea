"""Diagnostics platform — flight-recorder combined bundle.

Pulls the HA-side DebugRing and the gateway-side ring (via the `debug_dump`
WS command), merges them by timestamp, and returns a redacted dict. The HA
"Download Diagnostics" button delivers this as a single JSON file.

See blaueis-libmidea/docs/flight_recorder.md §4.4.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant

from .const import CONF_GLOSSARY_OVERRIDES, CONF_PSK

_LOGGER = logging.getLogger(__name__)

# Redact secrets and anything that narrows down a specific install.
_TO_REDACT = {CONF_PSK, "psk", "token", "password"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    ring = getattr(coordinator, "debug_ring", None)

    local_records = ring.dump_records() if ring is not None else []
    local_meta = {
        "enabled": ring is not None,
        "size_bytes": ring.byte_count if ring is not None else 0,
        "record_count": len(local_records),
        "capacity_bytes": ring.size_bytes if ring is not None else 0,
    }

    gateway_records, gateway_meta = await _pull_gateway_ring(coordinator)

    combined = sorted(
        local_records + gateway_records,
        key=lambda r: r.get("ts", 0.0),
    )

    session_dict: dict[str, Any] = {}
    client = coordinator.device.client
    if client is not None and getattr(client, "gw_session", None) is not None:
        session_dict = dataclasses.asdict(client.gw_session)

    # Glossary override snapshot — raw user YAML text + the affected
    # leaf paths the override produced. Tiny payload, useful for bug
    # reports and offline diffs against an unmodified glossary.
    glossary_override = _glossary_override_section(entry, coordinator)

    data: dict[str, Any] = {
        "entry": {
            "title": entry.title,
            "host": entry.data.get(CONF_HOST),
            "port": entry.data.get(CONF_PORT),
        },
        "gateway_info": dict(getattr(coordinator.device, "gateway_info", {})),
        "gateway_session": session_dict,
        "glossary_override": glossary_override,
        "available_fields": list(coordinator.device.available_fields.keys()),
        "local_ring": local_meta,
        "gateway_ring": gateway_meta,
        "combined_records": combined,
    }

    return async_redact_data(data, _TO_REDACT)


def _glossary_override_section(
    entry: ConfigEntry, coordinator,
) -> dict[str, Any]:
    """Build the diagnostics block for the device's glossary override.

    Always present (even when no override is set) so consumers can rely
    on a fixed shape:

    - ``yaml``: the raw user-supplied text (empty string if unset).
    - ``affected_paths``: dotted paths of leaves the override changed
      in the merged glossary view (empty list if no override).
    - ``meta``: cached integer count, used for quick sanity checks.

    The full merged glossary is intentionally NOT included by default —
    it's a few hundred KB and is mostly identical to the un-overridden
    base. Use the in-app "View merged glossary" menu (G9) for a scoped
    on-screen view, or run the override locally to reconstruct it.
    """
    yaml_text = entry.options.get(CONF_GLOSSARY_OVERRIDES, "") or ""
    affected = list(getattr(coordinator.device, "glossary_override_affected", []))
    return {
        "yaml": yaml_text,
        "affected_paths": affected,
        "meta": {
            "yaml_bytes": len(yaml_text),
            "affected_count": len(affected),
        },
    }


async def _pull_gateway_ring(coordinator) -> tuple[list[dict], dict]:
    """Request the gateway's ring via `debug_dump`. Returns (records, meta).

    Failure is non-fatal — diagnostics returns the local ring plus an error
    marker so the user always gets *something* to attach to a bug report.
    """
    client = coordinator.device.client
    if client is None or getattr(client, "_ws", None) is None:
        return [], {"error": "gateway not connected"}

    try:
        reply = await client.request_debug_dump(timeout=10.0)
    except asyncio.TimeoutError:
        return [], {"error": "gateway did not respond within 10 s"}
    except Exception as exc:  # noqa: BLE001 — diagnostics must not crash HA
        _LOGGER.debug("debug_dump failed: %s", exc, exc_info=True)
        return [], {"error": f"{type(exc).__name__}: {exc}"}

    jsonl = reply.get("jsonl", "") or ""
    records: list[dict] = []
    for line in jsonl.strip().split("\n"):
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            # Keep going — one bad line should not poison the whole dump.
            continue

    meta = {
        "record_count": reply.get("record_count"),
        "size_bytes": reply.get("size_bytes"),
        "capacity_bytes": reply.get("ring_capacity_bytes"),
        "parsed_record_count": len(records),
    }
    return records, meta
