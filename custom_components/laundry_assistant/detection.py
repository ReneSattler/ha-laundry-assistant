"""Band classification and the phase state machine.

Kept free of Home Assistant imports on purpose: everything in here is pure
logic over `(timestamp, watts)` samples, so a recorded run can be replayed
through it in a test without a running Home Assistant instance.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from .const import (
    ANOMALY_ENERGY_HIGHER,
    ANOMALY_MISSING_PHASE,
    ANOMALY_PHASE_LONGER,
    ANOMALY_PHASE_SHORTER,
    APPLIANCE_TYPE_DRYER,
    APPLIANCE_TYPE_WASHER,
    BAND_HIGH,
    BAND_LOW,
    BAND_MEDIUM,
    BAND_OFF,
    BAND_STANDBY,
    BANDS,
    CONFIDENCE_CLEAR,
    CONFIDENCE_LIKELY,
    CONFIDENCE_UNCERTAIN,
    PHASE_COOLDOWN,
    PHASE_DRAINING,
    PHASE_DRYING,
    PHASE_HEATING,
    PHASE_IDLE,
    PHASE_INTAKE,
    PHASE_RUNNING,
    PHASE_SPINNING,
    PHASE_WASHING,
    THRESHOLD_KEYS,
)

# While washing, the drum reverses in bursts of a few seconds and the power
# jumps into "medium" each time. Those bursts are not a drain, so leaving the
# wash phase requires "medium" to hold longer than any single burst.
WASH_BURST_MAX_SECONDS = 45
# A "medium" stretch that holds beyond this is no longer a drain pulse - it
# is the spin spinning up. The two are indistinguishable by wattage alone.
DRAIN_MAX_SECONDS = 120
# Machines spin between rinses, not only at the end. Dropping back to "low"
# for this long means the spin was an intermediate one and washing continues.
# Long enough that the run-down at the end of the final spin does not trip
# it before the run-end detection closes the run.
SPIN_EXIT_SECONDS = 180
# Rhythmic low/medium alternation counts as washing once this many band
# changes have been seen without leaving the low/medium range.
WASH_ALTERNATIONS = 2
# A dryer's cool-down is the drum turning without heat: a sustained drop to
# "low" after drying, held at least this long before it is reported.
COOLDOWN_MIN_SECONDS = 60


def classify(watts: float, thresholds: dict[str, float]) -> str:
    """Map a wattage reading to a band.

    The highest band whose edge the value reaches wins; anything below the
    standby edge is off.
    """
    for band in reversed(THRESHOLD_KEYS):
        edge = thresholds.get(band)
        if edge is not None and watts >= edge:
            return band
    return BAND_OFF


def band_index(band: str) -> int:
    """Ordinal position of a band, for `>=` style comparisons."""
    return BANDS.index(band)


@dataclass
class PhaseContext:
    """Everything the transition rules are allowed to look at.

    Deliberately small: the rules must be expressible in terms of the
    current band, how long it has held, what has already happened in this
    run, and how far in we are. Anything needing more than that is a sign
    the rule is overfitted to one machine.
    """

    band: str
    band_dwell_seconds: float
    watts: float
    run_elapsed_seconds: float
    seen_phases: set[str] = field(default_factory=set)
    # Band changes since entering the current phase, used to recognise the
    # rhythmic drum reversal of a wash phase.
    alternations: int = 0


def next_phase_washer(phase: str, ctx: PhaseContext) -> tuple[str, float]:
    """Return the phase a washing machine is in, plus a confidence value.

    The instantaneous wattage is ambiguous - 350 W is either draining or a
    spin ramping up - so every rule below is conditioned on what the run has
    already been through, not on the value alone.
    """
    band = ctx.band

    # Heating is the least ambiguous signal a washing machine produces:
    # nothing else in the cycle draws two kilowatts, and it holds flat for
    # minutes. The one exception is a spin already under way - a fast final
    # spin on a machine with a low high-edge can reach into the band, and
    # calling that "heating" would be plainly wrong.
    if band == BAND_HIGH and phase != PHASE_SPINNING:
        return PHASE_HEATING, CONFIDENCE_CLEAR

    if phase in (PHASE_IDLE, PHASE_INTAKE):
        # Before any heating, a low draw is the machine taking on water.
        if band == BAND_LOW:
            return PHASE_INTAKE, CONFIDENCE_LIKELY
        if band == BAND_MEDIUM:
            # Cold programs never heat, so medium this early is the drum
            # already turning rather than an intake.
            return PHASE_WASHING, CONFIDENCE_UNCERTAIN
        return PHASE_INTAKE, CONFIDENCE_UNCERTAIN

    if phase == PHASE_HEATING:
        # Heating ended. What follows is the wash itself.
        if band in (BAND_LOW, BAND_MEDIUM):
            return PHASE_WASHING, CONFIDENCE_CLEAR
        return PHASE_WASHING, CONFIDENCE_UNCERTAIN

    if phase == PHASE_WASHING:
        # Every drum reversal briefly pushes the draw into "medium". Only a
        # stretch that outlasts such a burst is something else - and even
        # then it is still ambiguous, because a drain pulse and a spin
        # ramping up look identical. Report draining, and let the dwell
        # time below promote it to spinning if it keeps going.
        if band == BAND_MEDIUM and ctx.band_dwell_seconds >= WASH_BURST_MAX_SECONDS:
            return PHASE_DRAINING, CONFIDENCE_UNCERTAIN
        confidence = (
            CONFIDENCE_CLEAR if ctx.alternations >= WASH_ALTERNATIONS else CONFIDENCE_LIKELY
        )
        return PHASE_WASHING, confidence

    if phase == PHASE_DRAINING:
        if band == BAND_MEDIUM and ctx.band_dwell_seconds >= DRAIN_MAX_SECONDS:
            # Held too long to be a drain pulse.
            return PHASE_SPINNING, CONFIDENCE_CLEAR
        if band == BAND_MEDIUM:
            return PHASE_DRAINING, CONFIDENCE_LIKELY
        if band == BAND_LOW:
            # Dropped back down - the drain was between two wash blocks.
            return PHASE_WASHING, CONFIDENCE_LIKELY
        return PHASE_DRAINING, CONFIDENCE_UNCERTAIN

    if phase == PHASE_SPINNING:
        # Machines spin between rinses too, and without a way back the
        # phase would stick for the rest of the cycle.
        #
        # The way back cannot be "low held for a while": during a wash the
        # band alternates every few tens of seconds and never holds long
        # enough, so that condition could not fire in the one situation it
        # exists for. What separates the two is the alternation itself - a
        # spin holds a steady draw, a tumbling drum does not.
        if ctx.alternations >= WASH_ALTERNATIONS:
            return PHASE_WASHING, CONFIDENCE_LIKELY
        if band == BAND_LOW and ctx.band_dwell_seconds >= SPIN_EXIT_SECONDS:
            return PHASE_WASHING, CONFIDENCE_LIKELY
        return PHASE_SPINNING, CONFIDENCE_CLEAR

    return PHASE_RUNNING, CONFIDENCE_UNCERTAIN


def next_phase_dryer(phase: str, ctx: PhaseContext) -> tuple[str, float]:
    """Return the phase a tumble dryer is in, plus a confidence value.

    Two very different machine types share these rules. A condenser dryer
    cycles its heating element at 2000-2600 W and therefore reaches the
    "high" band; a heat-pump dryer runs at a fairly constant 500-900 W and
    never leaves "medium". Both end with a clearly lower cool-down where
    only the drum still turns, which is what makes the end of the cycle
    detectable in either case.
    """
    band = ctx.band

    if phase in (PHASE_IDLE, PHASE_HEATING):
        if band == BAND_HIGH:
            return PHASE_HEATING, CONFIDENCE_CLEAR
        if band == BAND_MEDIUM:
            return PHASE_DRYING, CONFIDENCE_CLEAR
        if band == BAND_LOW:
            # Low right at the start is the drum spinning up before the
            # heat comes on, not a cool-down.
            if PHASE_DRYING in ctx.seen_phases:
                return PHASE_COOLDOWN, CONFIDENCE_LIKELY
            return PHASE_DRYING, CONFIDENCE_UNCERTAIN
        return PHASE_DRYING, CONFIDENCE_UNCERTAIN

    if phase == PHASE_DRYING:
        # A condenser dryer switches its heating element on and off
        # throughout the whole cycle, crossing in and out of the high band
        # dozens of times. That is what drying looks like on that machine -
        # treating each crossing as a new heating phase would turn the
        # timeline into noise. Only the warm-up before drying starts is
        # reported as heating.
        if band in (BAND_HIGH, BAND_MEDIUM):
            return PHASE_DRYING, CONFIDENCE_CLEAR
        if band == BAND_LOW and ctx.band_dwell_seconds >= COOLDOWN_MIN_SECONDS:
            return PHASE_COOLDOWN, CONFIDENCE_CLEAR
        # Could still be a momentary dip between compressor cycles.
        return PHASE_DRYING, CONFIDENCE_UNCERTAIN

    if phase == PHASE_COOLDOWN:
        if band in (BAND_MEDIUM, BAND_HIGH):
            # Heat came back on - it was a dip, not the end.
            return PHASE_DRYING, CONFIDENCE_LIKELY
        return PHASE_COOLDOWN, CONFIDENCE_CLEAR

    return PHASE_RUNNING, CONFIDENCE_UNCERTAIN


def next_phase(appliance_type: str, phase: str, ctx: PhaseContext) -> tuple[str, float]:
    """Dispatch to the transition rules for the appliance type."""
    if appliance_type == APPLIANCE_TYPE_WASHER:
        return next_phase_washer(phase, ctx)
    if appliance_type == APPLIANCE_TYPE_DRYER:
        return next_phase_dryer(phase, ctx)
    return PHASE_RUNNING, CONFIDENCE_UNCERTAIN


def propose_thresholds(samples: list[float], appliance_type: str) -> dict[str, float] | None:
    """Propose band edges from the wattage values of recorded runs.

    This is a starting point for the user to confirm or override, not a
    measurement. The reasoning is that every appliance's cycle is dominated
    by one peak load - the heating element, or the heat pump's compressor -
    and the other bands sit at roughly fixed fractions below it. Deriving
    the edges from the observed peak therefore adapts to the machine's
    absolute scale, which is what differs most between models, without
    pretending to identify individual phases.

    Returns None when there is not enough signal to say anything.
    """
    active = sorted(w for w in samples if w >= 5.0)
    if len(active) < 50:
        return None

    # 95th percentile rather than the maximum: inrush current when a motor
    # starts can be several times the steady draw for a fraction of a
    # second, and would drag every edge up with it.
    peak = active[int(len(active) * 0.95)]
    if peak < 50.0:
        return None

    if appliance_type == APPLIANCE_TYPE_DRYER:
        # A heat-pump dryer's peak *is* its drying load, so the high edge
        # has to sit above it or the whole cycle would read as "high".
        high = peak * 1.15
        medium = peak * 0.25
    else:
        high = peak * 0.55
        medium = peak * 0.08

    low = max(10.0, peak * 0.012)
    standby = 2.0

    return {
        BAND_STANDBY: round(standby, 1),
        BAND_LOW: round(low, 1),
        BAND_MEDIUM: round(medium, 1),
        BAND_HIGH: round(high, 1),
    }


def find_anomalies(
    run: dict[str, Any],
    history: list[dict[str, Any]],
    factor: float,
    min_runs: int,
) -> list[dict[str, Any]]:
    """Compare a finished run against the runs that went the same way.

    The comparison is against runs with an identical phase sequence, so a
    quick wash is never measured against a cotton program. Within that set,
    each phase's duration and the cycle's energy are compared to the median
    rather than the mean - one pathological run should not move the
    baseline it is being judged against.

    Returns an empty list when there is not enough history to have an
    opinion. Silence is the correct output for the first few runs.
    """
    sequence = [entry["phase"] for entry in run.get("timeline", [])]
    comparable = [
        past
        for past in history
        if [entry["phase"] for entry in past.get("timeline", [])] == sequence
    ]

    findings: list[dict[str, Any]] = []

    # A phase that is present in most previous runs but missing here is
    # worth reporting even though the sequence no longer matches - a wash
    # that ended without a spin usually means the machine gave up on an
    # unbalanced load.
    if len(history) >= min_runs:
        usual = _phases_present_in_most_runs(history, min_runs)
        for phase in usual:
            if phase not in sequence:
                findings.append({"kind": ANOMALY_MISSING_PHASE, "phase": phase})

    if len(comparable) < min_runs:
        return findings

    for phase in dict.fromkeys(sequence):
        observed = sum(
            entry["seconds"] for entry in run["timeline"] if entry["phase"] == phase
        )
        past_durations = [
            sum(entry["seconds"] for entry in past["timeline"] if entry["phase"] == phase)
            for past in comparable
        ]
        expected = statistics.median(past_durations)
        if expected <= 0:
            continue
        if observed >= expected * factor:
            kind = ANOMALY_PHASE_LONGER
        elif observed <= expected / factor:
            kind = ANOMALY_PHASE_SHORTER
        else:
            continue
        findings.append(
            {
                "kind": kind,
                "phase": phase,
                "observed_seconds": round(observed),
                "expected_seconds": round(expected),
            }
        )

    observed_energy = run.get("energy_kwh", 0.0)
    expected_energy = statistics.median(past["energy_kwh"] for past in comparable)
    if expected_energy > 0 and observed_energy >= expected_energy * factor:
        findings.append(
            {
                "kind": ANOMALY_ENERGY_HIGHER,
                "observed_kwh": round(observed_energy, 3),
                "expected_kwh": round(expected_energy, 3),
            }
        )

    return findings


def _phases_present_in_most_runs(
    history: list[dict[str, Any]], min_runs: int
) -> list[str]:
    """Phases that appear in more than half of the recorded runs."""
    counts: dict[str, int] = {}
    for past in history:
        for phase in {entry["phase"] for entry in past.get("timeline", [])}:
            counts[phase] = counts.get(phase, 0) + 1
    threshold = max(min_runs, len(history) // 2 + 1)
    return [phase for phase, count in counts.items() if count >= threshold]


def validate_thresholds(thresholds: dict[str, Any]) -> dict[str, float]:
    """Coerce and sanity-check a threshold set.

    Raises ValueError if the edges are not strictly increasing - a set where
    the medium edge sits above the high edge would make bands unreachable
    and the phase rules silently nonsensical.
    """
    result: dict[str, float] = {}
    for key in THRESHOLD_KEYS:
        if key not in thresholds:
            raise ValueError(f"Missing threshold for band '{key}'")
        try:
            result[key] = float(thresholds[key])
        except (TypeError, ValueError) as err:
            raise ValueError(f"Threshold for band '{key}' is not a number") from err

    edges = [result[key] for key in THRESHOLD_KEYS]
    if any(later <= earlier for earlier, later in zip(edges, edges[1:])):
        raise ValueError("Thresholds must increase strictly from standby to high")
    if edges[0] <= 0:
        raise ValueError("The standby threshold must be greater than zero")
    return result
