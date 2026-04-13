"""Constants for the Blaueis Midea integration."""

DOMAIN = "blaueis_midea"

CONF_PSK = "psk"

# Fields that fold into the climate entity — never exposed as standalone entities.
CLIMATE_FIELDS = frozenset({
    "operating_mode",
    "target_temperature",
    "fan_speed",
})

# Glossary field_class → HA entity type mapping.
# writable=True/False selects the column.
FIELD_CLASS_MAP = {
    #                       writable      read-only
    "stateful_bool":       ("switch",     "binary_sensor"),
    "stateful_enum":       ("select",     "sensor"),
    "stateful_numeric":    ("number",     "sensor"),
    "sensor":              (None,         "sensor"),
}

# Midea operating_mode enum → HA HVACMode
MODE_MIDEA_TO_HA = {
    1: "auto",
    2: "cool",
    3: "dry",
    4: "heat",
    5: "fan_only",
}
MODE_HA_TO_MIDEA = {v: k for k, v in MODE_MIDEA_TO_HA.items()}

# Fan speed presets (default, overridable via overlay YAML)
DEFAULT_FAN_PRESETS = {
    "auto": 102,
    "low": 40,
    "medium": 60,
    "high": 80,
}
FAN_PRESET_TO_SPEED = DEFAULT_FAN_PRESETS
FAN_SPEED_TO_PRESET = {v: k for k, v in DEFAULT_FAN_PRESETS.items()}
