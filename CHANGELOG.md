# Changelog

## 0.4.1 - 2026-10-03

### Fixed

- **The new `aborted` phase had no label in the Lovelace card.** The 0.4.0
  backend could report it, but the card's string tables (English and
  German) did not know it, so CI failed on
  `test_the_card_translates_every_phase_too`. Added `Aborted` /
  `Abgebrochen` plus a timeline colour. This is the one failure the 0.4.0
  workflows reported; everything else was green.

## 0.4.0 - 2026-10-03

Power-only features: everything here is derived from the watt curve plus
time - no extra hardware. Closes #23, #24, #25, #26, #27.

### Added

- **Aborted runs (#23).** A cycle that never reaches its terminal phase
  (spin on a washer, cool-down on a dryer) reports `aborted` instead of
  `finished`. It still counts for energy and lifetime totals, but never for
  learning (remaining time, programs, calibration, deviation warnings),
  the drum reminder or the consumable counter.
- **Monthly totals (#24):** `month_cycles`, `month_energy` and `month_cost`
  sensors, same semantics as the weekly ones, month starting on the 1st.
- **Dynamic price sensor (#25):** `set_price_sensor` points the appliance
  at a price sensor (Tibber/Octopus/ENTSO-E, software-only). Cycle costs
  use the live price and fall back to the fixed price when unavailable.
- **Consumable counter (#26):** finished cycles since the last reset, with
  a `reset_consumable_counter` service (detergent, decalcification).
- **Ready-by planner (#27):** `plan_ready_by` stores when the laundry
  should be ready; a `latest_start` timestamp sensor derives the latest
  start from the learned duration (recognised program when available).

## 0.3.2 - 2026-08-22

### Fixed

- **Typing a programme name lost focus on every keystroke, live in Home
  Assistant, invisible in screenshots.** The focus guard added in 0.2.0
  checks whether a field is genuinely focused before allowing a re-render,
  using `document.activeElement`. That is correct for a card rendering into
  its own shadow root (ha-irrigation-sequencer's approach), but this card
  renders into the light DOM, and Home Assistant wraps every custom card
  inside `hui-card`, which has its own shadow root. `document.activeElement`
  does not cross that boundary: with focus genuinely inside the name field,
  it resolved to `hui-card` itself, not the field, so the guard concluded
  nothing was being edited. The failure needed a second ingredient to
  surface - the card's suppression timer is shared across every field, and
  any unrelated control committing a change (a price edit, a toggle)
  shrinks that shared window to 400ms - which is why it looked
  intermittent rather than constant. Fixed by checking
  `this.querySelector(":focus")` instead, which is evaluated within the
  card's own subtree and is unaffected by shadow roots above it.

  Verified with two pages under `tests/frontend/`, now run in CI: each
  wraps the real card inside a synthetic `hui-card` shadow root - matching
  how Home Assistant actually hosts it - and drives the exact scenario that
  used to wipe the field. Confirmed to fail on the pre-fix code and pass
  after.


## 0.3.1 - 2026-08-21

### Changed

- **Recognised programmes name themselves.** They were always recognised,
  matched and used for the remaining-time estimate without anyone doing
  anything - but a list reading "Unnamed" beside an empty text box looks
  like a form waiting to be filled in, so the automatic thing did not look
  automatic. Each programme now shows a label derived from its own shape -
  a warm wash, a cold wash, a quick programme, a long drying programme -
  and the section says outright that naming is optional. A name typed by
  hand still wins.

### Fixed

- The programme name field was squeezed to a few characters by the trend
  text beside it, which made the one thing it is for - renaming - awkward.
  It now has a line of its own.


## 0.3.0 - 2026-08-21

Three features, all suggested by what a live installation's data showed
was missing.

### Added

- **The wash tells you the dryer is free.** A washing machine and a tumble
  dryer set up in the same integration knew nothing about each other. The
  finished reminder now carries a note when a dryer is configured and
  idle. Opt-in, silent when no dryer exists, and silent when it is
  mid-cycle - "your wash is done and the dryer is busy" is noise. It is a
  suffix on the existing reminder rather than a second notification: being
  told twice about one load of washing is how a useful feature becomes one
  people switch off.
- **An expected-finish-time sensor**, with `device_class: timestamp`.
  Derived from the run's start plus its estimated total rather than from
  now plus the remaining time - arithmetically the same at any instant,
  but this one only moves when the estimate does, while the other shifts
  with every reading. A minute count is what you want on a card; an
  instant is what composes into an automation or a spoken sentence.
- **Energy per programme over time.** Each recognised programme keeps its
  run energies and reports which way they are moving. The existing
  deviation warnings compare one run against the median of comparable
  ones, so they catch a step change and miss a slow drift - a boil wash
  creeping from 1.9 to 2.4 kWh over months is a scaling heating element,
  and no single cycle shows it. Reported only above six runs, and shown as
  "steady" below five percent, because a figure that wobbles between one
  percent up and one percent down teaches the reader to ignore the line.


## 0.2.0 - 2026-08-21

Everything here came out of reading a live installation's data - a washing
machine and a tumble dryer that had been running for days. Six fixes, none
of which any synthetic curve had suggested.

### Fixed

- **One cycle was recorded as several runs.** A run ended after four
  minutes of quiet, but a boil wash is quiet for longer than that while it
  soaks. The wait is now long until the appliance has done the thing it
  does last - the spin, or the cool-down - and short afterwards. Splitting
  poisons the history that remaining time, calibration and the weekly
  totals all learn from; closing late only delays the reminder.
- **A plug reporting every five minutes produced a confident fiction.** At
  Tasmota's default of one reading per 300 s, a 47-minute wash yielded
  eleven samples: the band never left "high" and the cycle was recorded as
  one 39-minute heating phase, which then became thirteen calibration runs
  and twelve one-off "programs". Such runs are now marked unreliable and
  kept out of everything that learns, while still counting for energy and
  the finished reminder.
- **The warning that exists for exactly that never fired.** It needed ten
  intervals before judging anything, and a whole wash at 300 s spacing
  produces nine. Four now.
- **A dryer's heat pauses were read as cool-downs.** A heat-pump dryer
  switches its heat off for about a minute throughout the programme; each
  pause was announced as a cool-down and taken back. A cool-down now needs
  four minutes of low draw.
- **Every drying cycle opened with a phantom cool-down**, because the drum
  turns before the heat comes on and having seen drying once was enough to
  admit one. A cool-down now also requires a programme already five
  minutes old. Together these two stop the drying phase being fragmented,
  which is why runs of the same programme never clustered.
- **A replaced plug left the integration silent.** Pointed at an entity
  that no longer existed, it sat at idle indefinitely - indistinguishable
  from an appliance nobody had used. The card now says so, and setup logs
  a warning naming the entity.
- **Editing a field on Android lost focus every few seconds**, because the
  card rebuilt its DOM on every power reading. Guard ported from
  ha-irrigation-sequencer and adapted for the light DOM.

## 0.1.0 - 2026-08-04

First release. Verified in a Home Assistant container, against synthetic
power curves and a driven cycle - **not yet against a real washing machine
or tumble dryer**. Marked as a pre-release for that reason.

- Band classification and the phase state machine for washing machines and
  tumble dryers (`detection.py`), kept free of Home Assistant imports so a
  recorded run can be replayed through it in a test
- Sample collection from the plug's power sensor, with kW-to-W conversion
  and a warning when the sensor's update interval is too coarse
- Run start and end detection, energy integration and run history
- Remaining time estimated from stored runs with a matching phase sequence
- Cost per cycle and weekly totals
- Reminder for laundry left in the drum, with an optional door sensor
- Calibration mode proposing band thresholds from recorded runs
- Status and settings Lovelace cards, bundled and self-registering
- English and German documentation and translations

### Fixed after container verification

Three bugs the replay harness under `tools/` found, all in the phase
transition rules:

- The wash phase collapsed. Every drum reversal briefly pushes the draw into
  the medium band, and each one was read as a drain, which was then promoted
  to a spin with no way back - 35 minutes of washing were reported as 2
  minutes of washing and 43 minutes of spinning. Leaving the wash phase now
  requires medium to outlast a single burst.
- A condenser dryer alternated between heating and drying twenty times in
  one cycle, because its heating element cycles in and out of the high band
  by design. Only the warm-up before drying starts is reported as heating
  now.
- Recovery from an intermediate spin could not fire. It required the low
  band to hold for three minutes, but during a wash the band alternates
  every few tens of seconds and never holds that long - so the phase stuck
  on "spinning" for the rest of the cycle. It now keys on the alternation
  itself, which is what actually distinguishes a tumbling drum from a spin.

Also fixed: an empty `dependencies` list in the manifest, `idle` appearing
as a segment in the timeline, and the bulk attributes being written to the
recorder on every power sample.

### Fixed after running a cycle in a real Home Assistant instance

Driving the integration from an `input_number` inside the container - a
sensor that reports only when its value changes, exactly like a plug
configured with Tasmota's `PowerDelta` - exposed two failures that the
synthetic curves could not, because those fed a reading every ten seconds:

- **Nothing was ever detected.** A band change needs its dwell time to
  elapse, and that was only ever checked when a reading arrived. On a
  report-on-change sensor each reading sits in a different band from the
  one before, so the dwell never had a second sample to confirm against.
  The band stayed put, no run opened, and the four minutes of silence that
  end a cycle - during which such a sensor says nothing at all - could
  never close one either. There is now an evaluation tick that advances the
  time-based rules on its own clock.
- **Energy was understated by a third.** Integration averaged the two
  endpoints of each interval, which assumes the load ramped between them.
  A Home Assistant state holds until the next one arrives, so across the
  five-minute silence a flat-out heating element produces, that turned a
  step into a ramp. Now integrates left-hand, which is exact for a sensor
  that reports on change.

The "update interval too coarse" warning also no longer fires on
event-driven sensors, whose long gaps are flat phases rather than a slow
setting. It still fires on genuinely slow timer-driven ones.

### Added

- Program recognition: runs cluster by phase sequence and phase durations,
  can be named, and sharpen the remaining-time estimate
- A `total_increasing` lifetime energy sensor for the energy dashboard
- Solar surplus suggestion, valued at the difference between the price paid
  per kWh and the feed-in tariff rather than the full price
- `tools/export_history.py` and `tools/replay_fixture.py`, to turn a real
  appliance's recorded history into a fixture and replay it
