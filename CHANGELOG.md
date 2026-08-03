# Changelog

## Unreleased

First implementation pass. Written without a running Home Assistant
instance - syntax checked only, not verified against real appliances.

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
