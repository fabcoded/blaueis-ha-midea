"""Field-inventory HA integration — on-demand scan + single-snapshot persistence.

End-to-end user journey:

1. User ticks "Run new inventory scan on submit" in Configure, or calls
   the ``blaueis_midea.run_field_inventory`` service directly.
2. Handler attaches a :class:`ShadowDecoder` to the Device's frame-observer
   hook (``device.register_frame_observer``). Transparent interceptor —
   the normal ingress path keeps working; the shadow decodes
   cap-agnostically in parallel.
3. Handler injects the superset of read-query frames the Device doesn't
   normally poll, respecting the 200 ms frame-spacing safety floor.
4. After ~10 s of collection, the shadow is detached.
5. Markdown + JSON sidecar are built via ``blaueis.core.inventory``.
6. If a prior snapshot is present (loaded from ``helpers.storage.Store``
   at setup, or produced by an earlier scan in this session), a diff
   section is appended to the markdown.
7. The new snapshot (markdown + JSON) is persisted to Store (debounced
   write, overwrites prior) and also cached on the coordinator for the
   Configure textarea.

Memory + resource discipline:

- Ingress path cost **at rest**: one ``if self._frame_observers:`` check per
  frame (list is empty → branch skipped). Zero iteration, zero copy.
  Observer is attached only for the ~10 s scan window and removed in a
  ``finally:`` block.
- RAM **at rest**: one snapshot_json (~30 KB) + one rendered markdown
  (~20 KB) + a few scalars. Each scan rebinds the coordinator attrs;
  the previous Python dict becomes unreachable and is garbage-collected.
  No ring, no FIFO, no accumulation.
- Disk **at rest**: one JSON blob per config entry at
  ``/config/.storage/blaueis_midea.<entry_id>.snapshot``. Overwritten
  on each scan. ~50 KB. Survives restart, so the Configure textarea
  shows "your last scan" immediately after HA comes back up.

The core decoding + classification + override-synthesis logic lives
in ``blaueis.core.inventory`` — this module is purely orchestration.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.storage import Store

from blaueis.core.codec import (
    build_frame_from_spec,
    walk_fields,
)
from blaueis.core.inventory import (
    CLASS_POPULATED,
    ShadowDecoder,
    _load_glossary_schema,
    generate_compare_report,
    generate_json_sidecar,
    generate_markdown_report,
    synthesize_override_snippet,
)

from .const import DOMAIN

if TYPE_CHECKING:
    from . import BlaueisMideaConfigEntry
    from .coordinator import BlaueisMideaCoordinator

_LOGGER = logging.getLogger(__name__)

# ── Service config ─────────────────────────────────────────────────────

SERVICE_RUN_FIELD_INVENTORY = "run_field_inventory"

# Keep field set + types in sync with services.yaml. This schema defaults
# to PREVENT_EXTRA, so a YAML field without a matching key here will fail
# the call with "extra keys not allowed".
SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required("label"): vol.All(str, vol.Length(min=1, max=64)),
        vol.Optional("suggest_overrides", default=True): bool,
        # When True, ignore any prior snapshot on disk/RAM for this scan
        # (no diff section) — useful after a firmware change invalidates
        # the baseline.
        vol.Optional("reset_prior", default=False): bool,
    }
)

# ── Scan pacing ────────────────────────────────────────────────────────

# How long to leave the shadow decoder attached after the last injected
# query. 10 s is enough for all queries to round-trip at ~150–200 ms
# each; longer would just add latency.
_SCAN_COLLECTION_SECONDS = 10.0

# Per-query sleep between injected sends — respects the frame-spacing
# safety floor documented in the blaueis-hvacshark timing analysis.
_INJECT_SPACING_SECONDS = 0.20

# ── Store config ───────────────────────────────────────────────────────

_STORE_VERSION = 1
_STORE_KEY_FMT = "blaueis_midea.{entry_id}.snapshot"


def _store_for_entry(
    hass: HomeAssistant, entry: "BlaueisMideaConfigEntry"
) -> Store:
    """Return the per-entry HA Store handle. Store debounces writes and
    serialises via JSON; our payload is already a JSON-compatible dict
    (markdown as string + snapshot_json as dict)."""
    return Store(
        hass, _STORE_VERSION, _STORE_KEY_FMT.format(entry_id=entry.entry_id)
    )


# ══════════════════════════════════════════════════════════════════════════
#   Query list builder (unchanged from prior implementation)
# ══════════════════════════════════════════════════════════════════════════


def _build_scan_query_list(glossary: dict) -> list[tuple[str, bytes]]:
    """Build the superset of read-query frames to inject during a scan.

    Pulls the same set ``ac_probe.py`` uses: B5 simple + extended, C0
    status, C1 group pages, B1 property batches derived from the
    glossary, msg_type 0x07 device ID, and a handful of exploratory
    optCommand / C1-sub-page queries.
    """
    queries: list[tuple[str, bytes]] = []
    for fid in (
        "cmd_0xb5_extended",
        "cmd_0xb5_simple",
        "cmd_0x41",
        "cmd_0x41_group4_power",
        "cmd_0x41_group5",
        "cmd_0x41_ext",
    ):
        try:
            frame = build_frame_from_spec(glossary, fid, values={})
        except Exception as e:
            _LOGGER.debug("field_inventory: skip query %s — %s", fid, e)
            continue
        if frame:
            queries.append((fid, frame))

    for sp in (0x01, 0x02):
        try:
            frame = build_frame_from_spec(
                glossary, "cmd_0x41_direct_subpage", values={"subpage": sp}
            )
            if frame:
                queries.append((f"direct_subpage_0x{sp:02X}", frame))
        except Exception as e:
            _LOGGER.debug("field_inventory: skip subpage 0x%02X — %s", sp, e)

    try:
        frame = build_frame_from_spec(glossary, "cmd_0x07_device_id", values={})
        if frame:
            queries.append(("msg_type_0x07", frame))
    except Exception as e:
        _LOGGER.debug("field_inventory: skip 0x07 — %s", e)

    for opt in (0x00, 0x02, 0x04, 0x05, 0x06):
        try:
            frame = build_frame_from_spec(
                glossary, "cmd_0xa1_optcommand", values={"opt": opt}
            )
            if frame:
                queries.append((f"optcommand_0x{opt:02X}", frame))
        except Exception:
            pass

    for group in (0x42, 0x46, 0x47, 0x48, 0x49, 0x4A, 0x4B, 0x4C, 0x4D, 0x4E, 0x4F):
        try:
            frame = build_frame_from_spec(
                glossary, "cmd_0x41_group_raw", values={"group": group}
            )
            if frame:
                queries.append((f"c1_group_0x{group:02X}", frame))
        except Exception:
            pass

    return queries


# ══════════════════════════════════════════════════════════════════════════
#   Setup + teardown (called from __init__.async_setup_entry)
# ══════════════════════════════════════════════════════════════════════════


async def async_setup_field_inventory(
    hass: HomeAssistant, entry: "BlaueisMideaConfigEntry"
) -> None:
    """Register the service once globally and hydrate prior-snapshot
    state onto the coordinator from HA Store.

    Called once per config entry on ``async_setup_entry``. The service
    registration is idempotent — a second entry reuses the first's
    registration rather than colliding.
    """
    coordinator: BlaueisMideaCoordinator = entry.runtime_data

    # Warm the glossary-schema cache off-loop — the synthesizer's first
    # call opens glossary_schema.json synchronously, and HA's event-loop
    # watchdog flags that as blocking I/O. Once is enough.
    await hass.async_add_executor_job(_load_glossary_schema)

    store = _store_for_entry(hass, entry)
    coordinator.inventory_store = store  # type: ignore[attr-defined]

    # Initialise session state to empty; hydrate from disk if a prior
    # snapshot exists for this entry.
    coordinator.inventory_prior_snapshot = None  # type: ignore[attr-defined]
    coordinator.inventory_latest_md = None  # type: ignore[attr-defined]
    coordinator.inventory_latest_label = None  # type: ignore[attr-defined]
    coordinator.inventory_latest_ts = None  # type: ignore[attr-defined]

    try:
        stored = await store.async_load()
    except Exception:
        _LOGGER.exception("field_inventory: failed to load stored snapshot")
        stored = None

    if isinstance(stored, dict) and "snapshot_json" in stored:
        coordinator.inventory_prior_snapshot = stored.get("snapshot_json")
        coordinator.inventory_latest_md = stored.get("markdown")
        coordinator.inventory_latest_label = stored.get("label")
        coordinator.inventory_latest_ts = stored.get("timestamp")
        _LOGGER.info(
            "field_inventory: hydrated prior snapshot (label=%s, ts=%s)",
            stored.get("label"),
            stored.get("timestamp"),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_RUN_FIELD_INVENTORY):

        async def _service_handler(call: ServiceCall) -> None:
            await _handle_service_call(hass, call)

        hass.services.async_register(
            DOMAIN,
            SERVICE_RUN_FIELD_INVENTORY,
            _service_handler,
            schema=SERVICE_SCHEMA,
        )


async def async_teardown_field_inventory(
    hass: HomeAssistant, entry: "BlaueisMideaConfigEntry"
) -> None:
    """Release session state when the entry unloads. Disk snapshot
    stays put for the next load — persistent by design."""
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None:
        return
    coordinator.inventory_prior_snapshot = None  # type: ignore[attr-defined]
    coordinator.inventory_latest_md = None  # type: ignore[attr-defined]
    coordinator.inventory_latest_label = None  # type: ignore[attr-defined]
    coordinator.inventory_latest_ts = None  # type: ignore[attr-defined]


# ══════════════════════════════════════════════════════════════════════════
#   Service handler
# ══════════════════════════════════════════════════════════════════════════


async def _handle_service_call(hass: HomeAssistant, call: ServiceCall) -> None:
    """Fan the service call out across all loaded Blaueis config entries.

    Returns immediately; each scan runs in its own background task."""
    label = call.data["label"]
    suggest_overrides = call.data.get("suggest_overrides", True)
    reset_prior = call.data.get("reset_prior", False)

    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        _LOGGER.warning(
            "run_field_inventory: no Blaueis Midea AC config entries loaded"
        )
        return

    for entry in entries:
        coord = getattr(entry, "runtime_data", None)
        if coord is None or not getattr(coord, "connected", False):
            _LOGGER.warning(
                "run_field_inventory: skipping %s — not connected", entry.title
            )
            continue
        hass.async_create_task(
            _run_inventory_scan(hass, entry, label, suggest_overrides, reset_prior)
        )


async def _run_inventory_scan(
    hass: HomeAssistant,
    entry: "BlaueisMideaConfigEntry",
    label: str,
    suggest_overrides: bool,
    reset_prior: bool,
) -> None:
    """Run one scan end-to-end: attach shadow → inject → detach →
    build reports → diff against prior → persist to Store → rebind
    coordinator state.

    Runs as a background task spawned by ``_handle_service_call``.
    """
    coordinator: BlaueisMideaCoordinator = entry.runtime_data
    store: Store = coordinator.inventory_store  # type: ignore[attr-defined]
    device = coordinator.device

    _LOGGER.info("field_inventory: scan start — label=%s", label)

    try:
        glossary = device._glossary  # type: ignore[attr-defined]
        shadow = ShadowDecoder(glossary)

        def observer(protocol_key: str, body: bytes) -> None:
            shadow.observe(protocol_key, body)

        device.register_frame_observer(observer)

        try:
            queries = _build_scan_query_list(glossary)
            _LOGGER.info(
                "field_inventory: injecting %d queries (label=%s)",
                len(queries),
                label,
            )
            for qlabel, frame_bytes in queries:
                client = getattr(device, "_client", None)
                if client is None or getattr(client, "_ws", None) is None:
                    _LOGGER.warning(
                        "field_inventory: connection lost — aborting scan"
                    )
                    break
                try:
                    await client.send_frame(frame_bytes.hex(" "))
                except Exception as e:
                    _LOGGER.debug(
                        "field_inventory: send %s failed: %s", qlabel, e
                    )
                await asyncio.sleep(_INJECT_SPACING_SECONDS)
            await asyncio.sleep(_SCAN_COLLECTION_SECONDS)
        finally:
            # Always detach — exception-safe. After this line the ingress
            # path is back to its zero-cost steady state.
            device.unregister_frame_observer(observer)

        cap_records = (
            device._status.get("capabilities_raw", []) if device._status else []
        )
        snap = shadow.snapshot(cap_records=cap_records)
        _LOGGER.info(
            "field_inventory: shadow snapshot — %d populated, %d observations",
            sum(
                1
                for s in snap.states.values()
                if s.classification == CLASS_POPULATED
            ),
            len(snap.observations),
        )

        suggested = []
        if suggest_overrides:
            walk = walk_fields(glossary)
            for fname, state in snap.states.items():
                if state.classification != CLASS_POPULATED:
                    continue
                field_def = walk.get(fname)
                if field_def is None or state.frame is None or state.body is None:
                    continue
                snip = synthesize_override_snippet(
                    fname,
                    field_def,
                    state.frame,
                    state.body,
                    glossary,
                    cap_records,
                    current_value=state.value,
                )
                if snip is not None:
                    suggested.append(snip)
            _LOGGER.info(
                "field_inventory: synthesized %d override snippets",
                len(suggested),
            )

        host = entry.data.get("host")
        js = generate_json_sidecar(
            snap,
            glossary,
            label=label,
            host=host,
            suggested_overrides=suggested,
        )
        md = generate_markdown_report(
            snap,
            glossary,
            label=label,
            host=host,
            suggested_overrides=suggested,
        )

        # Auto-compare against the currently-held prior snapshot (either
        # hydrated from Store at setup, or produced by an earlier scan
        # this session). ``reset_prior=True`` suppresses the diff — use
        # it after a firmware change invalidates the baseline.
        prior_snap = (
            None
            if reset_prior
            else getattr(coordinator, "inventory_prior_snapshot", None)
        )
        if prior_snap is not None:
            try:
                diff_md = generate_compare_report(prior_snap, js)
                md = f"{md}\n\n{diff_md}"
                _LOGGER.info("field_inventory: diff section appended")
            except Exception:
                _LOGGER.exception(
                    "field_inventory: compare failed, continuing without diff"
                )

        ts_iso = js.get("meta", {}).get("timestamp", "")

        # Persist: Store serialises the dict to JSON under
        # /config/.storage/blaueis_midea.<entry>.snapshot. Debounced;
        # back-to-back scans coalesce into one write.
        await store.async_save(
            {
                "timestamp": ts_iso,
                "label": label,
                "markdown": md,
                "snapshot_json": js,
            }
        )

        # Rebind coordinator state. Rebinding drops the last reference
        # to the previous prior snapshot → immediate GC eligibility.
        # Scalars update first so the textarea can't race to a stale
        # ts while the new markdown is still being rendered on another
        # task.
        coordinator.inventory_latest_label = label  # type: ignore[attr-defined]
        coordinator.inventory_latest_ts = ts_iso  # type: ignore[attr-defined]
        coordinator.inventory_latest_md = md  # type: ignore[attr-defined]
        coordinator.inventory_prior_snapshot = js  # type: ignore[attr-defined]

        _LOGGER.info(
            "field_inventory: scan complete — label=%s md=%d B fields=%d",
            label,
            len(md),
            len(js.get("fields", {})),
        )

    except Exception:
        _LOGGER.exception("field_inventory: scan failed")


__all__ = [
    "SERVICE_RUN_FIELD_INVENTORY",
    "SERVICE_SCHEMA",
    "async_setup_field_inventory",
    "async_teardown_field_inventory",
]
