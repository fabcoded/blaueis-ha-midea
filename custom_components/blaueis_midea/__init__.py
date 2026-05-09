"""Blaueis Midea AC — Home Assistant integration.

Connects to a Blaueis gateway via WebSocket and exposes the AC unit
as HA entities. Capabilities are discovered via B5 queries; only
confirmed features become entities.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Make vendored blaueis library importable
_LIB = str(Path(__file__).parent / "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from homeassistant.config_entries import ConfigEntry  # noqa: E402
from homeassistant.const import CONF_HOST, CONF_PORT, Platform  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402

from ._glossary_override import (  # noqa: E402
    GlossaryOverrideError,
    validate_and_parse_overrides,
)
from .const import (  # noqa: E402
    CONF_DISPLAY_BUZZER_MODE,
    CONF_FMF_CONFIGURED,
    CONF_FMF_ENABLED,
    CONF_FMF_SENSOR,
    CONF_GLOSSARY_OVERRIDES,
    CONF_PSK,
    DEBUG_RING_SIZE_MB,
    DISPLAY_BUZZER_LEGACY_MIGRATION,
    DISPLAY_BUZZER_POLICIES,
    DOMAIN as DOMAIN,
    SYNTHETIC_ENTITY_CAP_DEPENDENCIES,
)
from .coordinator import BlaueisMideaCoordinator  # noqa: E402

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.NUMBER,
    # Platform.BUTTON was used to expose a 'Run field inventory scan'
    # entity on the AC device page. It moved into the Configure form
    # (as a 'Run new scan on submit' checkbox) because that's where
    # the scan result also surfaces — all inventory UX in one place.
    # The button.py module is retained but no longer forwarded.
]

# Loggers attached to the per-entry DebugRing. Keeping the list explicit (not
# attaching at root) prevents us from slurping unrelated HA records into the
# ring. Level is raised to VERBOSE so the ring can observe packet-level
# events without changing what ends up in homeassistant.log.
_VERBOSE = 5
_RING_LOGGERS = (
    "blaueis_midea",
    "blaueis.device",
    "blaueis.client",
    "hvac_client",
)

type BlaueisMideaConfigEntry = ConfigEntry[BlaueisMideaCoordinator]


# Glossary field renames that changed unique_ids. Map old → new canonical name.
# On setup the entity registry is walked and any entity whose unique_id ends in
# `_<old_name>` is rewritten in place — entity_id, history, and automations are
# preserved. Entries can stay in this map forever; once no entities match, the
# migration is a no-op.
_FIELD_RENAMES: dict[str, str] = {
    "ptc_heater": "auxiliary_heat_level",
    "total_power_kwh": "power_total_kwh",
    "total_run_power_kwh": "power_total_run_kwh",
    "current_run_power_kwh": "power_current_run_kwh",
    "realtime_power_kw": "power_realtime_kw",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: BlaueisMideaConfigEntry
) -> bool:
    """Set up Blaueis Midea AC from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    psk = entry.data[CONF_PSK]

    # Pre-load glossary in executor to avoid blocking the event loop
    from blaueis.core.codec import load_glossary

    await hass.async_add_executor_job(load_glossary)

    _migrate_renamed_unique_ids(hass, entry)
    _migrate_display_buzzer_options(hass, entry)
    _migrate_fmf_keys(hass, entry)

    debug_ring = _install_debug_ring(entry)

    # Parse any persisted glossary override (validated on save in
    # config_flow; we re-parse here as the authoritative source). If
    # parsing fails (e.g. user edited config_entries.json by hand), log
    # and proceed without the override so the integration still loads.
    glossary_overrides = _parse_stored_overrides(entry)

    coordinator = BlaueisMideaCoordinator(
        hass,
        host,
        port,
        psk,
        debug_ring=debug_ring,
        glossary_overrides=glossary_overrides,
    )
    # Snapshot the YAML text we just applied so _async_options_updated
    # can detect changes that warrant a full entry reload.
    coordinator._applied_override_yaml = (
        entry.options.get(CONF_GLOSSARY_OVERRIDES, "") or ""
    )
    await coordinator.async_start()

    entry.runtime_data = coordinator

    fm = coordinator.blaueis_follow_me
    fm.configure_guards(entry.options)
    # Invariant: Enabled cannot outlive Configured. If a stored
    # combination has Configured=False with Enabled=True (e.g. from a
    # hand-edited config_entries.json or a pre-invariant install),
    # normalise once at setup so the FM manager and the entity
    # registry visibility helper see consistent state.
    _enforce_fmf_invariant(hass, entry)
    configured = entry.options.get(CONF_FMF_CONFIGURED, False)
    enabled = entry.options.get(CONF_FMF_ENABLED, False)
    source = entry.options.get(CONF_FMF_SENSOR)
    if configured and enabled and source:
        try:
            await fm.async_start(source)
        except Exception:
            _LOGGER.warning("Follow Me Function auto-start failed")

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Generic cleanup: any HA entity owned by this entry whose unique_id
    # suffix matches a glossary field name that's NOT in the current
    # available_fields gets removed from the registry. Catches stale
    # entities left behind by cap changes (B5 update, override flip,
    # firmware repair) without per-field bespoke migration code.
    _cleanup_orphaned_field_entities(hass, entry, coordinator)

    # Reconcile the Follow Me switch's registration with the master
    # "Configured" flag. Adds the switch dynamically when Configured is
    # on (and somehow missing), purges it from the entity registry when
    # Configured is off. The unique_id is stable, so HA re-uses the
    # same entity_id when the switch is added back.
    _sync_fm_switch_registration(hass, entry, coordinator)

    # Register the field-inventory service + HTTP view (global,
    # registered on first entry setup; no-op on subsequent entries).
    from .field_inventory import async_setup_field_inventory

    await async_setup_field_inventory(hass, entry)

    # Register the debug-only test_suppress service (idempotent).
    from ._test_suppress import async_setup_test_suppress

    await async_setup_test_suppress(hass)

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: BlaueisMideaConfigEntry
) -> None:
    """Reconcile Follow Me Function + Display/Buzzer mode with runtime state."""
    coordinator: BlaueisMideaCoordinator = entry.runtime_data

    # Enforce the Configured ⇒ Enabled invariant before reading state.
    # If the user just unticked Configured while Enabled was still on,
    # this writes Enabled=False back to options. async_update_entry
    # re-fires this listener, so we early-return and let the second
    # pass do the actual reconciliation against the corrected state.
    if _enforce_fmf_invariant(hass, entry):
        return

    configured = entry.options.get(CONF_FMF_CONFIGURED, False)
    enabled = entry.options.get(CONF_FMF_ENABLED, False)
    source = entry.options.get(CONF_FMF_SENSOR)
    fm = coordinator.blaueis_follow_me

    if configured and enabled and source:
        fm.configure_guards(entry.options)
        if fm.active:
            if fm.source_entity_id != source:
                await fm.async_stop()
                await fm.async_start(source)
        else:
            await fm.async_start(source)
    else:
        if fm.active or fm._stopping:
            await fm.async_stop()

    # Mirror Configured → switch registration (add or purge).
    _sync_fm_switch_registration(hass, entry, coordinator)
    coordinator.fire_entity_callbacks("follow_me")
    # Notify the Display & Buzzer mode select that its backing option may
    # have changed. The entity registers a callback on this synthetic
    # field name in async_added_to_hass and uses the callback to refresh
    # its current_option AND kick the enforcer so the new policy takes
    # effect immediately (otherwise we'd wait for the next rsp_*
    # ingress to re-evaluate). Without this, picking forced_on/off in
    # the Configure dialog wouldn't propagate to either the entity UI
    # or the enforcer until the next AC state change.
    coordinator.fire_entity_callbacks("_display_buzzer_mode")

    # If the glossary-override YAML changed, the patched glossary view on
    # Device is built at __init__ and is therefore stale. Reload the
    # entire config entry so Device is rebuilt with the new view and
    # entities are recreated against the new available_fields. This is
    # the same path a fresh setup takes — clean, no special-case state.
    if _override_changed(entry):
        _LOGGER.info("Glossary override changed — reloading config entry to apply")
        await hass.config_entries.async_reload(entry.entry_id)
        return


