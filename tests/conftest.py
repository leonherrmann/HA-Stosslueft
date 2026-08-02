"""Fixtures for the Stoßlüften tests."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stosslueft.const import (
    CONF_HUMIDITY_ENTITY,
    CONF_NAME,
    CONF_OUTDOOR_HUMIDITY,
    CONF_OUTDOOR_TEMPERATURE,
    CONF_ROOM_ID,
    CONF_ROOMS,
    CONF_SETTLE_MINUTES,
    CONF_TEMPERATURE_ENTITY,
    CONF_WINDOW_ENTITY,
    DOMAIN,
)

OUTDOOR_TEMPERATURE = "sensor.outdoor_temperature"
OUTDOOR_HUMIDITY = "sensor.outdoor_humidity"

ROOMS = [
    {
        CONF_ROOM_ID: "living_room",
        CONF_NAME: "Living room",
        CONF_TEMPERATURE_ENTITY: "sensor.living_room_temperature",
        CONF_HUMIDITY_ENTITY: "sensor.living_room_humidity",
        CONF_WINDOW_ENTITY: "binary_sensor.living_room_window",
    },
    {
        CONF_ROOM_ID: "bedroom",
        CONF_NAME: "Bedroom",
        CONF_TEMPERATURE_ENTITY: "sensor.bedroom_temperature",
        CONF_HUMIDITY_ENTITY: None,
        CONF_WINDOW_ENTITY: "binary_sensor.bedroom_window",
    },
    {
        # A room with a thermometer but no window contact: it still cools down
        # when the flat is aired, so it must show up in the totals.
        CONF_ROOM_ID: "hallway",
        CONF_NAME: "Hallway",
        CONF_TEMPERATURE_ENTITY: "sensor.hallway_temperature",
        CONF_HUMIDITY_ENTITY: None,
        CONF_WINDOW_ENTITY: None,
    },
]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom_components in every test."""
    return


@pytest.fixture
def set_state(hass: HomeAssistant):
    """Helper to write a sensor state with a unit."""

    def _set(entity_id: str, state, **attributes) -> None:
        if entity_id.startswith("sensor.") and "unit_of_measurement" not in attributes:
            attributes["unit_of_measurement"] = "%" if "humidity" in entity_id else "°C"
        hass.states.async_set(entity_id, state, attributes)

    return _set


@pytest.fixture
def seed_states(set_state) -> None:
    """A plausible summer evening: warm inside, cooler outside."""
    set_state(OUTDOOR_TEMPERATURE, "18")
    set_state(OUTDOOR_HUMIDITY, "80")
    set_state("sensor.living_room_temperature", "26")
    set_state("sensor.living_room_humidity", "55")
    set_state("sensor.bedroom_temperature", "25")
    set_state("sensor.hallway_temperature", "24")
    set_state("binary_sensor.living_room_window", "off")
    set_state("binary_sensor.bedroom_window", "off")


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """A config entry covering all three room shapes."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Stoßlüften",
        data={
            CONF_OUTDOOR_TEMPERATURE: OUTDOOR_TEMPERATURE,
            CONF_OUTDOOR_HUMIDITY: OUTDOOR_HUMIDITY,
        },
        options={CONF_ROOMS: ROOMS, CONF_SETTLE_MINUTES: 10},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def setup_integration(
    freezer, hass: HomeAssistant, config_entry: MockConfigEntry, seed_states
) -> MockConfigEntry:
    """Set up the integration with the seeded states, on a frozen clock.

    Session timing is measured against the wall clock, so the tests need
    `freezer.tick()` rather than `async_fire_time_changed` alone -- the latter
    fires due timers without moving time forward.
    """
    assert await async_setup_component(hass, "sun", {})
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
