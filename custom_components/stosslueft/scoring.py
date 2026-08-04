"""The airing score model.

Pure functions only -- nothing in here imports Home Assistant, which is what
makes the model straightforward to unit test.

The idea in one paragraph: opening the windows drags every room's temperature
towards the outdoor temperature, so the question "is airing out a good idea?"
is really "does that drag move the room closer to where I want it, and does it
dry the room out or wet it?".  Scoring the *change* rather than the raw
temperature difference is what lets a single formula work in July and in
January.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .const import (
    BETA_MASS,
    K_AH,
    K_DUR,
    K_TEMP,
    MAX_DURATION,
    MIN_DURATION,
    RAIN_SCORE_CAP,
    RAINY_CONDITIONS,
    RATING_THRESHOLDS,
    RH_CRIT,
    RH_HIGH,
    TAU_AIR,
)


def clamp(value: float, low: float, high: float) -> float:
    """Clamp value into [low, high]."""
    return max(low, min(high, value))


def saturation_vapour_pressure(temperature: float) -> float:
    """Saturation vapour pressure in hPa (Magnus formula)."""
    return 6.112 * math.exp(17.62 * temperature / (243.12 + temperature))


def absolute_humidity(temperature: float, relative_humidity: float) -> float:
    """Absolute humidity in g/m3.

    This -- not relative humidity -- is what decides whether airing out dries
    the flat or wets it: 90 % at 2 °C carries far less water than 55 % at 26 °C.
    """
    vapour_pressure = (
        relative_humidity / 100.0 * saturation_vapour_pressure(temperature)
    )
    return 216.7 * vapour_pressure / (273.15 + temperature)


def dew_point(temperature: float, relative_humidity: float) -> float:
    """Dew point in °C."""
    if relative_humidity <= 0:
        return float("-inf")
    gamma = math.log(relative_humidity / 100.0) + (
        17.62 * temperature / (243.12 + temperature)
    )
    return 243.12 * gamma / (17.62 - gamma)


def recommended_duration(indoor: float, outdoor: float) -> float:
    """How long to leave the windows open, in minutes.

    The bigger the temperature difference, the faster the air is exchanged --
    the classic "5 minutes in winter, half an hour in summer" rule of thumb.
    """
    delta = abs(outdoor - indoor)
    return clamp(K_DUR / max(delta, 1.0), MIN_DURATION, MAX_DURATION)


def projected_temperature(indoor: float, outdoor: float, duration: float) -> float:
    """Indoor temperature we expect to settle at after airing for `duration`.

    Two effects: the air itself equilibrates towards outdoor with a time
    constant of TAU_AIR, and then the walls and furniture give a good part of
    that back once the windows are shut again (BETA_MASS).
    """
    exchanged = 1.0 - math.exp(-duration / TAU_AIR)
    return indoor + BETA_MASS * exchanged * (outdoor - indoor)


def _comfort_distance(temperature: float, target: float, band: float) -> float:
    """How far outside the comfort band a temperature is, in degrees."""
    return max(0.0, abs(temperature - target) - band)


@dataclass(frozen=True, slots=True)
class Conditions:
    """A temperature with optional relative humidity."""

    temperature: float
    humidity: float | None = None

    @property
    def absolute_humidity(self) -> float | None:
        """Absolute humidity in g/m3, if relative humidity is known."""
        if self.humidity is None:
            return None
        return absolute_humidity(self.temperature, self.humidity)

    @property
    def dew_point(self) -> float | None:
        """Dew point in °C, if relative humidity is known."""
        if self.humidity is None:
            return None
        return dew_point(self.temperature, self.humidity)


@dataclass(frozen=True, slots=True)
class ScoreSettings:
    """User-tunable knobs of the model."""

    target_temperature: float
    comfort_band: float
    humidity_weight: float
    rain_guard: bool = True


@dataclass(frozen=True, slots=True)
class Score:
    """The verdict for one room (or for the flat as a whole)."""

    score: int
    rating: str
    reason: str
    reason_key: str
    reason_placeholders: dict[str, float] = field(default_factory=dict)
    projected_temperature: float | None = None
    temperature_component: float = 0.0
    humidity_component: float | None = None
    applied_humidity_weight: float = 0.0
    blocked_reason: str | None = None


def rating_for(score: float) -> str:
    """Map a 0-100 score onto a coarse rating word."""
    for threshold, rating in RATING_THRESHOLDS:
        if score >= threshold:
            return rating
    return RATING_THRESHOLDS[-1][1]


# Human readable fallbacks. The card localises `reason_key` itself; `reason`
# exists so the attribute is readable in Developer Tools and in automations
# that just want to drop a sentence into a notification.
_REASON_TEXT: dict[str, str] = {
    "no_data": "No temperature data",
    "rain": "It is raining -- windows stay shut",
    "cooling_available": "{delta:.1f} °C cooler outside",
    "warming_available": "{delta:.1f} °C warmer outside, airing warms the room",
    "too_warm_outside": "{delta:.1f} °C warmer outside -- would heat the room up",
    "heat_loss": "{delta:.1f} °C colder outside -- would just waste heat",
    "drying": "Damp inside ({humidity:.0f} %), the outside air is drier",
    "would_add_moisture": "Damp inside ({humidity:.0f} %), but outside air is wetter still",
    "already_comfortable": "Comfortable already, little to gain",
}


def _reason(
    key: str, placeholders: dict[str, float]
) -> tuple[str, str, dict[str, float]]:
    return _REASON_TEXT[key].format(**placeholders), key, placeholders


def score_conditions(
    indoor: Conditions,
    outdoor: Conditions,
    settings: ScoreSettings,
    outdoor_condition: str | None = None,
) -> Score:
    """Score how good an idea airing out is, for a single room."""
    duration = recommended_duration(indoor.temperature, outdoor.temperature)
    projected = projected_temperature(indoor.temperature, outdoor.temperature, duration)

    target = settings.target_temperature
    band = settings.comfort_band
    improvement = _comfort_distance(
        indoor.temperature, target, band
    ) - _comfort_distance(projected, target, band)
    temperature_component = clamp(improvement / K_TEMP, -1.0, 1.0)

    # Humidity is optional: it needs a sensor on both sides and a non-zero
    # weight, otherwise the score is purely thermal.
    ah_in = indoor.absolute_humidity
    ah_out = outdoor.absolute_humidity
    humidity_component: float | None = None
    weight = 0.0
    if settings.humidity_weight > 0 and ah_in is not None and ah_out is not None:
        humidity_component = clamp((ah_in - ah_out) / K_AH, -1.0, 1.0)
        # Once a room gets damp, drying it out matters more than the couple of
        # degrees it costs -- that is what makes winter airing worthwhile.
        assert indoor.humidity is not None
        mould_urgency = clamp(
            (indoor.humidity - RH_HIGH) / (RH_CRIT - RH_HIGH), 0.0, 1.0
        )
        weight = (
            settings.humidity_weight + (1.0 - settings.humidity_weight) * mould_urgency
        )

    raw = (1.0 - weight) * temperature_component + weight * (humidity_component or 0.0)
    score = round(50 + 50 * clamp(raw, -1.0, 1.0))

    blocked_reason: str | None = None
    if (
        settings.rain_guard
        and outdoor_condition in RAINY_CONDITIONS
        and score > RAIN_SCORE_CAP
    ):
        score = RAIN_SCORE_CAP
        blocked_reason = "rain"

    delta = outdoor.temperature - indoor.temperature
    if blocked_reason == "rain":
        text, key, placeholders = _reason("rain", {})
    elif weight >= 0.5 and humidity_component is not None:
        assert indoor.humidity is not None
        text, key, placeholders = _reason(
            "drying" if humidity_component > 0 else "would_add_moisture",
            {"humidity": indoor.humidity},
        )
    elif temperature_component > 0.15:
        text, key, placeholders = _reason(
            "cooling_available" if delta < 0 else "warming_available",
            {"delta": abs(delta)},
        )
    elif temperature_component < -0.15:
        text, key, placeholders = _reason(
            "too_warm_outside" if delta > 0 else "heat_loss",
            {"delta": abs(delta)},
        )
    else:
        text, key, placeholders = _reason("already_comfortable", {})

    return Score(
        score=score,
        rating=rating_for(score),
        reason=text,
        reason_key=key,
        reason_placeholders=placeholders,
        projected_temperature=round(projected, 2),
        temperature_component=round(temperature_component, 3),
        humidity_component=(
            None if humidity_component is None else round(humidity_component, 3)
        ),
        applied_humidity_weight=round(weight, 3),
        blocked_reason=blocked_reason,
    )


def no_data_score(reason_key: str = "no_data") -> Score:
    """Placeholder verdict for a room we cannot score right now."""
    return Score(
        score=0,
        rating=rating_for(0),
        reason=_REASON_TEXT[reason_key],
        reason_key=reason_key,
    )
