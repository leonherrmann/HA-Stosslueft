"""Diagnostics for Stoßlüften."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from . import StoslueftConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: StoslueftConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "data": dict(entry.data),
        "options": dict(entry.options),
        "state": {
            "score": data.score,
            "rating": data.overall.rating,
            "reason_key": data.overall.reason_key,
            "indoor_temperature": data.indoor_temperature,
            "indoor_humidity": data.indoor_humidity,
            "outdoor_temperature": data.outdoor_temperature,
            "outdoor_humidity": data.outdoor_humidity,
            "outdoor_condition": data.outdoor_condition,
            "cooldown_today": data.cooldown_today,
            "rooms": [room.as_dict() for room in data.rooms],
            "active_session": data.active_session,
            "last_session": data.last_session,
        },
    }
