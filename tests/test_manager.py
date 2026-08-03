"""End-to-end tests: synthetic power curves replayed through the manager."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.util import dt as dt_util

from custom_components.laundry_assistant.const import (
    PHASE_COOLDOWN,
    PHASE_DRAINING,
    PHASE_DRYING,
    PHASE_HEATING,
    PHASE_IDLE,
    PHASE_INTAKE,
    PHASE_SPINNING,
    PHASE_WASHING,
)

from .curves import (
    CONDENSER_DRYER_CYCLE,
    HEAT_PUMP_DRYER_CYCLE,
    WASHER_CYCLE,
    WASHER_WITH_INTERMEDIATE_SPIN,
    alternating,
    feed,
    make_manager,
    minutes_in,
    phases,
)


class TestPhaseTimelines:
    def test_washer_cycle(self):
        manager = make_manager("washer")
        feed(manager, WASHER_CYCLE)
        assert phases(manager) == [
            PHASE_INTAKE,
            PHASE_HEATING,
            PHASE_WASHING,
            PHASE_DRAINING,
            PHASE_SPINNING,
        ]
        # The curve holds 22 minutes of heating and 35 of washing. Anything
        # far off means a transition fired at the wrong moment.
        assert 21 < minutes_in(manager, PHASE_HEATING) < 23
        assert 33 < minutes_in(manager, PHASE_WASHING) < 37
        assert 9 < minutes_in(manager, PHASE_SPINNING) < 12

    def test_washer_recovers_from_an_intermediate_spin(self):
        manager = make_manager("washer")
        feed(manager, WASHER_WITH_INTERMEDIATE_SPIN)
        sequence = phases(manager)
        # Washing has to resume after the intermediate spin rather than the
        # phase sticking on spinning until the end of the cycle.
        assert sequence.count(PHASE_WASHING) == 2
        assert sequence.count(PHASE_SPINNING) == 2
        assert sequence.index(PHASE_WASHING) < sequence.index(PHASE_SPINNING)
        assert sequence[-1] == PHASE_SPINNING

    def test_heat_pump_dryer_cycle(self):
        manager = make_manager("dryer")
        feed(manager, HEAT_PUMP_DRYER_CYCLE)
        assert phases(manager) == [PHASE_DRYING, PHASE_COOLDOWN]
        assert 75 < minutes_in(manager, PHASE_DRYING) < 79

    def test_condenser_dryer_cycle(self):
        manager = make_manager("dryer")
        feed(manager, CONDENSER_DRYER_CYCLE)
        # A cycling heating element must not produce a heating phase per
        # crossing - only the warm-up counts.
        assert phases(manager) == [PHASE_HEATING, PHASE_DRYING, PHASE_COOLDOWN]

    def test_idle_never_appears_in_the_timeline(self):
        manager = make_manager("washer")
        feed(manager, WASHER_CYCLE)
        assert PHASE_IDLE not in phases(manager)


class TestRunTracking:
    def test_duration_and_energy(self):
        manager = make_manager("washer")
        feed(manager, WASHER_CYCLE)
        run = manager.last_run
        assert 71 < run["duration_seconds"] / 60 < 73
        # Integrating the curve by hand: 22 min at 2000 W dominates, plus
        # the wash and the spin - about 0.91 kWh.
        assert 0.88 < run["energy_kwh"] < 0.94
        assert run["peak_watts"] == 2000.0
        assert abs(run["cost"] - run["energy_kwh"] * manager.price_per_kwh) < 0.001

    def test_a_sensor_reporting_kilowatts(self):
        manager = make_manager("washer")
        feed(manager, WASHER_CYCLE, unit="kW", divisor=1000.0)
        assert phases(manager) == [
            PHASE_INTAKE,
            PHASE_HEATING,
            PHASE_WASHING,
            PHASE_DRAINING,
            PHASE_SPINNING,
        ]
        assert manager.last_run["peak_watts"] == 2000.0

    def test_a_brief_burst_is_not_a_run(self):
        """A door light or a control panel waking up would otherwise poison
        both the remaining-time estimate and the weekly totals."""
        manager = make_manager("washer")
        feed(manager, [(5, 0.5), (2, 60), (10, 0.5)])
        assert manager.runs == []
        assert manager.phase == PHASE_IDLE

    def test_a_coarse_update_interval_is_flagged(self):
        manager = make_manager("washer")
        feed(manager, WASHER_CYCLE, step_seconds=300)
        assert manager.update_interval_seconds == 300.0
        assert manager.update_interval_ok is False

    def test_a_fine_update_interval_is_accepted(self):
        manager = make_manager("washer")
        feed(manager, WASHER_CYCLE, step_seconds=10)
        assert manager.update_interval_seconds == 10.0
        assert manager.update_interval_ok is True


class TestRemainingTime:
    def test_unknown_until_a_run_has_been_seen(self):
        manager = make_manager("washer")
        feed(manager, [(5, 0.5), (3, 50), (10, 2000)])
        assert manager.run_active
        assert manager.estimated_total_seconds is None
        assert manager.remaining_seconds is None

    def test_learned_from_previous_runs(self):
        manager = make_manager("washer")
        when = dt_util.utcnow() - timedelta(hours=12)
        for _ in range(3):
            when = feed(manager, WASHER_CYCLE, start=when) + timedelta(minutes=20)
        assert len(manager.runs) == 3

        # A fourth run, stopped part way through. Its samples end now,
        # because elapsed time is measured against the wall clock so that
        # the figure keeps counting between updates of a slow sensor.
        partial = [(5, 0.5), (3, 50), (22, 2000), (10, alternating(60, 180, 3))]
        elapsed_minutes = sum(minutes for minutes, _ in partial)
        feed(manager, partial, start=dt_util.utcnow() - timedelta(minutes=elapsed_minutes))

        assert manager.phase == PHASE_WASHING
        assert 71 * 60 < manager.estimated_total_seconds < 73 * 60
        # Roughly 35 minutes in on a 72 minute cycle.
        assert 30 * 60 < manager.remaining_seconds < 42 * 60


class TestWeeklyTotals:
    def test_totals_cover_the_runs_of_this_week(self):
        manager = make_manager("washer")
        when = dt_util.utcnow() - timedelta(hours=12)
        for _ in range(3):
            when = feed(manager, WASHER_CYCLE, start=when) + timedelta(minutes=20)

        assert manager.week_cycles == 3
        expected = sum(run["energy_kwh"] for run in manager.runs)
        assert abs(manager.week_energy_kwh - expected) < 0.01
        assert abs(manager.week_cost - expected * manager.price_per_kwh) < 0.01


class TestCalibration:
    def test_a_proposal_appears_after_enough_runs(self):
        manager = make_manager("washer")
        manager.calibration_state = "recording"
        when = dt_util.utcnow() - timedelta(hours=12)
        for _ in range(3):
            when = feed(manager, WASHER_CYCLE, start=when) + timedelta(minutes=20)

        assert manager.calibration_runs == 3
        assert manager.calibration_state == "ready"
        proposal = manager.calibration_proposal
        assert proposal is not None
        # Derived from this machine's 2000 W peak, so the high edge has to
        # sit well above the defaults for a generic washer.
        assert proposal["high"] > 1000
        assert proposal["standby"] < proposal["low"] < proposal["medium"] < proposal["high"]

    def test_no_proposal_while_only_one_run_is_recorded(self):
        manager = make_manager("washer")
        manager.calibration_state = "recording"
        feed(manager, WASHER_CYCLE)
        assert manager.calibration_runs == 1
        assert manager.calibration_state == "recording"
        assert manager.calibration_proposal is None
