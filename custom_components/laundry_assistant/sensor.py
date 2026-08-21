"""Sensors: the phase (main entity, carries everything the card needs),
plus remaining time, cycle energy and cost, and the weekly totals."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ALL_PHASES,
    ATTR_ANOMALIES,
    ATTR_ANOMALY_DETECTION_ENABLED,
    ATTR_ANOMALY_FACTOR,
    ATTR_ANOMALY_MESSAGES,
    ATTR_APPLIANCE_TYPE,
    ATTR_CONSUMPTION_ENTITY,
    ATTR_CURRENT_PROGRAM,
    ATTR_FEED_IN_TARIFF,
    ATTR_PROGRAMS,
    ATTR_SOLAR_COVERS_CYCLE,
    ATTR_SOLAR_ENTITY,
    ATTR_SOLAR_SAVING_PER_CYCLE,
    ATTR_SOLAR_SURPLUS_W,
    ATTR_TOTAL_ENERGY_KWH,
    ATTR_TYPICAL_DRAW_W,
    ATTR_BAND,
    ATTR_CALIBRATION_PROPOSAL,
    ATTR_CALIBRATION_RUNS,
    ATTR_CALIBRATION_RUNS_REQUIRED,
    ATTR_CALIBRATION_STATE,
    ATTR_CONFIDENCE,
    ATTR_CURRENCY,
    ATTR_CYCLE_COST,
    ATTR_CYCLE_ENERGY_KWH,
    ATTR_DOOR_ENTITY,
    ATTR_ELAPSED_SECONDS,
    ATTR_ESTIMATED_TOTAL_SECONDS,
    ATTR_KNOWN_PHASES,
    ATTR_LAST_RUN,
    ATTR_NOTIFY_TARGET,
    ATTR_PHASE_TIMELINE,
    ATTR_POWER_CURVE,
    ATTR_POWER_ENTITY,
    ATTR_PRICE_PER_KWH,
    ATTR_REMAINING_SECONDS,
    ATTR_REMINDER_DELAY_MINUTES,
    ATTR_REMINDER_ENABLED,
    ATTR_REMINDER_MAX_REPEATS,
    ATTR_REMINDER_PENDING,
    ATTR_REMINDER_REPEAT_MINUTES,
    ATTR_RUN_ACTIVE,
    ATTR_RUN_STARTED,
    ATTR_THRESHOLDS,
    ATTR_CHAIN_TO_DRYER,
    ATTR_DRYER_AVAILABLE,
    ATTR_POWER_SOURCE_STATUS,
    ATTR_UPDATE_INTERVAL_OK,
    ATTR_UPDATE_INTERVAL_SECONDS,
    ATTR_WATTS,
    ATTR_WEEK_COST,
    ATTR_WEEK_CYCLES,
    ATTR_WEEK_ENERGY_KWH,
    CALIBRATION_RUNS_REQUIRED,
    DOMAIN,
)
from .manager import LaundryApplianceManager


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    manager: LaundryApplianceManager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            LaundryPhaseSensor(manager, entry),
            LaundryRemainingSensor(manager, entry),
            LaundryCycleEnergySensor(manager, entry),
            LaundryCycleCostSensor(manager, entry),
            LaundryWeekCyclesSensor(manager, entry),
            LaundryWeekEnergySensor(manager, entry),
            LaundryWeekCostSensor(manager, entry),
            LaundryTotalEnergySensor(manager, entry),
            LaundryFinishesAtSensor(manager, entry),
        ]
    )


class LaundryBaseSensor(SensorEntity):
    """Shared wiring: device grouping and push updates from the manager."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, manager: LaundryApplianceManager, entry: ConfigEntry, key: str
    ) -> None:
        self._manager = manager
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "ha-laundry-assistant",
            "model": entry.data.get("appliance_type"),
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._manager.async_add_listener(self.async_write_ha_state))


