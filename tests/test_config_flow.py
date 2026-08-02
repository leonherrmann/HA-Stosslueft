"""Room discovery and the config / options flows."""

from __future__ import annotations

import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stosslueft.const import (
    CONF_HUMIDITY_ENTITY,
    CONF_NAME,
    CONF_OUTDOOR_HUMIDITY,
    CONF_OUTDOOR_TEMPERATURE,
    CONF_ROOM_ID,
    CONF_ROOMS,
    CONF_TARGET_TEMPERATURE,
    CONF_TEMPERATURE_ENTITY,
    CONF_WINDOW_ENTITY,
    DOMAIN,
)
from custom_components.stosslueft.discovery import async_discover_rooms

OUTDOOR = "sensor.outdoor_temperature"


@pytest.fixture
def source_entry(hass: HomeAssistant) -> MockConfigEntry:
    """A config entry to hang the mock source entities off."""
    entry = MockConfigEntry(domain="demo")
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def areas(hass: HomeAssistant, source_entry: MockConfigEntry) -> None:
    """Two furnished rooms, one bare area and one outdoor sensor."""
    area_reg = ar.async_get(hass)
    entity_reg = er.async_get(hass)
    living = area_reg.async_create("Living room")
    bedroom = area_reg.async_create("Bedroom")
    area_reg.async_create("Cellar")

    def register(
        domain: str,
        object_id: str,
        device_class,
        area_id: str | None,
        state_class=None,
    ) -> str:
        entry = entity_reg.async_get_or_create(
            domain,
            "demo",
            object_id,
            suggested_object_id=object_id,
            config_entry=source_entry,
            original_device_class=device_class,
            capabilities={"state_class": state_class} if state_class else None,
        )
        if area_id:
            entity_reg.async_update_entity(entry.entity_id, area_id=area_id)
        return entry.entity_id

    register(
        "sensor",
        "living_room_temperature",
        SensorDeviceClass.TEMPERATURE,
        living.id,
        SensorStateClass.MEASUREMENT,
    )
    register("sensor", "living_room_humidity", SensorDeviceClass.HUMIDITY, living.id)
    register(
        "binary_sensor",
        "living_room_window",
        BinarySensorDeviceClass.WINDOW,
        living.id,
    )
    register(
        "sensor",
        "bedroom_temperature",
        SensorDeviceClass.TEMPERATURE,
        bedroom.id,
        SensorStateClass.MEASUREMENT,
    )
    register(
        "binary_sensor", "bedroom_window", BinarySensorDeviceClass.OPENING, bedroom.id
    )
    # In an area, but a thermometer we should never mistake for an indoor one.
    register(
        "sensor",
        "outdoor_temperature",
        SensorDeviceClass.TEMPERATURE,
        living.id,
        SensorStateClass.MEASUREMENT,
    )


async def test_discovery_finds_furnished_areas(hass: HomeAssistant, areas) -> None:
    """Areas with a thermometer or a window contact become rooms."""
    rooms = async_discover_rooms(hass, exclude={OUTDOOR})
    assert [room.name for room in rooms] == ["Bedroom", "Living room"]

    living = rooms[1]
    assert living.temperature_entity == "sensor.living_room_temperature"
    assert living.humidity_entity == "sensor.living_room_humidity"
    assert living.window_entity == "binary_sensor.living_room_window"
    assert living.summary == "temperature, humidity, window"

    bedroom = rooms[0]
    assert bedroom.humidity_entity is None
    assert bedroom.window_entity == "binary_sensor.bedroom_window"


async def test_discovery_excludes_the_outdoor_sensor(
    hass: HomeAssistant, areas
) -> None:
    """The entity chosen as the outdoor source never doubles as a room's."""
    picked = {
        room.temperature_entity
        for room in async_discover_rooms(hass, exclude={OUTDOOR})
    }
    assert OUTDOOR not in picked
    assert "sensor.living_room_temperature" in picked


async def test_user_flow(hass: HomeAssistant, areas) -> None:
    """Setup asks for the outdoor source, then confirms the rooms."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_OUTDOOR_TEMPERATURE: OUTDOOR, CONF_OUTDOOR_HUMIDITY: "sensor.out_hum"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "rooms"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ROOMS: [room.room_id for room in _rooms(hass)]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_OUTDOOR_TEMPERATURE] == OUTDOOR
    rooms = result["options"][CONF_ROOMS]
    assert {room[CONF_NAME] for room in rooms} == {"Living room", "Bedroom"}


async def test_user_flow_deselecting_a_room(hass: HomeAssistant, areas) -> None:
    """Unticking a room leaves it out."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_OUTDOOR_TEMPERATURE: OUTDOOR}
    )
    keep = next(room for room in _rooms(hass) if room.name == "Bedroom")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ROOMS: [keep.room_id]}
    )
    assert [room[CONF_NAME] for room in result["options"][CONF_ROOMS]] == ["Bedroom"]


async def test_user_flow_without_any_areas(hass: HomeAssistant) -> None:
    """No areas is not a dead end -- rooms can be added later."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_OUTDOOR_TEMPERATURE: OUTDOOR}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_ROOMS] == []


async def test_options_settings(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The tuning knobs round-trip through the options flow."""
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    assert result["type"] is FlowResultType.MENU

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )
    assert result["step_id"] == "settings"

    user_input = dict(result["data_schema"]({}))
    user_input[CONF_TARGET_TEMPERATURE] = 19.5
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert setup_integration.options[CONF_TARGET_TEMPERATURE] == 19.5
    # Rooms must survive a settings-only edit.
    assert len(setup_integration.options[CONF_ROOMS]) == 3


async def test_options_edit_room(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """A room's sensors can be swapped out."""
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "rooms"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ROOM_ID: "bedroom"}
    )
    assert result["step_id"] == "room"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Bedroom",
            CONF_TEMPERATURE_ENTITY: "sensor.bedroom_temperature",
            CONF_HUMIDITY_ENTITY: "sensor.bedroom_humidity",
            CONF_WINDOW_ENTITY: "binary_sensor.bedroom_window",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    bedroom = next(
        room
        for room in setup_integration.options[CONF_ROOMS]
        if room[CONF_ROOM_ID] == "bedroom"
    )
    assert bedroom[CONF_HUMIDITY_ENTITY] == "sensor.bedroom_humidity"


async def test_options_remove_room(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Clearing both entities removes the room and its entities."""
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "rooms"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ROOM_ID: "hallway"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_NAME: "Hallway"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    ids = {room[CONF_ROOM_ID] for room in setup_integration.options[CONF_ROOMS]}
    assert ids == {"living_room", "bedroom"}
    assert hass.states.get("sensor.stossluften_hallway_airing_score") is None


async def test_options_add_room(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """A room can be added by hand, with an id derived from its name."""
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "rooms"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ROOM_ID: "__add__"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Study",
            CONF_TEMPERATURE_ENTITY: "sensor.study_temperature",
            CONF_WINDOW_ENTITY: "binary_sensor.study_window",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    ids = {room[CONF_ROOM_ID] for room in setup_integration.options[CONF_ROOMS]}
    assert "study" in ids


async def test_options_discover_without_new_rooms(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Re-running discovery with nothing new says so instead of doing nothing."""
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "discover"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_new_rooms"


def _rooms(hass: HomeAssistant):
    return async_discover_rooms(hass, exclude={OUTDOOR})
