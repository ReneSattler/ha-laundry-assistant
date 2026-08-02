"""Band classification and the phase state machine.

Kept free of Home Assistant imports on purpose: everything in here is pure
logic over `(timestamp, watts)` samples, so a recorded run can be replayed
through it in a test without a running Home Assistant instance.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .const import (
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

# A "medium" stretch shorter than this is a drain pulse; longer, and it is
# the spin cycle spinning up. The two are indistinguishable by wattage alone.
DRAIN_MAX_SECONDS = 90
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
    # minutes. Whenever it appears, it wins regardless of the current phase.
    if band == BAND_HIGH:
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
        if band == BAND_MEDIUM:
            # Still ambiguous at this point: a drain pulse and the start of
            # a spin look the same. Report draining, and let the dwell time
            # below promote it to spinning if it keeps going.
            return PHASE_DRAINING, CONFIDENCE_UNCERTAIN
        return PHASE_WASHING, CONFIDENCE_CLEAR if ctx.alternations >= WASH_ALTERNATIONS else CONFIDENCE_LIKELY

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
        if band in (BAND_MEDIUM, BAND_LOW):
            return PHASE_SPINNING, CONFIDENCE_CLEAR
        return PHASE_SPINNING, CONFIDENCE_LIKELY

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

    if band == BAND_HIGH:
        return PHASE_HEATING, CONFIDENCE_CLEAR

    if phase in (PHASE_IDLE, PHASE_HEATING):
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
        if band == BAND_MEDIUM:
            return PHASE_DRYING, CONFIDENCE_CLEAR
        if band == BAND_LOW and ctx.band_dwell_seconds >= COOLDOWN_MIN_SECONDS:
            return PHASE_COOLDOWN, CONFIDENCE_CLEAR
        if band == BAND_LOW:
            # Could still be a momentary dip between compressor cycles.
            return PHASE_DRYING, CONFIDENCE_UNCERTAIN
        return PHASE_DRYING, CONFIDENCE_LIKELY

    if phase == PHASE_COOLDOWN:
        if band == BAND_MEDIUM:
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
