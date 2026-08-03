"""Export a power sensor's recorded history from Home Assistant to CSV.

This is how a real appliance's power curve becomes a test fixture. Point it
at a copy of your instance's recorder database and at the plug's power
sensor, and it writes one CSV per detected run.

    python tools/export_history.py /path/to/home-assistant_v2.db \\
        sensor.washing_machine_power --out tests/fixtures

Work on a *copy* of the database. Home Assistant keeps it open, and reading
a live SQLite file that another process is writing can return a torn view.

Caveats worth knowing before trusting the output:

- The recorder purges after ten days by default, so a run older than that
  is simply gone.
- If the sensor's update interval was too coarse when the data was
  recorded, no amount of exporting fixes it - the phases were never
  captured. The script reports the median interval it found so this is
  visible rather than silent.
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

# A gap of at least this long at or below the idle threshold separates two
# runs. Matches RUN_END_SECONDS in the integration.
RUN_GAP_SECONDS = 240
# Below this the appliance counts as idle, in watts. Deliberately generous:
# the point is to cut the file into runs, not to classify anything.
IDLE_WATTS = 5.0
# A stretch shorter than this is a door light, not a cycle.
MIN_RUN_SECONDS = 600


def read_samples(db_path: Path, entity_id: str) -> list[tuple[float, float]]:
    """Every numeric state of one entity, oldest first."""
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT s.last_updated_ts, s.state FROM states s "
            "JOIN states_meta m ON s.metadata_id = m.metadata_id "
            "WHERE m.entity_id = ? AND s.last_updated_ts IS NOT NULL "
            "ORDER BY s.last_updated_ts",
            (entity_id,),
        ).fetchall()
    finally:
        connection.close()

    samples = []
    for timestamp, state in rows:
        try:
            samples.append((float(timestamp), float(state)))
        except (TypeError, ValueError):
            # unknown / unavailable - not a reading.
            continue
    return samples


def split_runs(samples: list[tuple[float, float]]) -> list[list[tuple[float, float]]]:
    """Cut the stream into runs, separated by long idle stretches."""
    runs: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    idle_since: float | None = None

    for timestamp, watts in samples:
        if watts > IDLE_WATTS:
            idle_since = None
            current.append((timestamp, watts))
            continue

        if current:
            current.append((timestamp, watts))
            if idle_since is None:
                idle_since = timestamp
            elif timestamp - idle_since >= RUN_GAP_SECONDS:
                runs.append(current)
                current = []
                idle_since = None

    if current:
        runs.append(current)

    return [
        run for run in runs if run and run[-1][0] - run[0][0] >= MIN_RUN_SECONDS
    ]


def median_interval(run: list[tuple[float, float]]) -> float:
    deltas = [b[0] - a[0] for a, b in zip(run, run[1:]) if b[0] > a[0]]
    return statistics.median(deltas) if deltas else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path, help="copy of home-assistant_v2.db")
    parser.add_argument("entity_id", help="e.g. sensor.washing_machine_power")
    parser.add_argument("--out", type=Path, default=Path("tests/fixtures"))
    parser.add_argument(
        "--prefix", default=None, help="filename prefix (default: from the entity id)"
    )
    args = parser.parse_args()

    if not args.database.is_file():
        print(f"No such database: {args.database}", file=sys.stderr)
        return 1

    samples = read_samples(args.database, args.entity_id)
    if not samples:
        print(
            f"No numeric states found for {args.entity_id}. Check the entity id, "
            "and remember the recorder purges after ten days by default.",
            file=sys.stderr,
        )
        return 1

    runs = split_runs(samples)
    if not runs:
        print(
            f"Found {len(samples)} samples but no run longer than "
            f"{MIN_RUN_SECONDS // 60} minutes.",
            file=sys.stderr,
        )
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    prefix = args.prefix or args.entity_id.split(".")[-1]

    for run in runs:
        started = datetime.fromtimestamp(run[0][0], tz=timezone.utc)
        interval = median_interval(run)
        name = f"{prefix}-{started:%Y%m%d-%H%M}.csv"
        path = args.out / name
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["timestamp", "watts"])
            for timestamp, watts in run:
                writer.writerow([f"{timestamp:.3f}", f"{watts:.2f}"])

        duration = (run[-1][0] - run[0][0]) / 60
        warning = ""
        if interval > 30:
            warning = (
                "  <-- sampled too coarsely for phase detection; the plug was "
                "reporting too slowly when this was recorded"
            )
        print(
            f"{name}: {len(run)} samples, {duration:.0f} min, "
            f"median interval {interval:.0f} s, peak {max(w for _, w in run):.0f} W"
            f"{warning}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
