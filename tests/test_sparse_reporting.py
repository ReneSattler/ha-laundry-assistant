"""Sensors that report only on change.

Tasmota's `PowerDelta` - which the README recommends - sends one update when
the load changes and then stays silent. Every time-based rule in the manager
has to keep working across that silence, which is what the evaluation tick
is for. A container simulation driven by an `input_number` found this the
hard way: without the tick, nothing was ever detected at all.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from custom_components.laundry_assistant.const import (
    EVALUATION_TICK_SECONDS,
    PHASE_HEATING,
    PHASE_IDLE,
    PHASE_INTAKE,
    PHASE_SPINNING,
    PHASE_WASHING,
)

from .curves import FakeState, make_manager

START = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)

# (minutes at this level, watts) - one reading per level change, nothing in
# between, exactly as a report-on-change plug behaves.
SPARSE_CYCLE = [
    (1, 0.5),
    (2, 50),
    (5, 2000),
    (2, 60),
    (2, 180),
    (2, 60),
    (2, 180),
    (2, 60),
    (2, 180),
    (2, 350),
    (4, 520),
    (6, 0.4),
]


def drive(manager, segments, tick: bool = True):
    """Report each level once, then let only the tick advance time."""
    when = START
    for minutes, watts in segments:
        manager._ingest(FakeState(watts), when)
        end = when + timedelta(minutes=minutes)
        if tick:
            cursor = when + timedelta(seconds=EVALUATION_TICK_SECONDS)
            while cursor < end:
                manager._async_tick(cursor)
                cursor += timedelta(seconds=EVALUATION_TICK_SECONDS)
        when = end
    return when


def test_a_report_on_change_sensor_still_produces_a_run():
    manager = make_manager("washer")
    drive(manager, SPARSE_CYCLE)

    assert manager.last_run is not None, (
        "no run was recorded from a sensor that only reports on change"
    )
    sequence = [entry["phase"] for entry in manager.last_run["timeline"]]
    assert sequence[0] == PHASE_INTAKE
    assert PHASE_HEATING in sequence
    assert PHASE_WASHING in sequence
    assert sequence[-1] == PHASE_SPINNING


def test_without_the_tick_no_run_is_ever_recorded():
    """Pins down why the tick exists.

    Some bands still commit, because two consecutive readings occasionally
    land in the same one - draining and spinning are both "medium". But the
    end of a run is four minutes below standby with no reading at all, so
    the run never closes and nothing is ever written to the history.
    """
    manager = make_manager("washer")
    drive(manager, SPARSE_CYCLE, tick=False)

    assert manager.runs == []
    assert manager.last_run is None


def test_the_run_closes_even_though_the_sensor_went_silent():
    """The end of a run is four minutes below standby - precisely a stretch
    during which a report-on-change sensor says nothing at all."""
    manager = make_manager("washer")
    drive(manager, SPARSE_CYCLE)
    assert not manager.run_active
    assert manager.last_run["duration_seconds"] > 0


def test_energy_is_integrated_across_the_silence():
    """Sparse samples are not missing data: the load really was constant
    between them, so the trapezoid over a long gap is the right answer."""
    manager = make_manager("washer")
    drive(manager, SPARSE_CYCLE)
    # 5 minutes at 2000 W alone is 0.167 kWh, and the rest adds to it.
    assert 0.18 < manager.last_run["energy_kwh"] < 0.30


def test_a_report_on_change_sensor_is_not_warned_about():
    """Its long gaps are flat phases, not a coarse setting. Warning about
    them would tell the user to fix what is already correct."""
    manager = make_manager("washer")
    drive(manager, SPARSE_CYCLE)

    assert manager.reports_on_change is True
    assert manager.update_interval_ok is True


def test_a_slow_timer_driven_sensor_is_still_warned_about():
    """Evenly spaced five-minute readings really do miss whole phases."""
    manager = make_manager("washer")
    when = START
    for _ in range(20):
        manager._ingest(FakeState(1500), when)
        when += timedelta(seconds=300)

    assert manager.reports_on_change is False
    assert manager.update_interval_ok is False


def test_the_tick_does_nothing_before_any_reading_arrives():
    manager = make_manager("washer")
    manager._async_tick(START)
    assert manager.phase == PHASE_IDLE
    assert manager.runs == []
