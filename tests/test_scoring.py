"""The airing score model."""

from __future__ import annotations

import pytest

from custom_components.stosslueft.scoring import (
    Conditions,
    ScoreSettings,
    absolute_humidity,
    dew_point,
    recommended_duration,
    score_conditions,
)

SETTINGS = ScoreSettings(target_temperature=21.0, comfort_band=1.5, humidity_weight=0.2)


@pytest.mark.parametrize(
    ("name", "indoor", "outdoor", "low", "high"),
    [
        ("summer night", Conditions(26, 55), Conditions(18, 80), 90, 100),
        ("summer afternoon", Conditions(24), Conditions(32), 0, 10),
        ("muggy warm rain", Conditions(24, 70), Conditions(22, 95), 0, 10),
        ("winter damp room", Conditions(21, 68), Conditions(2, 90), 78, 90),
        ("winter comfortable", Conditions(21, 45), Conditions(2, 90), 12, 28),
        ("already too cold", Conditions(19), Conditions(10), 0, 15),
    ],
)
def test_score_table(name, indoor, outdoor, low, high) -> None:
    """The scenarios the model was designed around."""
    score = score_conditions(indoor, outdoor, SETTINGS).score
    assert low <= score <= high, f"{name} scored {score}"


def test_rain_caps_the_score() -> None:
    """A perfect night is still no good if it is pouring."""
    perfect = score_conditions(Conditions(26, 55), Conditions(18, 80), SETTINGS)
    rained_off = score_conditions(
        Conditions(26, 55), Conditions(18, 80), SETTINGS, "pouring"
    )
    assert perfect.score > 90
    assert rained_off.score == 40
    assert rained_off.blocked_reason == "rain"
    assert rained_off.reason_key == "rain"


def test_rain_guard_can_be_switched_off() -> None:
    """Users with a sheltered balcony can ignore the rain."""
    settings = ScoreSettings(21.0, 1.5, 0.2, rain_guard=False)
    score = score_conditions(Conditions(26, 55), Conditions(18, 80), settings, "rainy")
    assert score.score > 90
    assert score.blocked_reason is None


def test_humidity_is_optional() -> None:
    """Without humidity readings the score is purely thermal."""
    score = score_conditions(Conditions(26), Conditions(18), SETTINGS)
    assert score.humidity_component is None
    assert score.applied_humidity_weight == 0
    assert score.score == 100


def test_humidity_weight_zero_disables_humidity() -> None:
    """A damp room does not override the temperature when humidity is off."""
    off = ScoreSettings(21.0, 1.5, humidity_weight=0.0)
    score = score_conditions(Conditions(21, 68), Conditions(2, 90), off)
    assert score.humidity_component is None
    assert score.score == 0


def test_damp_room_outweighs_the_heat_loss() -> None:
    """Mould risk is what makes winter airing worth the heating bill."""
    comfortable = score_conditions(Conditions(21, 45), Conditions(2, 90), SETTINGS)
    damp = score_conditions(Conditions(21, 68), Conditions(2, 90), SETTINGS)
    soaked = score_conditions(Conditions(21, 75), Conditions(2, 90), SETTINGS)
    assert comfortable.score < damp.score < soaked.score
    assert damp.reason_key == "drying"


def test_comfort_band_keeps_small_differences_quiet() -> None:
    """Inside the comfort band there is nothing to gain either way."""
    score = score_conditions(Conditions(22.0), Conditions(20.5), SETTINGS)
    assert score.reason_key == "already_comfortable"
    assert 45 <= score.score <= 55


def test_airing_can_warm_a_cold_room() -> None:
    """The model is not only about cooling."""
    score = score_conditions(Conditions(17), Conditions(24), SETTINGS)
    assert score.score > 80
    assert score.reason_key == "warming_available"


def test_recommended_duration_shrinks_with_the_difference() -> None:
    """Five minutes in winter, half an hour in summer."""
    assert recommended_duration(21, 2) < 8
    assert recommended_duration(24, 22) == 25
    assert 4 <= recommended_duration(20, -20) <= 25


def test_absolute_humidity_beats_relative_humidity() -> None:
    """90 % at 2 °C is far drier than 55 % at 26 °C."""
    assert absolute_humidity(2, 90) < absolute_humidity(26, 55)


def test_dew_point_is_below_the_temperature() -> None:
    """Sanity check on the psychrometrics."""
    assert dew_point(21, 50) == pytest.approx(10.2, abs=0.3)
    assert dew_point(21, 100) == pytest.approx(21, abs=0.1)
