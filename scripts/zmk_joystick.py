#!/usr/bin/env python3
"""
zmk-joystick dual-mode setup, inspection, and validation CLI.

Designed for both interactive human setup and structured AI-agent automation
(zero external dependencies — Python 3.9+ standard library only).

Subcommands:
  inspect   Analyze a target ZMK config repo (boards, shields, ZMK version,
            pin collisions across local & upstream in-tree shields).
  apply     Idempotently add zmk-joystick (unibody, split-central, or
            split-peripheral) to a target ZMK config repo. Supports --dry-run.
  validate  Run static health checks on a configured ZMK config repo.
  setup     Interactive terminal wizard combining inspect -> apply -> validate.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Hardware & Pinout Knowledge Base (nice!nano v2 / nRF52840)
# ---------------------------------------------------------------------------

# Official ZMK arduino_pro_micro_pins.dtsi mapping for nice!nano v2
PRO_MICRO_TO_GPIO: dict[int, str] = {
    0: "P0.08",
    1: "P0.06",
    2: "P0.17",
    3: "P0.20",
    4: "P0.22",
    5: "P0.24",
    6: "P1.00",
    7: "P0.11",
    8: "P1.04",
    9: "P1.06",
    10: "P0.09",
    14: "P1.11",
    15: "P1.13",
    16: "P0.10",
    18: "P1.15",
    19: "P0.02",
    20: "P0.29",
    21: "P0.31",
}

# pro_micro_a indices (A0..A10)
PRO_MICRO_A_TO_GPIO: dict[int, str] = {
    0: "P1.15",
    1: "P0.02",
    2: "P0.29",
    3: "P0.31",
    6: "P0.22",
    7: "P1.00",
    8: "P1.04",
    9: "P1.06",
    10: "P0.09",
}

GPIO_TO_PRO_MICRO: dict[str, int] = {v: k for k, v in PRO_MICRO_TO_GPIO.items()}

# All 8 nRF52840 SAADC channels
NRF52840_AIN_TO_GPIO: dict[int, str] = {
    0: "P0.02",
    1: "P0.03",
    2: "P0.04",
    3: "P0.05",
    4: "P0.28",
    5: "P0.29",
    6: "P0.30",
    7: "P0.31",
}

GPIO_TO_AIN: dict[str, int] = {v: k for k, v in NRF52840_AIN_TO_GPIO.items()}

# Only these 3 SAADC channels are broken out and usable on nice!nano v2
NICE_NANO_V2_USABLE_AINS: list[int] = [5, 7, 0]  # Preferred order: AIN5 (029), AIN7 (031), AIN0 (002)

NICE_NANO_PIN_LABELS: dict[str, str] = {
    "P0.29": "029 (Pro Micro D20/A2, AIN5)",
    "P0.31": "031 (Pro Micro D21/A3, AIN7)",
    "P0.02": "002 (Pro Micro D19/A1, AIN0)",
    "P1.15": "115 (Pro Micro D18/A0, digital-only)",
}

# Offline fallback pin maps (pro_micro indices) for popular in-tree ZMK shields.
# Used when neither local zmk/ nor GitHub network access is available.
KNOWN_IN_TREE_SHIELD_PRO_MICRO_PINS: dict[str, dict[str, list[int]]] = {
    "corne": {
        "shared": [4, 5, 6, 7],  # rows
        "left": [21, 20, 19, 18, 15, 14],  # cols
        "right": [14, 15, 18, 19, 20, 21],
    },
    "crkbd": {
        "shared": [4, 5, 6, 7],
        "left": [21, 20, 19, 18, 15, 14],
        "right": [14, 15, 18, 19, 20, 21],
    },
    "lily58": {
        "shared": [5, 6, 7, 8, 9],
        "left": [19, 18, 15, 14, 16, 10],
        "right": [10, 16, 14, 15, 18, 19],
    },
    "sofle": {
        "shared": [5, 6, 7, 8, 9],
        "left": [19, 18, 15, 14, 16, 10, 21, 20],  # cols + encoder
        "right": [10, 16, 14, 15, 18, 19, 20, 21],
    },
    "kyria": {
        "shared": [10, 16, 14, 15],
        "left": [21, 20, 19, 18, 9, 8, 7, 6],
        "right": [6, 7, 8, 9, 18, 19, 20, 21],
    },
    "reviung41": {
        "shared": [21, 20, 19, 18, 15, 14, 4, 5, 6, 7, 8, 9, 16],
    },
    "sweep": {
        "shared": [1, 0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 14, 15, 16, 18, 19, 20],
    },
    "ferris": {
        "shared": [1, 0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 14, 15, 16, 18, 19, 20],
    },
    "microdox": {
        "shared": [4, 5, 6, 7, 21, 20, 19, 18, 15],
    },
    "splitkb_aurora_corne": {
        "shared": [4, 5, 6, 7],
        "left": [21, 20, 19, 18, 15, 14],
        "right": [14, 15, 18, 19, 20, 21],
    },
    "splitkb_aurora_lily58": {
        "shared": [5, 6, 7, 8, 9],
        "left": [19, 18, 15, 14, 16, 10],
        "right": [10, 16, 14, 15, 18, 19],
    },
    "splitkb_aurora_sofle": {
        "shared": [5, 6, 7, 8, 9],
        "left": [19, 18, 15, 14, 16, 10, 21, 20],
        "right": [10, 16, 14, 15, 18, 19, 20, 21],
    },
    "splitkb_aurora_sweep": {
        "shared": [1, 0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 14, 15, 16, 18, 19, 20],
    },
}

JOYSTICK_SHIELD_NAMES = {
    "zmk_joystick",
    "zmk_joystick_addon",
    "zmk_joystick_central",
    "zmk_joystick_peripheral",
}

OVERLAY_BEGIN_MARKER = "/* BEGIN zmk-joystick */"
OVERLAY_END_MARKER = "/* END zmk-joystick */"

# ---------------------------------------------------------------------------
# ANSI Helpers
# ---------------------------------------------------------------------------


def _use_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def c_bold(s: str) -> str:
    return f"\033[1m{s}\033[0m" if _use_color() else s


def c_green(s: str) -> str:
    return f"\033[32m{s}\033[0m" if _use_color() else s


def c_yellow(s: str) -> str:
    return f"\033[33m{s}\033[0m" if _use_color() else s


def c_red(s: str) -> str:
    return f"\033[31m{s}\033[0m" if _use_color() else s


def c_cyan(s: str) -> str:
    return f"\033[36m{s}\033[0m" if _use_color() else s


# ---------------------------------------------------------------------------
# Lightweight Parsers (Zero External Dependencies)
# ---------------------------------------------------------------------------


def strip_dts_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def parse_build_yaml(path: Path) -> list[dict[str, str]]:
    """Parse ZMK build.yaml `include:` list entries using stdlib only."""
    if not path.exists():
        return []
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    in_include = False

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = re.sub(r"#.*$", "", raw_line).rstrip()
        if not line.strip():
            continue
        if re.match(r"^include\s*:\s*$", line):
            in_include = True
            continue
        if re.match(r"^\S", line) and not line.startswith("-"):
            in_include = False
            continue
        if not in_include:
            continue

        m_item = re.match(r"^\s*-\s+([A-Za-z0-9_-]+)\s*:\s*(.*)$", line)
        if m_item:
            if current:
                entries.append(current)
            val = m_item.group(2).strip().strip('"').strip("'")
            current = {m_item.group(1): val}
            continue

        m_kv = re.match(r"^\s+([A-Za-z0-9_-]+)\s*:\s*(.*)$", line)
        if m_kv and current is not None:
            val = m_kv.group(2).strip().strip('"').strip("'")
            current[m_kv.group(1)] = val

    if current:
        entries.append(current)
    return entries


def parse_west_yml(path: Path) -> dict[str, Any]:
    """Extract remotes and projects from config/west.yml using stdlib only."""
    result: dict[str, Any] = {
        "exists": path.exists(),
        "remotes": [],
        "projects": [],
        "zmk_revision": None,
        "has_analog_input_driver": False,
        "has_zmk_joystick": False,
    }
    if not path.exists():
        return result

    section: str | None = None
    current: dict[str, str] | None = None

    def flush() -> None:
        nonlocal current
        if current and section in ("remotes", "projects"):
            result[section].append(current)
        current = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = re.sub(r"#.*$", "", raw_line).rstrip()
        if not line.strip():
            continue
        m_sec = re.match(r"^\s{2}(remotes|projects|self)\s*:\s*$", line)
        if m_sec:
            flush()
            section = m_sec.group(1)
            continue
        if section not in ("remotes", "projects"):
            continue

        m_item = re.match(r"^\s*-\s+([A-Za-z0-9_-]+)\s*:\s*(.*)$", line)
        if m_item:
            flush()
            current = {m_item.group(1): m_item.group(2).strip().strip('"').strip("'")}
            continue

        m_kv = re.match(r"^\s+([A-Za-z0-9_-]+)\s*:\s*(.*)$", line)
        if m_kv and current is not None:
            current[m_kv.group(1)] = m_kv.group(2).strip().strip('"').strip("'")

    flush()

    for proj in result["projects"]:
        name = proj.get("name", "")
        if name == "zmk":
            result["zmk_revision"] = proj.get("revision")
        elif name == "zmk-analog-input-driver":
            result["has_analog_input_driver"] = True
        elif name == "zmk-joystick":
            result["has_zmk_joystick"] = True

    return result


def parse_workflow_zmk_ref(target: Path) -> str | None:
    wf_dir = target / ".github" / "workflows"
    if not wf_dir.is_dir():
        return None
    for wf in sorted(wf_dir.glob("*.y*ml")):
        text = wf.read_text(encoding="utf-8", errors="ignore")
        m = re.search(
            r"zmkfirmware/zmk/\.github/workflows/build-user-config\.yml@([^\s\"']+)",
            text,
        )
        if m:
            return m.group(1)
    return None


def extract_pins_from_dts(text: str, source: str) -> list[dict[str, Any]]:
    """Extract all nRF52840 GPIOs / Pro Micro / ADC references from DTS text."""
    clean = strip_dts_comments(text)
    found: dict[str, dict[str, Any]] = {}

    def record(gpio: str, ref: str, is_adc: bool = False) -> None:
        ain = GPIO_TO_AIN.get(gpio)
        pm = GPIO_TO_PRO_MICRO.get(gpio)
        if gpio not in found:
            found[gpio] = {
                "gpio": gpio,
                "pro_micro": pm,
                "ain": ain,
                "refs": [ref],
                "sources": [source],
                "is_adc_ref": is_adc,
            }
        else:
            if ref not in found[gpio]["refs"]:
                found[gpio]["refs"].append(ref)
            if source not in found[gpio]["sources"]:
                found[gpio]["sources"].append(source)
            found[gpio]["is_adc_ref"] = found[gpio]["is_adc_ref"] or is_adc

    for m in re.finditer(r"&pro_micro(?:_d)?\s+(\d+)", clean):
        idx = int(m.group(1))
        if idx in PRO_MICRO_TO_GPIO:
            record(PRO_MICRO_TO_GPIO[idx], f"&pro_micro {idx}")

    for m in re.finditer(r"&pro_micro_a\s+(\d+)", clean):
        idx = int(m.group(1))
        if idx in PRO_MICRO_A_TO_GPIO:
            record(PRO_MICRO_A_TO_GPIO[idx], f"&pro_micro_a {idx}")

    for m in re.finditer(r"&gpio([01])\s+(\d+)", clean):
        port, pin = int(m.group(1)), int(m.group(2))
        gpio = f"P{port}.{pin:02d}"
        record(gpio, f"&gpio{port} {pin}")

    for m in re.finditer(r"&adc\s+(\d+)", clean):
        ain = int(m.group(1))
        if ain in NRF52840_AIN_TO_GPIO:
            record(NRF52840_AIN_TO_GPIO[ain], f"&adc {ain}", is_adc=True)

    return list(found.values())


# ---------------------------------------------------------------------------
# 3-Tier Pin Resolution (Local -> Upstream ZMK -> Built-in Offline Fallback)
# ---------------------------------------------------------------------------


def split_shield_base_and_side(shield_token: str) -> tuple[str, str | None]:
    for suffix, side in (
        ("_left", "left"),
        ("_right", "right"),
        ("_central", "left"),
        ("_peripheral", "right"),
    ):
        if shield_token.endswith(suffix):
            return shield_token[: -len(suffix)], side
    return shield_token, None


def _fetch_url(url: str, timeout: float = 4.0) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "zmk-joystick-cli/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return resp.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    return None


def resolve_shield_pins(
    target: Path,
    shield_tokens: list[str],
    zmk_rev: str | None,
    offline: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Resolve all pins used by a build entry's shield list across 3 tiers:
      1. Local target repo files (config/ and boards/shields/)
      2. Upstream ZMK shield definitions (local zmk/ dir or GitHub raw fetch)
      3. Offline fallback table for popular Pro Micro ZMK shields
    Returns (pins_list, resolution_notes).
    """
    merged: dict[str, dict[str, Any]] = {}
    notes: list[str] = []

    def merge_pins(pins: list[dict[str, Any]]) -> None:
        for p in pins:
            gpio = p["gpio"]
            if gpio not in merged:
                merged[gpio] = {
                    "gpio": gpio,
                    "pro_micro": p["pro_micro"],
                    "ain": p["ain"],
                    "refs": list(p["refs"]),
                    "sources": list(p["sources"]),
                    "is_adc_ref": p["is_adc_ref"],
                }
            else:
                for r in p["refs"]:
                    if r not in merged[gpio]["refs"]:
                        merged[gpio]["refs"].append(r)
                for s in p["sources"]:
                    if s not in merged[gpio]["sources"]:
                        merged[gpio]["sources"].append(s)
                merged[gpio]["is_adc_ref"] = merged[gpio]["is_adc_ref"] or p["is_adc_ref"]

    # Tier 1: Local overlays/dtsi matching any shield token (or base name)
    local_candidate_dirs = [target / "config", target / "boards" / "shields"]
    locally_defined_shields: set[str] = set()

    for token in shield_tokens:
        if token in JOYSTICK_SHIELD_NAMES or token in ("settings_reset",):
            continue
        base, _ = split_shield_base_and_side(token)
        matched_local = False
        for root in local_candidate_dirs:
            if not root.exists():
                continue
            for ext in ("*.overlay", "*.dtsi", "*.dts"):
                for p in root.rglob(ext):
                    stem = p.stem
                    if stem in (token, base) or p.parent.name in (token, base):
                        matched_local = True
                        rel = str(p.relative_to(target))
                        merge_pins(extract_pins_from_dts(p.read_text(encoding="utf-8", errors="ignore"), f"local:{rel}"))
        if matched_local:
            locally_defined_shields.add(token)

    # Tier 2 & 3: In-tree upstream shields
    rev = zmk_rev or "v0.3"
    for token in shield_tokens:
        if token in JOYSTICK_SHIELD_NAMES or token in ("settings_reset", "nice_view_adapter", "nice_view"):
            continue
        base, side = split_shield_base_and_side(token)
        # Check if defined locally under boards/shields/<base>
        if (target / "boards" / "shields" / base).is_dir() or (target / "boards" / "shields" / token).is_dir():
            continue

        resolved_upstream = False

        # Tier 2a: Local west zmk/ checkout
        local_zmk_shield = target / "zmk" / "app" / "boards" / "shields" / base
        if local_zmk_shield.is_dir():
            for fname in (f"{base}.dtsi", f"{token}.overlay", f"{base}.overlay"):
                fp = local_zmk_shield / fname
                if fp.exists():
                    merge_pins(extract_pins_from_dts(fp.read_text(encoding="utf-8", errors="ignore"), f"zmk-local:{fname}"))
                    resolved_upstream = True

        # Tier 2b: Upstream GitHub fetch
        if not resolved_upstream and not offline:
            candidates = [f"{base}.dtsi", f"{token}.overlay"]
            if base == token:
                candidates.append(f"{base}.overlay")
            for fname in dict.fromkeys(candidates):
                url = f"https://raw.githubusercontent.com/zmkfirmware/zmk/{rev}/app/boards/shields/{base}/{fname}"
                content = _fetch_url(url)
                if content:
                    merge_pins(extract_pins_from_dts(content, f"zmk-upstream@{rev}:{base}/{fname}"))
                    resolved_upstream = True

        # Tier 3: Built-in offline fallback table
        if not resolved_upstream and base in KNOWN_IN_TREE_SHIELD_PRO_MICRO_PINS:
            pin_map = KNOWN_IN_TREE_SHIELD_PRO_MICRO_PINS[base]
            pm_indices = list(pin_map.get("shared", []))
            if side and side in pin_map:
                pm_indices.extend(pin_map[side])
            fallback_pins = []
            for idx in sorted(set(pm_indices)):
                gpio = PRO_MICRO_TO_GPIO.get(idx)
                if gpio:
                    fallback_pins.append(
                        {
                            "gpio": gpio,
                            "pro_micro": idx,
                            "ain": GPIO_TO_AIN.get(gpio),
                            "refs": [f"&pro_micro {idx}"],
                            "sources": [f"builtin-table:{token}"],
                            "is_adc_ref": False,
                        }
                    )
            merge_pins(fallback_pins)
            resolved_upstream = True
            notes.append(f"Used built-in pin table for in-tree shield '{token}' (offline/fallback).")

        if not resolved_upstream and token not in locally_defined_shields:
            notes.append(
                f"Could not resolve upstream pins for shield '{token}'; verify manually that P0.29 (AIN5) and P0.31 (AIN7) are unused."
            )

    return sorted(merged.values(), key=lambda x: x["gpio"]), notes


