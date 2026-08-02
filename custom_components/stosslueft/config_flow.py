"""Config and options flow for Stoßlüften."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import Platform
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.util import slugify

from .const import (
    CONF_COMFORT_BAND,
    CONF_HUMIDITY_ENTITY,
    CONF_HUMIDITY_WEIGHT,
    CONF_MIN_SESSION_MINUTES,
    CONF_NAME,
    CONF_OUTDOOR_HUMIDITY,
    CONF_OUTDOOR_TEMPERATURE,
    CONF_RAIN_GUARD,
    CONF_RECOMMEND_THRESHOLD,
    CONF_ROOM_ID,
    CONF_ROOMS,
    CONF_SETTLE_MINUTES,
    CONF_TARGET_TEMPERATURE,
    CONF_TEMPERATURE_ENTITY,
    CONF_WINDOW_ENTITY,
    DEFAULT_COMFORT_BAND,
    DEFAULT_HUMIDITY_WEIGHT,
    DEFAULT_MIN_SESSION_MINUTES,
    DEFAULT_RAIN_GUARD,
    DEFAULT_RECOMMEND_THRESHOLD,
    DEFAULT_SETTLE_MINUTES,
    DEFAULT_TARGET_TEMPERATURE,
    DOMAIN,
)
from .discovery import async_discover_rooms

ADD_ROOM = "__add__"

OUTDOOR_TEMPERATURE_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=[Platform.SENSOR, "weather"])
)
OUTDOOR_HUMIDITY_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=[Platform.SENSOR, "weather"])
)
TEMPERATURE_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=Platform.SENSOR)
)
HUMIDITY_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=Platform.SENSOR)
)
WINDOW_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=[Platform.BINARY_SENSOR, "input_boolean"])
)


def _settings_schema(options: dict[str, Any]) -> vol.Schema:
    """Schema for the tuning knobs, pre-filled with the current values."""
    return vol.Schema(
        {
            vol.Required(
                CONF_TARGET_TEMPERATURE,
                default=options.get(
                    CONF_TARGET_TEMPERATURE, DEFAULT_TARGET_TEMPERATURE
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=5, max=30, step=0.5, unit_of_measurement="°C"
                )
            ),
            vol.Required(
                CONF_COMFORT_BAND,
                default=options.get(CONF_COMFORT_BAND, DEFAULT_COMFORT_BAND),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=5, step=0.1, unit_of_measurement="K"
                )
            ),
            vol.Required(
                CONF_HUMIDITY_WEIGHT,
                default=options.get(CONF_HUMIDITY_WEIGHT, DEFAULT_HUMIDITY_WEIGHT),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=1, step=0.05)
            ),
            vol.Required(
                CONF_RECOMMEND_THRESHOLD,
                default=options.get(
                    CONF_RECOMMEND_THRESHOLD, DEFAULT_RECOMMEND_THRESHOLD
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=100, step=1)
            ),
            vol.Required(
                CONF_SETTLE_MINUTES,
                default=options.get(CONF_SETTLE_MINUTES, DEFAULT_SETTLE_MINUTES),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=60, step=1, unit_of_measurement="min"
                )
            ),
            vol.Required(
                CONF_MIN_SESSION_MINUTES,
                default=options.get(
                    CONF_MIN_SESSION_MINUTES, DEFAULT_MIN_SESSION_MINUTES
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=60, step=1, unit_of_measurement="min"
                )
            ),
            vol.Required(
                CONF_RAIN_GUARD,
                default=options.get(CONF_RAIN_GUARD, DEFAULT_RAIN_GUARD),
            ): selector.BooleanSelector(),
        }
    )


def _room_schema(room: dict[str, Any] | None) -> vol.Schema:
    """Schema for adding or editing a single room."""
    room = room or {}
    schema: dict[Any, Any] = {
        vol.Required(CONF_NAME, default=room.get(CONF_NAME, vol.UNDEFINED)): str,
    }
    for key, entity_selector in (
        (CONF_TEMPERATURE_ENTITY, TEMPERATURE_SELECTOR),
        (CONF_HUMIDITY_ENTITY, HUMIDITY_SELECTOR),
        (CONF_WINDOW_ENTITY, WINDOW_SELECTOR),
    ):
        # `description` keeps the current entity pre-selected while still
        # allowing the field to be cleared.
        schema[vol.Optional(key, description={"suggested_value": room.get(key)})] = (
            entity_selector
        )
    return vol.Schema(schema)


class StoslueftConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the flow."""
        self._outdoor: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask where the outdoor readings come from."""
        if user_input is not None:
            self._outdoor = user_input
            return await self.async_step_rooms()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_OUTDOOR_TEMPERATURE
                    ): OUTDOOR_TEMPERATURE_SELECTOR,
                    vol.Optional(CONF_OUTDOOR_HUMIDITY): OUTDOOR_HUMIDITY_SELECTOR,
                }
            ),
        )

    async def async_step_rooms(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the rooms we found in the area registry."""
        exclude = {
            entity_id
            for key in (CONF_OUTDOOR_TEMPERATURE, CONF_OUTDOOR_HUMIDITY)
            if (entity_id := self._outdoor.get(key))
        }
        discovered = async_discover_rooms(self.hass, exclude)

        if not discovered:
            # Nothing to confirm -- create the entry anyway so the user can add
            # rooms by hand instead of being stuck at a dead end.
            return self.async_create_entry(
                title="Stoßlüften", data=self._outdoor, options={CONF_ROOMS: []}
            )

        if user_input is not None:
            selected = set(user_input[CONF_ROOMS])
            rooms = [
                room.as_option() for room in discovered if room.room_id in selected
            ]
            return self.async_create_entry(
                title="Stoßlüften", data=self._outdoor, options={CONF_ROOMS: rooms}
            )

        options = [
            selector.SelectOptionDict(
                value=room.room_id, label=f"{room.name} ({room.summary})"
            )
            for room in discovered
        ]
        return self.async_show_form(
            step_id="rooms",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ROOMS, default=[room.room_id for room in discovered]
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options, multiple=True)
                    )
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return StoslueftOptionsFlow()


