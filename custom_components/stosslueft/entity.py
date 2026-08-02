"""Shared entity base for Stoßlüften."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ROOM_UNIQUE_ID_PREFIX
from .coordinator import RoomConfig, StoslueftCoordinator, StoslueftData


class StoslueftEntity(CoordinatorEntity[StoslueftCoordinator]):
    """Base entity, tied to the config entry's service device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: StoslueftCoordinator, key: str) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        assert entry is not None
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Stoßlüften",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def data(self) -> StoslueftData:
        """The current coordinator data."""
        return self.coordinator.data


class StoslueftRoomEntity(StoslueftEntity):
    """Base entity for a single room.

    The `room_` marker in the unique id is what lets setup tell a room's
    entities apart from the flat-wide ones, so it can clean up after a room
    that was removed. `key` must not contain an underscore.
    """

    def __init__(
        self, coordinator: StoslueftCoordinator, room: RoomConfig, key: str
    ) -> None:
        """Initialise the entity."""
        super().__init__(coordinator, f"{ROOM_UNIQUE_ID_PREFIX}{room.room_id}_{key}")
        self._room = room
        self._attr_translation_placeholders = {"room": room.name}

    @property
    def available(self) -> bool:
        """Whether the room is still configured and reporting."""
        return super().available and self.data.room(self._room.room_id) is not None