# ---------------------------------------------------------------------------
# Core Inspection Engine
# ---------------------------------------------------------------------------


def inspect_repo(target: Path, offline: bool = False) -> dict[str, Any]:
    target = target.resolve()
    west_info = parse_west_yml(target / "config" / "west.yml")
    wf_ref = parse_workflow_zmk_ref(target)
    build_entries = parse_build_yaml(target / "build.yaml")

    blocking_issues: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    recommended_actions: list[str] = []

    if not target.is_dir():
        return {
            "ok": False,
            "error": f"Target directory does not exist: {target}",
        }

    if not west_info["exists"]:
        blocking_issues.append(
            {
                "code": "MISSING_WEST_YML",
                "message": "config/west.yml not found. Target does not appear to be a ZMK user-config repository.",
            }
        )

    zmk_rev = west_info["zmk_revision"]
    if zmk_rev == "main" or wf_ref == "main":
        warnings.append(
            {
                "code": "UNPINNED_ZMK_MAIN",
                "message": (
                    f"ZMK is tracking 'main' (west.yml={zmk_rev}, workflow={wf_ref}), which uses Zephyr 4.1 HWMv2 "
                    "where nice_nano_v2 was renamed to nice_nano. Pin to 'v0.3' (via --pin-zmk v0.3) for tested stability."
                ),
            }
        )
        recommended_actions.append("Pin ZMK to v0.3 in config/west.yml and .github/workflows/build.yml (--pin-zmk v0.3).")

    if not west_info["has_analog_input_driver"]:
        recommended_actions.append("Add badjeff/zmk-analog-input-driver to config/west.yml.")
    is_self_module = (target / "boards" / "shields" / "zmk_joystick_addon").is_dir()
    if not west_info["has_zmk_joystick"] and not is_self_module:
        recommended_actions.append("Add FredForte/zmk-joystick to config/west.yml.")

    analyzed_targets: list[dict[str, Any]] = []
    left_targets: list[str] = []
    right_targets: list[str] = []

    for idx, entry in enumerate(build_entries):
        board = entry.get("board", "")
        shield_str = entry.get("shield", "")
        tokens = [t for t in shield_str.split() if t]
        if "settings_reset" in tokens:
            continue

        base_tokens = [t for t in tokens if t not in JOYSTICK_SHIELD_NAMES and t not in ("nice_view_adapter", "nice_view")]
        primary = base_tokens[0] if base_tokens else (tokens[0] if tokens else "")
        _, side = split_shield_base_and_side(primary)
        if side == "left":
            left_targets.append(primary)
        elif side == "right":
            right_targets.append(primary)

        pins, notes = resolve_shield_pins(target, tokens, zmk_rev, offline=offline)
        non_adc_claimed_gpios = {p["gpio"] for p in pins if not p["is_adc_ref"]}

        available_ains: list[dict[str, Any]] = []
        colliding_ains: list[dict[str, Any]] = []
        for ain in NICE_NANO_V2_USABLE_AINS:
            gpio = NRF52840_AIN_TO_GPIO[ain]
            info = {
                "ain": ain,
                "gpio": gpio,
                "pro_micro": GPIO_TO_PRO_MICRO.get(gpio),
                "label": NICE_NANO_PIN_LABELS.get(gpio, gpio),
            }
            if gpio in non_adc_claimed_gpios:
                matching = next(p for p in pins if p["gpio"] == gpio)
                info["claimed_by"] = matching["sources"]
                colliding_ains.append(info)
            else:
                available_ains.append(info)

        is_nice_nano_v2 = board in ("nice_nano_v2", "nice_nano", "nice_nano//zmk")
        if board and not is_nice_nano_v2:
            warnings.append(
                {
                    "code": "NON_NICE_NANO_BOARD",
                    "message": f"Target #{idx} uses board '{board}'. zmk-joystick pinouts and vbatt_no_os target nice_nano_v2 (nRF52840).",
                }
            )

        analyzed_targets.append(
            {
                "index": idx,
                "board": board,
                "shield": shield_str,
                "primary_shield": primary,
                "side": side,
                "joystick_shields_present": [t for t in tokens if t in JOYSTICK_SHIELD_NAMES],
                "is_nice_nano": is_nice_nano_v2,
                "claimed_pins_count": len(pins),
                "available_adc_pins": available_ains,
                "colliding_adc_pins": colliding_ains,
                "can_wire_2_axis_directly": len(available_ains) >= 2,
                "notes": notes,
            }
        )

    is_split = bool(left_targets and right_targets)
    if is_split:
        suggested_mode = "split-central"
    else:
        suggested_mode = "unibody"

    if not analyzed_targets:
        blocking_issues.append(
            {
                "code": "NO_BUILD_TARGETS",
                "message": "No build targets found in build.yaml.",
            }
        )

    return {
        "ok": len(blocking_issues) == 0,
        "target": str(target),
        "zmk": {
            "west_yml": west_info,
            "workflow_ref": wf_ref,
        },
        "topology": {
            "is_split": is_split,
            "left_shields": left_targets,
            "right_shields": right_targets,
            "suggested_mode": suggested_mode,
        },
        "targets": analyzed_targets,
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "recommended_actions": recommended_actions,
    }


