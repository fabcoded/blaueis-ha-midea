"""Field-inventory HA integration — service + download view + tempfile lifecycle.

End-to-end user journey:

1. User clicks the AC device's "Run field inventory scan" button, or
   calls the ``blaueis_midea.run_field_inventory`` service.
2. Handler attaches a :class:`ShadowDecoder` to the integration's
   existing ``Device`` via the frame-observer hook we added in
   blaueis-client. Transparent interceptor — the normal ingress path
   keeps working; the shadow just decodes cap-agnostically in parallel.
3. Handler injects the superset of read-query frames the Device doesn't
   normally poll (exploratory C1 group pages, msg_type 0x07, etc.) via
   the Device's WS connection, respecting the 150 ms frame-spacing
   safety floor.
4. After a bounded collection window (~10 s), the shadow is detached.
5. Handler builds the markdown report + JSON sidecar + suggested
   override YAML snippets entirely in memory via the core-library
   functions.
6. The two files land in :func:`tempfile.NamedTemporaryFile` under the
   OS tempdir. ``delete=False`` so the handle closes without removing
   the file — the HTTP view unlinks it after serving.
7. Two :class:`HomeAssistantView` instances register under
   ``/api/blaueis_midea/inventory/<uuid>.{md,json}``, each backed by
   its tempfile.
8. A persistent notification fires with the download URLs. Tap →
   browser downloads → view unlinks the file → subsequent GETs return
   410 Gone.
9. A ``hass.async_call_later(900, cleanup)`` task fires 15 min later
   as a belt-and-braces TTL: any tempfile still on disk gets unlinked
   and its view deregistered. An unload-entry hook cleans up
   outstanding tempfiles immediately when the integration is
   reloaded.

The core decoding + classification + override-synthesis logic lives
in ``blaueis.core.inventory`` — this module is purely orchestration.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.event import async_call_later

from blaueis.core.codec import (
    build_frame_from_spec,
    walk_fields,
)
from blaueis.core.inventory import (
    CLASS_POPULATED,
    ShadowDecoder,
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

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required("label"): vol.All(str, vol.Length(min=1, max=64)),
        vol.Optional("compare_to_blob_id"): str,
        vol.Optional("suggest_overrides", default=True): bool,
    }
)

# Scan window: how long to leave the shadow decoder attached after
# kicking off the injected queries. 10 s is enough for all 31 queries
# to round-trip at ~150-200 ms each; longer would just add latency.
_SCAN_COLLECTION_SECONDS = 10.0

# Per-query sleep between injected sends — respects the frame-spacing
# safety floor documented in the HVAC-shark timing analysis.
_INJECT_SPACING_SECONDS = 0.20

# How long a generated file survives after creation before TTL cleanup
# unlinks it even if nobody downloaded it. 15 min is long enough for a
# user to notice the notification and click through, short enough that
# the tempdir doesn't bloat.
_DOWNLOAD_TTL_SECONDS = 900

# How many past JSON snapshots to keep in the in-memory registry for
# compare-mode. Overwrites oldest FIFO. 5 matches "off / idle /
# cooling / heating / dry" in typical usage.
_SNAPSHOT_REGISTRY_MAX = 5

# ── Query list — mirrors blaueis.tools.field_inventory.CLI ─────────────
# We build locally rather than importing from blaueis-tools because
# blaueis-tools isn't vendored into ha-midea (the HA integration consumes
# blaueis-core + blaueis-client, not blaueis-tools — that's CLI-only).


def _build_scan_query_list(
    glossary: dict, proto: int = 0x02
) -> list[tuple[str, bytes]]:
    """Return the (label, frame_bytes) list the inventory scan sends.

    Same coverage as the CLI's :func:`blaueis.tools.field_inventory._build_query_list`.
    """
    from blaueis.core.frame import build_frame

    queries: list[tuple[str, bytes]] = []

    # Glossary-defined frames.
    for fid in [
        "cmd_0xb5_extended",
        "cmd_0xb5_simple",
        "cmd_0x41",
        "cmd_0x41_group4_power",
        "cmd_0x41_group5",
        "cmd_0x41_ext",
    ]:
        spec = glossary.get("frames", {}).get(fid)
        if not spec:
            continue
        bus = spec.get("bus", ["uart", "rt"])
        if "uart" not in bus:
            continue
        try:
            frame = build_frame_from_spec(fid, glossary, proto=proto)
            queries.append((fid, frame))
        except Exception as e:
            _LOGGER.debug("skip glossary frame %s: %s", fid, e)

    # Direct C1 sub-page queries.
    for sp in [0x01, 0x02]:
        body = bytes([0x41, sp & 0xFF])
        frame = build_frame(body=body, msg_type=0x03, appliance=0xAC, proto=proto)
        queries.append((f"direct_subpage_0x{sp:02X}", frame))

    # msg_type 0x07 device ID.
    queries.append(
        (
            "device_id_0x07",
            build_frame(body=bytes([0x00]), msg_type=0x07, appliance=0xAC, proto=proto),
        )
    )

    # C1 group pages — the exploratory range.
    for page in [
        0x40,
        0x42,
        0x43,
        0x46,
        0x47,
        0x48,
        0x49,
        0x4A,
        0x4B,
        0x4C,
        0x4D,
        0x4E,
        0x4F,
    ]:
        body = bytearray(24)
        body[0] = 0x41
        body[1] = 0x21
        body[2] = 0x01
        body[3] = page & 0xFF
        queries.append(
            (
                f"group_0x{page:02X}_v21",
                build_frame(
                    body=bytes(body), msg_type=0x03, appliance=0xAC, proto=proto
                ),
            )
        )

    return queries


# ══════════════════════════════════════════════════════════════════════════
#   Download view — single-use HTTP serving of tempfiles
# ══════════════════════════════════════════════════════════════════════════


class InventoryDownloadView(HomeAssistantView):
    """Serves one inventory tempfile and unlinks it after the first GET.

    URL: ``/api/blaueis_midea/inventory/<uuid>/<ext>`` where ext is ``md``
    or ``json``. After a successful download, the backing file is
    unlinked from disk and further GETs return 410 Gone until the
    enclosing ``InventoryDownloadRegistry`` entry is removed entirely.
    """

    url = "/api/blaueis_midea/inventory/{blob_id}/{ext}"
    name = "api:blaueis_midea:inventory"
    requires_auth = True

    def __init__(self, registry: "InventoryDownloadRegistry") -> None:
        self._registry = registry

    async def get(self, request, blob_id: str, ext: str) -> web.Response:
        entry = self._registry.get(blob_id)
        if entry is None:
            return web.Response(status=404, text="inventory blob not found or expired")
        path = entry.paths.get(ext)
        if path is None:
            return web.Response(status=404, text=f"inventory blob has no {ext} file")
        if not path.exists():
            # Already consumed — 410 Gone.
            return web.Response(status=410, text="inventory file already downloaded")
        content_type = "text/markdown" if ext == "md" else "application/json"
        try:
            body = await _read_tempfile(path)
        except FileNotFoundError:
            return web.Response(status=410, text="inventory file gone")
        # Unlink after reading; protect against race with cleanup.
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        return web.Response(
            body=body,
            content_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{blob_id}.{ext}"',
            },
        )


async def _read_tempfile(path: Path) -> bytes:
    """Read a tempfile via an executor to keep the event loop responsive."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, path.read_bytes)


