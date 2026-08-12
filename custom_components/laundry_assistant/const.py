"""Constants for the Laundry Assistant integration."""
from __future__ import annotations

DOMAIN = "laundry_assistant"
PLATFORMS = ["sensor", "binary_sensor"]

# One config entry per appliance - a washing machine and a tumble dryer are
# set up separately, each with its own power sensor, thresholds and history.
CONF_POWER_ENTITY = "power_entity"
CONF_APPLIANCE_TYPE = "appliance_type"
CONF_DOOR_ENTITY = "door_entity"

APPLIANCE_TYPE_WASHER = "washer"
APPLIANCE_TYPE_DRYER = "dryer"
APPLIANCE_TYPES = [APPLIANCE_TYPE_WASHER, APPLIANCE_TYPE_DRYER]

DEFAULT_NAME_BY_LANGUAGE = {
    "en": {APPLIANCE_TYPE_WASHER: "Washing Machine", APPLIANCE_TYPE_DRYER: "Tumble Dryer"},
    "de": {APPLIANCE_TYPE_WASHER: "Waschmaschine", APPLIANCE_TYPE_DRYER: "Trockner"},
}

STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = f"{DOMAIN}_state"

# --------------------------------------------------------------------------- #
# Power bands
# --------------------------------------------------------------------------- #
# Raw wattage is classified into these bands first; the phase state machine
# then works on bands and their dwell times rather than on raw values. The
# band edges are per appliance and stored in the run-time state, because a
# heat-pump dryer and a condenser dryer differ by a factor of three.

BAND_OFF = "off"
BAND_STANDBY = "standby"
BAND_LOW = "low"
BAND_MEDIUM = "medium"
BAND_HIGH = "high"

# Ordered from lowest to highest - the index is used for comparisons.
BANDS = [BAND_OFF, BAND_STANDBY, BAND_LOW, BAND_MEDIUM, BAND_HIGH]

# A sample is classified into the highest band whose edge it reaches.
# "standby" is the edge above "off", and so on; there is no edge for "off"
# itself, everything below the standby edge is off.
THRESHOLD_KEYS = [BAND_STANDBY, BAND_LOW, BAND_MEDIUM, BAND_HIGH]

DEFAULT_THRESHOLDS = {
    # Washer: intake ~30-60 W, wash bursts 50-200 W, drain/spin 300-600 W,
    # heating 1800-2200 W.
    APPLIANCE_TYPE_WASHER: {
        BAND_STANDBY: 2.0,
        BAND_LOW: 20.0,
        BAND_MEDIUM: 150.0,
        BAND_HIGH: 800.0,
    },
    # Dryer: cool-down (drum only) ~100-200 W, heat-pump operation
    # 500-900 W, condenser heating 2000-2600 W. The high edge sits above a
    # heat pump's normal draw on purpose, so that a heat-pump dryer spends
    # its drying phase in "medium" and only a condenser model ever reaches
    # "high".
    APPLIANCE_TYPE_DRYER: {
        BAND_STANDBY: 2.0,
        BAND_LOW: 20.0,
        BAND_MEDIUM: 150.0,
        BAND_HIGH: 1200.0,
    },
}

# A band change is only accepted once the new band has held for this long.
# Swallows single-sample spikes (a compressor starting, a heating element
# switching) without needing a filter over the raw values.
BAND_DWELL_SECONDS = 15

# How often the band, run state and phase are re-evaluated regardless of
# whether a reading arrived. Plugs that report on change go silent between
# load changes, and every time-based rule here - the dwell time, the
# run-start threshold, the run-end threshold - would then never elapse.
EVALUATION_TICK_SECONDS = 15

# --------------------------------------------------------------------------- #
# Phases
# --------------------------------------------------------------------------- #

PHASE_IDLE = "idle"
PHASE_INTAKE = "intake"
PHASE_HEATING = "heating"
PHASE_WASHING = "washing"
PHASE_DRAINING = "draining"
PHASE_SPINNING = "spinning"
PHASE_DRYING = "drying"
PHASE_COOLDOWN = "cooldown"
PHASE_FINISHED = "finished"
# Generic fallback: the appliance is clearly running, but the band pattern
# does not match any known phase for its type. Reported with low confidence
# rather than guessing a specific phase.
PHASE_RUNNING = "running"

