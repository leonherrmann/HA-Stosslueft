"""Airing session detection and the cooldown report."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.stosslueft.const import EVENT_AIRING_FINISHED

SETTLE = timedelta(minutes=11)


async def _advance(hass: HomeAssistant, freezer, delta: timedelta) -> None:
    """Move the clock forward and let every due timer run."""
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_full_session_reports_cooldown(
    hass: HomeAssistant, setup_integration: MockConfigEntry, set_state, freezer
) -> None:
    """Opening and closing the windows produces a per-room cooldown report."""
    events = async_capture_events(hass, EVENT_AIRING_FINISHED)

    set_state("binary_sensor.living_room_window", "on")
    set_state("binary_sensor.bedroom_window", "on")
    await hass.async_block_till_done()

    active = hass.states.get("binary_sensor.stossluften_airing_active")
    assert active.state == "on"
    assert active.attributes["open_rooms"] == ["Bedroom", "Living room"]

    # The hallway cools too, but it has no window contact of its own, so it
    # must not dilute the figure.
    set_state("sensor.living_room_temperature", "22.5")
    set_state("sensor.bedroom_temperature", "22")
    set_state("sensor.hallway_temperature", "23")
    await _advance(hass, freezer, timedelta(minutes=20))

    set_state("binary_sensor.living_room_window", "off")
    set_state("binary_sensor.bedroom_window", "off")
    await hass.async_block_till_done()

    # Nothing is reported until the sensors have settled.
    assert not events
    assert hass.states.get("sensor.stossluften_last_airing_cooldown").state == "unknown"

    await _advance(hass, freezer, SETTLE)

    assert len(events) == 1
    payload = events[0].data
    assert payload["delta"] == 3.25  # (3.5 + 3.0) / 2, the hallway is left out
    assert payload["duration_minutes"] > 19
    rooms = {room["room_id"]: room for room in payload["rooms"]}
    assert rooms["living_room"]["delta"] == 3.5
    assert rooms["living_room"]["aired"] is True
    assert "hallway" not in rooms

    assert hass.states.get("sensor.stossluften_last_airing_cooldown").state == "3.25"
    assert (
        hass.states.get("sensor.stossluften_living_room_airing_cooldown").state == "3.5"
    )
    # A room with no window gets no cooldown sensor at all...
    assert hass.states.get("sensor.stossluften_hallway_airing_cooldown") is None
    # ...but is still scored and still counts toward the overall score.
    assert hass.states.get("sensor.stossluften_hallway_airing_score") is not None
    assert hass.states.get("sensor.stossluften_airing_cooldown_today").state == "3.25"
    assert hass.states.get("binary_sensor.stossluften_airing_active").state == "off"


async def test_short_session_is_discarded(
    hass: HomeAssistant, setup_integration: MockConfigEntry, set_state, freezer
) -> None:
    """A window opened for a moment is not an airing session."""
    events = async_capture_events(hass, EVENT_AIRING_FINISHED)

    set_state("binary_sensor.living_room_window", "on")
    await hass.async_block_till_done()
    set_state("binary_sensor.living_room_window", "off")
    await hass.async_block_till_done()

    await _advance(hass, freezer, SETTLE)

    assert not events
    assert hass.states.get("sensor.stossluften_last_airing_cooldown").state == "unknown"


async def test_reopening_during_settle_continues_the_session(
    hass: HomeAssistant, setup_integration: MockConfigEntry, set_state, freezer
) -> None:
    """Closing one window and opening another is still one session."""
    events = async_capture_events(hass, EVENT_AIRING_FINISHED)

    set_state("binary_sensor.living_room_window", "on")
    await hass.async_block_till_done()
    set_state("sensor.living_room_temperature", "24")
    await _advance(hass, freezer, timedelta(minutes=10))

    set_state("binary_sensor.living_room_window", "off")
    await hass.async_block_till_done()
    await _advance(hass, freezer, timedelta(minutes=2))
    assert not events

    set_state("binary_sensor.bedroom_window", "on")
    await hass.async_block_till_done()
    set_state("sensor.bedroom_temperature", "23")
    await _advance(hass, freezer, timedelta(minutes=10))
    set_state("binary_sensor.bedroom_window", "off")
    await hass.async_block_till_done()

    await _advance(hass, freezer, SETTLE)

    assert len(events) == 1
    payload = events[0].data
    # One session spanning both windows, so the start temperatures are the ones
    # from before the first window was opened.
    assert payload["duration_minutes"] >= 22
    rooms = {room["room_id"]: room for room in payload["rooms"]}
    assert rooms["living_room"]["delta"] == 2.0
    assert rooms["bedroom"]["delta"] == 2.0
    assert rooms["living_room"]["aired"] is True
    assert rooms["bedroom"]["aired"] is True


async def test_unavailable_window_does_not_start_a_session(
    hass: HomeAssistant, setup_integration: MockConfigEntry, set_state, freezer
) -> None:
    """A radio stick coming back online is not somebody opening a window."""
    set_state("binary_sensor.living_room_window", "unavailable")
    await hass.async_block_till_done()
    set_state("binary_sensor.living_room_window", "on")
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.stossluften_airing_active").state == "off"


async def test_night_flag_and_live_progress(
    hass: HomeAssistant, setup_integration: MockConfigEntry, set_state, freezer
) -> None:
    """Mid-session the binary sensor shows how much has been gained so far."""
    hass.states.async_set("sun.sun", "below_horizon")
    set_state("binary_sensor.living_room_window", "on")
    await hass.async_block_till_done()

    set_state("sensor.living_room_temperature", "24")
    set_state("sensor.bedroom_temperature", "24")
    set_state("sensor.hallway_temperature", "23.5")
    await _advance(hass, freezer, timedelta(minutes=5))

    active = hass.states.get("binary_sensor.stossluften_airing_active")
    assert active.state == "on"
    assert active.attributes["at_night"] is True
    assert active.attributes["open_rooms"] == ["Living room"]
    # (26-24 + 25-24) / 2 -- the windowless hallway is not counted
    assert active.attributes["cooldown_so_far"] == 1.5


async def test_session_survives_a_restart(
    hass: HomeAssistant, setup_integration: MockConfigEntry, set_state, freezer
) -> None:
    """An airing that spans a restart is still reported."""
    events = async_capture_events(hass, EVENT_AIRING_FINISHED)

    set_state("binary_sensor.living_room_window", "on")
    await hass.async_block_till_done()
    await _advance(hass, freezer, timedelta(minutes=15))

    # Unloading must flush the still-debounced store write by itself.
    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()

    set_state("sensor.living_room_temperature", "23")
    assert await hass.config_entries.async_setup(setup_integration.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.stossluften_airing_active").state == "on"

    set_state("binary_sensor.living_room_window", "off")
    await hass.async_block_till_done()
    await _advance(hass, freezer, SETTLE)

    assert len(events) == 1
    rooms = {room["room_id"]: room for room in events[0].data["rooms"]}
    assert rooms["living_room"]["delta"] == 3.0
