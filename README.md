# zmk-joystick

[![Build ZMK firmware](https://github.com/FredForte/zmk-joystick/actions/workflows/build.yml/badge.svg)](https://github.com/FredForte/zmk-joystick/actions/workflows/build.yml)
[![Verify Add-on Shields & CLI](https://github.com/FredForte/zmk-joystick/actions/workflows/verify-addons.yml/badge.svg)](https://github.com/FredForte/zmk-joystick/actions/workflows/verify-addons.yml)

ZMK module and reference configuration for wiring a 2-axis analog thumbstick to a `nice!nano v2` (`nRF52840`) using [`badjeff/zmk-analog-input-driver`](https://github.com/badjeff/zmk-analog-input-driver).

It started as a personal test config and grew into a reusable module covering the annoying parts of nRF52840 analog setups: pin constraints on the `nice!nano v2`, the 60-second SAADC lockup caused by ZMK's stock battery driver (fixed here without forking ZMK), split-keyboard forwarding via `zmk,input-split`, layer-based scroll mode, and a zero-dependency Python CLI for checking pin collisions in existing ZMK repos.

## Hardware & Wiring

Requires a `nice!nano v2` and a 3.3V 2-axis potentiometer thumbstick (KY-023, PSP, Alps, etc.). Do not power the stick from 5V; nRF52840 ADC pins are 3.3V max.

All 5 wires land on the right-side header of the `nice!nano v2`:

| Joystick Pin | nice!nano v2 | nRF52840 | Pro Micro | Devicetree | Behavior |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `GND` | `GND` | | `GND` | Ground | Common ground (axes + `SW`) |
| `VCC` | `VCC` (3.3V) | | `VCC` | 3.3V rail | Potentiometer supply |
| `VRy` | `031` | `P0.31` | `D21` / `A3` | `<&adc 7>` (`AIN7`) | `INPUT_REL_Y` |
| `VRx` | `029` | `P0.29` | `D20` / `A2` | `<&adc 5>` (`AIN5`) | `INPUT_REL_X` |
| `SW` (optional) | `115` | `P1.15` | `D18` / `A0` | `<&pro_micro 18 (GPIO_ACTIVE_LOW \| GPIO_PULL_UP)>` | Tap: left click, Hold: scroll layer |

```text
          nice!nano v2 (USB-C at top)                  Joystick Module
      ┌───────────────────────────────┐
      │            [USB-C]            │
  006 │ o                           o │ RAW
  008 │ o                           o │ GND ─────────► GND
  GND │ o                           o │ RST
  GND │ o                           o │ VCC (3.3V) ──► VCC (+3.3V)
  017 │ o                           o │ 031 (AIN7) ──► VRy (Y-Axis)
  020 │ o                           o │ 029 (AIN5) ──► VRx (X-Axis)
  022 │ o                           o │ 002 (AIN0)     (free 3rd ADC pin)
  024 │ o                           o │ 115 (P1.15) ─► SW  (optional click)
  100 │ o                           o │ 113
  011 │ o                           o │ 111
  104 │ o                           o │ 010
  106 │ o                           o │ 009
      └───────────────────────────────┘
```

Note on Devicetree indexing: `io-channels = <&adc N>` takes the nRF52840 SAADC `AIN` number (`0`..`7`), not the GPIO number (`29`/`31`) and not the Pro Micro pin index (`20`/`21`).

## Why `P0.29` (`AIN5`) and `P0.31` (`AIN7`)

The nRF52840 has 8 SAADC channels (`AIN0`..`AIN7`), but only 3 are exposed on a `nice!nano v2`:

| SAADC | Specifier | GPIO | nice!nano v2 | Used here |
| :--- | :--- | :--- | :--- | :--- |
| `AIN0` | `<&adc 0>` | `P0.02` | `002` (`D19` / `A1`) | Free (3rd analog channel) |
| `AIN1` | `<&adc 1>` | `P0.03` | Not broken out | Internal SAADC slot 1 (`vbatt_no_os`) |
| `AIN2` | `<&adc 2>` | `P0.04` | Reserved internally | Do not use |
| `AIN3` | `<&adc 3>` | `P0.05` | Not broken out | Unavailable |
| `AIN4` | `<&adc 4>` | `P0.28` | Not broken out | Unavailable |
| `AIN5` | `<&adc 5>` | `P0.29` | `029` (`D20` / `A2`) | X-axis (`x-ch`) |
| `AIN6` | `<&adc 6>` | `P0.30` | Not broken out | Unavailable |
| `AIN7` | `<&adc 7>` | `P0.31` | `031` (`D21` / `A3`) | Y-axis (`y-ch`) |

Picking `029` and `031` keeps both analog lines right next to `VCC` and `GND` on the same header side, leaves `002` (`AIN0`) free for a third analog axis or existing matrix rows, and avoids the classic Pro Micro trap: pins labeled `A0` (`115`/`P1.15`) and `A6`..`A10` on an ATmega32U4 Pro Micro are digital-only on the nRF52840. That's why `115` is used for the digital `SW` button instead of an axis.

## The 60-Second SAADC Freeze (Zero-Fork Fix)

On stock ZMK, `nice!nano v2` uses `zmk,battery-nrf-vddh` (`&vbatt`) to poll battery voltage every 60 seconds with `adc_sequence.oversampling = 4`. The nRF52840 SAADC hardware does not allow oversampling with multi-channel scan mode (`AIN5` + `AIN7`), so the joystick stops responding right after the first battery poll.

Instead of maintaining a forked ZMK branch, this module bundles a small replacement driver at [`drivers/sensor/battery_nrf_vddh_no_os.c`](drivers/sensor/battery_nrf_vddh_no_os.c) (`compatible = "zmk,battery-nrf-vddh-no-os"`) that sets `.oversampling = 0` and uses SAADC slot 1 (`AIN1`, unexposed on `nice!nano v2`). The shields disable `&vbatt` and point `chosen { zmk,battery = &vbatt_no_os; };` to it, keeping Bluetooth battery reporting working on stock ZMK `v0.3`.

## Adding to an Existing ZMK Config

This repo can be imported directly as a ZMK module (`config/west.yml`) and combined with your existing keyboard shield in `build.yaml`, similar to `nice_view`. The add-on shields do not touch `kscan` or `keymap`.

| Setup | Shield(s) to add in `build.yaml` | Notes |
| :--- | :--- | :--- |
| Unibody or split (joystick on central) | `zmk_joystick_addon` on central/unibody | Adds `vbatt_no_os`, `&adc`, `&anin0`, `&joystick_listener` |
| Split (joystick on peripheral) | `zmk_joystick_peripheral` on peripheral, `zmk_joystick_central` on central | Peripheral forwards events via `zmk,input-split` (`reg = <0>`) to central's `&joystick_listener` |

### Option 1: Interactive CLI / AI Agent Script

[`scripts/zmk_joystick.py`](scripts/zmk_joystick.py) (Python 3 stdlib only, no `pip install`) inspects a target ZMK repo, checks for `nice!nano v2` ADC pin collisions across local overlays and upstream ZMK shields (Corne, Lily58, Sofle, Kyria, Sweep, etc.), patches `west.yml`/`build.yaml`/`.overlay`, and validates the result.

Run interactively inside your ZMK config directory:

```bash
curl -sSL https://raw.githubusercontent.com/FredForte/zmk-joystick/main/scripts/zmk_joystick.py | python3 - setup
```

For scripting or coding agents (see [`SKILL.md`](SKILL.md) for the agent workflow):

```bash
python3 scripts/zmk_joystick.py inspect --target /path/to/zmk-config --json
python3 scripts/zmk_joystick.py apply --target /path/to/zmk-config --mode split-peripheral --scroll-layer 3 --dry-run --json
python3 scripts/zmk_joystick.py validate --target /path/to/zmk-config --json
```

### Option 2: Manual Setup

1. Add both modules to `config/west.yml` (pin ZMK to `v0.3`, since `main` moved to Zephyr 4.1 HWMv2 and renamed `nice_nano_v2`):

```yaml
manifest:
  remotes:
    - name: zmkfirmware
      url-base: https://github.com/zmkfirmware
    - name: badjeff
      url-base: https://github.com/badjeff
    - name: fredforte
      url-base: https://github.com/FredForte
  projects:
    - name: zmk
      remote: zmkfirmware
      revision: v0.3
      import: app/west.yml
    - name: zmk-analog-input-driver
      remote: badjeff
      revision: main
    - name: zmk-joystick
      remote: fredforte
      revision: main
  self:
    path: config
```

2. Append the add-on shield(s) in `build.yaml`. Example for a split board with the joystick on the right (peripheral) half:

```yaml
include:
  - board: nice_nano_v2
    shield: lily58_left zmk_joystick_central
  - board: nice_nano_v2
    shield: lily58_right zmk_joystick_peripheral
```

3. Override any pins, calibration values, or scroll layers in your keyboard's `.overlay` using the exposed labels (`&x_ch`, `&y_ch`, `&anin0`, `&joystick_listener`). See [`boards/shields/zmk_joystick/zmk_joystick.overlay`](boards/shields/zmk_joystick/zmk_joystick.overlay) for a complete working example.

## Scroll Mode

The standalone `zmk_joystick` shield uses ZMK Input Processors on Layer 1 (`scroll_layer`):

- Tap `SW`: left click (`&mkp LCLK`)
- Hold `SW` (>= 200 ms) + move stick: vertical and horizontal scrolling (`&zip_xy_to_scroll_mapper`, `&zip_scroll_scaler 1 128`, `&zip_scroll_transform INPUT_TRANSFORM_Y_INVERT`)
- Double-tap and hold `SW`: hold left click for click-and-drag (`quick-tap-ms = <200>`)

On a full keyboard, bind any key to `&mo <layer>` and attach a `scroller` child node to `&joystick_listener` with `layers = <<layer>>;`. Increase the divisor in `&zip_scroll_scaler 1 128` (e.g. `1 180`) for slower scrolling, decrease it (e.g. `1 64`) for faster scrolling, or drop `INPUT_TRANSFORM_Y_INVERT` for natural scroll direction.

## Calibration

`zmk-analog-input-driver` converts raw SAADC samples into millivolts (`0`..`3300 mV` at 3.3V) and computes per sample:

```text
v = mv - mv-mid
v = 0 if |v| < mv-deadzone else sign(v) * (|v| - mv-deadzone)
v = clamp(v, -mv-min-max, +mv-min-max)
v = -v if invert
out = (v * scale-multiplier) / scale-divisor
```

Default values for a 3.3V thumbstick in [`zmk_joystick.overlay`](boards/shields/zmk_joystick/zmk_joystick.overlay):

| Property | Default | Meaning |
| :--- | :--- | :--- |
| `sampling-hz` | `100` | Polling rate in Hz |
| `mv-mid` | `1650` | Resting midpoint in mV (`~3.3V / 2`; do not use Arduino's `512`) |
| `mv-min-max` | `1600` | Full deflection swing (+/- mV) |
| `mv-deadzone` | `60` | Resting drift filter (+/- mV) |
| `scale-multiplier` / `scale-divisor` | `1` / `80` | Cursor speed scaling (higher divisor = slower cursor) |
| `invert` | set | Flips axis direction; remove on either axis to reverse |

To measure your stick's exact millivolt readings over USB serial:

1. Uncomment `snippet: zmk-usb-logging` in [`build.yaml`](build.yaml).
2. Uncomment `CONFIG_ANALOG_INPUT_LOG_DBG_RAW=y` and `CONFIG_ANALOG_INPUT_LOG_DBG_REPORT=y` in [`boards/shields/zmk_joystick/zmk_joystick.conf`](boards/shields/zmk_joystick/zmk_joystick.conf).
3. Flash, connect over USB, and open a serial monitor (`tio /dev/tty.usbmodem*` on macOS, `tio /dev/ttyACM0` on Linux).
4. Set `mv-mid` to the resting reading, `mv-deadzone` slightly above resting jitter, and adjust `scale-divisor` to taste. Re-comment the debug lines afterwards to save power.

## Building & Flashing (Standalone Shield)

**GitHub Actions:** Fork this repo, enable Actions, run the **Build ZMK firmware** workflow, download `firmware.zip`, and copy `zmk_joystick-nice_nano_v2-zmk.uf2` onto the `NICENANO` drive (double-tap Reset). Pre-built `.uf2` binaries are also attached to [Releases](https://github.com/FredForte/zmk-joystick/releases).

**Local build** (with a configured [ZMK toolchain](https://zmk.dev/docs/development/local-toolchain/setup)):

```bash
git clone https://github.com/FredForte/zmk-joystick.git
cd zmk-joystick
west init -l config && west update && west zephyr-export
west build -s zmk/app -b nice_nano_v2 -- -DSHIELD=zmk_joystick -DZMK_EXTRA_MODULES="$PWD"
```

## Troubleshooting

- **Runaway cursor at rest:** Usually caused by `mv-mid` not matching the resting voltage (e.g. `512` instead of `~1650`) or `mv-deadzone` being too small. Check raw mV over USB serial.
- **Inverted or swapped axes:** Add/remove `invert;` inside `x-ch`/`y-ch`, or swap `<&adc 5>` and `<&adc 7>`.
- **High wireless battery drain:** Continuous ADC polling draws more power than a switch matrix. Keep debug logs off outside calibration and lower `sampling-hz` (e.g. `50` or `60`).

## Credits & License

Built on [ZMK Firmware](https://github.com/zmkfirmware/zmk) and [`badjeff/zmk-analog-input-driver`](https://github.com/badjeff/zmk-analog-input-driver). Released under the [MIT License](LICENSE). See [CONTRIBUTING.md](CONTRIBUTING.md) for PR guidelines.
