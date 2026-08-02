"""Setup, entity creation and the overall score."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stosslueft.const import CARD_URL


async def test_setup_and_unload(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The entry loads, creates entities and unloads again."""
    assert setup_integration.state is ConfigEntryState.LOADED

    assert hass.states.get("sensor.stossluften_airing_score") is not None
    assert hass.states.get("sensor.stossluften_living_room_airing_score") is not None
    assert hass.states.get("sensor.stossluften_indoor_temperature") is not None
    assert hass.states.get("binary_sensor.stossluften_airing_recommended") is not None
    assert hass.states.get("binary_sensor.stossluften_airing_active") is not None

    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert setup_integration.state is ConfigEntryState.NOT_LOADED


async def test_card_is_served(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The dashboard card is registered with the frontend."""
    from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL

    urls = hass.data[DATA_EXTRA_MODULE_URL].urls
    assert any(url.startswith(CARD_URL) for url in urls)


async def test_card_is_downloadable(
    hass: HomeAssistant, setup_integration: MockConfigEntry, hass_client
) -> None:
    """The registered path really resolves to the card file."""
    client = await hass_client()
    response = await client.get(CARD_URL)
    assert response.status == 200
    assert "stosslueft-card" in await response.text()


async def test_scores_a_warm_evening(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Warm inside and cool outside scores well, room by room."""
    overall = hass.states.get("sensor.stossluften_airing_score")
    assert overall is not None
    assert int(overall.state) > 80
    assert overall.attributes["rating"] == "excellent"
    assert overall.attributes["indoor_temperature"] == 25.0
    assert overall.attributes["outdoor_temperature"] == 18.0
    assert overall.attributes["temperature_delta"] == -7.0
    assert len(overall.attributes["rooms"]) == 3
    assert overall.attributes["worst_room"] == "Hallway"
    assert overall.attributes["best_room"] in ("Living room", "Bedroom")

    assert hass.states.get("binary_sensor.stossluften_airing_recommended").state == "on"
    assert hass.states.get("binary_sensor.stossluften_airing_active").state == "off"

    room = hass.states.get("sensor.stossluften_hallway_airing_score")
    assert room is not None
    assert room.attributes["has_window_sensor"] is False
    assert room.attributes["temperature"] == 24.0


async def test_reacts_to_outdoor_change(
    hass: HomeAssistant, setup_integration: MockConfigEntry, set_state
) -> None:
    """A heatwave outside flips the recommendation."""
    set_state("sensor.outdoor_temperature", "34")
    await hass.async_block_till_done()

    overall = hass.states.get("sensor.stossluften_airing_score")
    assert int(overall.state) < 20
    assert (
        hass.states.get("binary_sensor.stossluften_airing_recommended").state == "off"
    )


async def test_missing_outdoor_data(
    hass: HomeAssistant, setup_integration: MockConfigEntry, set_state
) -> None:
    """Without outdoor data the score falls back instead of raising."""
    set_state("sensor.outdoor_temperature", "unavailable")
    await hass.async_block_till_done()

    overall = hass.states.get("sensor.stossluften_airing_score")
    assert overall.state == "0"
    assert overall.attributes["reason_key"] == "no_data"
