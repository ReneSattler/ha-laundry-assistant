"""Unit tests for the pure detection logic."""
from __future__ import annotations

import pytest

from custom_components.laundry_assistant.const import (
    APPLIANCE_TYPE_DRYER,
    APPLIANCE_TYPE_WASHER,
    BAND_HIGH,
    BAND_LOW,
    BAND_MEDIUM,
    BAND_OFF,
    BAND_STANDBY,
    PHASE_COOLDOWN,
    PHASE_DRAINING,
    PHASE_DRYING,
    PHASE_HEATING,
    PHASE_SPINNING,
    PHASE_WASHING,
)
from custom_components.laundry_assistant.detection import (
    COOLDOWN_MIN_SECONDS,
    DRAIN_MAX_SECONDS,
    WASH_ALTERNATIONS,
    WASH_BURST_MAX_SECONDS,
    PhaseContext,
    classify,
    next_phase_dryer,
    next_phase_washer,
    propose_thresholds,
    validate_thresholds,
)

THRESHOLDS = {BAND_STANDBY: 2.0, BAND_LOW: 20.0, BAND_MEDIUM: 150.0, BAND_HIGH: 800.0}


@pytest.mark.parametrize(
    ("watts", "expected"),
    [
        (0.0, BAND_OFF),
        (1.9, BAND_OFF),
        (2.0, BAND_STANDBY),
        (19.9, BAND_STANDBY),
        (20.0, BAND_LOW),
        (149.9, BAND_LOW),
        (150.0, BAND_MEDIUM),
        (799.9, BAND_MEDIUM),
        (800.0, BAND_HIGH),
        (2400.0, BAND_HIGH),
    ],
)
def test_classify_boundaries(watts, expected):
    assert classify(watts, THRESHOLDS) == expected


def ctx(band, dwell=0.0, seen=None, alternations=0, watts=100.0, elapsed=600.0):
    return PhaseContext(
        band=band,
        band_dwell_seconds=dwell,
        watts=watts,
        run_elapsed_seconds=elapsed,
        seen_phases=seen or set(),
        alternations=alternations,
    )


class TestWasherRules:
    def test_a_drum_reversal_does_not_end_the_wash(self):
        """Regression: every reversal pushes the draw into the medium band.

        Treating each one as a drain collapsed the wash phase entirely.
        """
        phase, _ = next_phase_washer(
            PHASE_WASHING, ctx(BAND_MEDIUM, dwell=WASH_BURST_MAX_SECONDS - 1)
        )
        assert phase == PHASE_WASHING

    def test_sustained_medium_leaves_the_wash(self):
        phase, _ = next_phase_washer(
            PHASE_WASHING, ctx(BAND_MEDIUM, dwell=WASH_BURST_MAX_SECONDS)
        )
        assert phase == PHASE_DRAINING

    def test_a_drain_that_keeps_going_is_a_spin(self):
        phase, _ = next_phase_washer(
            PHASE_DRAINING, ctx(BAND_MEDIUM, dwell=DRAIN_MAX_SECONDS)
        )
        assert phase == PHASE_SPINNING

    def test_a_drain_that_stops_returns_to_washing(self):
        phase, _ = next_phase_washer(PHASE_DRAINING, ctx(BAND_LOW, dwell=30))
        assert phase == PHASE_WASHING

    def test_alternation_ends_an_intermediate_spin(self):
        """Regression: the way back out of a spin used to require the low
        band to hold for minutes, which never happens during a wash - so the
        phase stuck on spinning for the rest of the cycle."""
        phase, _ = next_phase_washer(
            PHASE_SPINNING, ctx(BAND_LOW, dwell=20, alternations=WASH_ALTERNATIONS)
        )
        assert phase == PHASE_WASHING

    def test_a_steady_spin_stays_a_spin(self):
        phase, _ = next_phase_washer(PHASE_SPINNING, ctx(BAND_MEDIUM, dwell=300))
        assert phase == PHASE_SPINNING

    def test_high_draw_is_heating(self):
        phase, _ = next_phase_washer(PHASE_WASHING, ctx(BAND_HIGH, dwell=60))
        assert phase == PHASE_HEATING

    def test_high_draw_during_a_spin_is_not_heating(self):
        phase, _ = next_phase_washer(PHASE_SPINNING, ctx(BAND_HIGH, dwell=60))
        assert phase == PHASE_SPINNING