class LaundryPhaseSensor(LaundryBaseSensor):
    """The appliance's current phase, and the card's entire data source."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ALL_PHASES
    _attr_icon = "mdi:washing-machine"
    # These attributes are lists and dicts that change on every power
    # sample. The recorder would write a copy of each one several times a
    # minute for the lifetime of the instance, for data the cards only ever
    # read live. Keeping them out of history is the difference between a
    # few kilobytes a day and a few hundred megabytes.
    _unrecorded_attributes = frozenset(
        {
            ATTR_POWER_CURVE,
            ATTR_PHASE_TIMELINE,
            ATTR_LAST_RUN,
            ATTR_THRESHOLDS,
            ATTR_CALIBRATION_PROPOSAL,
            ATTR_KNOWN_PHASES,
            ATTR_ANOMALIES,
            ATTR_ANOMALY_MESSAGES,
            ATTR_PROGRAMS,
            ATTR_CURRENT_PROGRAM,
        }
    )

    def __init__(self, manager: LaundryApplianceManager, entry: ConfigEntry) -> None:
        super().__init__(manager, entry, "phase")

    @property
    def native_value(self) -> str:
        return self._manager.phase

    @property
    def extra_state_attributes(self) -> dict:
        manager = self._manager
        return {
            "entry_id": manager.entry_id,
            ATTR_APPLIANCE_TYPE: manager.appliance_type,
            ATTR_POWER_ENTITY: manager.power_entity,
            ATTR_DOOR_ENTITY: manager.door_entity,
            ATTR_CONFIDENCE: manager.confidence,
            ATTR_BAND: manager.band,
            ATTR_WATTS: round(manager.watts, 1),
            ATTR_RUN_ACTIVE: manager.run_active,
            ATTR_RUN_STARTED: manager.run_started.isoformat() if manager.run_started else None,
            ATTR_ELAPSED_SECONDS: manager.elapsed_seconds,
            ATTR_REMAINING_SECONDS: manager.remaining_seconds,
            ATTR_ESTIMATED_TOTAL_SECONDS: manager.estimated_total_seconds,
            ATTR_PHASE_TIMELINE: manager.phase_timeline,
            ATTR_POWER_CURVE: manager.power_curve,
            ATTR_KNOWN_PHASES: manager.known_phases,
            ATTR_CYCLE_ENERGY_KWH: manager.cycle_energy_kwh,
            ATTR_CYCLE_COST: manager.cycle_cost,
            ATTR_LAST_RUN: manager.last_run,
            ATTR_WEEK_CYCLES: manager.week_cycles,
            ATTR_WEEK_ENERGY_KWH: manager.week_energy_kwh,
            ATTR_WEEK_COST: manager.week_cost,
            ATTR_PRICE_PER_KWH: manager.price_per_kwh,
            ATTR_CURRENCY: manager.currency,
            ATTR_THRESHOLDS: manager.thresholds,
            ATTR_CALIBRATION_STATE: manager.calibration_state,
            ATTR_CALIBRATION_RUNS: manager.calibration_runs,
            ATTR_CALIBRATION_RUNS_REQUIRED: CALIBRATION_RUNS_REQUIRED,
            ATTR_CALIBRATION_PROPOSAL: manager.calibration_proposal,
            ATTR_UPDATE_INTERVAL_SECONDS: manager.update_interval_seconds,
            ATTR_UPDATE_INTERVAL_OK: manager.update_interval_ok,
            ATTR_POWER_SOURCE_STATUS: manager.power_source_status,
            ATTR_CHAIN_TO_DRYER: manager.chain_to_dryer,
            ATTR_DRYER_AVAILABLE: manager.dryer_available,
            ATTR_REMINDER_ENABLED: manager.reminder_enabled,
            ATTR_REMINDER_DELAY_MINUTES: manager.reminder_delay_minutes,
            ATTR_REMINDER_REPEAT_MINUTES: manager.reminder_repeat_minutes,
            ATTR_REMINDER_MAX_REPEATS: manager.reminder_max_repeats,
            ATTR_REMINDER_PENDING: manager.reminder_pending,
            ATTR_NOTIFY_TARGET: manager.notify_target,
            ATTR_ANOMALIES: manager.last_anomalies,
            ATTR_ANOMALY_MESSAGES: [
                manager.describe_anomaly(finding) for finding in manager.last_anomalies
            ],
            ATTR_ANOMALY_DETECTION_ENABLED: manager.anomaly_detection_enabled,
            ATTR_ANOMALY_FACTOR: manager.anomaly_factor,
            ATTR_PROGRAMS: manager.programs,
            ATTR_CURRENT_PROGRAM: manager.current_program,
            ATTR_TOTAL_ENERGY_KWH: manager.total_energy_kwh,
            ATTR_FEED_IN_TARIFF: manager.feed_in_tariff,
            ATTR_SOLAR_ENTITY: manager.solar_entity,
            ATTR_CONSUMPTION_ENTITY: manager.consumption_entity,
            ATTR_SOLAR_SURPLUS_W: manager.solar_surplus_w,
            ATTR_TYPICAL_DRAW_W: manager.typical_draw_w,
            ATTR_SOLAR_COVERS_CYCLE: manager.solar_covers_cycle,
            ATTR_SOLAR_SAVING_PER_CYCLE: manager.solar_saving_per_cycle,
        }


class LaundryRemainingSensor(LaundryBaseSensor):
    """Estimated minutes left in the run in progress."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_icon = "mdi:timer-sand"

    def __init__(self, manager: LaundryApplianceManager, entry: ConfigEntry) -> None:
        super().__init__(manager, entry, "remaining")

    @property
    def native_value(self) -> int | None:
        # Deliberately None rather than 0 when nothing is running or no
        # comparable run exists - a confident "0 minutes left" would be a
        # lie in both cases.
        if not self._manager.run_active:
            return None
        remaining = self._manager.remaining_seconds
        return None if remaining is None else remaining // 60