# ---------------------------------------------------------------------------
# Idempotent Patching Helpers (apply)
# ---------------------------------------------------------------------------


def patch_west_yml_text(text: str, pin_zmk: str | None = None) -> str:
    """Idempotently ensure badjeff & fredforte remotes + projects exist in west.yml."""
    lines = text.splitlines()

    if pin_zmk:
        # Replace `revision: ...` under the `name: zmk` project block
        out: list[str] = []
        in_zmk_proj = False
        for line in lines:
            if re.match(r"^\s*-\s+name:\s*zmk\s*$", line):
                in_zmk_proj = True
            elif re.match(r"^\s*-\s+name:", line) or re.match(r"^\s{2}self:", line):
                in_zmk_proj = False
            if in_zmk_proj and re.match(r"^(\s*)revision:\s*\S+", line):
                indent = re.match(r"^(\s*)", line).group(1)
                line = f"{indent}revision: {pin_zmk}"
            out.append(line)
        lines = out

    joined = "\n".join(lines)

    # Remotes to ensure
    remotes_to_add: list[tuple[str, str]] = []
    if not re.search(r"name:\s*badjeff\b", joined):
        remotes_to_add.append(("badjeff", "https://github.com/badjeff"))
    if not re.search(r"name:\s*fredforte\b", joined):
        remotes_to_add.append(("fredforte", "https://github.com/FredForte"))

    if remotes_to_add:
        new_lines: list[str] = []
        inserted = False
        for i, line in enumerate(lines):
            if not inserted and re.match(r"^\s{2}projects:\s*$", line):
                for rname, rurl in remotes_to_add:
                    new_lines.append(f"    - name: {rname}")
                    new_lines.append(f"      url-base: {rurl}")
                inserted = True
            new_lines.append(line)
        lines = new_lines

    joined = "\n".join(lines)
    projects_to_add: list[tuple[str, str, str]] = []
    if not re.search(r"name:\s*zmk-analog-input-driver\b", joined):
        projects_to_add.append(("zmk-analog-input-driver", "badjeff", "main"))
    if not re.search(r"name:\s*zmk-joystick\b", joined):
        projects_to_add.append(("zmk-joystick", "fredforte", "main"))

    if projects_to_add:
        new_lines = []
        inserted = False
        for line in lines:
            if not inserted and re.match(r"^\s{2}self:\s*$", line):
                for pname, premote, prev in projects_to_add:
                    new_lines.append(f"    - name: {pname}")
                    new_lines.append(f"      remote: {premote}")
                    new_lines.append(f"      revision: {prev}")
                inserted = True
            new_lines.append(line)
        if not inserted:
            for pname, premote, prev in projects_to_add:
                new_lines.append(f"    - name: {pname}")
                new_lines.append(f"      remote: {premote}")
                new_lines.append(f"      revision: {prev}")
        lines = new_lines

    return "\n".join(lines).rstrip() + "\n"