async def async_unload_entry(
    hass: HomeAssistant, entry: BlaueisMideaConfigEntry
) -> bool:
    """Unload a config entry."""
    coordinator: BlaueisMideaCoordinator = entry.runtime_data

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # Unlink any outstanding inventory tempfiles for this entry.
        from .field_inventory import async_teardown_field_inventory

        await async_teardown_field_inventory(hass, entry)
        await coordinator.async_stop()
        _uninstall_debug_ring(entry)

    return unload_ok


# ── Field-rename migration ─────────────────────────────────────────────


def _migrate_renamed_unique_ids(
    hass: HomeAssistant,
    entry: BlaueisMideaConfigEntry,
) -> None:
    """Rewrite entity_registry unique_ids for fields whose canonical name
    changed in the glossary.

    Unique_ids are of the form ``{host}_{port}_{field_name}``. For every
    entry in ``_FIELD_RENAMES`` this walks the registry, finds entities
    whose unique_id ends with ``_<old_name>`` and belongs to this
    config_entry, and rewrites the tail to ``_<new_name>``. Entity_id,
    history, and dashboards / automations referencing the entity_id are
    preserved by HA's registry semantics.

    Safe to run on every setup — idempotent once no old unique_ids remain.
    """
    from homeassistant.helpers import entity_registry as er

    if not _FIELD_RENAMES:
        return
    reg = er.async_get(hass)
    renamed = 0
    for ent in list(reg.entities.values()):
        if ent.config_entry_id != entry.entry_id:
            continue
        for old_name, new_name in _FIELD_RENAMES.items():
            old_suffix = f"_{old_name}"
            if ent.unique_id.endswith(old_suffix):
                new_uid = ent.unique_id[: -len(old_suffix)] + f"_{new_name}"
                reg.async_update_entity(ent.entity_id, new_unique_id=new_uid)
                _LOGGER.info(
                    "Migrated unique_id: %s %s → %s",
                    ent.entity_id,
                    ent.unique_id,
                    new_uid,
                )
                renamed += 1
                break
    if renamed:
        _LOGGER.info("Field-rename migration: %d entity ids updated", renamed)


