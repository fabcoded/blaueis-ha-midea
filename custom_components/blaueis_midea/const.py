"""Constants for the Blaueis Midea integration."""

DOMAIN = "blaueis_midea"

CONF_PSK = "psk"

# Flight-recorder ring size, per-config-entry.
# See blaueis-libmidea/docs/flight_recorder.md §3.2 — ~35 k records / ~35 min
# of capture at 10 Hz UART + 5 Hz loop traffic.
DEBUG_RING_SIZE_MB = 5

# ── Climate preset fields ──────────────────────────────────
# Mutually exclusive performance/comfort presets.
# Setting one clears all others. B5-gated: only confirmed fields appear.
CLIMATE_PRESET_FIELDS = {
    "turbo_mode": "Turbo",
    "eco_mode": "ECO",
    "sleep_mode": "Sleep",
    "frost_protection": "Frost Protection",
}
PRESET_NAME_TO_FIELD = {v: k for k, v in CLIMATE_PRESET_FIELDS.items()}

# ── Climate field sets (two separate concerns) ─────────────

# Fields that trigger a climate entity state refresh.
# Any change to these fires the _climate callback.
CLIMATE_CALLBACK_FIELDS = frozenset({
    "power",
    "operating_mode",
    "target_temperature",
    "fan_speed",
    "indoor_temperature",
    "swing_vertical",
    "swing_horizontal",
    *CLIMATE_PRESET_FIELDS.keys(),
})

# Fields consumed exclusively by the climate entity.
# These are NOT created as standalone entities (no separate switch/sensor).
# Note: power and indoor_temperature are NOT here — power has no standalone
# switch (climate on/off handles it), but indoor_temperature IS a standalone
# sensor in addition to being climate's current_temperature.
CLIMATE_EXCLUSIVE_FIELDS = frozenset({
    "operating_mode",
    "target_temperature",
    "fan_speed",
    *CLIMATE_PRESET_FIELDS.keys(),
})

# ── Glossary field_class → HA entity type mapping ──────────
# writable=True/False selects the column.
FIELD_CLASS_MAP = {
    #                       writable      read-only
    "stateful_bool":       ("switch",     "binary_sensor"),
    "stateful_enum":       ("select",     "sensor"),
    "stateful_numeric":    ("number",     "sensor"),
    "sensor":              (None,         "sensor"),
    "binary_sensor":       ("binary_sensor", "binary_sensor"),
}

# ── Follow Me Function config options ─────────────────────
# CONF_FMF_CONFIGURED  — master availability flag. "Is this feature
#                        properly set up?" Gates whether the on/off
#                        switch is shown on the device card.
# CONF_FMF_ENABLED     — engage state. The on/off switch IS this option:
#                        toggle the switch → the option flips, save
#                        the option → the switch reflects the new state.
# Both flags appear in the Configure menu; only the Enabled one also
# surfaces as a switch on the device card (and only when Configured).
#
# Storage keys preserved across restarts via entry.options. Legacy keys
# (``follow_me_function_enabled`` for old master, ``follow_me_function_armed``
# for old engage) are migrated by ``_migrate_fmf_keys`` in __init__.py.
CONF_FMF_CONFIGURED     = "follow_me_function_configured"
CONF_FMF_ENABLED        = "follow_me_function_enabled"
CONF_FMF_GUARD_TEMP_MAX = "follow_me_function_guard_temp_max"
CONF_FMF_GUARD_TEMP_MIN = "follow_me_function_guard_temp_min"
CONF_FMF_SAFETY_TIMEOUT = "follow_me_function_safety_timeout"
CONF_FMF_SENSOR         = "follow_me_function_sensor"

# ── Midea operating_mode enum → HA HVACMode ────────────────
MODE_MIDEA_TO_HA = {
    1: "auto",
    2: "cool",
    3: "dry",
    4: "heat",
    5: "fan_only",
}
MODE_HA_TO_MIDEA = {v: k for k, v in MODE_MIDEA_TO_HA.items()}

# ── Fan speed presets ──────────────────────────────────────
DEFAULT_FAN_PRESETS = {
    "auto": 102,
    "low": 40,
    "medium": 60,
    "high": 80,
}
FAN_PRESET_TO_SPEED = DEFAULT_FAN_PRESETS
FAN_SPEED_TO_PRESET = {v: k for k, v in DEFAULT_FAN_PRESETS.items()}