# Every state the phase sensor can report, across both appliance types.
# Declared as the sensor's enum options, so an unexpected value shows up as
# an error instead of silently becoming an untranslated state.
ALL_PHASES = [
    PHASE_IDLE,
    PHASE_INTAKE,
    PHASE_HEATING,
    PHASE_WASHING,
    PHASE_DRAINING,
    PHASE_SPINNING,
    PHASE_DRYING,
    PHASE_COOLDOWN,
    PHASE_RUNNING,
    PHASE_FINISHED,
]

PHASES_BY_TYPE = {
    APPLIANCE_TYPE_WASHER: [
        PHASE_INTAKE,
        PHASE_HEATING,
        PHASE_WASHING,
        PHASE_DRAINING,
        PHASE_SPINNING,
    ],
    APPLIANCE_TYPE_DRYER: [PHASE_HEATING, PHASE_DRYING, PHASE_COOLDOWN],
}

CONFIDENCE_CLEAR = 0.9
CONFIDENCE_LIKELY = 0.7
CONFIDENCE_UNCERTAIN = 0.4

# --------------------------------------------------------------------------- #
# Run detection
# --------------------------------------------------------------------------- #

# Power must stay at or above the "low" band for this long before a run is
# considered started - keeps a brief door-light or control-panel wake-up from
# opening a run.
RUN_START_SECONDS = 60
# ... and must stay at or below "standby" for this long before it ends.
#
# Two thresholds, not one. A single four-minute rule split a real boil wash
# into three "runs": that programme has quiet stretches longer than four
# minutes - soaking, and the pause between the main wash and the spin - and
# during them a washing machine draws no more than its control panel does.
#
# Splitting a cycle is far more damaging than closing one late. It poisons
# the run history, so the remaining-time estimate learns from fragments;
# it miscounts calibration runs; and it inflates the weekly cycle count.
# Closing late only delays the "finished" reminder.
#
# So: be patient until the appliance has done the thing it does last - the
# spin on a washing machine, the cool-down on a dryer. Once that has been
# seen, the cycle really is over and there is no reason to wait.
RUN_END_SECONDS = 240
RUN_END_PATIENT_SECONDS = 1200

# Patience is only extended to runs that have been going long enough to
# plausibly be a real cycle. Without this, a two-minute burst from a door
# light would leave the card showing "water intake" for twenty minutes -
# a worse outcome than the splitting this is meant to prevent. A real
# programme has been running for half an hour before its first long soak.
RUN_PATIENCE_MIN_ELAPSED_SECONDS = 600

# The phase that, once seen, means the programme has reached its end. Used
# only to decide how long to wait before closing a run.
TERMINAL_PHASE_BY_TYPE = {
    APPLIANCE_TYPE_WASHER: PHASE_SPINNING,
    APPLIANCE_TYPE_DRYER: PHASE_COOLDOWN,
}

# Samples buffered per run. At one sample every few seconds a long cotton
# program still fits; older samples are dropped from the front.
MAX_SAMPLES_PER_RUN = 5000
# Completed runs kept for the remaining-time estimate and the weekly
# statistics. Beyond this the oldest are discarded.
MAX_STORED_RUNS = 60

# --------------------------------------------------------------------------- #
# Update interval validation
# --------------------------------------------------------------------------- #

# Above this median interval between samples, detection is unreliable: a spin
# cycle or a cool-down phase can pass between two readings. Tasmota's default
# TelePeriod of 300 s is five times this.
MAX_USABLE_UPDATE_INTERVAL_SECONDS = 30
# Samples needed before the observed interval is judged at all.
MIN_SAMPLES_FOR_INTERVAL_CHECK = 10

# --------------------------------------------------------------------------- #
# Calibration
# --------------------------------------------------------------------------- #

# Completed runs recorded before thresholds are proposed.
CALIBRATION_RUNS_REQUIRED = 3

CALIBRATION_STATE_INACTIVE = "inactive"
CALIBRATION_STATE_RECORDING = "recording"
CALIBRATION_STATE_READY = "ready"

# --------------------------------------------------------------------------- #
# Anomaly detection
# --------------------------------------------------------------------------- #
# A finished run is compared against the stored runs that went the same way.
# The point is to surface the slow drifts nobody notices by eye - a heating
# phase creeping longer over months as the element scales up, a drain that
# takes twice as long because the filter is clogging.

ANOMALY_PHASE_LONGER = "phase_longer"
ANOMALY_PHASE_SHORTER = "phase_shorter"
ANOMALY_ENERGY_HIGHER = "energy_higher"
ANOMALY_MISSING_PHASE = "missing_phase"

