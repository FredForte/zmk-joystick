# zmk-joystick

[![Build ZMK firmware](https://github.com/FredForte/zmk-joystick/actions/workflows/build.yml/badge.svg)](https://github.com/FredForte/zmk-joystick/actions/workflows/build.yml)
![MCU: nice!nano v2](https://img.shields.io/badge/MCU-nice!nano%20v2-blue)
![Firmware: ZMK](https://img.shields.io/badge/Firmware-ZMK-brightgreen)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A [ZMK Firmware](https://zmk.dev/) **reference implementation** for adding a 2-axis analog joystick (thumbstick) with push-button click to an **nRF52840 / `nice!nano v2`** controller using [`badjeff/zmk-analog-input-driver`](https://github.com/badjeff/zmk-analog-input-driver).

Out of the box, the shield reads two analog potentiometer axes over the nRF52840 SAADC peripheral (`INPUT_REL_X` / `INPUT_REL_Y`), uses the joystick's push button (`SW`) as **tap for left click / hold for scroll mode** via ZMK Input Processors (`&zip_xy_to_scroll_mapper`), and includes a **zero-fork fix for the known nRF52840 1-minute SAADC battery-polling freeze** while keeping Bluetooth battery percentage reporting active.

---

## Table of Contents

- [Quick Install Into Any ZMK Config (CLI & AI Agents)](#quick-install-into-any-zmk-config-cli--ai-agents)
- [Hardware Requirements](#hardware-requirements)
- [Wiring & Pinout](#wiring--pinout)
- [Why These Specific Pins (`P0.29` / `AIN5` and `P0.31` / `AIN7`)?](#why-these-specific-pins-p029--ain5-and-p031--ain7)
- [Fixing the 1-Minute nRF52840 SAADC Freeze (Zero-Fork)](#fixing-the-1-minute-nrf52840-saadc-freeze-zero-fork)
- [Composable Add-On Shields (Unibody & Split Keyboards)](#composable-add-on-shields-unibody--split-keyboards)
- [Adapting This Reference Manually](#adapting-this-reference-manually)
- [Scroll Mode (ZMK Input Processors)](#scroll-mode-zmk-input-processors)
- [Joystick Calibration & Tuning](#joystick-calibration--tuning)
- [Building & Flashing](#building--flashing)
- [Repository Structure](#repository-structure)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [Credits & License](#credits--license)

---

## Quick Install Into Any ZMK Config (CLI & AI Agents)

`zmk-joystick` ships composable add-on shields **plus** a zero-dependency Python 3 CLI ([`scripts/zmk_joystick.py`](scripts/zmk_joystick.py)) that automatically inspects your ZMK config, detects `nice!nano v2` SAADC pin collisions (including across upstream in-tree shields like Corne, Lily58, Sofle, Kyria, and Sweep), and configures unibody or split keyboards cleanly.

### For Humans (Interactive Wizard)

Run from inside your existing ZMK config repo (no clone or `pip install` needed):

```bash
curl -sSL https://raw.githubusercontent.com/FredForte/zmk-joystick/main/scripts/zmk_joystick.py | python3 - setup
```

### For AI Coding Agents (Antigravity, Claude Code, Cursor, Codex)

This repo includes a standard [`SKILL.md`](SKILL.md) and structured JSON commands (`inspect --json`, `apply --dry-run --json`, `apply --json`, `validate --json`). Tell your agent:

> *"Follow `https://github.com/FredForte/zmk-joystick/blob/main/SKILL.md` to inspect this ZMK config for pin conflicts and install `zmk-joystick`."*

```bash
# Non-interactive agent workflow:
python3 scripts/zmk_joystick.py inspect --target /path/to/zmk-config --json
python3 scripts/zmk_joystick.py apply --target /path/to/zmk-config --mode split-peripheral --scroll-layer 3 --dry-run --json
python3 scripts/zmk_joystick.py validate --target /path/to/zmk-config --json
```

---

## Hardware Requirements

| Component | Specification | Notes |
| :--- | :--- | :--- |
| **Microcontroller** | `nice!nano v2` (`nRF52840`) | 3.3V logic, Pro Micro footprint |
| **Analog Joystick** | 2-axis potentiometer thumbstick module (e.g., KY-023, PSP, Alps) | Must be powered at **3.3V** (never apply 5V to nRF52840 ADC pins); `SW` button pin is optional |
| **LiPo Battery** *(optional)* | 3.7V LiPo (`B+` / `B-`) | For wireless operation (see [battery drain note](#high-battery-drain-on-wireless-builds)) |

---

## Wiring & Pinout

All five connections of a standard 2-axis thumbstick module land cleanly on the **right-side header** of the `nice!nano v2`:

| Joystick Pin | nice!nano v2 Label | nRF52840 GPIO | Pro Micro Pin | Zephyr Devicetree Specifier | Function |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **GND** | `GND` | — | `GND` | Ground | Common ground (axes + `SW`) |
| **VCC** | `VCC` (`3.3V`) | — | `VCC` | 3.3V power rail | Potentiometer supply |
| **VRy (Y-Axis)** | `031` | `P0.31` | `D21` / `A3` | `io-channels = <&adc 7>;` (`AIN7`) | Vertical cursor movement (`INPUT_REL_Y`) |
| **VRx (X-Axis)** | `029` | `P0.29` | `D20` / `A2` | `io-channels = <&adc 5>;` (`AIN5`) | Horizontal cursor movement (`INPUT_REL_X`) |
| **SW (Click)** *(optional)* | `115` | `P1.15` | `D18` / `A0` | `<&pro_micro 18 (GPIO_ACTIVE_LOW \| GPIO_PULL_UP)>` | Tap: left click (`&mkp LCLK`) / Hold: scroll mode (`&mo 1`) |

```text
          nice!nano v2 (USB-C at top)                  Analog Joystick Module
      ┌───────────────────────────────┐
      │            [USB-C]            │
  006 │ o                           o │ RAW
  008 │ o                           o │ GND ─────────► GND
  GND │ o                           o │ RST
  GND │ o                           o │ VCC (3.3V) ──► VCC (+3.3V)
  017 │ o                           o │ 031 (AIN7) ──► VRy (Y-Axis)
  020 │ o                           o │ 029 (AIN5) ──► VRx (X-Axis)
  022 │ o                           o │ 002 (AIN0)     (free 3rd ADC pin)
  024 │ o                           o │ 115 (P1.15) ─► SW  (Click, optional)
  100 │ o                           o │ 113
  011 │ o                           o │ 111
  104 │ o                           o │ 010
  106 │ o                           o │ 009
      └───────────────────────────────┘
```

> [!IMPORTANT]
> In [`boards/shields/zmk_joystick/zmk_joystick.overlay`](boards/shields/zmk_joystick/zmk_joystick.overlay), `io-channels = <&adc N>` takes the **nRF52840 SAADC `AIN` channel number (`0`–`7`)** — **not** the GPIO pin number (`29`/`31`) and **not** the Pro Micro pin index (`20`/`21`). Using the wrong index is the most common mistake when configuring analog inputs in ZMK.

---

## Why These Specific Pins (`P0.29` / `AIN5` and `P0.31` / `AIN7`)?

Choosing analog pins on a `nice!nano v2` is more constrained than it looks at first glance. The Nordic **nRF52840** SoC has 8 Successive Approximation ADC (SAADC) channels (`AIN0`–`AIN7`), but **only 3 of them are usable on a `nice!nano v2`**:

| SAADC Channel | Devicetree Specifier | nRF52840 GPIO | nice!nano v2 Status | Assignment |
| :--- | :--- | :--- | :--- | :--- |
| `AIN0` | `<&adc 0>` | `P0.02` | Exposed on outer header (`002` / `D19` / `A1`) | Kept free (spare 3rd analog channel) |
| `AIN1` | `<&adc 1>` | `P0.03` | **Not broken out** on nice!nano v2 | Used internally as SAADC slot 1 by `vbatt_no_os` (`VDDHDIV5`) |
| `AIN2` | `<&adc 2>` | `P0.04` | **Not broken out / reserved internally** on nice!nano | **Do not use** |
| `AIN3` | `<&adc 3>` | `P0.05` | **Not broken out** on nice!nano v2 | Unavailable |
| `AIN4` | `<&adc 4>` | `P0.28` | **Not broken out** on nice!nano v2 | Unavailable |
| **`AIN5`** | **`<&adc 5>`** | **`P0.29`** | **Exposed on outer header (`029` / `D20` / `A2`)** | **X-Axis (`x-ch`)** |
| `AIN6` | `<&adc 6>` | `P0.30` | **Not broken out** on nice!nano v2 | Unavailable |
| **`AIN7`** | **`<&adc 7>`** | **`P0.31`** | **Exposed on outer header (`031` / `D21` / `A3`)** | **Y-Axis (`y-ch`)** |

### Key Reasons for Selecting These Pins

1. **All 5 joystick wires stay grouped on one header side**:
   On the right-hand header of the `nice!nano v2`, `GND`, `VCC`, `031` (`AIN7`), `029` (`AIN5`), and `115` (`P1.15`) sit right next to each other. Putting `VRy` on `031` and `VRx` on `029` places both analog lines directly adjacent to `VCC`, minimizing wire length, noise pickup, and routing clutter on breadboards or PCBs.
2. **Avoids the Pro Micro `A*` pinout trap**:
   On an ATmega32U4 Pro Micro, pins `D18`/`A0`, `D4`/`A6`, `D6`/`A7`, `D8`/`A8`, `D9`/`A9`, and `D10`/`A10` support analog input. On a `nice!nano v2`, those positions map to **digital-only** nRF52840 GPIOs (`P1.15`, `P0.22`, `P1.00`, `P1.04`, `P1.06`, `P0.09`). Wiring an analog axis to `A0` (`115`) will not produce ADC readings — which is why `115` is used here for the **digital `SW` push button** instead.
3. **Avoids internal / unexposed SAADC channels**:
   Four SAADC pins (`P0.03`, `P0.05`, `P0.28`, `P0.30`) are not broken out on the nice!nano v2, and `P0.04` (`AIN2`) is reserved internally (battery divider on v1; unexposed on v2, which reads `VDDHDIV5` internally).
4. **Preserves the 3rd exposed analog pin (`AIN0` / `P0.02`)**:
   By placing `SW` on digital pin `115` (`P1.15`) and the axes on `029`/`031`, `002` (`AIN0`) stays untouched in case you want to add a third analog input (e.g., potentiometer, Z-axis, or throttle) or reuse a standard keyboard matrix that already claims `D19`/`002`.

---

## Fixing the 1-Minute nRF52840 SAADC Freeze (Zero-Fork)

A well-known issue when using analog joysticks on a `nice!nano v2` with stock ZMK is that **the joystick stops responding after ~60 seconds**.

- **Root cause:** ZMK's built-in `nice!nano v2` battery driver (`zmk,battery-nrf-vddh`) polls the internal `VDDHDIV5` channel every 60 seconds with `adc_sequence.oversampling = 4`. The nRF52840 SAADC peripheral does **not** support oversampling alongside multi-channel scan mode (`AIN5` + `AIN7`), so the first battery poll locks up the ADC.
- **How this repository solves it (without forking ZMK):** This repo ships a self-contained Zephyr sensor driver module ([`drivers/sensor/battery_nrf_vddh_no_os.c`](drivers/sensor/battery_nrf_vddh_no_os.c)) with `compatible = "zmk,battery-nrf-vddh-no-os"` that:
  1. Sets `.oversampling = 0` so battery polling coexists safely with multi-channel analog joystick reads.
  2. Uses SAADC slot `1` (`AIN1`, which is unexposed on `nice!nano v2`) so it never collides with external analog inputs (`AIN0`, `AIN5`, `AIN7`).
- In [`boards/shields/zmk_joystick/zmk_joystick.overlay`](boards/shields/zmk_joystick/zmk_joystick.overlay), stock `&vbatt` is disabled and `chosen { zmk,battery = &vbatt_no_os; };` points ZMK to the oversampling-free driver — **keeping full Bluetooth battery percentage reporting active on stock upstream ZMK `v0.3`**.

---

## Composable Add-On Shields (Unibody & Split Keyboards)

In addition to the standalone `zmk_joystick` reference shield, this module ships three **composable add-on shields** (like ZMK's `nice_view`) that never touch your existing `kscan` or `keymap` and automatically include the zero-fork `vbatt_no_os` battery fix:

| Keyboard Setup | Shield(s) to Append in `build.yaml` | How It Works |
| :--- | :--- | :--- |
| **Unibody** or **Split (joystick on central half)** | `zmk_joystick_addon` on the central/unibody target | Adds `vbatt_no_os`, `&adc`, `&anin0`, and `&joystick_listener` directly on that board |
| **Split (joystick on peripheral half)** | `zmk_joystick_peripheral` on peripheral + `zmk_joystick_central` on central | Peripheral reads `&anin0` and forwards events over BLE via `zmk,input-split` (`reg = <0>`); central receives them into `&joystick_listener` so layer-based scroll mode works seamlessly |

Example `build.yaml` for a split keyboard with the joystick wired to the **right (peripheral)** half:

```yaml
include:
  - board: nice_nano_v2
    shield: lily58_left zmk_joystick_central
  - board: nice_nano_v2
    shield: lily58_right zmk_joystick_peripheral
```

All add-on shields expose Devicetree labels (`&x_ch`, `&y_ch`, `&anin0`, `&joystick_listener`) so you can override any pin, calibration value, or scroll layer in a few lines inside your keyboard's `.overlay` without duplicating boilerplate.

---

## Adapting This Reference Manually

To add a 2-axis analog joystick (plus the zero-fork battery fix) to your own ZMK repository, copy these four pieces:

### 1. Add the Modules to `config/west.yml`

Include `badjeff/zmk-analog-input-driver` (and optionally `FredForte/zmk-joystick` if you want to reuse the `zmk,battery-nrf-vddh-no-os` driver directly in your own repo):

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
    # Optional: import this repo to use zmk,battery-nrf-vddh-no-os without forking ZMK
    - name: zmk-joystick
      remote: fredforte
      revision: main
  self:
    path: config
```

### 2. Enable ADC, Pointing, and the Analog Driver in Your `.conf`

See [`boards/shields/zmk_joystick/zmk_joystick.conf`](boards/shields/zmk_joystick/zmk_joystick.conf):

```ini
CONFIG_ADC=y
CONFIG_ADC_ASYNC=y
CONFIG_ZMK_POINTING=y
CONFIG_ANALOG_INPUT=y
```

### 3. Add the No-Oversampling Battery Sensor, ADC, Analog Input, and Listener to Your `.overlay`

See [`boards/shields/zmk_joystick/zmk_joystick.overlay`](boards/shields/zmk_joystick/zmk_joystick.overlay):

```dts
#include <zephyr/dt-bindings/input/input-event-codes.h>
#include <dt-bindings/zmk/input_transform.h>
#include <input/processors.dtsi>

/ {
    chosen {
        zmk,battery = &vbatt_no_os;
    };

    vbatt_no_os: vbatt_no_os {
        compatible = "zmk,battery-nrf-vddh-no-os";
    };
};

&vbatt {
    status = "disabled";
};

&adc {
    status = "okay";
};

/ {
    anin0: analog_input_0 {
        compatible = "zmk,analog-input";
        sampling-hz = <100>;
        x-ch {
            io-channels = <&adc 5>; /* nice!nano v2 pin 029 (P0.29 / AIN5) */
            mv-mid = <1650>;        /* ~3.3V / 2 resting midpoint in millivolts */
            mv-min-max = <1600>;    /* full-scale +/- deflection in millivolts */
            mv-deadzone = <60>;     /* ignore +/-60 mV resting drift/jitter */
            scale-multiplier = <1>;
            scale-divisor = <80>;   /* scale mV to smooth cursor steps */
            invert;
            evt-type = <INPUT_EV_REL>;
            input-code = <INPUT_REL_X>;
        };
        y-ch {
            io-channels = <&adc 7>; /* nice!nano v2 pin 031 (P0.31 / AIN7) */
            mv-mid = <1650>;        /* ~3.3V / 2 resting midpoint in millivolts */
            mv-min-max = <1600>;    /* full-scale +/- deflection in millivolts */
            mv-deadzone = <60>;     /* ignore +/-60 mV resting drift/jitter */
            scale-multiplier = <1>;
            scale-divisor = <80>;   /* scale mV to smooth cursor steps */
            invert;
            evt-type = <INPUT_EV_REL>;
            input-code = <INPUT_REL_Y>;
        };
    };

    joystick_listener {
        compatible = "zmk,input-listener";
        device = <&anin0>;

        scroller {
            layers = <1>;
            input-processors
                = <&zip_xy_to_scroll_mapper>
                , <&zip_scroll_scaler 1 128>
                , <&zip_scroll_transform INPUT_TRANSFORM_Y_INVERT>
                ;
        };
    };
};
```

### 4. Register Your Board & Shield in `build.yaml`

See [`build.yaml`](build.yaml):

```yaml
include:
  - board: nice_nano_v2
    shield: zmk_joystick
```

---

## Scroll Mode (ZMK Input Processors)

This reference demonstrates ZMK's layer-aware **Input Processors** to turn the same joystick into a vertical/horizontal scroll wheel while a modifier key is held:

- **Tap `SW`** → Left mouse click (`&mkp LCLK`)
- **Hold `SW` (`≥ 200 ms`) + move joystick** → Activates Layer 1 (`scroll_layer`), switching the joystick from pointer movement to scrolling
- **Double-tap & hold `SW`** → Holds left click for click-and-drag (`quick-tap-ms = <200>`)

On a full keyboard, you don't need to use `SW` — bind any modifier key to `&mo 1` (or change `layers = <1>;` in [`zmk_joystick.overlay`](boards/shields/zmk_joystick/zmk_joystick.overlay) to match your preferred layer index).

### Tuning Scroll Behavior

Inside the `scroller` block of [`zmk_joystick.overlay`](boards/shields/zmk_joystick/zmk_joystick.overlay):

- **Scroll speed**: Adjust `&zip_scroll_scaler 1 128` — increase the second number (e.g. `1 180`) to scroll slower, or decrease it (e.g. `1 64`) to scroll faster.
- **Scroll direction**: Remove `, <&zip_scroll_transform INPUT_TRANSFORM_Y_INVERT>` if you prefer inverted ("natural") vertical scrolling, or swap it for `INPUT_TRANSFORM_X_INVERT` to flip horizontal scroll.

---

## Joystick Calibration & Tuning

Every thumbstick module has slightly different resting voltages and deflection ranges. All axis parameters live in [`boards/shields/zmk_joystick/zmk_joystick.overlay`](boards/shields/zmk_joystick/zmk_joystick.overlay).

> [!TIP]
> On a `3.3V` (`3300 mV`) `nice!nano v2`, the driver converts raw nRF52840 SAADC readings directly into **millivolts (`0`–`3300 mV`)**, so a centered potentiometer thumbstick rests near **`1650 mV`** (not `512`). For each sample, the driver computes:
> 1. `v = mv - mv-mid`
> 2. Subtracts `mv-deadzone` (values within `±mv-deadzone` become `0`)
> 3. Clamps `v` to `±mv-min-max`
> 4. Negates `v` if `invert;` is set
> 5. Scales to cursor pixels: `(v * scale-multiplier) / scale-divisor`

### Parameter Reference

| Property | Description |
| :--- | :--- |
| `sampling-hz` | Polling frequency in Hz (default `100`). Lowering this reduces power draw. |
| `io-channels` | nRF52840 SAADC channel (`<&adc 5>` for `P0.29`, `<&adc 7>` for `P0.31`). |
| `mv-mid` | Resting center voltage in millivolts (`mV`) when the stick is untouched. |
| `mv-min-max` | Expected voltage swing (`±mV`) from `mv-mid` to full stick deflection. |
| `mv-deadzone` | Deadzone radius (`±mV`) around `mv-mid` ignored to eliminate resting drift/jitter. |
| `scale-multiplier` / `scale-divisor` | Fractional speed scaling applied to output movement (`output × multiplier / divisor`). |
| `invert` | Reverses axis direction. Remove this line on an axis to flip it back. |
| `evt-type` & `input-code` | HID event type (`INPUT_EV_REL`) and axis (`INPUT_REL_X` / `INPUT_REL_Y`). Can also use `INPUT_REL_WHEEL` / `INPUT_REL_HWHEEL` for scrolling. |
| `report-on-change-only` | *(Optional, omitted by default)* Only emits reports when the quantized value changes — useful for gamepads/knobs, not continuous mouse cursor movement. |

### Calibrating with USB Debug Logs

Debug logging is disabled by default to save power. To calibrate a new joystick module:

1. Uncomment `snippet: zmk-usb-logging` in [`build.yaml`](build.yaml):
   ```yaml
   include:
     - board: nice_nano_v2
       shield: zmk_joystick
       snippet: zmk-usb-logging
   ```
2. Uncomment the analog debug logging options in [`boards/shields/zmk_joystick/zmk_joystick.conf`](boards/shields/zmk_joystick/zmk_joystick.conf):
   ```ini
   CONFIG_ANALOG_INPUT_LOG_DBG_RAW=y
   CONFIG_ANALOG_INPUT_LOG_DBG_REPORT=y
   ```
3. Build and flash the firmware, connect over USB, and open the serial console (e.g., `tio /dev/tty.usbmodem*` on macOS or `tio /dev/ttyACM0` on Linux).
4. Record the logged millivolt (`mV`) readings for both axes:
   - **Stick at rest (centered)** → set as `mv-mid`.
   - **Resting jitter around center** → set `mv-deadzone` slightly larger than the observed jitter.
   - **Full deflection** → measure `|max_mv - mv-mid|` and tune `mv-min-max`, `scale-multiplier`, and `scale-divisor` to taste.
5. Re-comment the debug logging lines in `build.yaml` and `zmk_joystick.conf` once calibrated, then rebuild and flash.

---

## Building & Flashing

### Option A: GitHub Actions (Recommended)

1. **Fork this repository** on GitHub.
2. Open the **Actions** tab in your fork and enable workflows if prompted.
3. Trigger the **Build ZMK firmware** workflow (via **Run workflow** or by pushing a commit).
4. Download the `firmware` artifact (`.zip`) from the completed run and extract `zmk_joystick-nice_nano_v2-zmk.uf2`.
5. Connect the `nice!nano v2` over USB-C and double-tap Reset (or bridge `RST` and `GND` twice) to mount the `NICENANO` drive.
6. Copy `zmk_joystick-nice_nano_v2-zmk.uf2` onto the `NICENANO` drive; the board reboots automatically and advertises as **`ZMK Joystick`**.

### Option B: Local Build

With a configured [ZMK / Zephyr local toolchain](https://zmk.dev/docs/development/local-toolchain/setup):

```bash
git clone https://github.com/FredForte/zmk-joystick.git
cd zmk-joystick

west init -l config
west update
west zephyr-export

west build -s zmk/app -b nice_nano_v2 -- \
  -DSHIELD=zmk_joystick \
  -DZMK_EXTRA_MODULES="$PWD"
```

The compiled firmware is written to `build/zephyr/zmk.uf2`.

---

## Repository Structure

```text
.
├── .github/
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md                        # Bug report template
│   │   └── hardware_support.md                  # Hardware / module question template
│   ├── build-addons.yaml                        # CI matrix verifying unibody & split add-on shields
│   └── workflows/
│       ├── build.yml                            # ZMK GitHub Actions build workflow (standalone firmware)
│       └── verify-addons.yml                    # CI workflow verifying add-on shields + CLI unit tests
├── boards/shields/
│   ├── zmk_joystick/                            # Standalone reference shield (joystick + SW click/scroll)
│   ├── zmk_joystick_addon/                      # Composable add-on shield (unibody / split central)
│   ├── zmk_joystick_central/                    # Composable add-on shield (split central receiver)
│   └── zmk_joystick_peripheral/                 # Composable add-on shield (split peripheral sensor)
├── config/
│   └── west.yml                                 # West manifest (ZMK v0.3 + zmk-analog-input-driver)
├── drivers/sensor/
│   └── battery_nrf_vddh_no_os.c                 # Replacement VDDH battery driver (oversampling = 0)
├── dts/bindings/sensor/
│   └── zmk,battery-nrf-vddh-no-os.yaml          # Devicetree binding for the no-oversampling battery driver
├── scripts/
│   └── zmk_joystick.py                          # Dual-mode setup, pin-collision inspector & validator CLI
├── tests/
│   └── test_zmk_joystick_cli.py                 # Unit tests for scripts/zmk_joystick.py
├── zephyr/
│   └── module.yml                               # Registers this repo as a Zephyr module (boards, DTS, driver)
├── CMakeLists.txt                               # Builds the no-oversampling battery driver when enabled
├── Kconfig                                      # Kconfig option for ZMK_BATTERY_NRF_VDDH_NO_OS
├── SKILL.md                                     # AI agent skill instructions (inspect -> apply -> validate)
├── build.yaml                                   # Standalone firmware build matrix
├── CONTRIBUTING.md                              # Contribution guidelines
├── LICENSE                                      # MIT License
└── README.md                                    # Documentation & pinout reference
```

---

## Troubleshooting

### Analog input stops responding after ~1 minute on nRF52840

This repository **already fixes this out of the box** via [`drivers/sensor/battery_nrf_vddh_no_os.c`](drivers/sensor/battery_nrf_vddh_no_os.c) (see [Fixing the 1-Minute nRF52840 SAADC Freeze](#fixing-the-1-minute-nrf52840-saadc-freeze-zero-fork)).

If you hit this in a separate ZMK repo where you haven't included the `zmk,battery-nrf-vddh-no-os` driver yet, you can either:
- Import `FredForte/zmk-joystick` in `config/west.yml` and swap `&vbatt` to `zmk,battery-nrf-vddh-no-os` (recommended — keeps BLE battery % reporting with zero ZMK fork), **or**
- Disable battery reporting entirely (`CONFIG_ZMK_BATTERY_REPORTING=n` + `&vbatt { status = "disabled"; };`).

### Cursor drifts when the joystick is untouched

- Enable USB logging (see [Calibration](#calibrating-with-usb-debug-logs)) and check whether the resting voltage matches `mv-mid`.
- Increase `mv-deadzone` in `zmk_joystick.overlay` until resting jitter is completely filtered out.

### Axes are inverted or swapped

- **Direction is reversed**: add or remove `invert;` inside `x-ch` or `y-ch`.
- **X and Y are swapped**: swap `io-channels = <&adc 5>;` and `io-channels = <&adc 7>;` between `x-ch` and `y-ch`.

### High battery drain on wireless builds

Continuous ADC polling draws noticeably more current than a passive switch matrix:

- Keep `CONFIG_ANALOG_INPUT_LOG_DBG_*` disabled outside calibration.
- Lower `sampling-hz` (e.g., from `100` to `50` or `60`).
- Use a larger LiPo battery or power-switch the joystick module when using the keyboard purely for typing.

---

## Contributing

Contributions — especially calibration profiles for common thumbsticks, pinout notes for other nRF52840 boards, and documentation improvements — are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) to get started.

---

## Credits & License

- Built on [ZMK Firmware](https://github.com/zmkfirmware/zmk).
- Analog thumbstick driver by [`badjeff/zmk-analog-input-driver`](https://github.com/badjeff/zmk-analog-input-driver).
- Released under the [MIT License](LICENSE).
