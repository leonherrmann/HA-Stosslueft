"""Coordinator: scores every room and tracks airing sessions."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import fmean
from typing import Any

from homeassistant.components.weather import (
    ATTR_WEATHER_HUMIDITY,
    ATTR_WEATHER_TEMPERATURE,
    ATTR_WEATHER_TEMPERATURE_UNIT,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

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
    EVENT_AIRING_FINISHED,
    STORAGE_VERSION,
    UPDATE_INTERVAL_SECONDS,
)
from .scoring import Conditions, Score, ScoreSettings, no_data_score, score_conditions

_LOGGER = logging.getLogger(__name__)

WEATHER_DOMAIN = "weather"
INVALID_STATES = (STATE_UNKNOWN, STATE_UNAVAILABLE)


@dataclass(frozen=True, slots=True)
class RoomConfig:
    """One configured room."""

    room_id: str
    name: str
    temperature_entity: str | None
    humidity_entity: str | None
    window_entity: str | None

    @classmethod
    def from_option(cls, option: dict[str, Any]) -> RoomConfig:
        """Build from the dict stored in the config entry options."""
        return cls(
            room_id=option[CONF_ROOM_ID],
            name=option.get(CONF_NAME, option[CONF_ROOM_ID]),
            temperature_entity=option.get(CONF_TEMPERATURE_ENTITY),
            humidity_entity=option.get(CONF_HUMIDITY_ENTITY),
            window_entity=option.get(CONF_WINDOW_ENTITY),
        )


@dataclass
class RoomSessionRecord:
    """What one room did during an airing session."""

    room_id: str
    name: str
    temperature_start: float | None
    temperature_min: float | None = None
    temperature_end: float | None = None
    humidity_start: float | None = None
    humidity_end: float | None = None
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    aired: bool = False

    @property
    def delta(self) -> float | None:
        """How much the room cooled down, in K (positive means cooler)."""
        if self.temperature_start is None or self.temperature_end is None:
            return None
        return self.temperature_start - self.temperature_end

    @property
    def duration_minutes(self) -> float | None:
        """How long this room's window was open."""
        if self.opened_at is None or self.closed_at is None:
            return None
        return (self.closed_at - self.opened_at).total_seconds() / 60

    def as_dict(self) -> dict[str, Any]:
        """Serialise for storage, attributes and the event payload."""
        return {
            "room_id": self.room_id,
            "name": self.name,
            "temperature_start": _round(self.temperature_start),
            "temperature_min": _round(self.temperature_min),
            "temperature_end": _round(self.temperature_end),
            "humidity_start": _round(self.humidity_start),
            "humidity_end": _round(self.humidity_end),
            "opened_at": _iso(self.opened_at),
            "closed_at": _iso(self.closed_at),
            "aired": self.aired,
            "delta": _round(self.delta),
            "duration_minutes": _round(self.duration_minutes, 1),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RoomSessionRecord:
        """Restore from storage."""
        return cls(
            room_id=data["room_id"],
            name=data["name"],
            temperature_start=data.get("temperature_start"),
            temperature_min=data.get("temperature_min"),
            temperature_end=data.get("temperature_end"),
            humidity_start=data.get("humidity_start"),
            humidity_end=data.get("humidity_end"),
            opened_at=_parse(data.get("opened_at")),
            closed_at=_parse(data.get("closed_at")),
            aired=data.get("aired", False),
        )


@dataclass
class AiringSession:
    """One airing of the flat, from the first window opening to the last closing."""

    started: datetime
    at_night: bool
    outdoor_temperature_start: float | None
    rooms: dict[str, RoomSessionRecord] = field(default_factory=dict)
    ended: datetime | None = None
    open_rooms: set[str] = field(default_factory=set)

    @property
    def duration_minutes(self) -> float:
        """Length of the session in minutes."""
        end = self.ended or dt_util.utcnow()
        return (end - self.started).total_seconds() / 60

    @property
    def delta(self) -> float | None:
        """Average cooldown across every room we have both readings for."""
        deltas = [
            record.delta for record in self.rooms.values() if record.delta is not None
        ]
        return fmean(deltas) if deltas else None

    def as_dict(self) -> dict[str, Any]:
        """Serialise for storage, attributes and the event payload."""
        return {
            "started": _iso(self.started),
            "ended": _iso(self.ended),
            "duration_minutes": _round(self.duration_minutes, 1),
            "at_night": self.at_night,
            "outdoor_temperature": _round(self.outdoor_temperature_start),
            "delta": _round(self.delta),
            "rooms": [record.as_dict() for record in self.rooms.values()],
            "open_rooms": sorted(self.open_rooms),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AiringSession:
        """Restore from storage."""
        started = _parse(data["started"])
        assert started is not None
        return cls(
            started=started,
            at_night=data.get("at_night", False),
            outdoor_temperature_start=data.get("outdoor_temperature"),
            rooms={
                room["room_id"]: RoomSessionRecord.from_dict(room)
                for room in data.get("rooms", [])
            },
            ended=_parse(data.get("ended")),
            open_rooms=set(data.get("open_rooms", [])),
        )


@dataclass(frozen=True, slots=True)
class RoomData:
    """Everything the entities need to know about one room right now."""

    config: RoomConfig
    temperature: float | None
    humidity: float | None
    window_open: bool | None
    score: Score
    last_cooldown: float | None

    @property
    def room_id(self) -> str:
        """Identifier of the room."""
        return self.config.room_id

    @property
    def name(self) -> str:
        """Friendly name of the room."""
        return self.config.name

    def as_dict(self) -> dict[str, Any]:
        """Render for the overall sensor's attributes and for the card."""
        return {
            "room_id": self.room_id,
            "name": self.name,
            "score": self.score.score,
            "rating": self.score.rating,
            "reason": self.score.reason,
            "reason_key": self.score.reason_key,
            "temperature": _round(self.temperature),
            "humidity": _round(self.humidity),
            "window_open": self.window_open,
            "last_cooldown": _round(self.last_cooldown),
            # Lets the card open more-info for the underlying thermometer.
            "temperature_entity": self.config.temperature_entity,
        }


@dataclass(frozen=True, slots=True)
class StoslueftData:
    """The full picture, recomputed on every coordinator update."""

    score: int
    overall: Score
    indoor_temperature: float | None
    indoor_humidity: float | None
    outdoor_temperature: float | None
    outdoor_humidity: float | None
    outdoor_condition: str | None
    rooms: list[RoomData]
    active_session: dict[str, Any] | None
    last_session: dict[str, Any] | None
    cooldown_today: float
    recommend_threshold: int

    @property
    def airing_recommended(self) -> bool:
        """Whether the flat as a whole should be aired right now."""
        return self.score >= self.recommend_threshold

    @property
    def airing_active(self) -> bool:
        """Whether at least one window is currently open."""
        return bool(self.active_session and self.active_session["open_rooms"])

    def room(self, room_id: str) -> RoomData | None:
        """Look up one room."""
        return next((room for room in self.rooms if room.room_id == room_id), None)


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _parse(value: str | None) -> datetime | None:
    return None if value is None else dt_util.parse_datetime(value)


class StoslueftCoordinator(DataUpdateCoordinator[StoslueftData]):
    """Scores the flat and keeps track of what airing out achieved."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Set up the coordinator for one config entry."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
            config_entry=entry,
        )
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._active: AiringSession | None = None
        self._last: dict[str, Any] | None = None
        self._cooldown_today: float = 0.0
        self._cooldown_today_date: str | None = None
        self._settle_unsub: Any = None
        self._unsubs: list[Any] = []

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    @property
    def rooms(self) -> list[RoomConfig]:
        """The configured rooms."""
        assert self.config_entry is not None
        return [
            RoomConfig.from_option(option)
            for option in self.config_entry.options.get(CONF_ROOMS, [])
        ]

    @property
    def settings(self) -> ScoreSettings:
        """The user's tuning knobs."""
        assert self.config_entry is not None
        options = self.config_entry.options
        return ScoreSettings(
            target_temperature=float(
                options.get(CONF_TARGET_TEMPERATURE, DEFAULT_TARGET_TEMPERATURE)
            ),
            comfort_band=float(options.get(CONF_COMFORT_BAND, DEFAULT_COMFORT_BAND)),
            humidity_weight=float(
                options.get(CONF_HUMIDITY_WEIGHT, DEFAULT_HUMIDITY_WEIGHT)
            ),
            rain_guard=bool(options.get(CONF_RAIN_GUARD, DEFAULT_RAIN_GUARD)),
        )

    def _option_int(self, key: str, default: int) -> int:
        assert self.config_entry is not None
        return int(self.config_entry.options.get(key, default))

    @property
    def _window_entities(self) -> dict[str, str]:
        """Window entity id -> room id."""
        return {
            room.window_entity: room.room_id
            for room in self.rooms
            if room.window_entity
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def async_setup(self) -> None:
        """Restore state and start listening."""
        await self._async_restore()

        tracked = [
            entity_id
            for room in self.rooms
            for entity_id in (
                room.temperature_entity,
                room.humidity_entity,
                room.window_entity,
            )
            if entity_id
        ]
        assert self.config_entry is not None
        for key in (CONF_OUTDOOR_TEMPERATURE, CONF_OUTDOOR_HUMIDITY):
            if entity_id := self.config_entry.data.get(key):
                tracked.append(entity_id)

        if tracked:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, sorted(set(tracked)), self._handle_state_event
                )
            )
        self._unsubs.append(
            async_track_time_change(
                self.hass, self._reset_daily_total, hour=0, minute=0, second=0
            )
        )

        # A session that was open when Home Assistant went down is still open
        # now unless every window was closed in the meantime.
        if self._active is not None and not self._active.open_rooms:
            self._schedule_settle()

    async def async_shutdown(self) -> None:
        """Stop listening and flush anything still queued for disk."""
        self._cancel_settle()
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        # Saves are debounced by 10 s, and an options change unloads the entry
        # right away -- without this, a window event could be lost.
        await self._store.async_save(self._data_to_save())
        await super().async_shutdown()

    # ------------------------------------------------------------------
    # Reading source entities
    # ------------------------------------------------------------------
    def _temperature(self, entity_id: str | None) -> float | None:
        """Read a temperature in °C from a sensor or weather entity."""
        if not entity_id or (state := self.hass.states.get(entity_id)) is None:
            return None
        if state.state in INVALID_STATES:
            return None
        if state.domain == WEATHER_DOMAIN:
            value = state.attributes.get(ATTR_WEATHER_TEMPERATURE)
            unit = (
                state.attributes.get(ATTR_WEATHER_TEMPERATURE_UNIT)
                or self.hass.config.units.temperature_unit
            )
        else:
            value = state.state
            unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        try:
            celsius = float(value)
        except (TypeError, ValueError):
            return None
        if unit and unit != UnitOfTemperature.CELSIUS:
            try:
                celsius = TemperatureConverter.convert(
                    celsius, unit, UnitOfTemperature.CELSIUS
                )
            except ValueError:
                return None
        return celsius

    def _humidity(self, entity_id: str | None) -> float | None:
        """Read a relative humidity in percent."""
        if not entity_id or (state := self.hass.states.get(entity_id)) is None:
            return None
        if state.state in INVALID_STATES:
            return None
        value = (
            state.attributes.get(ATTR_WEATHER_HUMIDITY)
            if state.domain == WEATHER_DOMAIN
            else state.state
        )
        try:
            humidity = float(value)
        except (TypeError, ValueError):
            return None
        return humidity if 0 <= humidity <= 100 else None

    def _window_open(self, entity_id: str | None) -> bool | None:
        """Whether a window contact reports open."""
        if not entity_id or (state := self.hass.states.get(entity_id)) is None:
            return None
        if state.state in INVALID_STATES:
            return None
        return state.state == STATE_ON

    def _outdoor_condition(self) -> str | None:
        """Current weather condition, if the outdoor source is a weather entity."""
        assert self.config_entry is not None
        entity_id = self.config_entry.data.get(CONF_OUTDOOR_TEMPERATURE)
        if not entity_id or not entity_id.startswith(f"{WEATHER_DOMAIN}."):
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in INVALID_STATES:
            return None
        return state.state

    # ------------------------------------------------------------------
    # Updating
    # ------------------------------------------------------------------
    async def _async_update_data(self) -> StoslueftData:
        """Recompute every score."""
        assert self.config_entry is not None
        entry_data = self.config_entry.data
        settings = self.settings
        condition = self._outdoor_condition()

        outdoor_temperature = self._temperature(
            entry_data.get(CONF_OUTDOOR_TEMPERATURE)
        )
        outdoor_humidity = self._humidity(entry_data.get(CONF_OUTDOOR_HUMIDITY))
        outdoor = (
            None
            if outdoor_temperature is None
            else Conditions(outdoor_temperature, outdoor_humidity)
        )

        last_deltas = {
            room["room_id"]: room["delta"]
            for room in (self._last or {}).get("rooms", [])
        }

        rooms: list[RoomData] = []
        for room in self.rooms:
            temperature = self._temperature(room.temperature_entity)
            humidity = self._humidity(room.humidity_entity)
            if temperature is None or outdoor is None:
                score = no_data_score()
            else:
                score = score_conditions(
                    Conditions(temperature, humidity), outdoor, settings, condition
                )
            rooms.append(
                RoomData(
                    config=room,
                    temperature=temperature,
                    humidity=humidity,
                    window_open=self._window_open(room.window_entity),
                    score=score,
                    last_cooldown=last_deltas.get(room.room_id),
                )
            )

        self._track_session_temperatures(rooms)

        temperatures = [r.temperature for r in rooms if r.temperature is not None]
        humidities = [r.humidity for r in rooms if r.humidity is not None]
        indoor_temperature = fmean(temperatures) if temperatures else None
        indoor_humidity = fmean(humidities) if humidities else None

        # The published number is the mean of the room scores, so one hot room
        # cannot hide behind five comfortable ones. The wording and the
        # suggested duration come from scoring the flat as a whole, which reads
        # better than picking one room's sentence.
        scored = [r.score.score for r in rooms if r.score.reason_key != "no_data"]
        if scored and indoor_temperature is not None and outdoor is not None:
            overall = score_conditions(
                Conditions(indoor_temperature, indoor_humidity),
                outdoor,
                settings,
                condition,
            )
            score = round(fmean(scored))
        else:
            overall = no_data_score()
            score = 0

        self._roll_daily_total()

        return StoslueftData(
            score=score,
            overall=overall,
            indoor_temperature=indoor_temperature,
            indoor_humidity=indoor_humidity,
            outdoor_temperature=outdoor_temperature,
            outdoor_humidity=outdoor_humidity,
            outdoor_condition=condition,
            rooms=rooms,
            active_session=self._active.as_dict() if self._active else None,
            last_session=self._last,
            cooldown_today=round(self._cooldown_today, 2),
            recommend_threshold=self._option_int(
                CONF_RECOMMEND_THRESHOLD, DEFAULT_RECOMMEND_THRESHOLD
            ),
        )

    @callback
    def _handle_state_event(self, event: Event[EventStateChangedData]) -> None:
        """React to a source entity changing."""
        entity_id = event.data["entity_id"]
        if room_id := self._window_entities.get(entity_id):
            self._handle_window_change(
                room_id, event.data["old_state"], event.data["new_state"]
            )
            # Windows move rarely and the user is standing right there, so skip
            # the debouncer -- a second window opening must show up at once.
            self.hass.async_create_task(self.async_refresh())
        else:
            self.hass.async_create_task(self.async_request_refresh())

    # ------------------------------------------------------------------
    # Airing sessions
    # ------------------------------------------------------------------
    @callback
    def _handle_window_change(self, room_id: str, old_state, new_state) -> None:
        """Start or end a room's airing when its window contact flips."""
        if new_state is None or new_state.state in INVALID_STATES:
            return
        if old_state is None or old_state.state in INVALID_STATES:
            # Ignore the transitions a restarting radio stick produces --
            # those are not somebody opening a window.
            return
        is_open = new_state.state == STATE_ON
        if is_open == (old_state.state == STATE_ON):
            return
        if is_open:
            self._open_window(room_id)
        else:
            self._close_window(room_id)

    @callback
    def _open_window(self, room_id: str) -> None:
        """Note that a window was opened."""
        now = dt_util.utcnow()
        self._cancel_settle()

        if self._active is None:
            assert self.config_entry is not None
            self._active = AiringSession(
                started=now,
                at_night=self._is_night(),
                outdoor_temperature_start=self._temperature(
                    self.config_entry.data.get(CONF_OUTDOOR_TEMPERATURE)
                ),
            )
            # Snapshot every room, not just the ones with an open window: the
            # whole flat cools down, and the user asked for the whole flat.
            for room in self.rooms:
                temperature = self._temperature(room.temperature_entity)
                self._active.rooms[room.room_id] = RoomSessionRecord(
                    room_id=room.room_id,
                    name=room.name,
                    temperature_start=temperature,
                    temperature_min=temperature,
                    humidity_start=self._humidity(room.humidity_entity),
                )

        record = self._active.rooms.get(room_id)
        if record is None:
            room = next((r for r in self.rooms if r.room_id == room_id), None)
            if room is None:
                return
            temperature = self._temperature(room.temperature_entity)
            record = RoomSessionRecord(
                room_id=room.room_id,
                name=room.name,
                temperature_start=temperature,
                temperature_min=temperature,
                humidity_start=self._humidity(room.humidity_entity),
            )
            self._active.rooms[room_id] = record

        record.aired = True
        if record.opened_at is None:
            record.opened_at = now
        record.closed_at = None
        self._active.open_rooms.add(room_id)
        self._async_save()

    @callback
    def _close_window(self, room_id: str) -> None:
        """Note that a window was closed."""
        if self._active is None:
            return
        now = dt_util.utcnow()
        if (record := self._active.rooms.get(room_id)) is not None:
            record.closed_at = now
        self._active.open_rooms.discard(room_id)
        if not self._active.open_rooms:
            self._active.ended = now
            self._schedule_settle()
        self._async_save()

    @callback
    def _track_session_temperatures(self, rooms: list[RoomData]) -> None:
        """Keep the running minimum of every room in the active session."""
        if self._active is None:
            return
        for room in rooms:
            record = self._active.rooms.get(room.room_id)
            if record is None or room.temperature is None:
                continue
            if record.temperature_start is None:
                record.temperature_start = room.temperature
            if (
                record.temperature_min is None
                or room.temperature < record.temperature_min
            ):
                record.temperature_min = room.temperature

    @callback
    def _schedule_settle(self) -> None:
        """Wait for the indoor sensors to settle before drawing conclusions."""
        self._cancel_settle()
        delay = self._option_int(CONF_SETTLE_MINUTES, DEFAULT_SETTLE_MINUTES) * 60
        self._settle_unsub = async_call_later(self.hass, delay, self._finalise)

    @callback
    def _cancel_settle(self) -> None:
        if self._settle_unsub is not None:
            self._settle_unsub()
            self._settle_unsub = None

    @callback
    def _finalise(self, _now: datetime) -> None:
        """Close the books on an airing session."""
        self._settle_unsub = None
        session = self._active
        self._active = None
        if session is None:
            return

        session.ended = session.ended or dt_util.utcnow()
        minimum = self._option_int(
            CONF_MIN_SESSION_MINUTES, DEFAULT_MIN_SESSION_MINUTES
        )
        if session.duration_minutes < minimum:
            _LOGGER.debug(
                "Discarding airing session of %.1f min (below %d min)",
                session.duration_minutes,
                minimum,
            )
            self._async_save()
            self.hass.async_create_task(self.async_request_refresh())
            return

        for room in self.rooms:
            record = session.rooms.get(room.room_id)
            if record is None:
                continue
            record.temperature_end = self._temperature(room.temperature_entity)
            record.humidity_end = self._humidity(room.humidity_entity)

        payload = session.as_dict()
        self._last = payload
        if (delta := session.delta) is not None:
            self._roll_daily_total()
            self._cooldown_today += delta

        self.hass.bus.async_fire(EVENT_AIRING_FINISHED, payload)
        self._async_save()
        self.hass.async_create_task(self.async_request_refresh())

    def _is_night(self) -> bool:
        """Whether it is currently dark outside."""
        if (sun := self.hass.states.get("sun.sun")) is not None:
            return sun.state == "below_horizon"
        hour = dt_util.now().hour
        return hour < 6 or hour >= 21

    # ------------------------------------------------------------------
    # Daily total
    # ------------------------------------------------------------------
    @callback
    def _roll_daily_total(self) -> None:
        """Zero the daily total when the date has moved on."""
        today = dt_util.now().date().isoformat()
        if self._cooldown_today_date != today:
            self._cooldown_today_date = today
            self._cooldown_today = 0.0

    @callback
    def _reset_daily_total(self, _now: datetime) -> None:
        self._roll_daily_total()
        self.hass.async_create_task(self.async_request_refresh())

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------
    async def _async_restore(self) -> None:
        """Load the last and any in-flight session from disk."""
        stored = await self._store.async_load()
        if not stored:
            return
        self._last = stored.get("last")
        self._cooldown_today = stored.get("cooldown_today", 0.0)
        self._cooldown_today_date = stored.get("cooldown_today_date")
        self._roll_daily_total()
        if active := stored.get("active"):
            try:
                self._active = AiringSession.from_dict(active)
            except (KeyError, TypeError, ValueError):
                _LOGGER.warning("Could not restore the in-flight airing session")

    @callback
    def _data_to_save(self) -> dict[str, Any]:
        return {
            "active": self._active.as_dict() if self._active else None,
            "last": self._last,
            "cooldown_today": round(self._cooldown_today, 3),
            "cooldown_today_date": self._cooldown_today_date,
        }

    @callback
    def _async_save(self) -> None:
        self._store.async_delay_save(self._data_to_save, 10)
