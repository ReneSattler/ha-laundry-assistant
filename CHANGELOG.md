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
