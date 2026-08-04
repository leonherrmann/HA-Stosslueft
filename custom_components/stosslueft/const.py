"""Constants for the Stoßlüften integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "stosslueft"

# Frontend
CARD_FILENAME: Final = "stosslueft-card.js"
CARD_URL: Final = f"/{DOMAIN}/{CARD_FILENAME}"
DATA_FRONTEND_REGISTERED: Final = "frontend_registered"

# Events
EVENT_AIRING_FINISHED: Final = f"{DOMAIN}_airing_finished"

# Config entry data (set once, at setup)
CONF_OUTDOOR_TEMPERATURE: Final = "outdoor_temperature"
CONF_OUTDOOR_HUMIDITY: Final = "outdoor_humidity"

# Config entry options
CONF_ROOMS: Final = "rooms"
CONF_TARGET_TEMPERATURE: Final = "target_temperature"
CONF_COMFORT_BAND: Final = "comfort_band"
CONF_HUMIDITY_WEIGHT: Final = "humidity_weight"
CONF_RECOMMEND_THRESHOLD: Final = "recommend_threshold"
CONF_SETTLE_MINUTES: Final = "settle_minutes"
CONF_MIN_SESSION_MINUTES: Final = "min_session_minutes"
CONF_RAIN_GUARD: Final = "rain_guard"

# Per-room option keys
CONF_ROOM_ID: Final = "room_id"
CONF_NAME: Final = "name"
CONF_TEMPERATURE_ENTITY: Final = "temperature_entity"
CONF_HUMIDITY_ENTITY: Final = "humidity_entity"
CONF_WINDOW_ENTITY: Final = "window_entity"

# Option defaults
DEFAULT_TARGET_TEMPERATURE: Final = 21.0
DEFAULT_COMFORT_BAND: Final = 1.5
DEFAULT_HUMIDITY_WEIGHT: Final = 0.2
DEFAULT_RECOMMEND_THRESHOLD: Final = 65
DEFAULT_SETTLE_MINUTES: Final = 10
DEFAULT_MIN_SESSION_MINUTES: Final = 2
DEFAULT_RAIN_GUARD: Final = True

# Scoring model constants. These are deliberately not user configurable: they
# describe the physics of a flat, not a preference. See scoring.py.
K_DUR: Final = 120.0  # K*min, maps |dT| to a sensible airing duration
MIN_DURATION: Final = 4.0  # minutes
MAX_DURATION: Final = 25.0  # minutes
TAU_AIR: Final = 8.0  # minutes, air exchange time constant with windows wide open
BETA_MASS: Final = 0.35  # fraction of the air temperature change that survives
K_TEMP: Final = 2.0  # K of improvement that scores full marks
K_AH: Final = 3.0  # g/m3 of drying benefit that scores full marks
RH_HIGH: Final = 60.0  # % where humidity starts to outweigh temperature
RH_CRIT: Final = 70.0  # % where humidity fully outweighs temperature

# Rain guard
RAINY_CONDITIONS: Final = frozenset(
    {"rainy", "pouring", "snowy-rainy", "hail", "lightning-rainy"}
)
RAIN_SCORE_CAP: Final = 40

# Rating thresholds, best first. Three levels on purpose: the useful question
# is "open the windows or not", and five shades of that were just noise. The
# 0-100 number is still there underneath for automations and for telling two
# good moments apart.
RATING_THRESHOLDS: Final = (
    (65, "good"),
    (35, "neutral"),
    (0, "bad"),
)

# Marks the unique ids that belong to a room rather than to the whole flat.
ROOM_UNIQUE_ID_PREFIX: Final = "room_"

# Per-room entity keys. Must not contain an underscore: setup splits a room
# unique id on the last one to recover the room id. Also drives the migration
# of pre-0.2.0 unique ids, so keep it in step with the room entities.
ROOM_KEY_SCORE: Final = "score"
ROOM_KEY_COOLDOWN: Final = "cooldown"
ROOM_ENTITY_KEYS: Final = (ROOM_KEY_SCORE, ROOM_KEY_COOLDOWN)

UPDATE_INTERVAL_SECONDS: Final = 60
STORAGE_VERSION: Final = 1