class LaundryFinishesAtSensor(LaundryBaseSensor):
    """When the cycle in progress is expected to end.

    A companion to the remaining-minutes sensor rather than a replacement:
    a count of minutes is what you want on a card, an instant is what you
    want in an automation or a spoken sentence. This one also holds still
    between readings, because it is derived from the run's start rather
    than from the current moment.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-end"

    def __init__(self, manager: LaundryApplianceManager, entry: ConfigEntry) -> None:
        super().__init__(manager, entry, "finishes_at")

    @property
    def native_value(self):
        return self._manager.finishes_at


class LaundryCycleEnergySensor(LaundryBaseSensor):
    """Energy of the current run, or of the last completed one.

    Carries no `device_class: energy`: that class is reserved for meters
    that only ever count up, and this value resets with every cycle. The
    unit is still kWh, so it displays and converts correctly.
    """

    _attr_native_unit_of_measurement = "kWh"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:lightning-bolt"

    def __init__(self, manager: LaundryApplianceManager, entry: ConfigEntry) -> None:
        super().__init__(manager, entry, "cycle_energy")

    @property
    def native_value(self) -> float:
        return self._manager.cycle_energy_kwh


class LaundryCycleCostSensor(LaundryBaseSensor):
    """Cost of the current run, or of the last completed one."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:cash"

    def __init__(self, manager: LaundryApplianceManager, entry: ConfigEntry) -> None:
        super().__init__(manager, entry, "cycle_cost")

    @property
    def native_unit_of_measurement(self) -> str:
        return self._manager.currency

    @property
    def native_value(self) -> float:
        return self._manager.cycle_cost


class LaundryWeekCyclesSensor(LaundryBaseSensor):
    """Completed runs so far this week."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:counter"

    def __init__(self, manager: LaundryApplianceManager, entry: ConfigEntry) -> None:
        super().__init__(manager, entry, "week_cycles")

    @property
    def native_value(self) -> int:
        return self._manager.week_cycles


class LaundryWeekEnergySensor(LaundryBaseSensor):
    """Energy used by all runs so far this week."""

    _attr_native_unit_of_measurement = "kWh"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:lightning-bolt-outline"

    def __init__(self, manager: LaundryApplianceManager, entry: ConfigEntry) -> None:
        super().__init__(manager, entry, "week_energy")

    @property
    def native_value(self) -> float:
        return self._manager.week_energy_kwh


class LaundryTotalEnergySensor(LaundryBaseSensor):
    """Lifetime energy across every completed cycle.

    This is the one that belongs in the energy dashboard. `cycle_energy`
    cannot: it resets with every cycle, and `total_increasing` means what it
    says. Clearing the run history deliberately leaves this untouched -
    a meter that jumps backwards makes long-term statistics unrecoverable.
    """

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = "kWh"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:counter"

    def __init__(self, manager: LaundryApplianceManager, entry: ConfigEntry) -> None:
        super().__init__(manager, entry, "total_energy")

    @property
    def native_value(self) -> float:
        return self._manager.total_energy_kwh


class LaundryWeekCostSensor(LaundryBaseSensor):
    """Cost of all runs so far this week."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:cash-multiple"

    def __init__(self, manager: LaundryApplianceManager, entry: ConfigEntry) -> None:
        super().__init__(manager, entry, "week_cost")

    @property
    def native_unit_of_measurement(self) -> str:
        return self._manager.currency

    @property
    def native_value(self) -> float:
        return self._manager.week_cost
