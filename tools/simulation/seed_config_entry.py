"""Add a Laundry Assistant config entry to the throwaway test instance.

Adding the integration through the UI needs a login. This writes the entry
straight into the instance's storage instead, so a simulated cycle can be
run without one.

    docker compose stop
    python tools/simulation/seed_config_entry.py .docker-config
    docker compose up -d

Only ever point this at the throwaway instance created by
docker-compose.yml. It edits `.storage/core.config_entries`, which Home
Assistant owns.

Two things this gets right that are easy to get wrong by hand, and which
cost an evening once:

- The file must be written **without a byte order mark**. Home Assistant's
  JSON loader rejects one, declares the store corrupt, moves it aside and
  rebuilds it empty - taking every other configured integration with it.
- Home Assistant must not be running. It rewrites the store on shutdown and
  would overwrite the edit.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

def entry_id_for(appliance_type: str) -> str:
    """A stable, recognisable id per appliance type.

    Fixed rather than random so that running the script twice does not add a
    second copy of the same appliance, and so a washer and a dryer can both
    be seeded into one instance.
    """
    return f"01SIM{appliance_type.upper()}".ljust(26, "0")[:26]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config_dir", type=Path, help="e.g. .docker-config")
    parser.add_argument("--type", default="washer", choices=["washer", "dryer"])
    parser.add_argument("--title", help="defaults to 'Sim Washer' / 'Sim Dryer'")
    parser.add_argument(
        "--power-entity", help="defaults to the matching input_number helper"
    )
    args = parser.parse_args()

    # Both default off the appliance type, so seeding a dryer needs no more
    # than `--type dryer` and still lines up with the helper and the entity
    # id the simulation automations reference.
    title = args.title or f"Sim {args.type.capitalize()}"
    power_entity = args.power_entity or f"input_number.fake_{args.type}_power"

    store_path = args.config_dir / ".storage" / "core.config_entries"
    if not store_path.is_file():
        print(
            f"No config entry store at {store_path}. Start the container once "
            "and complete onboarding first.",
            file=sys.stderr,
        )
        return 1

    # Deliberately no "is Home Assistant running" check. The obvious
    # candidate, `.ha_run.lock`, stays on disk after a clean shutdown, so its
    # presence proves nothing - an earlier version refused to run because of
    # it even with the container stopped. From outside the container there is
    # no reliable signal, so this warns instead of guessing.
    print(
        "Stop Home Assistant before running this. It rewrites the store on "
        "shutdown and would overwrite the entry.",
        file=sys.stderr,
    )

    store = json.loads(store_path.read_text(encoding="utf-8"))
    entries = store["data"]["entries"]

    entry_id = entry_id_for(args.type)
    if any(entry["entry_id"] == entry_id for entry in entries):
        print("The simulation entry is already present; nothing to do.")
        return 0

    now = datetime.now(timezone.utc).isoformat()
    entries.append(
        {
            "created_at": now,
            "data": {
                "power_entity": power_entity,
                "appliance_type": args.type,
                "door_entity": None,
            },
            "disabled_by": None,
            "discovery_keys": {},
            "domain": "laundry_assistant",
            "entry_id": entry_id,
            "minor_version": 1,
            "modified_at": now,
            "options": {},
            "pref_disable_new_entities": False,
            "pref_disable_polling": False,
            "source": "user",
            "subentries": [],
            "title": title,
            "unique_id": f"laundry_assistant_{power_entity}",
            "version": 1,
        }
    )

    backup = store_path.with_suffix(store_path.suffix + ".bak")
    if not backup.exists():
        backup.write_text(json.dumps(store, indent=2), encoding="utf-8")

    # encoding="utf-8" rather than "utf-8-sig": a BOM here is what makes
    # Home Assistant declare the store corrupt and rebuild it empty.
    store_path.write_text(json.dumps(store, indent=2), encoding="utf-8")

    slug = title.lower().replace(" ", "_")
    print(f"Added entry {entry_id} ({title}, {args.type}).")
    print(f"After starting the container the phase sensor will be sensor.{slug}_phase.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
