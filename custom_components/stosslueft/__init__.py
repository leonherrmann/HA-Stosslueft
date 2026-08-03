"""The Stoßlüften integration."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration

from .const import (
    CARD_FILENAME,
    CARD_URL,
    DATA_FRONTEND_REGISTERED,
    DOMAIN,
    ROOM_ENTITY_KEYS,
    ROOM_UNIQUE_ID_PREFIX,
)
from .coordinator import StoslueftCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

type StoslueftConfigEntry = ConfigEntry[StoslueftCoordinator]


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the dashboard card and load it into the frontend.

    Shipping the card with the integration means one install instead of two,
    and no manual Lovelace resource entry -- `add_extra_js_url` works in both
    storage and YAML mode.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(DATA_FRONTEND_REGISTERED):
        return

    card_path = Path(__file__).parent / "frontend" / CARD_FILENAME
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(card_path), False)]
    )
    integration = await async_get_integration(hass, DOMAIN)
    add_extra_js_url(hass, f"{CARD_URL}?v={integration.version}")
    domain_data[DATA_FRONTEND_REGISTERED] = True
    _LOGGER.debug("Registered %s at %s", CARD_FILENAME, CARD_URL)


async def async_setup_entry(hass: HomeAssistant, entry: StoslueftConfigEntry) -> bool:
    """Set up Stoßlüften from a config entry."""
    await _async_register_frontend(hass)

    coordinator = StoslueftCoordinator(hass, entry)
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    _async_migrate_room_unique_ids(hass, entry, coordinator)
    _async_remove_stale_rooms(hass, entry, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: StoslueftConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded


@callback
def _async_migrate_room_unique_ids(
    hass: HomeAssistant, entry: StoslueftConfigEntry, coordinator: StoslueftCoordinator
) -> None:
    """Move pre-0.2.0 room entities onto the `room_` unique id scheme.

    0.1.0 keyed room entities as `<entry>_<room>_<key>`. Marking them with a
    `room_` prefix is what lets setup tell them from the flat-wide ones, but
    without this the old entities would be orphaned as `unavailable` and fresh
    ones created beside them with `_2` entity ids -- losing their history and
    breaking any dashboard that referenced them.

    Rebuilding the exact old and new ids from the configured rooms avoids
    having to guess where the room id ends and the key begins.
    """
    registry = er.async_get(hass)

    for room in coordinator.rooms:
        for key in ROOM_ENTITY_KEYS:
            legacy = f"{entry.entry_id}_{room.room_id}_{key}"
            current = f"{entry.entry_id}_{ROOM_UNIQUE_ID_PREFIX}{room.room_id}_{key}"
            entity_id = registry.async_get_entity_id(Platform.SENSOR, DOMAIN, legacy)
            if entity_id is None:
                continue
            if registry.async_get_entity_id(Platform.SENSOR, DOMAIN, current):
                # Already migrated on an earlier start and the old row somehow
                # survived; removing it is better than colliding.
                _LOGGER.debug("Dropping superseded %s", entity_id)
                registry.async_remove(entity_id)
                continue
            _LOGGER.debug("Migrating %s to unique id %s", entity_id, current)
            registry.async_update_entity(entity_id, new_unique_id=current)


@callback
def _async_remove_stale_rooms(
    hass: HomeAssistant, entry: StoslueftConfigEntry, coordinator: StoslueftCoordinator
) -> None:
    """Drop the entities of rooms the user has removed.

    Without this they would linger in the entity registry as `unavailable`
    forever, one set per room ever configured.
    """
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_{ROOM_UNIQUE_ID_PREFIX}"
    configured = {room.room_id for room in coordinator.rooms}

    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if not entity.unique_id.startswith(prefix):
            continue
        room_id = entity.unique_id[len(prefix) :].rsplit("_", 1)[0]
        if room_id not in configured:
            _LOGGER.debug("Removing %s, room %s is gone", entity.entity_id, room_id)
            registry.async_remove(entity.entity_id)


async def _async_reload_entry(hass: HomeAssistant, entry: StoslueftConfigEntry) -> None:
    """Reload when the options change -- rooms and tuning affect everything."""
    await hass.config_entries.async_reload(entry.entry_id)
