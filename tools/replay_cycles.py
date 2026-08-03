"""Replay synthetic power curves through the real LaundryApplianceManager.

Checks the phase timeline the detection rules produce, and the duration,
energy and cost derived from a run.

Run it in the container started by docker-compose.yml, which is where
homeassistant is importable:

    docker compose exec homeassistant python /repo/tools/replay_cycles.py

Home Assistant itself is stubbed out - the manager only needs `hass` for
storage and scheduling, neither of which affects detection.

These curves are hand-built and only prove the code does what it was
written to do. Whether the rules match a real appliance is a separate
question, tracked in issue #11.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.laundry_assistant.manager import LaundryApplianceManager


class FakeState:
    def __init__(self, watts):
        self.state = str(watts)
        self.attributes = {"unit_of_measurement": "W"}


def build(segments, step_seconds=10):
    """Expand (minutes, watts-or-callable) segments into samples."""
    samples = []
    t = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
    for minutes, value in segments:
        for i in range(int(minutes * 60 / step_seconds)):
            watts = value(i) if callable(value) else value
            samples.append((t, watts))
            t += timedelta(seconds=step_seconds)
    return samples


def alternating(low, high, period_samples):
    return lambda i: high if (i // period_samples) % 2 else low


def run(name, appliance_type, segments):
    manager = LaundryApplianceManager(
        MagicMock(), "test", name, "sensor.power", appliance_type, None
    )
    observed = []
    for when, watts in build(segments):
        manager._ingest(FakeState(watts), when)
        if not observed or observed[-1][0] != manager.phase:
            observed.append((manager.phase, when, manager.confidence))

    print(f"\n=== {name} ({appliance_type}) ===")
    print("phase sequence as it was reported live:")
    for phase, when, conf in observed:
        print(f"  {when.strftime('%H:%M:%S')}  {phase:<10} confidence {conf}")

    if manager.last_run:
        r = manager.last_run
        print(f"\nstored run: {r['duration_seconds'] / 60:.1f} min, "
              f"{r['energy_kwh']} kWh, cost {r['cost']}, peak {r['peak_watts']} W")
        print("timeline:")
        for entry in r["timeline"]:
            print(f"  {entry['phase']:<10} {entry['seconds'] / 60:6.1f} min")
    else:
        print("\nNO RUN WAS RECORDED")
    return manager


# A washing machine: standby, water intake, a long heating phase, the wash
# itself alternating as the drum reverses every 30 s, a short drain, the
# spin, then off.
run(
    "Washing machine",
    "washer",
    [
        (5, 0.5),
        (3, 50),
        (22, 2000),
        (35, alternating(60, 180, 3)),
        (1, 350),
        (11, 520),
        (8, 0.5),
    ],
)

# The same machine, but with an intermediate spin between two wash blocks -
# which real programs do. The phase must fall back to washing afterwards
# instead of sticking on "spinning" for the rest of the cycle.
run(
    "Washing machine (intermediate spin)",
    "washer",
    [
        (5, 0.5),
        (3, 50),
        (20, 2000),
        (15, alternating(60, 180, 3)),
        (3, 450),
        (12, alternating(60, 180, 3)),
        (1, 350),
        (10, 520),
        (8, 0.5),
    ],
)

# A heat-pump dryer: never reaches the "high" band, ends with a cool-down
# where only the drum turns.
run(
    "Heat pump dryer",
    "dryer",
    [
        (5, 0.5),
        (2, 300),
        (75, alternating(620, 780, 30)),
        (9, 130),
        (8, 0.5),
    ],
)

# A condenser dryer: cycles its heating element into the "high" band.
run(
    "Condenser dryer",
    "dryer",
    [
        (5, 0.5),
        (60, alternating(2400, 900, 18)),
        (10, 140),
        (8, 0.5),
    ],
)
