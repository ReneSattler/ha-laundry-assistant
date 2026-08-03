"""The behaviours that only show up over several runs.

Remaining-time learning, calibration, weekly totals, kW-reporting sensors,
a too-coarse update interval, and a false run that must not be recorded.

    docker compose exec homeassistant python /repo/tools/replay_behaviour.py
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.laundry_assistant.manager import LaundryApplianceManager
from homeassistant.util import dt as dt_util


class FakeState:
    def __init__(self, watts, unit="W"):
        self.state = str(watts)
        self.attributes = {"unit_of_measurement": unit}


def alternating(low, high, period):
    return lambda i: high if (i // period) % 2 else low


WASH = [
    (5, 0.5),
    (3, 50),
    (22, 2000),
    (35, alternating(60, 180, 3)),
    (1, 350),
    (11, 520),
    (8, 0.5),
]


def feed(manager, segments, start, step=10, unit="W", divisor=1.0):
    t = start
    for minutes, value in segments:
        for i in range(int(minutes * 60 / step)):
            watts = value(i) if callable(value) else value
            manager._ingest(FakeState(round(watts / divisor, 3), unit), t)
            t += timedelta(seconds=step)
    return t


def new_manager(appliance_type="washer"):
    return LaundryApplianceManager(
        MagicMock(), "test", "Test", "sensor.power", appliance_type, None
    )


print("=" * 62)
print("1. Remaining time is learned from previous runs")
print("=" * 62)
m = new_manager()
# Start three hours ago so the runs land inside the current week.
t = dt_util.utcnow() - timedelta(hours=12)
print(f"first ever run, mid-cycle estimate: {m.estimated_total_seconds}")
for n in range(3):
    t = feed(m, WASH, t) + timedelta(minutes=20)
print(f"after 3 stored runs: {len(m.runs)} runs, "
      f"durations {[round(r['duration_seconds'] / 60) for r in m.runs]} min")

# Fourth run, stopped part way through, to read the estimate live. Its
# samples have to end at the present moment: elapsed time is measured
# against the wall clock, not against the last sample, so that the figure
# keeps counting up between two updates of a slow sensor.
partial = [(5, 0.5), (3, 50), (22, 2000), (10, alternating(60, 180, 3))]
partial_minutes = sum(minutes for minutes, _ in partial)
feed(m, partial, dt_util.utcnow() - timedelta(minutes=partial_minutes))
print(f"mid-run phase: {m.phase}")
print(f"estimated total: {m.estimated_total_seconds} s "
      f"({(m.estimated_total_seconds or 0) / 60:.0f} min)")
print(f"remaining: {m.remaining_seconds} s "
      f"({(m.remaining_seconds or 0) / 60:.0f} min)")

print()
print("=" * 62)
print("2. Weekly totals and cost")
print("=" * 62)
print(f"cycles this week: {m.week_cycles}")
print(f"energy this week: {m.week_energy_kwh} kWh")
print(f"cost this week:   {m.week_cost} {m.currency} "
      f"(at {m.price_per_kwh}/kWh)")

print()
print("=" * 62)
print("3. Calibration proposes thresholds from recorded runs")
print("=" * 62)
m2 = new_manager()
m2.calibration_state = "recording"
t = dt_util.utcnow() - timedelta(hours=12)
for n in range(3):
    t = feed(m2, WASH, t) + timedelta(minutes=20)
print(f"state: {m2.calibration_state}, runs recorded: {m2.calibration_runs}")
print(f"defaults:  {new_manager().thresholds}")
print(f"proposal:  {m2.calibration_proposal}")

print()
print("=" * 62)
print("4. A sensor reporting kW instead of W")
print("=" * 62)
m3 = new_manager()
feed(m3, WASH, dt_util.utcnow() - timedelta(hours=12), unit="kW", divisor=1000.0)
r = m3.last_run
print(f"run recorded: {r is not None}")
if r:
    print(f"duration {r['duration_seconds'] / 60:.0f} min, "
          f"{r['energy_kwh']} kWh, peak {r['peak_watts']} W")
    print(f"timeline: {[e['phase'] for e in r['timeline']]}")

print()
print("=" * 62)
print("5. Update interval too coarse (Tasmota default of 300 s)")
print("=" * 62)
m4 = new_manager()
feed(m4, WASH, dt_util.utcnow() - timedelta(hours=12), step=300)
print(f"observed interval: {m4.update_interval_seconds} s, "
      f"usable: {m4.update_interval_ok}")
print(f"run recorded: {m4.last_run is not None}")
if m4.last_run:
    print(f"timeline at 300 s sampling: "
          f"{[e['phase'] for e in m4.last_run['timeline']]}")

m5 = new_manager()
feed(m5, WASH, dt_util.utcnow() - timedelta(hours=12), step=10)
print(f"at 10 s sampling: interval {m5.update_interval_seconds} s, "
      f"usable: {m5.update_interval_ok}")

print()
print("=" * 62)
print("6. A brief burst must not be recorded as a run")
print("=" * 62)
m6 = new_manager()
feed(m6, [(5, 0.5), (2, 60), (10, 0.5)], dt_util.utcnow() - timedelta(hours=12))
print(f"runs recorded: {len(m6.runs)} (expected 0)")
print(f"phase now: {m6.phase}")