def patch_build_yaml_text(
    text: str,
    shield_additions: dict[str, str],
) -> str:
    """
    Append add-on shield tokens to matching `shield:` lines in build.yaml.
    `shield_additions` maps a primary shield token (e.g. 'corne_left') to the
    add-on shield name to append (e.g. 'zmk_joystick_central').
    """
    lines = text.splitlines()
    out: list[str] = []
    for line in lines:
        m = re.match(r"^(\s*(?:-\s+)?shield\s*:\s*)(.+?)(\s*(?:#.*)?)$", line)
        if m:
            prefix, raw_val, suffix = m.group(1), m.group(2).strip(), m.group(3)
            quoted = raw_val.startswith('"') and raw_val.endswith('"')
            val = raw_val.strip('"').strip("'")
            tokens = val.split()
            for match_primary, addon in shield_additions.items():
                if match_primary in tokens:
                    # Remove any conflicting joystick add-on shield first
                    tokens = [t for t in tokens if t not in JOYSTICK_SHIELD_NAMES or t == addon]
                    if addon not in tokens:
                        tokens.append(addon)
            new_val = " ".join(tokens)
            if quoted:
                new_val = f'"{new_val}"'
            line = f"{prefix}{new_val}{suffix}"
        out.append(line)
    return "\n".join(out).rstrip() + "\n"


