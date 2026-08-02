# Laundry Assistant

Home Assistant integration that turns a plain power-metering smart plug into a
detailed view of what your washing machine or tumble dryer is actually doing -
which phase it is in, how much longer it will run, and what the cycle cost.

> **Status: early development.** The concept and the detection approach are
> documented below, but the integration is not usable yet. Nothing here is
> released or published to HACS.

## Why

A power-metering plug already tells you whether an appliance draws current, and
most setups stop there: a template sensor flips a binary sensor to `on` above a
few watts and back to `off` below it. That answers "is it running?" but not the
questions you actually have while the machine runs:

- Is it still heating, or already spinning?
- How much longer do I have before I need to be there?
- What did this cycle cost?
- Did I forget the load in the drum again?

All of that is recoverable from the power curve alone - no appliance API, no
manufacturer cloud, no hardware modification.

## How phase detection works

An appliance's power draw is not a single number, it is a sequence of
characteristic bands. A washing machine cycle looks roughly like this:

| Phase | Signature |
|---|---|
| Off / standby | < 2 W |
| Water intake | brief spike, ~30-60 W |
| Heating | 1800-2200 W, flat, sustained for minutes - the most distinctive marker |
| Wash / tumble | 50-200 W, rhythmic on/off bursts as the drum reverses |
| Drain | ~300-400 W, short |
| Spin | ramp from ~200 W to 400-600 W, then falling |
| Finished | back to standby, no further bursts |

A tumble dryer is similar in structure: a heat-pump model draws a fairly
constant 500-900 W, a condenser model cycles at 2000-2600 W, and both end with a
clearly lower cool-down phase at ~100-200 W where only the drum still turns.

Detection is therefore not machine learning. It is a **state machine with
hysteresis**: classify each power sample into a band, then derive the phase from
which bands have already been seen in this run. "High load has occurred, and now
there is rhythmic medium load" means main wash. "A rising ramp past 300 W after a
wash phase" means spin.

Thresholds are per appliance, so the integration records a few complete runs
during setup and proposes the band boundaries from the observed data rather than
shipping guessed defaults.

Remaining time is not estimated from a fixed program table either. Completed runs
are stored with their phase timeline; a run whose phase sequence matches a stored
one so far is expected to take about as long in total.

## Requirements

- A smart plug that reports **active power in watts** as its own sensor entity
- That sensor must update **fast enough to see short phases**

The second point is the one that trips people up. Tasmota, for example, sends
telemetry every 300 seconds by default - at that rate a spin cycle can pass
between two samples and is simply invisible. On Tasmota devices, set one of:

```
TelePeriod 10
```

or, better, push on change instead of on a timer:

```
PowerDelta 10
```

Other firmware and integrations have equivalent settings. The integration will
warn during setup when the observed update interval is too coarse for reliable
detection.

## Planned features

- Per-appliance phase sensor with the current phase and a confidence value
- Estimated remaining time, learned from previous runs
- Energy and cost per cycle, using a configurable price per kWh
- "Load still in the drum" reminder, a configurable time after the cycle ends
- A Lovelace card showing the phase timeline and the live power curve
- Weekly summary: number of cycles, total energy, total cost

## Installation

Not yet available. Once the integration reaches a usable state it will be
installable as a single HACS integration entry, with the card bundled inside it -
the same packaging approach used by
[ha-irrigation-sequencer](https://github.com/ReneSattler/ha-irrigation-sequencer).

## License

MIT - see [LICENSE](LICENSE).