# ── Glossary override helpers ──────────────────────────────────────────


def _parse_stored_overrides(entry: BlaueisMideaConfigEntry) -> dict | None:
    """Re-parse the YAML override text stored in the config entry.

    Returns the parsed override dict or ``None`` if no override is set.
    On parse failure (should not happen — config_flow validates on save —
    but possible if someone hand-edited config_entries.json) logs and
    returns ``None`` so the integration still loads.
    """
    raw = entry.options.get(CONF_GLOSSARY_OVERRIDES)
    if not raw:
        return None
    try:
        parsed, _affected, messages = validate_and_parse_overrides(raw)
    except GlossaryOverrideError as err:
        _LOGGER.warning(
            "Stored glossary override failed re-validation; ignoring. Error: %s",
            err,
        )
        return None
    for m in messages:
        where = m.field or "<top>"
        if m.severity in ("error", "warning"):
            _LOGGER.warning("Glossary override [%s] %s: %s", m.code, where, m.message)
        else:
            _LOGGER.info("Glossary override [%s] %s: %s", m.code, where, m.message)
    return parsed


def _override_changed(entry: BlaueisMideaConfigEntry) -> bool:
    """True if the stored override YAML differs from what's currently
    applied on the coordinator. Compares raw text — no parsing — so the
    check is cheap and avoids reload thrash on equivalent reformats
    (those are rare and a reload is not a destructive operation anyway)."""
    coord = entry.runtime_data
    current = entry.options.get(CONF_GLOSSARY_OVERRIDES, "") or ""
    applied = getattr(coord, "_applied_override_yaml", "") or ""
    return current != applied


# ── Follow Me Function key migration ────────────────────────────────────


def _migrate_fmf_keys(
    hass: HomeAssistant,
    entry: BlaueisMideaConfigEntry,
) -> None:
    """Rewrite legacy Follow Me option keys to their new names.

    The flag semantics are unchanged; only the key strings move so the
    storage names match the user-visible labels:

      ``follow_me_function_enabled`` (old master)  → ``follow_me_function_configured``
      ``follow_me_function_armed``   (old engage)  → ``follow_me_function_enabled``

    Order matters — rename the master first, freeing the
    ``follow_me_function_enabled`` slot for the engage flag's new home.
    Idempotent: a second call is a no-op once the new keys are present.
    """
    opts = dict(entry.options)
    changed = False

    OLD_MASTER = "follow_me_function_enabled"
    OLD_ENGAGE = "follow_me_function_armed"
    NEW_MASTER = "follow_me_function_configured"
    NEW_ENGAGE = "follow_me_function_enabled"

    # Step 1: old master → new master (frees OLD_MASTER for step 2).
    if OLD_MASTER in opts and NEW_MASTER not in opts:
        opts[NEW_MASTER] = opts.pop(OLD_MASTER)
        changed = True

    # Step 2: old engage → new engage (which lives at OLD_MASTER's name).
    if OLD_ENGAGE in opts and NEW_ENGAGE not in opts:
        opts[NEW_ENGAGE] = opts.pop(OLD_ENGAGE)
        changed = True

    if changed:
        _LOGGER.info(
            "Follow Me: migrated legacy option keys → "
            "follow_me_function_configured, follow_me_function_enabled"
        )
        hass.config_entries.async_update_entry(entry, options=opts)


# ── Follow Me invariant: Configured ⇒ Enabled ─────────────────────────