def build_overlay_override_block(
    *,
    include_axis_overrides: bool,
    x_adc: int,
    y_adc: int,
    mv_mid: int,
    mv_min_max: int,
    mv_deadzone: int,
    scale_multiplier: int,
    scale_divisor: int,
    invert_x: bool,
    invert_y: bool,
    scroll_layer: int | None,
    scroll_divisor: int,
    invert_scroll_y: bool,
) -> str:
    parts: list[str] = [OVERLAY_BEGIN_MARKER]

    if include_axis_overrides:
        x_lines = [
            "&x_ch {",
            f"    io-channels = <&adc {x_adc}>;",
            f"    mv-mid = <{mv_mid}>;",
            f"    mv-min-max = <{mv_min_max}>;",
            f"    mv-deadzone = <{mv_deadzone}>;",
            f"    scale-multiplier = <{scale_multiplier}>;",
            f"    scale-divisor = <{scale_divisor}>;",
        ]
        if not invert_x:
            x_lines.append("    /delete-property/ invert;")
        x_lines.append("};")

        y_lines = [
            "&y_ch {",
            f"    io-channels = <&adc {y_adc}>;",
            f"    mv-mid = <{mv_mid}>;",
            f"    mv-min-max = <{mv_min_max}>;",
            f"    mv-deadzone = <{mv_deadzone}>;",
            f"    scale-multiplier = <{scale_multiplier}>;",
            f"    scale-divisor = <{scale_divisor}>;",
        ]
        if not invert_y:
            y_lines.append("    /delete-property/ invert;")
        y_lines.append("};")

        parts.append("\n".join(x_lines))
        parts.append("\n".join(y_lines))

    if scroll_layer is not None:
        procs = [
            "<&zip_xy_to_scroll_mapper>",
            f"<&zip_scroll_scaler 1 {scroll_divisor}>",
        ]
        if invert_scroll_y:
            procs.append("<&zip_scroll_transform INPUT_TRANSFORM_Y_INVERT>")
        proc_body = "\n            , ".join(procs)
        scroller_block = "\n".join(
            [
                "&joystick_listener {",
                "    joystick_scroller: scroller {",
                f"        layers = <{scroll_layer}>;",
                "        input-processors",
                f"            = {proc_body}",
                "            ;",
                "    };",
                "};",
            ]
        )
        parts.append(scroller_block)

    parts.append(OVERLAY_END_MARKER)
    return "\n\n".join(parts) + "\n"


def upsert_fenced_block(existing: str, block: str) -> str:
    pattern = re.compile(
        re.escape(OVERLAY_BEGIN_MARKER) + r".*?" + re.escape(OVERLAY_END_MARKER) + r"\n?",
        flags=re.DOTALL,
    )
    if pattern.search(existing):
        return pattern.sub(block, existing, count=1)
    if not existing.strip():
        return block
    return existing.rstrip() + "\n\n" + block


def make_unified_diff(old: str, new: str, relpath: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{relpath}",
            tofile=f"b/{relpath}",
        )
    )


