"""Power-only features: no extra hardware, derived from watt + time.

Covers issues #23-#27: aborted runs, monthly totals, dynamic price sensor,
consumable counter and the ready-by planner.
"""
from __future__ import annotations

from datetime import timedelta

from homeassistant.util import dt as dt_util

from .curves import WASHER_CYCLE, feed, make_manager


def test_finished_run_marks_outcome_and_counts_consumable():
    manager = make_manager("washer")
    feed(manager, WASHER_CYCLE, start=dt_util.utcnow() - timedelta(hours=3))
    assert manager.last_run["outcome"] == "finished"
    assert manager.last_outcome == "finished"
    assert manager.phase == "finished"
    assert manager.cycles_since_reset == 1
    assert manager.week_cycles == 1
    assert manager.month_cycles == 1


def test_aborted_run_without_terminal_phase():
    manager = make_manager("washer")
    # Heating then a long quiet stretch: never reaches spinning, so it is
    # aborted. Quiet must outlast the patient close threshold (20 min),
    # which deliberately waits for late spins before giving up on a run.
    feed(
        manager,
        [(5, 0.5), (3, 50), (10, 2000), (5, 80), (25, 0.5)],
        start=dt_util.utcnow() - timedelta(hours=3),
    )
    assert manager.last_run is not None
    assert manager.last_run["outcome"] == "aborted"
    assert manager.phase == "aborted"
    # Aborted cycles cost energy but are no finished cycles.
    assert manager.cycles_since_reset == 0
    assert manager.week_cycles == 0
    assert manager.month_cycles == 0
    assert manager.total_energy_kwh > 0
    # ... and they must not shape the remaining-time expectation.
    assert manager.estimated_total_seconds is None


def test_monthly_totals_cover_this_month():
    manager = make_manager("washer")
    when = dt_util.utcnow() - timedelta(hours=12)
    for _ in range(2):
        when = feed(manager, WASHER_CYCLE, start=when) + timedelta(minutes=20)
    assert manager.month_cycles == 2
    expected = sum(run["energy_kwh"] for run in manager.runs)
    assert abs(manager.month_energy_kwh - expected) < 0.01
    assert abs(manager.month_cost - expected * manager.effective_price) < 0.01


async def test_dynamic_price_sensor_overrides_fixed_price():
    manager = make_manager("washer")
    manager.hass.states.set("sensor.price", 0.50)
    await manager.async_set_price_sensor("sensor.price")
    assert manager.effective_price == 0.50
    feed(manager, WASHER_CYCLE)
    run = manager.last_run
    assert abs(run["cost"] - run["energy_kwh"] * 0.50) < 0.001
    await manager.async_set_price_sensor(None)
    assert manager.effective_price == manager.price_per_kwh


async def test_consumable_counter_reset():
    manager = make_manager("washer")
    when = dt_util.utcnow() - timedelta(hours=12)
    for _ in range(2):
        when = feed(manager, WASHER_CYCLE, start=when) + timedelta(minutes=20)
    assert manager.cycles_since_reset == 2
    await manager.async_reset_consumable_counter()
    assert manager.cycles_since_reset == 0


async def test_ready_by_planner_derives_latest_start():
    manager = make_manager("washer")
    when = dt_util.utcnow() - timedelta(hours=12)
    for _ in range(2):
        when = feed(manager, WASHER_CYCLE, start=when) + timedelta(minutes=20)
    import statistics

    median_total = statistics.median(r["duration_seconds"] for r in manager.runs)
    ready_by = dt_util.utcnow() + timedelta(hours=5)
    await manager.async_plan_ready_by(ready_by.isoformat())
    latest = manager.planned_latest_start
    assert latest is not None
    assert abs((ready_by - latest).total_seconds() - median_total) < 5
    await manager.async_plan_ready_by(None)
    assert manager.planned_latest_start is None
