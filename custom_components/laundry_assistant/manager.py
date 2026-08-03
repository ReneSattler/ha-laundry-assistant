"""Runtime manager: sample collection, run tracking, history and reminders.

One instance per configured appliance. The detection rules themselves live
in `detection.py`; this module is what feeds them, times them and persists
what comes out.
"""
from __future__ import annotations

import logging
import statistics
from datetime import datetime, timedelta
from typing import Any, Callable

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    APPLIANCE_TYPE_WASHER,
    BAND_DWELL_SECONDS,
    BAND_LOW,
    BAND_MEDIUM,
    BAND_OFF,
    BAND_STANDBY,
    CALIBRATION_RUNS_REQUIRED,
    CALIBRATION_STATE_INACTIVE,
    CALIBRATION_STATE_READY,
    CALIBRATION_STATE_RECORDING,
    DEFAULT_CURRENCY,
    DEFAULT_PRICE_PER_KWH,
    DEFAULT_REMINDER_DELAY_MINUTES,
    DEFAULT_REMINDER_ENABLED,
    DEFAULT_REMINDER_MAX_REPEATS,
    DEFAULT_REMINDER_REPEAT_MINUTES,
    DEFAULT_THRESHOLDS,
    MAX_SAMPLES_PER_RUN,
    MAX_STORED_RUNS,
    MAX_USABLE_UPDATE_INTERVAL_SECONDS,
    MIN_SAMPLES_FOR_INTERVAL_CHECK,
    PHASE_FINISHED,
    PHASE_IDLE,
    PHASES_BY_TYPE,
    POWER_CURVE_POINTS,
    REMINDER_MESSAGES_BY_LANGUAGE,
    RUN_END_SECONDS,
    RUN_START_SECONDS,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
)
from .detection import (
    PhaseContext,
    band_index,
    classify,
    next_phase,
    propose_thresholds,
    validate_thresholds,
)

_LOGGER = logging.getLogger(__name__)

# Wattage values retained for the calibration proposal. Every completed run
# contributes; without a cap a few long cotton programs would put tens of
# thousands of floats into the store.
MAX_CALIBRATION_SAMPLES = 4000


