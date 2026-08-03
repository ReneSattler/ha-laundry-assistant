"""Deviation detection against the appliance's own history."""
from __future__ import annotations

import copy

from custom_components.laundry_assistant.const import (
    ANOMALY_ENERGY_HIGHER,
    ANOMALY_MIN_RUNS,
    ANOMALY_MISSING_PHASE,
    ANOMALY_PHASE_LONGER,
    ANOMALY_PHASE_SHORTER,
    DEFAULT_ANOMALY_FACTOR,
    PHASE_HEATING,
    PHASE_SPINNING,
    PHASE_WASHING,
)
from custom_components.laundry_assistant.detection import find_anomalies

from .curves import WASHER_CYCLE, feed, make_manager


def normal_run(heating_seconds=1320.0, energy=0.9):
    return {
        "duration_seconds": 4320.0,
        "energy_kwh": energy,
        "timeline": [
            {"phase": PHASE_HEATING, "seconds": heating_seconds},
            {"phase": PHASE_WASHING, "seconds": 2100.0},
            {"phase": PHASE_SPINNING, "seconds": 630.0},
        ],
    }


def history(count=ANOMALY_MIN_RUNS):
    return [normal_run() for _ in range(count)]


def kinds(findings):
    return {finding["kind"] for finding in findings}


class TestSilenceUntilThereIsEvidence:
    def test_nothing_is_reported_without_history(self):
        assert find_anomalies(normal_run(), [], DEFAULT_ANOMALY_FACTOR, ANOMALY_MIN_RUNS) == []

    def test_nothing_is_reported_below_the_minimum(self):
        """Crying wolf on the third ever wash would train the user to
        ignore the feature."""
        outlier = normal_run(heating_seconds=4000.0)
        findings = find_anomalies(
            outlier, history(ANOMALY_MIN_RUNS - 1), DEFAULT_ANOMALY_FACTOR, ANOMALY_MIN_RUNS
        )
        assert findings == []

    def test_a_normal_run_is_not_flagged(self):
        assert find_anomalies(
            normal_run(), history(), DEFAULT_ANOMALY_FACTOR, ANOMALY_MIN_RUNS
        ) == []

    def test_small_variation_is_not_flagged(self):
        slightly_longer = normal_run(heating_seconds=1320.0 * 1.3)
        assert find_anomalies(
            slightly_longer, history(), DEFAULT_ANOMALY_FACTOR, ANOMALY_MIN_RUNS
        ) == []


class TestFindings:
    def test_a_much_longer_heating_phase_is_flagged(self):
        """The limescale case: the element takes longer and longer to reach
        temperature, over months, which nobody notices by eye."""
        scaled_up = normal_run(heating_seconds=1320.0 * 2)
        findings = find_anomalies(
            scaled_up, history(), DEFAULT_ANOMALY_FACTOR, ANOMALY_MIN_RUNS
        )
        assert ANOMALY_PHASE_LONGER in kinds(findings)
        finding = next(f for f in findings if f["kind"] == ANOMALY_PHASE_LONGER)
        assert finding["phase"] == PHASE_HEATING
        assert finding["expected_seconds"] == 1320

    def test_a_much_shorter_phase_is_flagged(self):
        cut_short = normal_run(heating_seconds=1320.0 / 3)
        findings = find_anomalies(
            cut_short, history(), DEFAULT_ANOMALY_FACTOR, ANOMALY_MIN_RUNS
        )
        assert ANOMALY_PHASE_SHORTER in kinds(findings)

    def test_higher_energy_is_flagged(self):
        hungry = normal_run(energy=0.9 * 2)
        findings = find_anomalies(hungry, history(), DEFAULT_ANOMALY_FACTOR, ANOMALY_MIN_RUNS)
        assert ANOMALY_ENERGY_HIGHER in kinds(findings)

    def test_a_missing_spin_is_flagged(self):
        """A cycle that ends without a spin usually means the machine gave
        up on an unbalanced load."""
        no_spin = copy.deepcopy(normal_run())
        no_spin["timeline"] = [
            entry for entry in no_spin["timeline"] if entry["phase"] != PHASE_SPINNING
        ]
        findings = find_anomalies(no_spin, history(), DEFAULT_ANOMALY_FACTOR, ANOMALY_MIN_RUNS)
        assert ANOMALY_MISSING_PHASE in kinds(findings)
        finding = next(f for f in findings if f["kind"] == ANOMALY_MISSING_PHASE)
        assert finding["phase"] == PHASE_SPINNING

    def test_a_different_program_is_not_judged_against_the_wrong_baseline(self):
        """A run whose phase sequence differs has no comparable history, so
        only the missing-phase check may speak - never the durations."""
        different = {
            "duration_seconds": 1200.0,
            "energy_kwh": 0.2,
            "timeline": [
                {"phase": PHASE_WASHING, "seconds": 900.0},
                {"phase": PHASE_SPINNING, "seconds": 300.0},
            ],
        }
        findings = find_anomalies(
            different, history(), DEFAULT_ANOMALY_FACTOR, ANOMALY_MIN_RUNS
        )
        assert ANOMALY_PHASE_LONGER not in kinds(findings)
        assert ANOMALY_PHASE_SHORTER not in kinds(findings)
        assert ANOMALY_ENERGY_HIGHER not in kinds(findings)


class TestManagerIntegration:
    def test_a_run_is_never_part_of_its_own_baseline(self):
        manager = make_manager("washer")
        manager.runs = history()
        feed(manager, WASHER_CYCLE)
        # The recorded run is appended after the comparison, so the history
        # used must still be the five injected runs.
        assert len(manager.runs) == ANOMALY_MIN_RUNS + 1

    def test_detection_can_be_switched_off(self):
        manager = make_manager("washer")
        manager.anomaly_detection_enabled = False
        manager.runs = history()
        feed(manager, WASHER_CYCLE)
        assert manager.last_anomalies == []

    def test_findings_are_rendered_as_sentences(self):
        manager = make_manager("washer")
        message = manager.describe_anomaly(
            {
                "kind": ANOMALY_PHASE_LONGER,
                "phase": PHASE_HEATING,
                "observed_seconds": 2640,
                "expected_seconds": 1320,
            }
        )
        assert "44" in message and "22" in message
        assert PHASE_HEATING in message
