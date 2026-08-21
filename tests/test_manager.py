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
        # The curve holds 77 minutes of drying, but a cool-down is only
        # accepted once the low band has held for four minutes, so those
        # four count as drying. That is the deliberate trade: a cool-down
        # recognised late, against a heat pause never mistaken for one.
        assert 77 <= minutes_in(manager, PHASE_DRYING) < 83

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


class TestRunSplitting:
    """A cycle with long internal pauses must stay one run.

    Reported from a live installation: a boil wash was recorded as two or
    three separate runs, which made the calibration count them as separate
    cycles. Splitting is worse than closing late - it poisons the history
    that remaining time, calibration and the weekly totals all learn from.
    """

    def test_a_boil_wash_with_soak_pauses_stays_one_run(self):
        from .curves import BOIL_WASH_WITH_SOAK

        manager = make_manager("washer")
        feed(manager, BOIL_WASH_WITH_SOAK)

        assert len(manager.runs) == 1, (
            f"the cycle was split into {len(manager.runs)} runs"
        )
        run = manager.runs[0]
        # The curve runs 95 minutes from the first intake to the end of the
        # spin. A split would show up as a much shorter first run.
        assert 90 < run["duration_seconds"] / 60 < 100
        assert PHASE_SPINNING in [entry["phase"] for entry in run["timeline"]]

    def test_a_cycle_closes_promptly_once_it_has_spun(self):
        """Patience is only for cycles that have not reached their end yet.

        Waiting the long threshold after every cycle would delay the
        finished reminder by twenty minutes for no reason.
        """
        from custom_components.laundry_assistant.const import (
            RUN_END_PATIENT_SECONDS,
            RUN_END_SECONDS,
        )

        manager = make_manager("washer")
        feed(manager, WASHER_CYCLE)
        run = manager.runs[0]
        # WASHER_CYCLE ends with 8 minutes of standby. Closing only after
        # the patient threshold would push the recorded duration past it.
        quiet_tail = run["duration_seconds"] - (3 + 22 + 35 + 1 + 11) * 60
        assert quiet_tail < RUN_END_PATIENT_SECONDS
        assert quiet_tail <= RUN_END_SECONDS + 60

    def test_calibration_counts_a_boil_wash_once(self):
        from .curves import BOIL_WASH_WITH_SOAK

        manager = make_manager("washer")
        manager.calibration_state = "recording"
        feed(manager, BOIL_WASH_WITH_SOAK)
        assert manager.calibration_runs == 1


class TestCoarseSensorIsNotTrusted:
    """Readings every five minutes must not produce a confident timeline.

    Taken from a live installation whose Gosund plug still had Tasmota's
    default TelePeriod of 300 s. The integration reported one 39-minute
    "heating" phase for a whole boil wash, recorded thirteen calibration
    runs and invented twelve one-off "programs" - all of it fiction built
    on eleven samples, and all of it persisted.
    """

    # The actual readings, at the actual 300 s spacing.
    REAL_GOSUND_READINGS = [2041, 12, 2141, 2133, 2036, 2160, 2141, 2139, 2107, 2081, 5]

    def _feed_real_curve(self, manager):
        from datetime import datetime, timezone

        from .curves import FakeState

        when = datetime(2026, 8, 19, 9, 10, 0, tzinfo=timezone.utc)
        for watts in self.REAL_GOSUND_READINGS:
            manager._ingest(FakeState(watts), when)
            when += timedelta(seconds=300)
        # Let the run close out.
        for _ in range(10):
            manager._ingest(FakeState(0.4), when)
            when += timedelta(seconds=300)

    def test_the_reporting_rate_is_recognised_as_unusable(self):
        manager = make_manager("washer")
        self._feed_real_curve(manager)
        assert manager.update_interval_seconds == 300.0
        assert manager.update_interval_ok is False
        assert manager.detection_reliable is False

    def test_nothing_is_learned_from_it(self):
        manager = make_manager("washer")
        manager.calibration_state = "recording"
        self._feed_real_curve(manager)

        # The run itself is kept - its energy is still roughly right, and
        # the user should see that a wash happened.
        assert manager.runs, "the run should still be recorded"
        assert manager.runs[-1]["reliable"] is False
        # But none of it may reach anything that learns.
        assert manager.calibration_runs == 0
        assert manager.programs == []
        assert manager.last_anomalies == []

    def test_a_dense_sensor_is_still_learned_from(self):
        """The gate must not disable learning for a correctly configured plug."""
        manager = make_manager("washer")
        manager.calibration_state = "recording"
        feed(manager, WASHER_CYCLE)
        assert manager.detection_reliable is True
        assert manager.runs[-1]["reliable"] is True
        assert manager.calibration_runs == 1


