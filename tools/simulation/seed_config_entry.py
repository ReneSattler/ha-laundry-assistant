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

ENTRY_ID = "01SIMWASHER00000000000000"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config_dir", type=Path, help="e.g. .docker-config")
    parser.add_argument("--title", default="Sim Washer")
    parser.add_argument("--type", default="washer", choices=["washer", "dryer"])
    parser.add_argument("--power-entity", default="input_number.fake_washer_power")
    args = parser.parse_args()

    store_path = args.config_dir / ".storage" / "core.config_entries"
    if not store_path.is_file():
        print(
            f"No config entry store at {store_path}. Start the container once "
            "and complete onboarding first.",
            file=sys.stderr,
        )
        return 1

    lock = args.config_dir / ".ha_run.lock"
    if lock.exists():
        print(
            "Home Assistant looks like it is still running. Stop the container "
            "first - it rewrites this store on shutdown and would overwrite "
            "the entry.",
            file=sys.stderr,
        )
        return 1

    store = json.loads(store_path.read_text(encoding="utf-8"))
    entries = store["data"]["entries"]

    if any(entry["entry_id"] == ENTRY_ID for entry in entries):
        print("The simulation entry is already present; nothing to do.")
        return 0

    now = datetime.now(timezone.utc).isoformat()
    entries.append(
        {
            "created_at": now,
            "data": {
                "power_entity": args.power_entity,
                "appliance_type": args.type,
                "door_entity": None,
            },
            "disabled_by": None,
            "discovery_keys": {},
            "domain": "laundry_assistant",
            "entry_id": ENTRY_ID,
            "minor_version": 1,
            "modified_at": now,
            "options": {},
            "pref_disable_new_entities": False,
            "pref_disable_polling": False,
            "source": "user",
            "subentries": [],
            "title": args.title,
            "unique_id": f"laundry_assistant_{args.power_entity}",
            "version": 1,
        }
    )

    backup = store_path.with_suffix(store_path.suffix + ".bak")
    if not backup.exists():
        backup.write_text(json.dumps(store, indent=2), encoding="utf-8")

    # encoding="utf-8" rather than "utf-8-sig": a BOM here is what makes
    # Home Assistant declare the store corrupt and rebuild it empty.
    store_path.write_text(json.dumps(store, indent=2), encoding="utf-8")

    slug = args.title.lower().replace(" ", "_")
    print(f"Added entry {ENTRY_ID} ({args.title}, {args.type}).")
    print(f"After starting the container the phase sensor will be sensor.{slug}_phase.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