# ── Display & Buzzer mode (Finding 07 §4.8 / §4.9) ────────
# The AC's display-LED latch globally gates the indoor-unit buzzer:
# cmd_0xb0 writes are silent while the latch is OFF. The model exposes
# a single select to the user that covers both "policy" and "immediate
# state": one widget, no split between switch.screen_display and a
# separate mode select.
#
#   stored policy (config entry):
#     - non_enforced (default) — no enforcer, user drives on/off directly
#     - forced_on            — enforcer keeps display ON
#     - forced_off           — enforcer keeps display OFF
#
#   entity options (what the user sees):
#     - on         — non-enforced, current state is ON  (picking it sends
#                    one toggle if currently OFF)
#     - off        — non-enforced, current state is OFF (picking it sends
#                    one toggle if currently ON)
#     - forced_on  — forced ON, enforcer active
#     - forced_off — forced OFF, enforcer active
#
# When the stored policy is non_enforced, current_option mirrors live
# state so picking `on`/`off` writes only when there's drift.

CONF_DISPLAY_BUZZER_MODE = "display_buzzer_mode"

# Glossary override — multiline YAML text entered in the Configure
# dialog's Advanced section. Stored verbatim (string), parsed on
# every entry load. See ``_glossary_override.py`` for validation.
CONF_GLOSSARY_OVERRIDES = "glossary_overrides_yaml"

# Synthetic-entity → required-cap-field map.
#
# Used by ``_cleanup_orphaned_field_entities`` to extend the
# pattern-based field-entity sweep to entities whose unique_id suffix
# is NOT a glossary field name (so the field-name check skips them)
# but which still depend on one or more glossary fields being in
# ``available_fields`` to make sense.
#
# The key is the unique_id suffix (after ``{host}_{port}_``); the
# value is the set of glossary field names the entity needs. If ANY of
# the required fields is missing from ``available_fields``, the entity
# is removed from the HA registry on next setup. Empty set means "no
# cap dependency, never auto-remove".
SYNTHETIC_ENTITY_CAP_DEPENDENCIES: dict[str, set[str]] = {
    "display_buzzer_mode": {"screen_display"},
    "blaueis_follow_me": set(),  # always-available; no cap gate
}

# Stored policy keys (persisted in config entry options).
DISPLAY_BUZZER_POLICY_NON_ENFORCED = "non_enforced"
DISPLAY_BUZZER_POLICY_FORCED_ON = "forced_on"
DISPLAY_BUZZER_POLICY_FORCED_OFF = "forced_off"
DISPLAY_BUZZER_POLICIES = (
    DISPLAY_BUZZER_POLICY_NON_ENFORCED,
    DISPLAY_BUZZER_POLICY_FORCED_ON,
    DISPLAY_BUZZER_POLICY_FORCED_OFF,
)
DISPLAY_BUZZER_MODE_DEFAULT = DISPLAY_BUZZER_POLICY_NON_ENFORCED

# Entity-visible options.
DISPLAY_BUZZER_OPTION_ON = "on"
DISPLAY_BUZZER_OPTION_OFF = "off"
DISPLAY_BUZZER_OPTION_FORCED_ON = DISPLAY_BUZZER_POLICY_FORCED_ON
DISPLAY_BUZZER_OPTION_FORCED_OFF = DISPLAY_BUZZER_POLICY_FORCED_OFF
DISPLAY_BUZZER_OPTIONS = (
    DISPLAY_BUZZER_OPTION_ON,
    DISPLAY_BUZZER_OPTION_OFF,
    DISPLAY_BUZZER_OPTION_FORCED_ON,
    DISPLAY_BUZZER_OPTION_FORCED_OFF,
)

# Legacy-key migration map, applied once on config-entry load.
# Earlier installs used `auto`/`permanent_on`/`permanent_off` as the
# stored mode. These map 1:1 to the new policy keys.
DISPLAY_BUZZER_LEGACY_MIGRATION = {
    "auto": DISPLAY_BUZZER_POLICY_NON_ENFORCED,
    "permanent_on": DISPLAY_BUZZER_POLICY_FORCED_ON,
    "permanent_off": DISPLAY_BUZZER_POLICY_FORCED_OFF,
}