class TestRealDryerCurve:
    """Taken from a live heat-pump dryer, whose plug reports every second.

    Its recorded timeline read drying 1s, cooldown 19s, drying 2569s,
    cooldown 58s - two cool-downs that were not cool-downs. The first was
    the drum turning before the heat came on; the second was the heat
    switching off for a minute mid-programme, which that machine does
    throughout.
    """

    def _curve(self):
        # Warm-up at drum-only power, the long drying stretch, a mid-cycle
        # heat pause, more drying, then the real cool-down.
        return [
            (5, 0.5),
            (2, 92),                          # drum only, before the heat
            (40, alternating(820, 870, 30)),  # drying
            (1.5, 115),                       # heat off for ninety seconds
            (20, alternating(820, 870, 30)),  # drying resumes
            (9, 120),                         # the actual cool-down
            (10, 0.5),
        ]

    def test_the_warm_up_is_not_a_cooldown(self):
        manager = make_manager("dryer")
        feed(manager, self._curve())
        sequence = phases(manager)
        assert sequence[0] != PHASE_COOLDOWN, (
            f"the cycle opened with a spurious cool-down: {sequence}"
        )

    def test_a_mid_cycle_heat_pause_is_not_a_cooldown(self):
        manager = make_manager("dryer")
        feed(manager, self._curve())
        sequence = phases(manager)
        # Exactly one cool-down, and it has to be the last thing that
        # happened rather than something in the middle.
        assert sequence.count(PHASE_COOLDOWN) == 1, f"got {sequence}"
        assert sequence[-1] == PHASE_COOLDOWN

    def test_the_drying_phase_is_not_chopped_into_pieces(self):
        """The spurious cool-downs split drying into fragments, which is
        why eight runs of the same programme never clustered together."""
        manager = make_manager("dryer")
        feed(manager, self._curve())
        sequence = phases(manager)
        assert sequence.count(PHASE_DRYING) == 1, f"drying was split: {sequence}"
        # 60 minutes of drying plus the 90-second heat pause and the
        # four minutes before the cool-down is accepted.
        assert 60 < minutes_in(manager, PHASE_DRYING) < 70


class TestPowerSourceStatus:
    """An appliance pointed at a sensor that is not there must say so.

    A live installation replaced its washing machine plug, which left the
    integration watching an entity that no longer existed. It sat at idle
    for days, which looks exactly like a machine nobody has used.
    """

    def test_a_missing_entity_is_reported(self):
        manager = make_manager("washer")
        manager.hass.states.get = lambda entity_id: None
        assert manager.power_source_status == "missing"

    def test_an_unavailable_entity_is_reported(self):
        from .curves import FakeState

        manager = make_manager("washer")
        manager.hass.states.get = lambda entity_id: FakeState("unavailable")
        assert manager.power_source_status == "unavailable"

    def test_a_reporting_entity_is_ok(self):
        from .curves import FakeState

        manager = make_manager("washer")
        manager.hass.states.get = lambda entity_id: FakeState(120)
        assert manager.power_source_status == "ok"


class TestFinishesAt:
    def test_unknown_while_nothing_runs(self):
        manager = make_manager("washer")
        assert manager.finishes_at is None

    def test_holds_still_between_readings(self):
        """The point of a timestamp over a minute count: it must not move
        every time a reading lands, or history becomes a staircase and an
        automation reads a value that is already stale."""
        manager = make_manager("washer")
        when = dt_util.utcnow() - timedelta(hours=12)
        for _ in range(3):
            when = feed(manager, WASHER_CYCLE, start=when) + timedelta(minutes=20)

        partial = [(5, 0.5), (3, 50), (22, 2000)]
        elapsed = sum(minutes for minutes, _ in partial)
        end = feed(manager, partial, start=dt_util.utcnow() - timedelta(minutes=elapsed))

        first = manager.finishes_at
        assert first is not None
        # A few more readings that do not change the estimate.
        feed(manager, [(1, alternating(60, 180, 3))], start=end)
        assert manager.finishes_at == first

    def test_matches_start_plus_the_estimate(self):
        manager = make_manager("washer")
        when = dt_util.utcnow() - timedelta(hours=12)
        for _ in range(3):
            when = feed(manager, WASHER_CYCLE, start=when) + timedelta(minutes=20)
        partial = [(5, 0.5), (3, 50), (20, 2000)]
        elapsed = sum(minutes for minutes, _ in partial)
        feed(manager, partial, start=dt_util.utcnow() - timedelta(minutes=elapsed))

        expected = manager.run_started + timedelta(seconds=manager.estimated_total_seconds)
        assert manager.finishes_at == expected


class TestDryerChaining:
    def _pair(self):
        from unittest.mock import MagicMock

        from custom_components.laundry_assistant.const import DOMAIN
        from custom_components.laundry_assistant.manager import LaundryApplianceManager

        hass = MagicMock()
        hass.async_create_task = lambda coro: coro.close()
        hass.config.language = "de"
        washer = LaundryApplianceManager(hass, "w", "Waschmaschine", "sensor.w", "washer", None)
        dryer = LaundryApplianceManager(hass, "d", "Trockner", "sensor.d", "dryer", None)
        hass.data = {DOMAIN: {"w": washer, "d": dryer}}
        return washer, dryer

    def test_nothing_is_said_when_no_dryer_is_configured(self):
        manager = make_manager("washer")
        manager.hass.data = {}
        assert manager.dryer_available is None
        assert manager._dryer_suffix("de") == ""

    def test_an_idle_dryer_is_mentioned(self):
        washer, _dryer = self._pair()
        washer.chain_to_dryer = True
        assert washer.dryer_available is True
        assert "Trockner" in washer._dryer_suffix("de")

    def test_a_busy_dryer_is_not_mentioned(self):
        """"Your wash is done and the dryer is busy" is noise."""
        washer, dryer = self._pair()
        washer.chain_to_dryer = True
        dryer.run_started = dt_util.utcnow()
        assert washer.dryer_available is False
        assert washer._dryer_suffix("de") == ""

    def test_silent_while_the_option_is_off(self):
        washer, _dryer = self._pair()
        assert washer.chain_to_dryer is False
        assert washer._dryer_suffix("de") == ""

    def test_a_dryer_never_chains_to_itself(self):
        _washer, dryer = self._pair()
        assert dryer.dryer_available is None