def apply_config(
    target: Path,
    *,
    mode: str | None = None,
    central_shield: str | None = None,
    peripheral_shield: str | None = None,
    x_adc: int = 5,
    y_adc: int = 7,
    mv_mid: int = 1650,
    mv_min_max: int = 1600,
    mv_deadzone: int = 60,
    scale_multiplier: int = 1,
    scale_divisor: int = 80,
    invert_x: bool = True,
    invert_y: bool = True,
    scroll_layer: int | None = None,
    scroll_divisor: int = 128,
    invert_scroll_y: bool = True,
    pin_zmk: str | None = None,
    dry_run: bool = False,
    force: bool = False,
    offline: bool = False,
) -> dict[str, Any]:
    target = target.resolve()
    report = inspect_repo(target, offline=offline)
    if not report.get("ok") and not force:
        return {
            "ok": False,
            "applied": False,
            "error": "Target repo has blocking issues. Fix them or re-run with --force.",
            "blocking_issues": report.get("blocking_issues", []),
        }

    if x_adc == y_adc:
        return {"ok": False, "applied": False, "error": "x-adc and y-adc must be different SAADC channels."}

    for label, ch in (("x-adc", x_adc), ("y-adc", y_adc)):
        if ch not in NICE_NANO_V2_USABLE_AINS and not force:
            return {
                "ok": False,
                "applied": False,
                "error": (
                    f"{label}={ch} is not a usable external SAADC channel on nice!nano v2 "
                    f"(usable channels: {NICE_NANO_V2_USABLE_AINS}). Pass --force to override."
                ),
            }

    targets = report["targets"]
    resolved_mode = mode or report["topology"]["suggested_mode"]

    # Determine which shield(s) get patched
    shield_additions: dict[str, str] = {}
    joystick_host_target: dict[str, Any] | None = None
    central_target: dict[str, Any] | None = None

    if resolved_mode == "unibody":
        chosen = (
            next((t for t in targets if t["primary_shield"] == central_shield), None)
            if central_shield
            else targets[0]
        )
        if not chosen:
            return {"ok": False, "applied": False, "error": f"Shield '{central_shield}' not found in build.yaml."}
        shield_additions[chosen["primary_shield"]] = "zmk_joystick_addon"
        joystick_host_target = chosen
        central_target = chosen
    elif resolved_mode == "split-central":
        chosen = (
            next((t for t in targets if t["primary_shield"] == central_shield), None)
            if central_shield
            else next((t for t in targets if t["side"] == "left"), targets[0])
        )
        if not chosen:
            return {"ok": False, "applied": False, "error": f"Central shield '{central_shield}' not found in build.yaml."}
        shield_additions[chosen["primary_shield"]] = "zmk_joystick_addon"
        joystick_host_target = chosen
        central_target = chosen
    elif resolved_mode == "split-peripheral":
        c_tgt = (
            next((t for t in targets if t["primary_shield"] == central_shield), None)
            if central_shield
            else next((t for t in targets if t["side"] == "left"), None)
        )
        p_tgt = (
            next((t for t in targets if t["primary_shield"] == peripheral_shield), None)
            if peripheral_shield
            else next((t for t in targets if t["side"] == "right"), None)
        )
        if not c_tgt or not p_tgt:
            return {
                "ok": False,
                "applied": False,
                "error": (
                    "Could not auto-detect both central and peripheral shields in build.yaml. "
                    "Pass --central-shield and --peripheral-shield explicitly."
                ),
            }
        shield_additions[c_tgt["primary_shield"]] = "zmk_joystick_central"
        shield_additions[p_tgt["primary_shield"]] = "zmk_joystick_peripheral"
        joystick_host_target = p_tgt
        central_target = c_tgt
    else:
        return {"ok": False, "applied": False, "error": f"Unknown mode: {resolved_mode}"}

    # Pin collision check on the joystick-bearing half
    colliding = {c["ain"]: c for c in joystick_host_target["colliding_adc_pins"]}
    pin_conflicts = []
    for axis_name, ch in (("x-ch", x_adc), ("y-ch", y_adc)):
        if ch in colliding:
            pin_conflicts.append(
                {
                    "axis": axis_name,
                    "ain": ch,
                    "gpio": colliding[ch]["gpio"],
                    "claimed_by": colliding[ch]["claimed_by"],
                }
            )
    if pin_conflicts and not force:
        return {
            "ok": False,
            "applied": False,
            "error": (
                f"Selected ADC pin(s) collide with pins already claimed by '{joystick_host_target['primary_shield']}'. "
                "Free those pins on your keyboard matrix, pick different --x-adc/--y-adc channels, or pass --force."
            ),
            "pin_conflicts": pin_conflicts,
            "available_adc_pins": joystick_host_target["available_adc_pins"],
        }

    # Plan all file edits
    planned_edits: dict[Path, tuple[str, str]] = {}

    # 1. config/west.yml
    west_path = target / "config" / "west.yml"
    old_west = west_path.read_text(encoding="utf-8")
    new_west = patch_west_yml_text(old_west, pin_zmk=pin_zmk)
    if new_west != old_west:
        planned_edits[west_path] = (old_west, new_west)

    # 2. .github/workflows/build.yml (only when --pin-zmk is given)
    if pin_zmk:
        wf_path = target / ".github" / "workflows" / "build.yml"
        if wf_path.exists():
            old_wf = wf_path.read_text(encoding="utf-8")
            new_wf = re.sub(
                r"(zmkfirmware/zmk/\.github/workflows/build-user-config\.yml@)[^\s\"']+",
                rf"\g<1>{pin_zmk}",
                old_wf,
            )
            if new_wf != old_wf:
                planned_edits[wf_path] = (old_wf, new_wf)

    # 3. build.yaml
    build_path = target / "build.yaml"
    old_build = build_path.read_text(encoding="utf-8")
    new_build = patch_build_yaml_text(old_build, shield_additions)
    if new_build != old_build:
        planned_edits[build_path] = (old_build, new_build)

    # 4. Optional overlay override(s) for non-default axes/calibration or scroll layer
    needs_axis_override = any(
        [
            x_adc != 5,
            y_adc != 7,
            mv_mid != 1650,
            mv_min_max != 1600,
            mv_deadzone != 60,
            scale_multiplier != 1,
            scale_divisor != 80,
            not invert_x,
            not invert_y,
        ]
    )

    if needs_axis_override or scroll_layer is not None:
        if resolved_mode == "split-peripheral" and needs_axis_override and scroll_layer is not None:
            # Split peripheral gets axis overrides; central gets scroll layer override
            p_ov = target / "config" / f"{joystick_host_target['primary_shield']}.overlay"
            old_p = p_ov.read_text(encoding="utf-8") if p_ov.exists() else ""
            block_p = build_overlay_override_block(
                include_axis_overrides=True,
                x_adc=x_adc,
                y_adc=y_adc,
                mv_mid=mv_mid,
                mv_min_max=mv_min_max,
                mv_deadzone=mv_deadzone,
                scale_multiplier=scale_multiplier,
                scale_divisor=scale_divisor,
                invert_x=invert_x,
                invert_y=invert_y,
                scroll_layer=None,
                scroll_divisor=scroll_divisor,
                invert_scroll_y=invert_scroll_y,
            )
            new_p = upsert_fenced_block(old_p, block_p)
            if new_p != old_p:
                planned_edits[p_ov] = (old_p, new_p)

            c_ov = target / "config" / f"{central_target['primary_shield']}.overlay"
            old_c = c_ov.read_text(encoding="utf-8") if c_ov.exists() else ""
            block_c = build_overlay_override_block(
                include_axis_overrides=False,
                x_adc=x_adc,
                y_adc=y_adc,
                mv_mid=mv_mid,
                mv_min_max=mv_min_max,
                mv_deadzone=mv_deadzone,
                scale_multiplier=scale_multiplier,
                scale_divisor=scale_divisor,
                invert_x=invert_x,
                invert_y=invert_y,
                scroll_layer=scroll_layer,
                scroll_divisor=scroll_divisor,
                invert_scroll_y=invert_scroll_y,
            )
            new_c = upsert_fenced_block(old_c, block_c)
            if new_c != old_c:
                planned_edits[c_ov] = (old_c, new_c)
        else:
            ov_target = central_target if (scroll_layer is not None and not needs_axis_override) else joystick_host_target
            ov_path = target / "config" / f"{ov_target['primary_shield']}.overlay"
            old_ov = ov_path.read_text(encoding="utf-8") if ov_path.exists() else ""
            block = build_overlay_override_block(
                include_axis_overrides=needs_axis_override,
                x_adc=x_adc,
                y_adc=y_adc,
                mv_mid=mv_mid,
                mv_min_max=mv_min_max,
                mv_deadzone=mv_deadzone,
                scale_multiplier=scale_multiplier,
                scale_divisor=scale_divisor,
                invert_x=invert_x,
                invert_y=invert_y,
                scroll_layer=scroll_layer,
                scroll_divisor=scroll_divisor,
                invert_scroll_y=invert_scroll_y,
            )
            new_ov = upsert_fenced_block(old_ov, block)
            if new_ov != old_ov:
                planned_edits[ov_path] = (old_ov, new_ov)

    diffs: dict[str, str] = {}
    changed_files: list[str] = []
    for path, (old_txt, new_txt) in planned_edits.items():
        rel = str(path.relative_to(target))
        diffs[rel] = make_unified_diff(old_txt, new_txt, rel)
        changed_files.append(rel)
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new_txt, encoding="utf-8")

    next_steps = [
        f"Wire VRx to nice!nano v2 {NICE_NANO_PIN_LABELS.get(NRF52840_AIN_TO_GPIO[x_adc], f'AIN{x_adc}')} and VRy to {NICE_NANO_PIN_LABELS.get(NRF52840_AIN_TO_GPIO[y_adc], f'AIN{y_adc}')} (with VCC=3.3V and GND).",
        "Commit and push to trigger GitHub Actions, then flash the compiled .uf2 firmware.",
    ]
    if scroll_layer is not None:
        next_steps.insert(
            1,
            f"Ensure your keymap has a binding to activate layer {scroll_layer} (e.g. `&mo {scroll_layer}`) to toggle scroll mode.",
        )

    return {
        "ok": True,
        "dry_run": dry_run,
        "applied": not dry_run,
        "mode": resolved_mode,
        "shield_additions": shield_additions,
        "changed_files": changed_files,
        "diffs": diffs,
        "pin_conflicts_ignored": pin_conflicts,
        "next_steps": next_steps,
    }


# ---------------------------------------------------------------------------
# Static Validator (validate)
# ---------------------------------------------------------------------------


