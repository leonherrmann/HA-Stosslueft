"""Sensors for Stoßlüften."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import RoomConfig, StoslueftCoordinator
from .entity import StoslueftEntity, StoslueftRoomEntity

if TYPE_CHECKING:
    from . import StoslueftConfigEntry

# Cooldowns are temperature *differences*, so they carry no device class: a
# 2 °C drop is a 2 K difference, not a temperature that should be converted.
DELTA_UNIT = UnitOfTemperature.CELSIUS


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StoslueftConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        AiringScoreSensor(coordinator),
        IndoorTemperatureSensor(coordinator),
        LastCooldownSensor(coordinator),
        CooldownTodaySensor(coordinator),
    ]
    for room in coordinator.rooms:
        entities.append(RoomScoreSensor(coordinator, room))
        # No window contact means the room is never aired directly, so there
        # is no cooldown to attribute to it -- but it is still scored above.
        if room.temperature_entity and room.window_entity:
            entities.append(RoomCooldownSensor(coordinator, room))
    async_add_entities(entities)


class AiringScoreSensor(StoslueftEntity, SensorEntity):
    """How good an idea it is to open every window right now."""

    _attr_translation_key = "score"
    _attr_icon = "mdi:window-open-variant"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: StoslueftCoordinator) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, "score")

    @property
    def native_value(self) -> int:
        """The overall score, 0-100."""
        return self.data.score

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Everything the dashboard card needs, from a single entity."""
        data = self.data
        rooms = sorted(
            (room for room in data.rooms if room.score.reason_key != "no_data"),
            key=lambda room: room.score.score,
        )
        return {
            "rating": data.overall.rating,
            "reason": data.overall.reason,
            "reason_key": data.overall.reason_key,
            "reason_placeholders": data.overall.reason_placeholders,
            "duration_minutes": data.overall.duration_minutes,
            "blocked_reason": data.overall.blocked_reason,
            "recommend_threshold": data.recommend_threshold,
            "indoor_temperature": _round(data.indoor_temperature, 1),
            "indoor_humidity": _round(data.indoor_humidity, 1),
            "outdoor_temperature": _round(data.outdoor_temperature, 1),
            "outdoor_humidity": _round(data.outdoor_humidity, 1),
            "outdoor_condition": data.outdoor_condition,
            "temperature_delta": _round(
                None
                if data.outdoor_temperature is None or data.indoor_temperature is None
                else data.outdoor_temperature - data.indoor_temperature,
                1,
            ),
            "worst_room": rooms[0].name if rooms else None,
            "best_room": rooms[-1].name if rooms else None,
            "rooms_recommended": sum(
                1 for room in rooms if room.score.score >= data.recommend_threshold
            ),
            "rooms": [room.as_dict() for room in data.rooms],
            "airing_active": data.airing_active,
            "active_session": data.active_session,
            "last_session": data.last_session,
            "cooldown_today": data.cooldown_today,
        }


class RoomScoreSensor(StoslueftRoomEntity, SensorEntity):
    """How good an idea it is to open this room's window."""

    _attr_translation_key = "room_score"
    _attr_icon = "mdi:window-open-variant"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: StoslueftCoordinator, room: RoomConfig) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, room, "score")

    @property
    def native_value(self) -> int | None:
        """The room's score, 0-100."""
        room = self.data.room(self._room.room_id)
        return None if room is None else room.score.score

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Why the room scored what it scored."""
        room = self.data.room(self._room.room_id)
        if room is None:
            return {}
        score = room.score
        return {
            "rating": score.rating,
            "reason": score.reason,
            "reason_key": score.reason_key,
            "duration_minutes": score.duration_minutes,
            "blocked_reason": score.blocked_reason,
            "temperature": _round(room.temperature, 1),
            "humidity": _round(room.humidity, 1),
            "projected_temperature": score.projected_temperature,
            "temperature_component": score.temperature_component,
            "humidity_component": score.humidity_component,
            "applied_humidity_weight": score.applied_humidity_weight,
            "window_open": room.window_open,
            "has_window_sensor": room.config.window_entity is not None,
            "last_cooldown": _round(room.last_cooldown, 2),
        }


class IndoorTemperatureSensor(StoslueftEntity, SensorEntity):
    """Average temperature across all configured rooms."""

    _attr_translation_key = "indoor_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: StoslueftCoordinator) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, "indoor_temperature")

    @property
    def native_value(self) -> float | None:
        """The flat's average indoor temperature."""
        return _round(self.data.indoor_temperature, 2)


class LastCooldownSensor(StoslueftEntity, SensorEntity):
    """How much the flat cooled down during the last airing."""

    _attr_translation_key = "last_cooldown"
    _attr_icon = "mdi:thermometer-chevron-down"
    _attr_native_unit_of_measurement = DELTA_UNIT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: StoslueftCoordinator) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, "last_cooldown")

    @property
    def native_value(self) -> float | None:
        """Average cooldown over all rooms, in K."""
        session = self.data.last_session
        return None if session is None else session.get("delta")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The full breakdown of the last session."""
        session = self.data.last_session
        if session is None:
            return {}
        return {
            "started": session.get("started"),
            "ended": session.get("ended"),
            "duration_minutes": session.get("duration_minutes"),
            "at_night": session.get("at_night"),
            "outdoor_temperature": session.get("outdoor_temperature"),
            "rooms": session.get("rooms", []),
        }


class RoomCooldownSensor(StoslueftRoomEntity, SensorEntity):
    """How much this room cooled down during the last airing."""

    _attr_translation_key = "room_cooldown"
    _attr_icon = "mdi:thermometer-chevron-down"
    _attr_native_unit_of_measurement = DELTA_UNIT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: StoslueftCoordinator, room: RoomConfig) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, room, "cooldown")

    @property
    def native_value(self) -> float | None:
        """The room's cooldown from the last session, in K."""
        room = self.data.room(self._room.room_id)
        return None if room is None else _round(room.last_cooldown, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """This room's part of the last session."""
        session = self.data.last_session or {}
        record = next(
            (
                room
                for room in session.get("rooms", [])
                if room["room_id"] == self._room.room_id
            ),
            None,
        )
        return record or {}


class CooldownTodaySensor(StoslueftEntity, SensorEntity):
    """Total cooldown achieved by airing out since midnight."""

    _attr_translation_key = "cooldown_today"
    _attr_icon = "mdi:thermometer-chevron-down"
    _attr_native_unit_of_measurement = DELTA_UNIT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: StoslueftCoordinator) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, "cooldown_today")

    @property
    def native_value(self) -> float:
        """Sum of every session's cooldown today, in K."""
        return self.data.cooldown_today


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)