class StoslueftOptionsFlow(OptionsFlow):
    """Edit settings and rooms after setup."""

    def __init__(self) -> None:
        """Initialise the flow."""
        self._editing_room: str | None = None

    @property
    def _rooms(self) -> list[dict[str, Any]]:
        return list(self.config_entry.options.get(CONF_ROOMS, []))

    def _save(
        self, rooms: list[dict[str, Any]] | None = None, **changes: Any
    ) -> ConfigFlowResult:
        options = dict(self.config_entry.options)
        options.update(changes)
        if rooms is not None:
            options[CONF_ROOMS] = rooms
        return self.async_create_entry(title="", data=options)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the top level menu."""
        return self.async_show_menu(
            step_id="init", menu_options=["settings", "rooms", "discover"]
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the tuning knobs."""
        if user_input is not None:
            return self._save(**user_input)
        return self.async_show_form(
            step_id="settings",
            data_schema=_settings_schema(dict(self.config_entry.options)),
        )

    async def async_step_rooms(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a room to edit, or add a new one."""
        if user_input is not None:
            self._editing_room = user_input[CONF_ROOM_ID]
            return await self.async_step_room()

        options = [
            selector.SelectOptionDict(
                value=room[CONF_ROOM_ID], label=room.get(CONF_NAME, room[CONF_ROOM_ID])
            )
            for room in self._rooms
        ]
        options.append(selector.SelectOptionDict(value=ADD_ROOM, label="Add a room"))
        return self.async_show_form(
            step_id="rooms",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ROOM_ID): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options)
                    )
                }
            ),
        )

    async def async_step_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit, add or remove one room."""
        room_id = self._editing_room
        assert room_id is not None
        existing = next(
            (room for room in self._rooms if room[CONF_ROOM_ID] == room_id), None
        )

        if user_input is not None:
            rooms = [room for room in self._rooms if room[CONF_ROOM_ID] != room_id]
            if user_input.get(CONF_TEMPERATURE_ENTITY) or user_input.get(
                CONF_WINDOW_ENTITY
            ):
                new_id = room_id
                if new_id == ADD_ROOM:
                    new_id = _slugify_room_id(user_input[CONF_NAME], rooms)
                rooms.append(
                    {
                        CONF_ROOM_ID: new_id,
                        CONF_NAME: user_input[CONF_NAME],
                        CONF_TEMPERATURE_ENTITY: user_input.get(
                            CONF_TEMPERATURE_ENTITY
                        ),
                        CONF_HUMIDITY_ENTITY: user_input.get(CONF_HUMIDITY_ENTITY),
                        CONF_WINDOW_ENTITY: user_input.get(CONF_WINDOW_ENTITY),
                    }
                )
            # Clearing both the temperature and the window entity is how a room
            # is removed -- there would be nothing left to report on.
            return self._save(rooms=rooms)

        return self.async_show_form(
            step_id="room",
            data_schema=_room_schema(existing),
            description_placeholders={
                "name": (existing or {}).get(CONF_NAME, "new room")
            },
        )

    async def async_step_discover(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-scan the areas and offer any rooms that are not configured yet."""
        exclude = {
            entity_id
            for key in (CONF_OUTDOOR_TEMPERATURE, CONF_OUTDOOR_HUMIDITY)
            if (entity_id := self.config_entry.data.get(key))
        }
        known = {room[CONF_ROOM_ID] for room in self._rooms}
        discovered = [
            room
            for room in async_discover_rooms(self.hass, exclude)
            if room.room_id not in known
        ]

        if not discovered:
            return self.async_abort(reason="no_new_rooms")

        if user_input is not None:
            selected = set(user_input[CONF_ROOMS])
            rooms = self._rooms + [
                room.as_option() for room in discovered if room.room_id in selected
            ]
            return self._save(rooms=rooms)

        options = [
            selector.SelectOptionDict(
                value=room.room_id, label=f"{room.name} ({room.summary})"
            )
            for room in discovered
        ]
        return self.async_show_form(
            step_id="discover",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ROOMS, default=[room.room_id for room in discovered]
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options, multiple=True)
                    )
                }
            ),
        )


def _slugify_room_id(name: str, existing: list[dict[str, Any]]) -> str:
    """Build a room id that does not collide with the configured rooms."""
    base = slugify(name) or "room"
    taken = {room[CONF_ROOM_ID] for room in existing}
    if base not in taken:
        return base
    index = 2
    while f"{base}_{index}" in taken:
        index += 1
    return f"{base}_{index}"
