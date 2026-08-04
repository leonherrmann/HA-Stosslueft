"""Binary sensors for Stoßlüften."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import StoslueftCoordinator
from .entity import StoslueftEntity

if TYPE_CHECKING:
    from . import StoslueftConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StoslueftConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [AiringRecommendedSensor(coordinator), AiringActiveSensor(coordinator)]
    )


class AiringRecommendedSensor(StoslueftEntity, BinarySensorEntity):
    """On while the overall score clears the recommendation threshold."""

    _attr_translation_key = "airing_recommended"
    _attr_icon = "mdi:window-open"

    def __init__(self, coordinator: StoslueftCoordinator) -> None:
        """Initialise the binary sensor."""
        super().__init__(coordinator, "airing_recommended")

    @property
    def is_on(self) -> bool:
        """Whether airing out is a good idea right now."""
        return self.data.airing_recommended

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Score, threshold and the rooms that would benefit most."""
        data = self.data
        return {
            "score": data.score,
            "rating": data.overall.rating,
            "reason": data.overall.reason,
            "threshold": data.recommend_threshold,
            "rooms": [
                room.name
                for room in sorted(
                    data.rooms, key=lambda room: room.score.score, reverse=True
                )
                if room.score.score >= data.recommend_threshold
            ],
        }


class AiringActiveSensor(StoslueftEntity, BinarySensorEntity):
    """On while at least one window is open."""

    _attr_translation_key = "airing_active"
    _attr_icon = "mdi:weather-windy"

    def __init__(self, coordinator: StoslueftCoordinator) -> None:
        """Initialise the binary sensor."""
        super().__init__(coordinator, "airing_active")

    @property
    def is_on(self) -> bool:
        """Whether an airing session is running."""
        return self.data.airing_active

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Live progress of the running session."""
        session = self.data.active_session
        if session is None:
            return {}
        rooms_by_id = {room["room_id"]: room for room in session.get("rooms", [])}
        open_rooms = [
            rooms_by_id[room_id]["name"]
            for room_id in session.get("open_rooms", [])
            if room_id in rooms_by_id
        ]
        # Compare the running minimum against the starting temperature so the
        # attribute shows what has been gained so far, mid-session.
        gained = [
            room["temperature_start"] - room["temperature_min"]
            for room in session.get("rooms", [])
            if room.get("temperature_start") is not None
            and room.get("temperature_min") is not None
        ]
        return {
            "started": session.get("started"),
            "duration_minutes": session.get("duration_minutes"),
            "at_night": session.get("at_night"),
            "open_rooms": sorted(open_rooms),
            "cooldown_so_far": round(sum(gained) / len(gained), 2) if gained else None,
        }
