---
name: zmk-joystick
description: Inspect, install, and validate 2-axis analog joystick support (unibody, split-central, or split-peripheral) in any ZMK Firmware nice!nano v2 user-config repository with automatic pin-collision detection and the zero-fork 1-minute SAADC battery fix.
---

# ZMK Joystick Installer Skill

Use this skill whenever a user wants to add a 2-axis analog joystick (thumbstick) to an existing ZMK Firmware configuration repository (unibody or split keyboard) using [`FredForte/zmk-joystick`](https://github.com/FredForte/zmk-joystick).

## What This Module Provides

- **Composable Add-On Shields** (no `kscan` or `keymap` conflicts):
  - `zmk_joystick_addon`: for unibody keyboards or the **central half** of a split keyboard.
  - `zmk_joystick_peripheral` + `zmk_joystick_central`: for a **split keyboard** where the joystick is physically wired to the **peripheral half** (uses ZMK's `zmk,input-split`).
  - `zmk_joystick`: standalone reference shield with `SW` tap-click / hold-scroll behavior.
- **Zero-Fork 1-Minute SAADC Fix (`zmk,battery-nrf-vddh-no-os`)**: Replaces ZMK's stock `nice!nano v2` `vbatt` sensor (`oversampling = 4`) with an oversampling-free VDDH driver on SAADC slot 1 (`AIN1`) so the joystick never freezes at 60 seconds and Bluetooth battery % reporting stays enabled.
- **Optional Layer-Based Scroll Mode**: Uses ZMK Input Processors (`&zip_xy_to_scroll_mapper`, `&zip_scroll_scaler 1 128`, `&zip_scroll_transform INPUT_TRANSFORM_Y_INVERT`) on any chosen layer.
- **Dual-Mode Zero-Dependency CLI** (`scripts/zmk_joystick.py`): Python 3 stdlib only.

## Standard Agent Workflow

Always follow this 4-step sequence against the user's target ZMK config directory (`TARGET_DIR`):

### 1. Inspect the Target Repository (Read-Only)

Run `inspect --json` first to discover the ZMK version, board/shield topology, and **3-tier pin collisions** (local overlays, upstream ZMK shield files, and built-in offline pin maps):

```bash
python3 scripts/zmk_joystick.py inspect --target "$TARGET_DIR" --json
```

*(Add `--offline` if running without network access.)*

Check the JSON output carefully:
- `zmk.west_yml.zmk_revision` & `zmk.workflow_ref`: If either is `main`, warn the user that ZMK `main` moved to Zephyr 4.1 HWMv2 (`nice_nano_v2` was renamed) and recommend `--pin-zmk v0.3`.
- `topology.is_split`: If `true`, confirm with the user whether the joystick is wired to the **central** half (`--mode split-central`) or **peripheral** half (`--mode split-peripheral`).
- `targets[*].available_adc_pins` & `colliding_adc_pins`:
  - Only 3 SAADC channels are broken out on `nice!nano v2`: **`AIN5` (`P0.29` / `029`)**, **`AIN7` (`P0.31` / `031`)**, and **`AIN0` (`P0.02` / `002`)**.
  - If `can_wire_2_axis_directly` is `false` on the target half (for example, a stock Corne claims all three for matrix columns), **stop and report the exact `colliding_adc_pins`** to the user before editing anything.
  - If `AIN5` or `AIN7` is busy but `AIN0` is free (leaving 2 free channels), pick the 2 free channels via `--x-adc` and `--y-adc`.

### 2. Preview Changes (`--dry-run --json`)

Before writing files, preview the exact unified diffs:

```bash
python3 scripts/zmk_joystick.py apply \
  --target "$TARGET_DIR" \
  --mode unibody \
  --x-adc 5 \
  --y-adc 7 \
  --scroll-layer 1 \
  --pin-zmk v0.3 \
  --dry-run \
  --json
```

For a split keyboard with the joystick on the **peripheral** half (e.g. `lily58_right`):

```bash
python3 scripts/zmk_joystick.py apply \
  --target "$TARGET_DIR" \
  --mode split-peripheral \
  --central-shield lily58_left \
  --peripheral-shield lily58_right \
  --x-adc 5 \
  --y-adc 7 \
  --scroll-layer 3 \
  --dry-run \
  --json
```

### 3. Apply Changes

Re-run the same `apply` command without `--dry-run`. The command is **idempotent** — running it again produces zero changes.

### 4. Validate the Result

Always run `validate --json` after applying:

```bash
python3 scripts/zmk_joystick.py validate --target "$TARGET_DIR" --json
```

Confirm `"ok": true` and `"errors": []`. If `--scroll-layer <N>` was enabled, remind the user (or offer) to ensure their `.keymap` has a binding such as `&mo <N>` to activate scroll mode.

## Hardware & Calibration Guardrails

- **Never** set `mv-mid = <512>` on a 3.3V `nice!nano v2`: `zmk-analog-input-driver` operates in **millivolts** (`0`–`3300 mV`), so centered sticks rest around `1650 mV` with `mv-min-max = <1600>`, `mv-deadzone = <60>`, and `scale-divisor = <80>`.
- **Never** wire an analog axis to Pro Micro `A0` (`115` / `P1.15`) or `A6`–`A10` on `nice!nano v2`: those pins are digital-only on nRF52840.
- **Do not** recommend `badjeff/analog-axis-hires-input-zephyr-module` for nRF52840's 12-bit internal SAADC (it allocates 32-bit `int32_t` buffers intended for 24-bit external ADCs).
- For scroll mode on macOS/Windows/Linux, start at `&zip_scroll_scaler 1 128` (smaller divisors like `1 16` scroll far too fast at `100 Hz`).