# ══════════════════════════════════════════════════════════════════════════
#   Download registry — blob_id → tempfile paths + JSON snapshot
# ══════════════════════════════════════════════════════════════════════════


@dataclass
class InventoryBlob:
    """One inventory result with download tempfiles + in-memory snapshot."""

    blob_id: str
    label: str
    timestamp: float
    paths: dict[str, Path] = field(default_factory=dict)  # {"md": Path, "json": Path}
    snapshot_json: dict | None = None  # full JSON content, kept in RAM for compares


class InventoryDownloadRegistry:
    """Per-config-entry registry of active inventory blobs.

    Lives on ``entry.runtime_data.inventory_registry``. Holds up to
    :data:`_SNAPSHOT_REGISTRY_MAX` JSON snapshots for compare-mode and
    any number of currently-downloadable tempfile-backed blobs.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._blobs: dict[str, InventoryBlob] = {}
        # Separate FIFO of snapshot-only entries (for compare-mode
        # lookup after the tempfiles have been unlinked).
        self._snapshots: dict[str, dict] = {}
        self._snapshot_order: list[str] = []

    def add(self, blob: InventoryBlob) -> None:
        self._blobs[blob.blob_id] = blob
        if blob.snapshot_json is not None:
            self._snapshots[blob.blob_id] = blob.snapshot_json
            self._snapshot_order.append(blob.blob_id)
            while len(self._snapshot_order) > _SNAPSHOT_REGISTRY_MAX:
                evict = self._snapshot_order.pop(0)
                self._snapshots.pop(evict, None)

    def get(self, blob_id: str) -> InventoryBlob | None:
        return self._blobs.get(blob_id)

    def get_snapshot(self, blob_id: str) -> dict | None:
        return self._snapshots.get(blob_id)

    def drop(self, blob_id: str) -> None:
        self._blobs.pop(blob_id, None)

    def cleanup_blob(self, blob_id: str) -> None:
        """Unlink any remaining tempfiles for a blob and drop it from
        the active registry. Snapshot (if any) stays in the FIFO until
        aged out — that's intentional for compare-mode continuity.
        """
        blob = self._blobs.pop(blob_id, None)
        if blob is None:
            return
        for path in blob.paths.values():
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            except Exception as e:  # pragma: no cover — OS permission errors
                _LOGGER.debug("cleanup: couldn't unlink %s: %s", path, e)

    def cleanup_all(self) -> None:
        for blob_id in list(self._blobs):
            self.cleanup_blob(blob_id)


# ══════════════════════════════════════════════════════════════════════════
#   Setup + teardown (called from __init__.async_setup_entry)
# ══════════════════════════════════════════════════════════════════════════


async def async_setup_field_inventory(
    hass: HomeAssistant, entry: "BlaueisMideaConfigEntry"
) -> None:
    """Register the service + HTTP view for a config entry.

    Idempotent per HA run — the service and view are registered once
    globally; per-entry state lives on ``entry.runtime_data``.
    """
    coordinator: BlaueisMideaCoordinator = entry.runtime_data

    # Per-entry download registry.
    registry = InventoryDownloadRegistry(hass)
    coordinator.inventory_registry = registry  # type: ignore[attr-defined]

    # Register HTTP view once globally — subsequent entries reuse it.
    view_registered_key = f"{DOMAIN}_inventory_view_registered"
    if not hass.data.get(view_registered_key):
        # The view needs a registry; route to the correct per-entry
        # registry by looking up entry -> coordinator via blob_id
        # prefix. Simplest: one view dispatches by walking all config
        # entries' registries.
        hass.http.register_view(_MultiEntryInventoryView(hass))
        hass.data[view_registered_key] = True

    # Register the service once globally; handler dispatches by entry_id.
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
    """Clean up any outstanding tempfiles when the entry is unloaded."""
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None:
        return
    registry: InventoryDownloadRegistry | None = getattr(
        coordinator, "inventory_registry", None
    )
    if registry is not None:
        registry.cleanup_all()


# ══════════════════════════════════════════════════════════════════════════
#   Multi-entry HTTP view
# ══════════════════════════════════════════════════════════════════════════


class _MultiEntryInventoryView(HomeAssistantView):
    """Global HTTP view that looks up the blob across all config
    entries' inventory registries. Keeps us to one registered view even
    when the user has multiple Blaueis gateways configured.
    """

    url = "/api/blaueis_midea/inventory/{blob_id}/{ext}"
    name = "api:blaueis_midea:inventory"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def get(self, request, blob_id: str, ext: str) -> web.Response:
        for entry in self._hass.config_entries.async_entries(DOMAIN):
            coord = getattr(entry, "runtime_data", None)
            registry: InventoryDownloadRegistry | None = getattr(
                coord, "inventory_registry", None
            )
            if registry is None:
                continue
            blob = registry.get(blob_id)
            if blob is None:
                continue
            path = blob.paths.get(ext)
            if path is None:
                return web.Response(status=404, text=f"no {ext} file for blob")
            if not path.exists():
                return web.Response(
                    status=410, text="inventory file already downloaded"
                )
            try:
                body = await _read_tempfile(path)
            except FileNotFoundError:
                return web.Response(status=410, text="inventory file gone")
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            return web.Response(
                body=body,
                content_type="text/markdown" if ext == "md" else "application/json",
                headers={
                    "Content-Disposition": f'attachment; filename="{blob_id}.{ext}"',
                },
            )
        return web.Response(status=404, text="inventory blob not found or expired")


# ══════════════════════════════════════════════════════════════════════════
#   Service handler
# ══════════════════════════════════════════════════════════════════════════


async def _handle_service_call(hass: HomeAssistant, call: ServiceCall) -> None:
    """Route a ``blaueis_midea.run_field_inventory`` service call to the
    correct config entry. With multiple Blaueis gateways configured,
    the service runs for every entry (no explicit selector today —
    simplest UX for the 99% case of one gateway)."""
    label = call.data["label"]
    compare_to_blob_id = call.data.get("compare_to_blob_id")
    suggest_overrides = call.data.get("suggest_overrides", True)

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
                "run_field_inventory: skipping %s — not connected",
                entry.title,
            )
            continue
        # Fire-and-forget — service returns immediately; scan runs in
        # the background and posts a notification when done.
        hass.async_create_task(
            _run_inventory_scan(
                hass, entry, label, compare_to_blob_id, suggest_overrides
            )
        )


async def _run_inventory_scan(
    hass: HomeAssistant,
    entry: "BlaueisMideaConfigEntry",
    label: str,
    compare_to_blob_id: str | None,
    suggest_overrides: bool,
) -> None:
    """The actual scan + build + serve logic. Runs as a background task."""
    coordinator: BlaueisMideaCoordinator = entry.runtime_data
    registry: InventoryDownloadRegistry = coordinator.inventory_registry  # type: ignore[attr-defined]
    device = coordinator.device

    try:
        glossary = device._glossary  # type: ignore[attr-defined]
        shadow = ShadowDecoder(glossary)

        def observer(protocol_key: str, body: bytes) -> None:
            shadow.observe(protocol_key, body)

        device.register_frame_observer(observer)

        try:
            # Inject the superset of queries. Respect frame spacing.
            queries = _build_scan_query_list(glossary)
            _LOGGER.info(
                "field_inventory: injecting %d queries (label=%s)", len(queries), label
            )
            for qlabel, frame_bytes in queries:
                client = getattr(device, "_client", None)
                if client is None or getattr(client, "_ws", None) is None:
                    _LOGGER.warning("field_inventory: connection lost — aborting scan")
                    break
                try:
                    await client.send_frame(frame_bytes.hex(" "))
                except Exception as e:
                    _LOGGER.debug("field_inventory: send %s failed: %s", qlabel, e)
                await asyncio.sleep(_INJECT_SPACING_SECONDS)

            # Give responses time to arrive beyond the last inject.
            await asyncio.sleep(_SCAN_COLLECTION_SECONDS)
        finally:
            device.unregister_frame_observer(observer)

        # Pull cap records from the device's cumulative B5 store.
        cap_records = (
            device._status.get("capabilities_raw", []) if device._status else []
        )

        snap = shadow.snapshot(cap_records=cap_records)

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
                    fname, field_def, state.frame, state.body, glossary, cap_records
                )
                if snip is not None:
                    suggested.append(snip)

        host = entry.data.get("host")
        md = generate_markdown_report(
            snap, glossary, label=label, host=host, suggested_overrides=suggested
        )
        js = generate_json_sidecar(
            snap, glossary, label=label, host=host, suggested_overrides=suggested
        )

        # Optional compare.
        cmp_md: str | None = None
        if compare_to_blob_id:
            prev_js = registry.get_snapshot(compare_to_blob_id)
            if prev_js is None:
                _LOGGER.warning(
                    "field_inventory: compare_to_blob_id=%s not in registry — skipping diff",
                    compare_to_blob_id,
                )
            else:
                cmp_md = generate_compare_report(prev_js, js)

        # Build + register tempfiles.
        blob = await _persist_blob(hass, label, md, js, cmp_md, registry)

        # Notification.
        notification_msg = _build_notification(blob, host)
        hass.components.persistent_notification.async_create(
            message=notification_msg,
            title=f"Field inventory: {label}",
            notification_id=f"blaueis_midea_inventory_{blob.blob_id}",
        )

        # TTL cleanup.
        async def _ttl_cleanup(_now: Any) -> None:
            registry.cleanup_blob(blob.blob_id)
            _LOGGER.info("field_inventory: TTL expired, cleaned blob %s", blob.blob_id)

        async_call_later(hass, _DOWNLOAD_TTL_SECONDS, _ttl_cleanup)

    except Exception:
        _LOGGER.exception("field_inventory: scan failed")
        try:
            hass.components.persistent_notification.async_create(
                message=(
                    f"Field inventory (`{label}`) failed — see Home Assistant log for "
                    "details."
                ),
                title="Field inventory: failure",
                notification_id=f"blaueis_midea_inventory_failure_{time.time()}",
            )
        except Exception:
            pass


async def _persist_blob(
    hass: HomeAssistant,
    label: str,
    md: str,
    js: dict,
    cmp_md: str | None,
    registry: InventoryDownloadRegistry,
) -> InventoryBlob:
    """Write markdown + JSON (+ optional compare) to tempfiles and
    register them under a fresh blob_id."""
    blob_id = uuid.uuid4().hex
    paths: dict[str, Path] = {}

    def _write_tempfile(ext: str, data: bytes) -> Path:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            prefix=f"blaueis_inventory_{blob_id}_",
            suffix=f".{ext}",
        ) as tf:
            tf.write(data)
            return Path(tf.name)

    # Offload file I/O to the executor.
    paths["md"] = await hass.async_add_executor_job(
        _write_tempfile, "md", md.encode("utf-8")
    )
    paths["json"] = await hass.async_add_executor_job(
        _write_tempfile,
        "json",
        json.dumps(js, indent=2, default=str).encode("utf-8"),
    )
    if cmp_md is not None:
        paths["compare.md"] = await hass.async_add_executor_job(
            _write_tempfile, "compare.md", cmp_md.encode("utf-8")
        )

    blob = InventoryBlob(
        blob_id=blob_id,
        label=label,
        timestamp=time.time(),
        paths=paths,
        snapshot_json=js,
    )
    registry.add(blob)
    return blob


def _build_notification(blob: InventoryBlob, host: str | None) -> str:
    """Markdown body for the persistent notification. Links resolve to
    the single-use HomeAssistantView registered in ``async_setup_field_inventory``.
    """
    base = "/api/blaueis_midea/inventory"
    msg = (
        f"Field inventory (`{blob.label}`) ready.\n\n"
        f"- [Download markdown report]({base}/{blob.blob_id}/md)\n"
        f"- [Download JSON sidecar]({base}/{blob.blob_id}/json)\n"
    )
    if "compare.md" in blob.paths:
        msg += f"- [Download compare report]({base}/{blob.blob_id}/compare.md)\n"
    msg += (
        f"\nLinks expire in 15 min or after first download. "
        f"Blob ID `{blob.blob_id}` — pass to "
        f"`compare_to_blob_id` on the next scan for a diff."
    )
    return msg


__all__ = [
    "SERVICE_RUN_FIELD_INVENTORY",
    "SERVICE_SCHEMA",
    "InventoryBlob",
    "InventoryDownloadRegistry",
    "async_setup_field_inventory",
    "async_teardown_field_inventory",
]