def _enforce_fmf_invariant(
    hass: HomeAssistant,
    entry: BlaueisMideaConfigEntry,
) -> bool:
    """Force-clear the Enabled flag when Configured is off.

    Returns True if a correction was applied (caller should treat it
    as a re-fire-pending). Returns False when the state was already
    consistent and no write happened.

    Rationale: the on/off switch on the device card and the menu's
    "Enabled" checkbox are the same persistent flag. When the user
    unticks Configured (e.g. they're tearing down the integration or
    swapping sensors), letting Enabled stay True would silently arm
    Follow Me again the moment they re-tick Configured — dangerous
    given Follow Me overrides the AC's own thermistor reading. Auto-
    clearing keeps the persisted state matching the user's intent at
    the time of the last save.
    """
    configured = entry.options.get(CONF_FMF_CONFIGURED, False)
    enabled = entry.options.get(CONF_FMF_ENABLED, False)
    if configured or not enabled:
        return False
    new_opts = {**entry.options, CONF_FMF_ENABLED: False}
    hass.config_entries.async_update_entry(entry, options=new_opts)
    _LOGGER.info(
        "Follow Me: Configured=False — auto-clearing Enabled "
        "to keep persisted state consistent"
    )
    return True


# ── Follow Me switch registration ───────────────────────────────────────


def _sync_fm_switch_registration(
    hass: HomeAssistant,
    entry: BlaueisMideaConfigEntry,
    coordinator: BlaueisMideaCoordinator,
) -> None:
    """Add or purge the Follow Me switch to match the ``Configured``
    master flag.

    Configured=True with the entity missing → dynamic add via the
    ``async_add_entities`` callback that ``switch.async_setup_entry``
    stashed on the coordinator. No entry reload required.

    Configured=False with the entity present → ``async_remove`` from
    the entity registry. The switch's ``async_will_remove_from_hass``
    handles graceful FM-manager teardown.

    Re-ticking Configured creates a fresh entity instance; HA matches
    on the stable ``unique_id`` and re-uses the same ``entity_id``.
    """
    from homeassistant.helpers import entity_registry as er

    from .switch import BlauiesFollowMeSwitch

    reg = er.async_get(hass)
    unique_id = f"{coordinator.host}_{coordinator.port}_blaueis_follow_me"
    ent_id = reg.async_get_entity_id("switch", DOMAIN, unique_id)
    configured = entry.options.get(CONF_FMF_CONFIGURED, False)

    if configured and ent_id is None:
        add_entities = getattr(coordinator, "_fm_switch_add_entities", None)
        if add_entities is None:
            # switch.async_setup_entry hasn't run yet — it will create
            # the switch itself when it does, gated on Configured.
            return
        add_entities([BlauiesFollowMeSwitch(coordinator, entry)])
        _LOGGER.info("Follow Me switch added (Configured=True)")
    elif not configured and ent_id is not None:
        reg.async_remove(ent_id)
        _LOGGER.info(
            "Follow Me switch %s purged from registry (Configured=False)",
            ent_id,
        )


# ── Display & Buzzer mode migration ────────────────────────────────────


def _migrate_display_buzzer_options(
    hass: HomeAssistant,
    entry: BlaueisMideaConfigEntry,
) -> None:
    """Migrate legacy ``display_buzzer_mode`` option values in the config
    entry to the current policy keys.

    Legacy keys (``auto``/``permanent_on``/``permanent_off``) are rewritten
    in place to ``non_enforced``/``forced_on``/``forced_off``. If the
    stored value is already a valid policy key, or the option is absent,
    this is a no-op.
    """
    raw = entry.options.get(CONF_DISPLAY_BUZZER_MODE)
    if raw is None or raw in DISPLAY_BUZZER_POLICIES:
        return
    new_value = DISPLAY_BUZZER_LEGACY_MIGRATION.get(raw)
    if new_value is None:
        _LOGGER.warning(
            "Unknown %s value %r in config entry — leaving as-is",
            CONF_DISPLAY_BUZZER_MODE,
            raw,
        )
        return
    new_options = {**entry.options, CONF_DISPLAY_BUZZER_MODE: new_value}
    hass.config_entries.async_update_entry(entry, options=new_options)
    _LOGGER.info(
        "Migrated %s: %r → %r",
        CONF_DISPLAY_BUZZER_MODE,
        raw,
        new_value,
    )