def validate_repo(target: Path, offline: bool = False) -> dict[str, Any]:
    target = target.resolve()
    report = inspect_repo(target, offline=offline)
    errors: list[dict[str, str]] = list(report.get("blocking_issues", []))
    warnings: list[dict[str, str]] = list(report.get("warnings", []))

    west = report.get("zmk", {}).get("west_yml", {})
    if not west.get("has_analog_input_driver"):
        errors.append(
            {
                "code": "MISSING_ANALOG_DRIVER",
                "message": "badjeff/zmk-analog-input-driver is missing from config/west.yml.",
            }
        )

    all_js_shields: set[str] = set()
    for t in report.get("targets", []):
        all_js_shields.update(t["joystick_shields_present"])

    if not all_js_shields:
        warnings.append(
            {
                "code": "NO_JOYSTICK_SHIELD_IN_BUILD_YAML",
                "message": "No zmk_joystick* shield found in build.yaml (ok only if manually configured in your own shield overlay).",
            }
        )
    if "zmk_joystick_peripheral" in all_js_shields and "zmk_joystick_central" not in all_js_shields:
        errors.append(
            {
                "code": "UNPAIRED_SPLIT_PERIPHERAL",
                "message": "zmk_joystick_peripheral is in build.yaml without a matching zmk_joystick_central on the central half.",
            }
        )
    if "zmk_joystick_central" in all_js_shields and "zmk_joystick_peripheral" not in all_js_shields:
        errors.append(
            {
                "code": "UNPAIRED_SPLIT_CENTRAL",
                "message": "zmk_joystick_central is in build.yaml without a matching zmk_joystick_peripheral on the peripheral half.",
            }
        )

    uses_addon_shield = bool(all_js_shields & {"zmk_joystick_addon", "zmk_joystick_central", "zmk_joystick_peripheral"})
    if uses_addon_shield and not west.get("has_zmk_joystick"):
        # Allow when validating the zmk-joystick repo itself
        if not (target / "boards" / "shields" / "zmk_joystick_addon").is_dir():
            errors.append(
                {
                    "code": "MISSING_ZMK_JOYSTICK_MODULE",
                    "message": "Add-on shield referenced in build.yaml, but FredForte/zmk-joystick is missing from config/west.yml.",
                }
            )

    # Check local overlays for common misconfigurations
    for ov in sorted(target.rglob("*.overlay")):
        if ".git" in ov.parts or "zmk" in ov.parts:
            continue
        clean = strip_dts_comments(ov.read_text(encoding="utf-8", errors="ignore"))
        rel = str(ov.relative_to(target))
        if re.search(r"mv-mid\s*=\s*<\s*512\s*>", clean):
            warnings.append(
                {
                    "code": "SUSPICIOUS_MV_MID_512",
                    "message": f"{rel} has mv-mid = <512>. On 3.3V nice!nano v2, centered sticks read ~1650 mV (512 causes runaway cursor drift).",
                }
            )
        if re.search(r"mv-min-max\s*=\s*<\s*([1-9]|[1-4]\d)\s*>", clean):
            warnings.append(
                {
                    "code": "SUSPICIOUS_MV_MIN_MAX",
                    "message": f"{rel} has a very small mv-min-max (<50 mV). Typical 3.3V sticks need ~1600.",
                }
            )

    return {
        "ok": len(errors) == 0,
        "target": str(target),
        "errors": errors,
        "warnings": warnings,
        "joystick_shields_detected": sorted(all_js_shields),
    }


# ---------------------------------------------------------------------------
# Human-Readable Renderers & Interactive Wizard
# ---------------------------------------------------------------------------


def print_inspect_human(report: dict[str, Any]) -> None:
    print(c_bold(f"=== zmk-joystick inspection: {report['target']} ==="))
    west = report["zmk"]["west_yml"]
    print(
        f"ZMK revision: {c_cyan(str(west.get('zmk_revision')))} "
        f"(workflow: {c_cyan(str(report['zmk'].get('workflow_ref')))})"
    )
    print(
        f"Modules: analog-input-driver={'yes' if west.get('has_analog_input_driver') else 'no'}, "
        f"zmk-joystick={'yes' if west.get('has_zmk_joystick') else 'no'}"
    )
    topo = report["topology"]
    print(
        f"Topology: {'split' if topo['is_split'] else 'unibody'} "
        f"(suggested mode: {c_cyan(topo['suggested_mode'])})"
    )
    print()

    for t in report["targets"]:
        status = c_green("OK (2+ ADC pins free)") if t["can_wire_2_axis_directly"] else c_red("CONFLICT (<2 ADC pins free)")
        print(f"Target #{t['index']}: board={c_bold(t['board'])} shield={c_bold(t['shield'])} -> {status}")
        if t["available_adc_pins"]:
            avail = ", ".join(f"AIN{p['ain']} ({p['gpio']})" for p in t["available_adc_pins"])
            print(f"  Free ADC pins:      {c_green(avail)}")
        if t["colliding_adc_pins"]:
            cols = ", ".join(f"AIN{p['ain']} ({p['gpio']} <- {p['claimed_by'][0]})" for p in t["colliding_adc_pins"])
            print(f"  Colliding ADC pins: {c_yellow(cols)}")
        for note in t["notes"]:
            print(f"  Note: {note}")

    if report["blocking_issues"]:
        print("\n" + c_red("Blocking issues:"))
        for b in report["blocking_issues"]:
            print(f"  - [{b['code']}] {b['message']}")
    if report["warnings"]:
        print("\n" + c_yellow("Warnings:"))
        for w in report["warnings"]:
            print(f"  - [{w['code']}] {w['message']}")
    if report["recommended_actions"]:
        print("\n" + c_bold("Recommended actions:"))
        for a in report["recommended_actions"]:
            print(f"  - {a}")