class LaundryApplianceManager:
    """Tracks one appliance: its current phase, run history and reminders."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        name: str,
        power_entity: str,
        appliance_type: str,
        door_entity: str | None,
    ) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.name = name
        self.power_entity = power_entity
        self.appliance_type = appliance_type
        self.door_entity = door_entity
        self._store: Store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}_{entry_id}")

        self.thresholds: dict[str, float] = dict(
            DEFAULT_THRESHOLDS.get(appliance_type, DEFAULT_THRESHOLDS[APPLIANCE_TYPE_WASHER])
        )
        self.price_per_kwh: float = DEFAULT_PRICE_PER_KWH
        self.currency: str = DEFAULT_CURRENCY

        self.reminder_enabled: bool = DEFAULT_REMINDER_ENABLED
        self.reminder_delay_minutes: int = DEFAULT_REMINDER_DELAY_MINUTES
        self.reminder_repeat_minutes: int = DEFAULT_REMINDER_REPEAT_MINUTES
        self.reminder_max_repeats: int = DEFAULT_REMINDER_MAX_REPEATS
        self.notify_target: str | None = None

        # Live state
        self.phase: str = PHASE_IDLE
        self.confidence: float = 0.0
        self.watts: float = 0.0
        self.band: str = BAND_OFF
        self.run_started: datetime | None = None
        self.phase_timeline: list[dict[str, Any]] = []
        self.last_run: dict[str, Any] | None = None

        self.runs: list[dict[str, Any]] = []

        self.calibration_state: str = CALIBRATION_STATE_INACTIVE
        self.calibration_runs: int = 0
        self.calibration_proposal: dict[str, float] | None = None
        self._calibration_samples: list[float] = []

        # Internals
        self._samples: list[tuple[datetime, float]] = []
        self._band_since: datetime | None = None
        self._pending_band: str = BAND_OFF
        self._pending_since: datetime | None = None
        self._phase_since: datetime | None = None
        self._alternations: int = 0
        self._above_low_since: datetime | None = None
        self._below_standby_since: datetime | None = None
        self._intervals: list[float] = []
        self._last_sample_at: datetime | None = None

        self._reminder_unsub: Callable[[], None] | None = None
        self._reminder_count: int = 0
        self.reminder_pending: bool = False

        self._unsubs: list[Callable[[], None]] = []
        self._listeners: list[Callable[[], None]] = []

    # ------------------------------------------------------------------ #
    # Setup / persistence
    # ------------------------------------------------------------------ #

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if data:
            stored = data.get("thresholds")
            if stored:
                try:
                    self.thresholds = validate_thresholds(stored)
                except ValueError:
                    _LOGGER.warning(
                        "Stored thresholds for %s are invalid and were discarded; "
                        "falling back to the defaults for this appliance type",
                        self.name,
                    )
            self.price_per_kwh = data.get("price_per_kwh", DEFAULT_PRICE_PER_KWH)
            self.currency = data.get("currency", DEFAULT_CURRENCY)
            self.reminder_enabled = data.get("reminder_enabled", DEFAULT_REMINDER_ENABLED)
            self.reminder_delay_minutes = data.get(
                "reminder_delay_minutes", DEFAULT_REMINDER_DELAY_MINUTES
            )
            self.reminder_repeat_minutes = data.get(
                "reminder_repeat_minutes", DEFAULT_REMINDER_REPEAT_MINUTES
            )
            self.reminder_max_repeats = data.get(
                "reminder_max_repeats", DEFAULT_REMINDER_MAX_REPEATS
            )
            self.notify_target = data.get("notify_target")
            self.runs = data.get("runs", [])[-MAX_STORED_RUNS:]
            self.last_run = data.get("last_run")
            self.calibration_state = data.get("calibration_state", CALIBRATION_STATE_INACTIVE)
            self.calibration_runs = data.get("calibration_runs", 0)
            self.calibration_proposal = data.get("calibration_proposal")
            self._calibration_samples = data.get("calibration_samples", [])

        # Subscribing during setup would race with the power sensor's own
        # integration still coming up; its first state would then be missed.
        async_at_started(self.hass, self._async_subscribe)

    @callback
    def _async_subscribe(self, _hass: HomeAssistant) -> None:
        self._unsubs.append(
            async_track_state_change_event(
                self.hass, [self.power_entity], self._async_power_changed
            )
        )
        if self.door_entity:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, [self.door_entity], self._async_door_changed
                )
            )
        # Seed from the current state so a restart mid-run does not have to
        # wait for the next update before showing anything.
        state = self.hass.states.get(self.power_entity)
        if state is not None:
            self._ingest(state, dt_util.utcnow())
            self._notify_listeners()

    async def async_unload(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._cancel_reminder()
        await self._async_save()

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "thresholds": self.thresholds,
                "price_per_kwh": self.price_per_kwh,
                "currency": self.currency,
                "reminder_enabled": self.reminder_enabled,
                "reminder_delay_minutes": self.reminder_delay_minutes,
                "reminder_repeat_minutes": self.reminder_repeat_minutes,
                "reminder_max_repeats": self.reminder_max_repeats,
                "notify_target": self.notify_target,
                "runs": self.runs[-MAX_STORED_RUNS:],
                "last_run": self.last_run,
                "calibration_state": self.calibration_state,
                "calibration_runs": self.calibration_runs,
                "calibration_proposal": self.calibration_proposal,
                "calibration_samples": self._calibration_samples[-MAX_CALIBRATION_SAMPLES:],
            }
        )

    @callback
    def async_add_listener(self, update_callback: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(update_callback)

        def remove() -> None:
            self._listeners.remove(update_callback)

        return remove

    @callback
    def _notify_listeners(self) -> None:
        for update_callback in self._listeners:
            update_callback()

    # ------------------------------------------------------------------ #
    # Sample ingestion
    # ------------------------------------------------------------------ #

    @callback
    def _async_power_changed(self, event: Event) -> None:
        state = event.data.get("new_state")
        if state is None:
            return
        self._ingest(state, event.time_fired)
        self._notify_listeners()

    def _ingest(self, state: Any, when: datetime) -> None:
        watts = self._to_watts(state)
        if watts is None:
            return

        self.watts = watts
        if self._last_sample_at is not None:
            delta = (when - self._last_sample_at).total_seconds()
            # Ignore non-positive deltas: state objects restored at startup
            # can carry an older timestamp than the event that delivered them.
            if delta > 0:
                self._intervals.append(delta)
                if len(self._intervals) > 200:
                    self._intervals.pop(0)
        self._last_sample_at = when

        self._samples.append((when, watts))
        if len(self._samples) > MAX_SAMPLES_PER_RUN:
            self._samples.pop(0)

        self._update_band(watts, when)
        self._update_run_state(when)
        if self.run_started is not None:
            self._advance_phase(when)

    def _to_watts(self, state: Any) -> float | None:
        """Read a power state as watts, accepting kW-reporting sensors."""
        if state.state in (None, "", "unknown", "unavailable"):
            return None
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return None
        unit = (state.attributes.get("unit_of_measurement") or "").strip()
        if unit.lower() == "kw":
            value *= 1000.0
        return value

    def _update_band(self, watts: float, when: datetime) -> None:
        """Commit a band change only once it has held for the dwell time."""
        raw = classify(watts, self.thresholds)
        if raw != self._pending_band:
            self._pending_band = raw
            self._pending_since = when
            return

        if raw == self.band:
            return

        if self._pending_since is None:
            self._pending_since = when
            return

        if (when - self._pending_since).total_seconds() < BAND_DWELL_SECONDS:
            return

        previous = self.band
        self.band = raw
        self._band_since = when
        # Rhythmic alternation between low and medium is what a drum
        # reversing back and forth looks like from the outside.
        if previous in (BAND_LOW, BAND_MEDIUM) and raw in (BAND_LOW, BAND_MEDIUM):
            self._alternations += 1

    def _update_run_state(self, when: datetime) -> None:
        """Open and close runs based on how long power has been up or down."""
        active_draw = band_index(self.band) >= band_index(BAND_LOW)

        if active_draw:
            self._below_standby_since = None
            if self._above_low_since is None:
                self._above_low_since = when
        else:
            self._above_low_since = None
            if self._below_standby_since is None:
                self._below_standby_since = when

        if self.run_started is None:
            if (
                self._above_low_since is not None
                and (when - self._above_low_since).total_seconds() >= RUN_START_SECONDS
            ):
                self._start_run(self._above_low_since)
            return

        if (
            self._below_standby_since is not None
            and (when - self._below_standby_since).total_seconds() >= RUN_END_SECONDS
        ):
            self._finish_run(self._below_standby_since)

    def _start_run(self, started: datetime) -> None:
        self.run_started = started
        # Everything before the run began belongs to standby noise.
        self._samples = [s for s in self._samples if s[0] >= started]
        self.phase = PHASE_IDLE
        self.confidence = 0.0
        self.phase_timeline = []
        self._phase_since = started
        self._alternations = 0
        self._cancel_reminder()
        _LOGGER.debug("%s: run started at %s", self.name, started)

    def _advance_phase(self, when: datetime) -> None:
        assert self.run_started is not None
        ctx = PhaseContext(
            band=self.band,
            band_dwell_seconds=(when - self._band_since).total_seconds()
            if self._band_since
            else 0.0,
            watts=self.watts,
            run_elapsed_seconds=(when - self.run_started).total_seconds(),
            seen_phases={entry["phase"] for entry in self.phase_timeline} | {self.phase},
            alternations=self._alternations,
        )
        phase, confidence = next_phase(self.appliance_type, self.phase, ctx)
        self.confidence = confidence

        if phase == self.phase:
            return

        # The run opens in "idle" for the moment between the run being
        # recognised and the first phase being decided. That is bookkeeping,
        # not a phase the appliance was ever in - keep it out of the
        # timeline the card draws.
        if self._phase_since is not None and self.phase != PHASE_IDLE:
            self.phase_timeline.append(
                {
                    "phase": self.phase,
                    "start": self._phase_since.isoformat(),
                    "seconds": round((when - self._phase_since).total_seconds(), 1),
                }
            )
        self.phase = phase
        self._phase_since = when
        self._alternations = 0

    def _finish_run(self, finished: datetime) -> None:
        assert self.run_started is not None
        started = self.run_started

        if self._phase_since is not None and self.phase != PHASE_IDLE:
            self.phase_timeline.append(
                {
                    "phase": self.phase,
                    "start": self._phase_since.isoformat(),
                    "seconds": round((finished - self._phase_since).total_seconds(), 1),
                }
            )

        samples = [s for s in self._samples if started <= s[0] <= finished]
        energy_kwh = self._integrate_energy(samples)
        duration = (finished - started).total_seconds()

        run = {
            "started": started.isoformat(),
            "finished": finished.isoformat(),
            "duration_seconds": round(duration, 1),
            "energy_kwh": round(energy_kwh, 4),
            "cost": round(energy_kwh * self.price_per_kwh, 4),
            "peak_watts": round(max((w for _, w in samples), default=0.0), 1),
            "timeline": [
                {"phase": entry["phase"], "seconds": entry["seconds"]}
                for entry in self.phase_timeline
            ],
        }

        # A "run" of a couple of minutes is a door light or a control panel
        # waking up, not a wash. Recording it would poison both the
        # remaining-time estimate and the weekly totals.
        if duration >= RUN_START_SECONDS * 3:
            self.runs.append(run)
            self.runs = self.runs[-MAX_STORED_RUNS:]
            self.last_run = run
            if self.calibration_state == CALIBRATION_STATE_RECORDING:
                self._record_calibration_run(samples)
            self._schedule_reminder(finished)

        self.run_started = None
        self.phase = PHASE_FINISHED if duration >= RUN_START_SECONDS * 3 else PHASE_IDLE
        self.confidence = 1.0 if self.phase == PHASE_FINISHED else 0.0
        self._phase_since = finished
        self._samples = []
        self.hass.async_create_task(self._async_save())
        _LOGGER.debug("%s: run finished after %.0f s", self.name, duration)

    @staticmethod
    def _integrate_energy(samples: list[tuple[datetime, float]]) -> float:
        """Trapezoidal integration of the power curve, in kWh.

        Each interval contributes the average of its two endpoints, which
        handles the uneven sample spacing that push-on-change reporting
        produces without needing to resample first.
        """
        if len(samples) < 2:
            return 0.0
        watt_seconds = 0.0
        for (t0, w0), (t1, w1) in zip(samples, samples[1:]):
            seconds = (t1 - t0).total_seconds()
            if seconds <= 0:
                continue
            watt_seconds += (w0 + w1) / 2.0 * seconds
        return watt_seconds / 3_600_000.0

    # ------------------------------------------------------------------ #
    # Derived values
    # ------------------------------------------------------------------ #

    @property
    def run_active(self) -> bool:
        return self.run_started is not None

    @property
    def elapsed_seconds(self) -> int:
        if self.run_started is None:
            return 0
        return int((dt_util.utcnow() - self.run_started).total_seconds())

    @property
    def estimated_total_seconds(self) -> int | None:
        """Expected total duration of the run in progress.

        Derived from stored runs whose phase sequence matches the current
        one so far, rather than from a fixed program table - programs differ
        per machine, and the same program differs with load size.
        """
        if self.run_started is None or not self.runs:
            return None

        completed = [entry["phase"] for entry in self.phase_timeline]
        matching = [
            run["duration_seconds"]
            for run in self.runs
            if [e["phase"] for e in run.get("timeline", [])][: len(completed)] == completed
        ]
        if not matching:
            # No run has gone this way before. Fall back to the overall
            # average, which is still a better answer than nothing once a
            # few runs exist, but never invent one from thin air.
            matching = [run["duration_seconds"] for run in self.runs]
        if not matching:
            return None
        return int(statistics.median(matching))

    @property
    def remaining_seconds(self) -> int | None:
        total = self.estimated_total_seconds
        if total is None:
            return None
        return max(0, total - self.elapsed_seconds)

    @property
    def cycle_energy_kwh(self) -> float:
        """Energy of the run in progress, or of the last completed one."""
        if self.run_started is not None:
            return round(self._integrate_energy(self._samples), 4)
        if self.last_run:
            return self.last_run["energy_kwh"]
        return 0.0

    @property
    def cycle_cost(self) -> float:
        return round(self.cycle_energy_kwh * self.price_per_kwh, 3)

    def _week_runs(self) -> list[dict[str, Any]]:
        """Runs finished in the current week.

        The week starts on Monday. Home Assistant does not expose the
        locale's first day of week to integrations, and picking one is
        better than silently using the server's C locale.
        """
        now = dt_util.now()
        start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        result = []
        for run in self.runs:
            finished = dt_util.parse_datetime(run["finished"])
            if finished is not None and dt_util.as_local(finished) >= start:
                result.append(run)
        return result

    @property
    def week_cycles(self) -> int:
        return len(self._week_runs())

    @property
    def week_energy_kwh(self) -> float:
        return round(sum(run["energy_kwh"] for run in self._week_runs()), 3)

    @property
    def week_cost(self) -> float:
        return round(sum(run["cost"] for run in self._week_runs()), 2)

    @property
    def update_interval_seconds(self) -> float | None:
        if len(self._intervals) < MIN_SAMPLES_FOR_INTERVAL_CHECK:
            return None
        return round(statistics.median(self._intervals), 1)

    @property
    def update_interval_ok(self) -> bool | None:
        interval = self.update_interval_seconds
        if interval is None:
            return None
        return interval <= MAX_USABLE_UPDATE_INTERVAL_SECONDS

    @property
    def power_curve(self) -> list[float]:
        """The current run's curve, downsampled for the card."""
        if not self._samples:
            return []
        if len(self._samples) <= POWER_CURVE_POINTS:
            return [round(w, 1) for _, w in self._samples]
        step = len(self._samples) / POWER_CURVE_POINTS
        return [
            round(self._samples[min(int(i * step), len(self._samples) - 1)][1], 1)
            for i in range(POWER_CURVE_POINTS)
        ]

    @property
    def known_phases(self) -> list[str]:
        return PHASES_BY_TYPE.get(self.appliance_type, [])

    # ------------------------------------------------------------------ #
    # Reminder
    # ------------------------------------------------------------------ #

    def _schedule_reminder(self, finished: datetime) -> None:
        if not self.reminder_enabled or not self.notify_target:
            return
        self._reminder_count = 0
        self.reminder_pending = True
        self._arm_reminder(self.reminder_delay_minutes, finished)

    def _arm_reminder(self, minutes: int, finished: datetime) -> None:
        self._cancel_reminder(keep_pending=True)

        async def _fire(_now: Any) -> None:
            self._reminder_unsub = None
            await self._async_send_reminder(finished)

        self._reminder_unsub = async_call_later(self.hass, minutes * 60, _fire)

    async def _async_send_reminder(self, finished: datetime) -> None:
        if not self.reminder_pending or not self.notify_target:
            return

        minutes = int((dt_util.utcnow() - finished).total_seconds() // 60)
        lang = (self.hass.config.language or "en").split("-")[0]
        texts = REMINDER_MESSAGES_BY_LANGUAGE.get(lang, REMINDER_MESSAGES_BY_LANGUAGE["en"])
        try:
            await self.hass.services.async_call(
                "notify",
                self.notify_target,
                {
                    "title": texts["title"].format(appliance=self.name),
                    "message": texts["message"].format(minutes=minutes),
                },
                blocking=False,
            )
        except Exception:  # noqa: BLE001 - a missing notify target must not break the run
            _LOGGER.exception("Sending the laundry reminder for %s failed", self.name)
            self._cancel_reminder()
            return

        self._reminder_count += 1
        if self._reminder_count >= self.reminder_max_repeats:
            self._cancel_reminder()
        else:
            self._arm_reminder(self.reminder_repeat_minutes, finished)
        self._notify_listeners()

    def _cancel_reminder(self, keep_pending: bool = False) -> None:
        if self._reminder_unsub is not None:
            self._reminder_unsub()
            self._reminder_unsub = None
        if not keep_pending:
            self.reminder_pending = False
            self._reminder_count = 0

    @callback
    def _async_door_changed(self, event: Event) -> None:
        state = event.data.get("new_state")
        if state is not None and state.state == "on":
            # Door opened - the load has been dealt with.
            self._cancel_reminder()
            self._notify_listeners()

    # ------------------------------------------------------------------ #
    # Calibration
    # ------------------------------------------------------------------ #

    def _record_calibration_run(self, samples: list[tuple[datetime, float]]) -> None:
        self._calibration_samples.extend(w for _, w in samples)
        if len(self._calibration_samples) > MAX_CALIBRATION_SAMPLES:
            # Keep a spread across all recorded runs rather than only the
            # most recent one, so the proposal is not dominated by whichever
            # program happened to run last.
            step = len(self._calibration_samples) / MAX_CALIBRATION_SAMPLES
            self._calibration_samples = [
                self._calibration_samples[int(i * step)] for i in range(MAX_CALIBRATION_SAMPLES)
            ]
        self.calibration_runs += 1
        if self.calibration_runs >= CALIBRATION_RUNS_REQUIRED:
            proposal = propose_thresholds(self._calibration_samples, self.appliance_type)
            if proposal is not None:
                self.calibration_proposal = proposal
                self.calibration_state = CALIBRATION_STATE_READY

    async def async_start_calibration(self) -> None:
        self.calibration_state = CALIBRATION_STATE_RECORDING
        self.calibration_runs = 0
        self.calibration_proposal = None
        self._calibration_samples = []
        await self._async_save()
        self._notify_listeners()

    async def async_cancel_calibration(self) -> None:
        self.calibration_state = CALIBRATION_STATE_INACTIVE
        self.calibration_runs = 0
        self.calibration_proposal = None
        self._calibration_samples = []
        await self._async_save()
        self._notify_listeners()

    async def async_apply_calibration(self) -> None:
        if self.calibration_proposal is None:
            raise ValueError("No calibration proposal is available yet")
        self.thresholds = validate_thresholds(self.calibration_proposal)
        self.calibration_state = CALIBRATION_STATE_INACTIVE
        self.calibration_proposal = None
        self._calibration_samples = []
        await self._async_save()
        self._notify_listeners()

    # ------------------------------------------------------------------ #
    # Settings
    # ------------------------------------------------------------------ #

    async def async_set_thresholds(self, thresholds: dict[str, Any]) -> None:
        self.thresholds = validate_thresholds(thresholds)
        await self._async_save()
        self._notify_listeners()

    async def async_set_price(self, price_per_kwh: float, currency: str | None = None) -> None:
        self.price_per_kwh = price_per_kwh
        if currency:
            self.currency = currency
        await self._async_save()
        self._notify_listeners()

    async def async_set_reminder(
        self,
        enabled: bool,
        delay_minutes: int | None = None,
        repeat_minutes: int | None = None,
        max_repeats: int | None = None,
    ) -> None:
        self.reminder_enabled = enabled
        if delay_minutes is not None:
            self.reminder_delay_minutes = delay_minutes
        if repeat_minutes is not None:
            self.reminder_repeat_minutes = repeat_minutes
        if max_repeats is not None:
            self.reminder_max_repeats = max_repeats
        if not enabled:
            self._cancel_reminder()
        await self._async_save()
        self._notify_listeners()

    async def async_set_notify_target(self, target: str | None) -> None:
        self.notify_target = target
        if target is None:
            self._cancel_reminder()
        await self._async_save()
        self._notify_listeners()

    async def async_dismiss_reminder(self) -> None:
        self._cancel_reminder()
        self._notify_listeners()

    async def async_clear_history(self) -> None:
        self.runs = []
        self.last_run = None
        await self._async_save()
        self._notify_listeners()