class TestDryerRules:
    def test_a_cycling_element_does_not_restart_heating(self):
        """Regression: a condenser dryer crosses in and out of the high band
        dozens of times per cycle. Each crossing used to open a new heating
        phase, which turned the timeline into noise."""
        phase, _ = next_phase_dryer(PHASE_DRYING, ctx(BAND_HIGH, dwell=60))
        assert phase == PHASE_DRYING

    def test_warm_up_before_drying_is_heating(self):
        phase, _ = next_phase_dryer(PHASE_HEATING, ctx(BAND_HIGH, dwell=60))
        assert phase == PHASE_HEATING

    def test_sustained_low_after_drying_is_cooldown(self):
        phase, _ = next_phase_dryer(
            PHASE_DRYING, ctx(BAND_LOW, dwell=COOLDOWN_MIN_SECONDS, elapsed=3600)
        )
        assert phase == PHASE_COOLDOWN

    def test_a_minute_long_heat_pause_is_not_a_cooldown(self):
        """A real heat-pump dryer switches its heat off for about a minute
        at a time throughout the programme. Each of those was reported as a
        cool-down and then taken back."""
        phase, _ = next_phase_dryer(PHASE_DRYING, ctx(BAND_LOW, dwell=90, elapsed=3600))
        assert phase == PHASE_DRYING

    def test_no_cooldown_before_the_programme_has_got_going(self):
        """A dryer opens by turning the drum without heat, which looks
        exactly like a cool-down from the outside."""
        phase, _ = next_phase_dryer(
            PHASE_DRYING,
            ctx(BAND_LOW, dwell=COOLDOWN_MIN_SECONDS, elapsed=30, seen={PHASE_DRYING}),
        )
        assert phase == PHASE_DRYING

    def test_a_brief_dip_is_not_cooldown(self):
        phase, _ = next_phase_dryer(PHASE_DRYING, ctx(BAND_LOW, dwell=10))
        assert phase == PHASE_DRYING

    def test_heat_returning_ends_the_cooldown(self):
        phase, _ = next_phase_dryer(PHASE_COOLDOWN, ctx(BAND_MEDIUM, dwell=30))
        assert phase == PHASE_DRYING


class TestThresholds:
    def test_validate_accepts_increasing_edges(self):
        assert validate_thresholds(THRESHOLDS) == THRESHOLDS

    def test_validate_rejects_non_increasing_edges(self):
        broken = {**THRESHOLDS, BAND_MEDIUM: 900.0}
        with pytest.raises(ValueError, match="increase strictly"):
            validate_thresholds(broken)

    def test_validate_rejects_a_missing_band(self):
        del (broken := dict(THRESHOLDS))[BAND_HIGH]
        with pytest.raises(ValueError, match="Missing threshold"):
            validate_thresholds(broken)

    def test_validate_rejects_a_zero_standby_edge(self):
        with pytest.raises(ValueError, match="greater than zero"):
            validate_thresholds({**THRESHOLDS, BAND_STANDBY: 0.0})

    def test_proposal_needs_enough_signal(self):
        assert propose_thresholds([0.0] * 500, APPLIANCE_TYPE_WASHER) is None
        assert propose_thresholds([40.0] * 10, APPLIANCE_TYPE_WASHER) is None

    def test_proposal_scales_with_the_observed_peak(self):
        samples = [60.0] * 400 + [2000.0] * 400
        proposal = propose_thresholds(samples, APPLIANCE_TYPE_WASHER)
        assert proposal is not None
        assert validate_thresholds(proposal) == proposal
        # The heating peak must land in the high band, the wash must not.
        assert classify(2000.0, proposal) == BAND_HIGH
        assert classify(60.0, proposal) in (BAND_LOW, BAND_MEDIUM)

    def test_a_heat_pump_dryer_keeps_its_drying_load_below_the_high_edge(self):
        """Its peak *is* its drying load, so a washer's fractions would put
        the whole cycle in the high band."""
        samples = [700.0] * 800
        proposal = propose_thresholds(samples, APPLIANCE_TYPE_DRYER)
        assert proposal is not None
        assert classify(700.0, proposal) == BAND_MEDIUM