def run_interactive_setup(target: Path, offline: bool = False) -> int:
    report = inspect_repo(target, offline=offline)
    print_inspect_human(report)
    if not report.get("ok"):
        print(c_red("\nCannot continue until blocking issues above are resolved."))
        return 1

    print()
    default_mode = report["topology"]["suggested_mode"]
    mode_prompt = f"Install mode [unibody / split-central / split-peripheral] ({default_mode}): "
    mode = input(mode_prompt).strip() or default_mode

    pin_zmk: str | None = None
    if report["zmk"]["west_yml"].get("zmk_revision") == "main":
        ans = input("ZMK is unpinned on 'main'. Pin to v0.3? [Y/n]: ").strip().lower()
        if ans in ("", "y", "yes"):
            pin_zmk = "v0.3"

    x_adc = int(input("X-axis SAADC channel [5=P0.29, 7=P0.31, 0=P0.02] (5): ").strip() or "5")
    y_adc = int(input("Y-axis SAADC channel [5=P0.29, 7=P0.31, 0=P0.02] (7): ").strip() or "7")

    scroll_raw = input("Enable scroll mode on a layer? Enter layer number (e.g. 1) or leave blank to skip: ").strip()
    scroll_layer = int(scroll_raw) if scroll_raw else None

    preview = apply_config(
        target,
        mode=mode,
        x_adc=x_adc,
        y_adc=y_adc,
        scroll_layer=scroll_layer,
        pin_zmk=pin_zmk,
        dry_run=True,
        offline=offline,
    )
    if not preview.get("ok"):
        print(c_red(f"\nError: {preview.get('error')}"))
        if preview.get("pin_conflicts"):
            print(json.dumps(preview["pin_conflicts"], indent=2))
        return 1

    print("\n" + c_bold("=== Planned Changes (dry-run) ==="))
    for rel, diff_txt in preview["diffs"].items():
        print(c_cyan(f"--- {rel} ---"))
        print(diff_txt)

    if not preview["changed_files"]:
        print(c_green("Repository is already configured; no file changes needed."))
    else:
        confirm = input("Apply these changes? [y/N]: ").strip().lower()
        if confirm not in ("y", "yes"):
            print("Aborted.")
            return 0
        res = apply_config(
            target,
            mode=mode,
            x_adc=x_adc,
            y_adc=y_adc,
            scroll_layer=scroll_layer,
            pin_zmk=pin_zmk,
            dry_run=False,
            offline=offline,
        )
        print(c_green(f"\nApplied changes to: {', '.join(res['changed_files'])}"))

    val = validate_repo(target, offline=offline)
    if val["ok"]:
        print(c_green("Validation passed!"))
        return 0
    print(c_red("Validation reported issues:"))
    for err in val["errors"]:
        print(f"  - [{err['code']}] {err['message']}")
    return 1


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zmk_joystick.py",
        description="Inspect, install, and validate zmk-joystick in any ZMK user-config repository.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_inspect = sub.add_parser("inspect", help="Analyze a target ZMK repo (boards, shields, pin collisions).")
    p_inspect.add_argument("--target", type=Path, default=Path("."), help="Path to target ZMK config repo.")
    p_inspect.add_argument("--json", action="store_true", help="Output structured JSON (recommended for AI agents).")
    p_inspect.add_argument("--offline", action="store_true", help="Skip GitHub upstream shield lookups.")

    p_apply = sub.add_parser("apply", help="Idempotently install zmk-joystick into a target ZMK repo.")
    p_apply.add_argument("--target", type=Path, default=Path("."), help="Path to target ZMK config repo.")
    p_apply.add_argument(
        "--mode",
        choices=["unibody", "split-central", "split-peripheral"],
        default=None,
        help="Install topology (auto-detected if omitted).",
    )
    p_apply.add_argument("--central-shield", default=None, help="Primary central/unibody shield name in build.yaml.")
    p_apply.add_argument("--peripheral-shield", default=None, help="Primary peripheral shield name in build.yaml.")
    p_apply.add_argument("--x-adc", type=int, default=5, help="SAADC channel for X axis (default: 5 = P0.29).")
    p_apply.add_argument("--y-adc", type=int, default=7, help="SAADC channel for Y axis (default: 7 = P0.31).")
    p_apply.add_argument("--mv-mid", type=int, default=1650, help="Resting center voltage in mV (default: 1650).")
    p_apply.add_argument("--mv-min-max", type=int, default=1600, help="Full deflection +/- mV (default: 1600).")
    p_apply.add_argument("--mv-deadzone", type=int, default=60, help="Deadzone radius in mV (default: 60).")
    p_apply.add_argument("--scale-multiplier", type=int, default=1, help="Cursor scale multiplier (default: 1).")
    p_apply.add_argument("--scale-divisor", type=int, default=80, help="Cursor scale divisor (default: 80).")
    p_apply.add_argument("--invert-x", action=argparse.BooleanOptionalAction, default=True, help="Invert X axis.")
    p_apply.add_argument("--invert-y", action=argparse.BooleanOptionalAction, default=True, help="Invert Y axis.")
    p_apply.add_argument("--scroll-layer", type=int, default=None, help="Optional layer index for scroll mode.")
    p_apply.add_argument("--scroll-divisor", type=int, default=128, help="Scroll speed divisor (default: 128).")
    p_apply.add_argument(
        "--invert-scroll-y",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Invert vertical scroll direction (default: true).",
    )
    p_apply.add_argument("--pin-zmk", default=None, help="Pin ZMK revision in west.yml and build.yml (e.g. v0.3).")
    p_apply.add_argument("--dry-run", action="store_true", help="Show planned diffs without modifying files.")
    p_apply.add_argument("--force", action="store_true", help="Apply even if pin conflicts or warnings exist.")
    p_apply.add_argument("--offline", action="store_true", help="Skip GitHub upstream shield lookups.")
    p_apply.add_argument("--json", action="store_true", help="Output structured JSON.")

    p_val = sub.add_parser("validate", help="Run static health checks on a configured ZMK repo.")
    p_val.add_argument("--target", type=Path, default=Path("."), help="Path to target ZMK config repo.")
    p_val.add_argument("--offline", action="store_true", help="Skip GitHub upstream shield lookups.")
    p_val.add_argument("--json", action="store_true", help="Output structured JSON.")

    p_setup = sub.add_parser("setup", help="Interactive terminal wizard for humans.")
    p_setup.add_argument("target", nargs="?", type=Path, default=Path("."), help="Path to target ZMK config repo.")
    p_setup.add_argument("--offline", action="store_true", help="Skip GitHub upstream shield lookups.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "inspect":
        report = inspect_repo(args.target, offline=args.offline)
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print_inspect_human(report)
        return 0 if report.get("ok") else 1

    if args.command == "apply":
        res = apply_config(
            args.target,
            mode=args.mode,
            central_shield=args.central_shield,
            peripheral_shield=args.peripheral_shield,
            x_adc=args.x_adc,
            y_adc=args.y_adc,
            mv_mid=args.mv_mid,
            mv_min_max=args.mv_min_max,
            mv_deadzone=args.mv_deadzone,
            scale_multiplier=args.scale_multiplier,
            scale_divisor=args.scale_divisor,
            invert_x=args.invert_x,
            invert_y=args.invert_y,
            scroll_layer=args.scroll_layer,
            scroll_divisor=args.scroll_divisor,
            invert_scroll_y=args.invert_scroll_y,
            pin_zmk=args.pin_zmk,
            dry_run=args.dry_run,
            force=args.force,
            offline=args.offline,
        )
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            if not res.get("ok"):
                print(c_red(f"Error: {res.get('error')}"))
                return 1
            verb = "Planned (dry-run)" if res["dry_run"] else "Updated"
            print(c_green(f"{verb} files ({res['mode']}): {', '.join(res['changed_files']) or 'none'}"))
            for rel, d in res["diffs"].items():
                print(c_cyan(f"--- {rel} ---"))
                print(d)
            for step in res["next_steps"]:
                print(f"  -> {step}")
        return 0 if res.get("ok") else 1

    if args.command == "validate":
        res = validate_repo(args.target, offline=args.offline)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            if res["ok"]:
                print(c_green(f"OK: {res['target']} passed validation."))
            else:
                print(c_red(f"FAILED: {res['target']} has validation errors:"))
                for e in res["errors"]:
                    print(f"  - [{e['code']}] {e['message']}")
            for w in res["warnings"]:
                print(c_yellow(f"  ! [{w['code']}] {w['message']}"))
        return 0 if res["ok"] else 1

    if args.command == "setup":
        return run_interactive_setup(args.target, offline=args.offline)

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
