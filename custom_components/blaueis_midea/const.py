"""Constants for the Blaueis Midea integration."""

DOMAIN = "blaueis_midea"

CONF_PSK = "psk"

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
}

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