DEFAULT_ANOMALY_DETECTION_ENABLED = True
# How far a phase may stray from its usual duration before it is reported.
DEFAULT_ANOMALY_FACTOR = 1.6
MIN_ANOMALY_FACTOR = 1.1
MAX_ANOMALY_FACTOR = 5.0
# Comparable runs needed before the integration is willing to have an
# opinion. Saying nothing beats crying wolf on the third ever wash.
ANOMALY_MIN_RUNS = 5

ANOMALY_MESSAGES_BY_LANGUAGE = {
    "en": {
        "title": "{appliance}: unusual cycle",
        ANOMALY_PHASE_LONGER: "{phase} took {observed} min instead of the usual {expected} min.",
        ANOMALY_PHASE_SHORTER: "{phase} took only {observed} min instead of the usual {expected} min.",
        ANOMALY_ENERGY_HIGHER: "The cycle used {observed} kWh instead of the usual {expected} kWh.",
        ANOMALY_MISSING_PHASE: "The cycle ended without a {phase} phase.",
    },
    "de": {
        "title": "{appliance}: ungewöhnlicher Durchgang",
        ANOMALY_PHASE_LONGER: "{phase} dauerte {observed} min statt der üblichen {expected} min.",
        ANOMALY_PHASE_SHORTER: "{phase} dauerte nur {observed} min statt der üblichen {expected} min.",
        ANOMALY_ENERGY_HIGHER: "Der Durchgang verbrauchte {observed} kWh statt der üblichen {expected} kWh.",
        ANOMALY_MISSING_PHASE: "Der Durchgang endete ohne {phase}-Phase.",
    },
}

# --------------------------------------------------------------------------- #
# Program recognition
# --------------------------------------------------------------------------- #
# Runs cluster naturally: a cotton program at 60 degrees looks nothing like
# a quick wash, and the difference is visible in the phase durations. Two
# runs belong to the same program when they went through the same phases in
# the same order and each phase took a comparable time.

# How far each phase's duration may differ before two runs are considered
# different programs.
PROGRAM_TOLERANCE = 1.4
# Programs are dropped once this many are stored, oldest first, so a machine
# used in unusual ways does not accumulate clusters forever.
MAX_PROGRAMS = 12
# A cluster is only offered as a program once it has been seen this often -
# a one-off run is not a program.
PROGRAM_MIN_RUNS = 2

# --------------------------------------------------------------------------- #
# Cost
# --------------------------------------------------------------------------- #

DEFAULT_PRICE_PER_KWH = 0.30
DEFAULT_CURRENCY = "EUR"
# What the grid pays for a kWh that is exported instead of used. With a
# fixed tariff there is no cheap hour to wait for, but every kWh taken from
# your own production rather than exported is worth the difference between
# these two numbers.
DEFAULT_FEED_IN_TARIFF = 0.08

# --------------------------------------------------------------------------- #
# Solar surplus
# --------------------------------------------------------------------------- #

CONF_SOLAR_ENTITY = "solar_entity"
CONF_CONSUMPTION_ENTITY = "consumption_entity"

# The surplus has to exceed the appliance's typical draw by this margin
# before a cycle is suggested - starting one that the sun cannot quite carry
# would import the difference from the grid for the whole cycle.
SOLAR_SURPLUS_MARGIN = 1.1
# A cloud passing over should not retract the suggestion. The surplus must
# hold for this long before it counts.
SOLAR_SURPLUS_DWELL_SECONDS = 300

# --------------------------------------------------------------------------- #
# Reminder
# --------------------------------------------------------------------------- #

DEFAULT_REMINDER_ENABLED = False
DEFAULT_REMINDER_DELAY_MINUTES = 30
DEFAULT_REMINDER_REPEAT_MINUTES = 30
DEFAULT_REMINDER_MAX_REPEATS = 3

REMINDER_MESSAGES_BY_LANGUAGE = {
    "en": {
        "title": "{appliance} is done",
        "message": "The load has been sitting in the drum for {minutes} minutes.",
    },
    "de": {
        "title": "{appliance} ist fertig",
        "message": "Die Wäsche liegt seit {minutes} Minuten in der Trommel.",
    },
}

# --------------------------------------------------------------------------- #
# Services
# --------------------------------------------------------------------------- #

