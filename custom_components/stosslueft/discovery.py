"""Suggest rooms by looking at what is already assigned to Home Assistant areas.

Most people have already done the work of putting their thermometers and
window contacts into areas, so setup should not ask them to do it a second
time.  Anything this module guesses wrong can be corrected in the options flow.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_HUMIDITY_ENTITY,
    CONF_NAME,
    CONF_ROOM_ID,
    CONF_TEMPERATURE_ENTITY,
    CONF_WINDOW_ENTITY,
)

WINDOW_DEVICE_CLASSES = frozenset(
    {BinarySensorDeviceClass.WINDOW, BinarySensorDeviceClass.OPENING}
)


@dataclass(frozen=True, slots=True)
class DiscoveredRoom:
    """A room we think exists, and the entities we think belong to it."""

    room_id: str
    name: str
    temperature_entity: str | None = None
    humidity_entity: str | None = None
    window_entity: str | None = None

    def as_option(self) -> dict[str, str | None]:
        """Render into the shape stored in the config entry options."""
        return {
            CONF_ROOM_ID: self.room_id,
            CONF_NAME: self.name,
            CONF_TEMPERATURE_ENTITY: self.temperature_entity,
            CONF_HUMIDITY_ENTITY: self.humidity_entity,
            CONF_WINDOW_ENTITY: self.window_entity,
        }

    @property
    def summary(self) -> str:
        """Short description of what was found, for the setup form."""
        found = []
        if self.temperature_entity:
            found.append("temperature")
        if self.humidity_entity:
            found.append("humidity")
        if self.window_entity:
            found.append("window")
        return ", ".join(found) if found else "nothing found"


def _effective_area(
    entry: er.RegistryEntry, device_reg: dr.DeviceRegistry
) -> str | None:
    """Area of an entity, falling back to the area of its device."""
    if entry.area_id:
        return entry.area_id
    if entry.device_id and (device := device_reg.async_get(entry.device_id)):
        return device.area_id
    return None


def _is_temperature(entry: er.RegistryEntry) -> bool:
    if entry.domain != Platform.SENSOR:
        return False
    device_class = entry.device_class or entry.original_device_class
    if device_class != SensorDeviceClass.TEMPERATURE:
        return False
    capabilities = entry.capabilities or {}
    return capabilities.get("state_class") == SensorStateClass.MEASUREMENT


def _is_humidity(entry: er.RegistryEntry) -> bool:
    if entry.domain != Platform.SENSOR:
        return False
    device_class = entry.device_class or entry.original_device_class
    return device_class == SensorDeviceClass.HUMIDITY


def _first(entity_ids: list[str]) -> str | None:
    """Pick a stable candidate when an area holds several matching entities."""
    return min(entity_ids) if entity_ids else None


def _is_window(entry: er.RegistryEntry) -> bool:
    if entry.domain != Platform.BINARY_SENSOR:
        return False
    device_class = entry.device_class or entry.original_device_class
    return device_class in WINDOW_DEVICE_CLASSES


@callback
def async_discover_rooms(
    hass: HomeAssistant, exclude: set[str] | None = None
) -> list[DiscoveredRoom]:
    """Return one suggested room per area that has something worth watching."""
    exclude = exclude or set()
    area_reg = ar.async_get(hass)
    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)

    candidates: dict[str, dict[str, list[str]]] = {
        area_id: {"temperature": [], "humidity": [], "window": []}
        for area_id in area_reg.areas
    }

    for entry in entity_reg.entities.values():
        if entry.disabled or entry.hidden or entry.entity_category is not None:
            continue
        if entry.entity_id in exclude:
            continue
        area_id = _effective_area(entry, device_reg)
        if area_id is None or area_id not in candidates:
            continue
        if _is_temperature(entry):
            candidates[area_id]["temperature"].append(entry.entity_id)
        elif _is_humidity(entry):
            candidates[area_id]["humidity"].append(entry.entity_id)
        elif _is_window(entry):
            candidates[area_id]["window"].append(entry.entity_id)

    rooms: list[DiscoveredRoom] = []
    for area_id, found in candidates.items():
        # A room with neither a thermometer nor a window contact is of no use
        # to us -- we could neither score it nor notice it being aired.
        if not found["temperature"] and not found["window"]:
            continue
        area = area_reg.async_get_area(area_id)
        if area is None:
            continue
        rooms.append(
            DiscoveredRoom(
                room_id=area_id,
                name=area.name,
                temperature_entity=_first(found["temperature"]),
                humidity_entity=_first(found["humidity"]),
                window_entity=_first(found["window"]),
            )
        )

    rooms.sort(key=lambda room: room.name)
    return rooms
