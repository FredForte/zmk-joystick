# Contributing to zmk-joystick

Thank you for helping improve this ZMK analog joystick reference repository! Contributions that make analog joystick integration clearer, more reliable, or better documented for ZMK builders are always welcome.

## Ways to Contribute

- **Documentation improvements**: Clarify wiring guides, pinout notes for additional nRF52840 controllers, or calibration steps.
- **Calibration presets & tuning tips**: Share tested `mv-mid`, `mv-min-max`, and `mv-deadzone` profiles for common joystick modules (e.g., PSP-1000, Switch Joy-Con, KY-023, Alps RKJXV).
- **Bug fixes & ZMK compatibility updates**: Keep the configuration aligned with upstream `zmkfirmware/zmk` and `badjeff/zmk-analog-input-driver`.

## Submitting a Pull Request

1. **Fork** the repository and create a branch from `main` (e.g., `docs/calibration-guide` or `fix/adc-config`).
2. Keep changes focused and verify that the **Build ZMK firmware** GitHub Actions workflow passes in your fork.
3. Follow existing formatting and SPDX license headers (`SPDX-License-Identifier: MIT`) in devicetree and Kconfig files.
4. Open a Pull Request describing:
   - What changed and why.
   - Which board/joystick module you tested on (if applicable).

## Reporting Issues

Please use the [GitHub Issue templates](.github/ISSUE_TEMPLATE/) and include your board name, joystick module, ZMK/driver revisions, and any relevant USB serial log output.