SERVICE_SET_PRICE = "set_price"
SERVICE_SET_REMINDER = "set_reminder"
SERVICE_SET_NOTIFY_TARGET = "set_notify_target"
SERVICE_SET_THRESHOLDS = "set_thresholds"
SERVICE_START_CALIBRATION = "start_calibration"
SERVICE_CANCEL_CALIBRATION = "cancel_calibration"
SERVICE_APPLY_CALIBRATION = "apply_calibration"
SERVICE_DISMISS_REMINDER = "dismiss_reminder"
SERVICE_CLEAR_HISTORY = "clear_history"
SERVICE_SET_ANOMALY_DETECTION = "set_anomaly_detection"
SERVICE_DISMISS_ANOMALIES = "dismiss_anomalies"
SERVICE_SET_PROGRAM_NAME = "set_program_name"
SERVICE_SET_SOLAR = "set_solar"

# --------------------------------------------------------------------------- #
# State attributes
# --------------------------------------------------------------------------- #

ATTR_APPLIANCE_TYPE = "appliance_type"
ATTR_POWER_ENTITY = "power_entity"
ATTR_DOOR_ENTITY = "door_entity"
ATTR_CONFIDENCE = "confidence"
ATTR_BAND = "band"
ATTR_WATTS = "watts"
ATTR_RUN_ACTIVE = "run_active"
ATTR_RUN_STARTED = "run_started"
ATTR_RUN_FINISHED = "run_finished"
ATTR_ELAPSED_SECONDS = "elapsed_seconds"
ATTR_REMAINING_SECONDS = "remaining_seconds"
ATTR_ESTIMATED_TOTAL_SECONDS = "estimated_total_seconds"
ATTR_PHASE_TIMELINE = "phase_timeline"
ATTR_POWER_CURVE = "power_curve"
ATTR_KNOWN_PHASES = "known_phases"
ATTR_CYCLE_ENERGY_KWH = "cycle_energy_kwh"
ATTR_CYCLE_COST = "cycle_cost"
ATTR_LAST_RUN = "last_run"
ATTR_WEEK_CYCLES = "week_cycles"
ATTR_WEEK_ENERGY_KWH = "week_energy_kwh"
ATTR_WEEK_COST = "week_cost"
ATTR_PRICE_PER_KWH = "price_per_kwh"
ATTR_CURRENCY = "currency"
ATTR_THRESHOLDS = "thresholds"
ATTR_CALIBRATION_STATE = "calibration_state"
ATTR_CALIBRATION_RUNS = "calibration_runs"
ATTR_CALIBRATION_RUNS_REQUIRED = "calibration_runs_required"
ATTR_CALIBRATION_PROPOSAL = "calibration_proposal"
ATTR_UPDATE_INTERVAL_SECONDS = "update_interval_seconds"
ATTR_UPDATE_INTERVAL_OK = "update_interval_ok"
ATTR_REMINDER_ENABLED = "reminder_enabled"
ATTR_REMINDER_DELAY_MINUTES = "reminder_delay_minutes"
ATTR_REMINDER_REPEAT_MINUTES = "reminder_repeat_minutes"
ATTR_REMINDER_MAX_REPEATS = "reminder_max_repeats"
ATTR_REMINDER_PENDING = "reminder_pending"
ATTR_NOTIFY_TARGET = "notify_target"
ATTR_ANOMALIES = "anomalies"
# The same findings rendered as sentences in the instance language, so the
# card does not have to duplicate the message templates.
ATTR_ANOMALY_MESSAGES = "anomaly_messages"
ATTR_ANOMALY_DETECTION_ENABLED = "anomaly_detection_enabled"
ATTR_ANOMALY_FACTOR = "anomaly_factor"
ATTR_PROGRAMS = "programs"
ATTR_CURRENT_PROGRAM = "current_program"
ATTR_TOTAL_ENERGY_KWH = "total_energy_kwh"
ATTR_FEED_IN_TARIFF = "feed_in_tariff"
ATTR_SOLAR_ENTITY = "solar_entity"
ATTR_CONSUMPTION_ENTITY = "consumption_entity"
ATTR_SOLAR_SURPLUS_W = "solar_surplus_w"
ATTR_TYPICAL_DRAW_W = "typical_draw_w"
ATTR_SOLAR_COVERS_CYCLE = "solar_covers_cycle"
ATTR_SOLAR_SAVING_PER_CYCLE = "solar_saving_per_cycle"

# How many points of the current run's power curve are handed to the card.
# The full buffer would bloat every state update; the card only draws a
# sparkline, so it is downsampled to this many points.
POWER_CURVE_POINTS = 120
