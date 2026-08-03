"""Replay a recorded CSV fixture through the real detection pipeline.

    docker compose exec homeassistant \\
        python /repo/tools/replay_fixture.py /repo/tests/fixtures/washer-....csv --type washer

Takes the CSV that `export_history.py` writes - `timestamp,watts` - and
prints the phase timeline the integration would have produced, plus the
energy and duration it would have recorded.

This is the tool that answers the only question the synthetic curves
cannot: whether the transition rules match a real machine. Run it on a
fixture from your own appliance, compare the printed timeline against what
the machine was actually doing, and adjust the thresholds if they disagree.
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.laundry_assistant.detection import propose_thresholds
from custom_components.laundry_assistant.manager import LaundryApplianceManager


class FakeState:
    def __init__(self, watts: float) -> None:
        self.state = str(watts)
        self.attributes = {"unit_of_measurement": "W"}


def load(path: Path) -> list[tuple[datetime, float]]:
    samples = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            samples.append(
                (
                    datetime.fromtimestamp(float(row["timestamp"]), tz=timezone.utc),
                    float(row["watts"]),
                )
            )
    return samples


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--type", default="washer", choices=["washer", "dryer"])
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="derive thresholds from this fixture instead of using the defaults",
    )
    args = parser.parse_args()

    samples = load(args.fixture)
    if len(samples) < 10:
        print(f"{args.fixture} holds too few samples to say anything.", file=sys.stderr)
        return 1

    hass = MagicMock()
    hass.async_create_task = lambda coro: coro.close()
    hass.config.language = "en"
    manager = LaundryApplianceManager(
        hass, "replay", args.fixture.stem, "sensor.power", args.type, None
    )

    if args.calibrate:
        proposal = propose_thresholds([w for _, w in samples], args.type)
        if proposal is None:
            print("Not enough signal in this fixture to propose thresholds.")
        else:
            manager.thresholds = proposal
            print(f"calibrated thresholds: {proposal}")

    print(f"thresholds in use: {manager.thresholds}")

    for when, watts in samples:
        manager._ingest(FakeState(watts), when)

    print(f"samples:          {len(samples)}")
    print(f"median interval:  {manager.update_interval_seconds} s "
          f"(usable: {manager.update_interval_ok})")

    run = manager.last_run
    if run is None:
        print()
        print("NO RUN WAS DETECTED.")
        print("Most likely causes: the fixture does not cover a full cycle "
              "(the run only closes after four minutes below standby), or the "
              "thresholds do not fit this machine - try --calibrate.")
        return 1

    print(f"duration:         {run['duration_seconds'] / 60:.1f} min")
    print(f"energy:           {run['energy_kwh']} kWh")
    print(f"peak:             {run['peak_watts']} W")
    print()
    print("phase timeline:")
    for entry in run["timeline"]:
        print(f"  {entry['phase']:<10} {entry['seconds'] / 60:6.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
