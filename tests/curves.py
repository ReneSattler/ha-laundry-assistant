"""Synthetic power curves and the helpers that replay them.

Kept out of conftest.py so the test modules can import them explicitly
rather than reaching into a fixture file.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from custom_components.laundry_assistant.manager import LaundryApplianceManager


class FakeState:
    """The part of a State object the manager actually reads."""

    def __init__(self, watts, unit: str = "W") -> None:
        self.state = str(watts)
        self.attributes = {"unit_of_measurement": unit}


class FakeStates:
    """Just enough of the state machine for the solar surplus lookups."""

    def __init__(self) -> None:
        self._states: dict[str, FakeState] = {}

    def get(self, entity_id: str) -> FakeState | None:
        return self._states.get(entity_id)

    def set(self, entity_id: str, watts, unit: str = "W") -> None:
        self._states[entity_id] = FakeState(watts, unit)


def stub_hass() -> MagicMock:
    """A `hass` good enough for the manager's non-detection needs.

    The manager only touches hass for storage, for scheduling the save
    after a run, and for reading the solar entities. Closing the coroutine
    handed to async_create_task keeps pytest from warning about a coroutine
    that was never awaited.
    """
    hass = MagicMock()
    hass.async_create_task = lambda coro: coro.close()
    hass.config.language = "en"
    hass.states = FakeStates()
    return hass


def make_manager(appliance_type: str = "washer", **kwargs) -> LaundryApplianceManager:
    return LaundryApplianceManager(
        kwargs.pop("hass", None) or stub_hass(),
        "test_entry",
        kwargs.pop("name", "Test appliance"),
        "sensor.power",
        appliance_type,
        kwargs.pop("door_entity", None),
    )


def alternating(low: float, high: float, period_samples: int):
    """A drum reversing: `period_samples` at one level, then the other."""
    return lambda i: high if (i // period_samples) % 2 else low


def feed(
    manager: LaundryApplianceManager,
    segments: list[tuple[float, object]],
    start: datetime | None = None,
    step_seconds: int = 10,
    unit: str = "W",
    divisor: float = 1.0,
) -> datetime:
    """Replay `(minutes, watts-or-callable)` segments through the manager."""
    when = start or datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
    for minutes, value in segments:
        for i in range(int(minutes * 60 / step_seconds)):
            watts = value(i) if callable(value) else value
            manager._ingest(FakeState(round(watts / divisor, 4), unit), when)
            when += timedelta(seconds=step_seconds)
    return when


def phases(manager: LaundryApplianceManager) -> list[str]:
    """The phase sequence of the last completed run."""
    assert manager.last_run is not None, "no run was recorded"
    return [entry["phase"] for entry in manager.last_run["timeline"]]


def minutes_in(manager: LaundryApplianceManager, phase: str) -> float:
    assert manager.last_run is not None, "no run was recorded"
    return sum(
        entry["seconds"] for entry in manager.last_run["timeline"] if entry["phase"] == phase
    ) / 60.0


# --------------------------------------------------------------------------- #
# Reference curves
# --------------------------------------------------------------------------- #
# The wash blocks alternate every 30 s, which is roughly how often a drum
# reverses. That timing matters: it is longer than the band dwell time, so
# the bands really do change, and shorter than the burst limit that
# separates washing from draining.

WASHER_CYCLE = [
    (5, 0.5),
    (3, 50),
    (22, 2000),
    (35, alternating(60, 180, 3)),
    (1, 350),
    (11, 520),
    (8, 0.5),
]

WASHER_WITH_INTERMEDIATE_SPIN = [
    (5, 0.5),
    (3, 50),
    (20, 2000),
    (15, alternating(60, 180, 3)),
    (3, 450),
    (12, alternating(60, 180, 3)),
    (1, 350),
    (10, 520),
    (8, 0.5),
]

HEAT_PUMP_DRYER_CYCLE = [
    (5, 0.5),
    (2, 300),
    (75, alternating(620, 780, 30)),
    (9, 130),
    (8, 0.5),
]

CONDENSER_DRYER_CYCLE = [
    (5, 0.5),
    (60, alternating(2400, 900, 18)),
    (10, 140),
    (8, 0.5),
]


# A boil wash, the programme that first exposed run splitting on real
# hardware. Its distinguishing feature is not the temperature but the
# pauses: soaking after the main wash, and again before the spin. During
# those the machine draws no more than its control panel does, for far
# longer than a rinse-and-spin programme ever pauses.
BOIL_WASH_WITH_SOAK = [
    (5, 0.5),
    (3, 50),
    (30, 2200),                      # heating to 95 degrees takes a while
    (20, alternating(60, 190, 3)),   # main wash
    (8, 1.0),                        # soaking - quiet, but not finished
    (15, alternating(60, 190, 3)),   # rinse
    (6, 1.0),                        # quiet again before the spin
    (1, 350),                        # drain
    (12, 540),                       # spin
    (10, 0.5),
]
