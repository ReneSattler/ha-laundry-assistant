# Changelog

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