def _cleanup_orphaned_field_entities(
    hass: HomeAssistant,
    entry: BlaueisMideaConfigEntry,
    coordinator: BlaueisMideaCoordinator,
) -> None:
    """Generic sweep: remove HA-registry entities for fields that are
    no longer in ``coord.device.available_fields``.

    Algorithm:
      1. Build the set of glossary field names (the un-filtered universe).
      2. Walk the HA entity registry for entries owned by this config
         entry.
      3. For each entry, extract the candidate field name from the
         ``unique_id`` suffix (after ``{host}_{port}_``).
      4. If the suffix is a known glossary field name AND that field is
         NOT in ``available_fields``, remove the entity from the registry.

    Two passes:

    1. **Field-driven entities.** Suffix matches a known glossary field
       name AND that field is not in ``available_fields`` → remove.
       Synthetic entities (suffixes that aren't glossary fields) skip
       this pass.

    2. **Synthetic entities with declared cap dependencies.** Suffix
       is in ``SYNTHETIC_ENTITY_CAP_DEPENDENCIES`` AND any required
       field is missing from ``available_fields`` → remove. Synthetic
       entities with empty dependency sets are never auto-removed.
       Synthetic entities NOT in the catalog are also left alone (the
       integration owns them; they can declare a dependency by being
       added to the catalog).

    Replaces the prior bespoke ``_remove_stale_screen_display_switch``
    helper.
    """
    from blaueis.core.codec import walk_fields
    from homeassistant.helpers import entity_registry as er

    all_field_names = set(walk_fields(coordinator.device.glossary).keys())
    available = set(coordinator.device.available_fields.keys())

    prefix = f"{coordinator.host}_{coordinator.port}_"
    reg = er.async_get(hass)
    removed = 0
    for ent in list(reg.entities.values()):
        if ent.config_entry_id != entry.entry_id:
            continue
        if not ent.unique_id.startswith(prefix):
            continue
        suffix = ent.unique_id[len(prefix) :]

        # Pass 1: glossary-field-driven.
        if suffix in all_field_names:
            if suffix in available:
                continue  # field still advertised — entity belongs
            _LOGGER.info(
                "Removing orphaned field entity %s (unique_id=%s) — "
                "field %r no longer in available_fields",
                ent.entity_id,
                ent.unique_id,
                suffix,
            )
            reg.async_remove(ent.entity_id)
            removed += 1
            continue

        # Pass 2: synthetic with declared cap dependency.
        deps = SYNTHETIC_ENTITY_CAP_DEPENDENCIES.get(suffix)
        if deps is None:
            continue  # not in catalog → integration owns it, leave alone
        if not deps:
            continue  # no dependencies → never auto-remove
        missing = deps - available
        if not missing:
            continue  # all required fields present
        _LOGGER.info(
            "Removing orphaned synthetic entity %s (unique_id=%s) — "
            "required cap field(s) %s no longer in available_fields",
            ent.entity_id,
            ent.unique_id,
            sorted(missing),
        )
        reg.async_remove(ent.entity_id)
        removed += 1

    if removed:
        _LOGGER.info(
            "Cleaned up %d orphaned entit%s",
            removed,
            "y" if removed == 1 else "ies",
        )


# ── DebugRing plumbing ─────────────────────────────────────────────────


def _install_debug_ring(entry: BlaueisMideaConfigEntry):
    """Create a per-entry DebugRing, attach it to the blaueis loggers.

    Ring level = VERBOSE, named-logger level raised to VERBOSE so records
    reach the handler. `propagate` is left untouched (default True) so that
    INFO+ records still appear in homeassistant.log. The ring observes
    everything; HA's handlers filter at their own level.
    """
    from blaueis.core.debug_ring import DebugRing

    logging.addLevelName(_VERBOSE, "VERBOSE")

    ring = DebugRing(size_bytes=DEBUG_RING_SIZE_MB * 1024 * 1024)
    ring.setLevel(_VERBOSE)

    attached: list[logging.Logger] = []
    for name in _RING_LOGGERS:
        lg = logging.getLogger(name)
        lg.setLevel(_VERBOSE)
        lg.addHandler(ring)
        attached.append(lg)

    # Stash so unload can detach cleanly via _uninstall_debug_ring.
    entry._blaueis_ring = ring  # type: ignore[attr-defined]
    entry._blaueis_ring_loggers = attached  # type: ignore[attr-defined]
    _LOGGER.debug(
        "DebugRing attached to %d loggers (%d MB)",
        len(attached),
        DEBUG_RING_SIZE_MB,
    )
    return ring


def _uninstall_debug_ring(entry: BlaueisMideaConfigEntry) -> None:
    ring = getattr(entry, "_blaueis_ring", None)
    loggers = getattr(entry, "_blaueis_ring_loggers", None) or []
    if ring is None:
        return
    for lg in loggers:
        lg.removeHandler(ring)
    ring.clear()
