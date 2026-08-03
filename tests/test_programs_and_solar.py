"""Program recognition, the lifetime energy meter, and solar surplus."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.util import dt as dt_util

from custom_components.laundry_assistant.const import (
    PHASE_HEATING,
    PHASE_SPINNING,
    PHASE_WASHING,
    PROGRAM_TOLERANCE,
    SOLAR_SURPLUS_DWELL_SECONDS,
)
from custom_components.laundry_assistant.detection import (
    match_program,
    runs_match,
    summarise_program,
)

from .curves import WASHER_CYCLE, alternating, feed, make_manager

# A short cotton-style program and a quick wash. Same phase sequence, very
# different durations - the case that used to poison the estimate.
QUICK_WASH = [
    (5, 0.5),
    (2, 50),
    (4, 2000),
    (8, alternating(60, 180, 3)),
    (1, 350),
    (4, 520),
    (7, 0.5),
]


def run_with(heating=1320.0, washing=2100.0, energy=0.9, duration=4320.0):
    return {
        "duration_seconds": duration,
        "energy_kwh": energy,
        "timeline": [
            {"phase": PHASE_HEATING, "seconds": heating},
            {"phase": PHASE_WASHING, "seconds": washing},
            {"phase": PHASE_SPINNING, "seconds": 630.0},
        ],
    }


class TestProgramMatching:
    def test_two_similar_runs_are_the_same_program(self):
        assert runs_match(run_with(), run_with(heating=1320 * 1.2), PROGRAM_TOLERANCE)

    def test_a_much_shorter_phase_is_a_different_program(self):
        """A quick wash and a cotton program can produce an identical phase
        sequence and still differ by an hour."""
        assert not runs_match(run_with(), run_with(heating=300.0), PROGRAM_TOLERANCE)

    def test_a_different_phase_sequence_is_a_different_program(self):
        no_spin = run_with()
        no_spin["timeline"] = no_spin["timeline"][:2]
        assert not runs_match(run_with(), no_spin, PROGRAM_TOLERANCE)

    def test_match_program_finds_nothing_in_an_empty_list(self):
        assert match_program(run_with(), [], PROGRAM_TOLERANCE) is None

    def test_summarise_uses_the_median(self):
        summary = summarise_program(
            [run_with(heating=1000.0), run_with(heating=1300.0), run_with(heating=9000.0)]
        )
        heating = next(e for e in summary["timeline"] if e["phase"] == PHASE_HEATING)
        # The outlier must not drag the representative shape with it.
        assert heating["seconds"] == 1300.0
        assert summary["runs"] == 3


class TestProgramsInTheManager:
    def test_repeated_identical_runs_form_one_program(self):
        manager = make_manager("washer")
        when = dt_util.utcnow() - timedelta(hours=12)
        for _ in range(3):
            when = feed(manager, WASHER_CYCLE, start=when) + timedelta(minutes=20)

        assert len(manager.programs) == 1
        assert manager.programs[0]["runs"] == 3
        assert all(run["program"] == manager.programs[0]["id"] for run in manager.runs)

    def test_a_different_program_gets_its_own_cluster(self):
        manager = make_manager("washer")
        when = dt_util.utcnow() - timedelta(hours=12)
        when = feed(manager, WASHER_CYCLE, start=when) + timedelta(minutes=20)
        feed(manager, QUICK_WASH, start=when)

        assert len(manager.programs) == 2
        durations = sorted(p["duration_seconds"] for p in manager.programs)
        assert durations[1] > durations[0] * 2

    def test_a_program_can_be_named(self):
        manager = make_manager("washer")
        feed(manager, WASHER_CYCLE)
        program_id = manager.programs[0]["id"]

        import asyncio

        asyncio.run(manager.async_set_program_name(program_id, "Cotton 60"))
        assert manager.programs[0]["name"] == "Cotton 60"

    def test_program_ids_survive_programs_being_dropped(self):
        """Ids are random rather than positional, so trimming the list
        cannot silently reassign old runs to a different program."""
        manager = make_manager("washer")
        feed(manager, WASHER_CYCLE)
        assert len(manager.programs[0]["id"]) == 8


class TestTotalEnergy:
    def test_it_accumulates_across_runs(self):
        manager = make_manager("washer")
        when = dt_util.utcnow() - timedelta(hours=12)
        for _ in range(3):
            when = feed(manager, WASHER_CYCLE, start=when) + timedelta(minutes=20)

        expected = sum(run["energy_kwh"] for run in manager.runs)
        assert abs(manager.total_energy_kwh - expected) < 0.01

    def test_clearing_the_history_does_not_move_it_backwards(self):
        """It backs a total_increasing sensor. A meter that jumps backwards
        makes the energy dashboard's long-term statistics unrecoverable."""
        import asyncio

        manager = make_manager("washer")
        feed(manager, WASHER_CYCLE)
        before = manager.total_energy_kwh
        assert before > 0

        asyncio.run(manager.async_clear_history())
        assert manager.total_energy_kwh == before
        assert manager.runs == []
        assert manager.programs == []


class TestSolarSurplus:
    def test_nothing_is_claimed_without_a_solar_sensor(self):
        manager = make_manager("washer")
        assert manager.solar_surplus_w is None
        assert manager.solar_covers_cycle is None

    def test_surplus_is_production_minus_consumption(self):
        manager = make_manager("washer")
        manager.solar_entity = "sensor.pv"
        manager.consumption_entity = "sensor.house"
        manager.hass.states.set("sensor.pv", 1800)
        manager.hass.states.set("sensor.house", 400)
        assert manager.solar_surplus_w == 1400.0

    def test_a_kilowatt_reporting_sensor_is_converted(self):
        manager = make_manager("washer")
        manager.solar_entity = "sensor.pv"
        manager.hass.states.set("sensor.pv", 1.8, unit="kW")
        assert manager.solar_surplus_w == 1800.0

    def test_typical_draw_comes_from_the_run_history(self):
        manager = make_manager("washer")
        assert manager.typical_draw_w is None
        feed(manager, WASHER_CYCLE)
        assert manager.typical_draw_w == 2000.0

    def test_a_brief_surplus_does_not_count(self):
        """A cloud passing over must not make the suggestion flicker."""
        manager = make_manager("washer")
        feed(manager, WASHER_CYCLE)
        manager.solar_entity = "sensor.pv"
        manager.hass.states.set("sensor.pv", 3000)

        manager._async_solar_changed(None)
        assert manager.solar_covers_cycle is False

        manager._surplus_since = dt_util.utcnow() - timedelta(
            seconds=SOLAR_SURPLUS_DWELL_SECONDS + 1
        )
        assert manager.solar_covers_cycle is True

    def test_a_surplus_below_the_draw_never_starts_the_clock(self):
        manager = make_manager("washer")
        feed(manager, WASHER_CYCLE)
        manager.solar_entity = "sensor.pv"
        manager.hass.states.set("sensor.pv", 500)

        manager._async_solar_changed(None)
        assert manager._surplus_since is None
        assert manager.solar_covers_cycle is False

    def test_the_saving_is_the_tariff_difference_not_the_full_price(self):
        """The alternative to using a kWh is not getting it free - it is
        being paid the feed-in tariff for the same kWh."""
        manager = make_manager("washer")
        feed(manager, WASHER_CYCLE)
        manager.price_per_kwh = 0.30
        manager.feed_in_tariff = 0.08

        energy = manager.runs[0]["energy_kwh"]
        assert abs(manager.solar_saving_per_cycle - energy * 0.22) < 0.001
