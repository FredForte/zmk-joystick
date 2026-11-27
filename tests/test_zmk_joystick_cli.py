"""Unit tests for scripts/zmk_joystick.py (stdlib unittest, zero external deps)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI = REPO_ROOT / "scripts" / "zmk_joystick.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def create_mock_repo(
    root: Path,
    *,
    build_yaml: str,
    zmk_rev: str = "v0.3",
    overlays: dict[str, str] | None = None,
) -> Path:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / ".github" / "workflows").mkdir(parents=True, exist_ok=True)

    (root / "config" / "west.yml").write_text(
        f"""manifest:
  remotes:
    - name: zmkfirmware
      url-base: https://github.com/zmkfirmware
  projects:
    - name: zmk
      remote: zmkfirmware
      revision: {zmk_rev}
      import: app/west.yml
  self:
    path: config
""",
        encoding="utf-8",
    )

    (root / ".github" / "workflows" / "build.yml").write_text(
        f"""name: Build ZMK firmware
on: [push]
jobs:
  build:
    uses: zmkfirmware/zmk/.github/workflows/build-user-config.yml@{zmk_rev}
""",
        encoding="utf-8",
    )

    (root / "build.yaml").write_text(build_yaml, encoding="utf-8")

    for rel, content in (overlays or {}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    return root


class TestZmkJoystickCli(unittest.TestCase):
    def test_self_repo_validates(self) -> None:
        proc = run_cli("validate", "--target", str(REPO_ROOT), "--offline", "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        data = json.loads(proc.stdout)
        self.assertTrue(data["ok"])
        self.assertEqual(data["errors"], [])
        self.assertIn("zmk_joystick", data["joystick_shields_detected"])

    def test_unibody_custom_board_apply_idempotent_and_validate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = create_mock_repo(
                Path(tmp),
                build_yaml="include:\n  - board: nice_nano_v2\n    shield: my_macropad\n",
                zmk_rev="main",
                overlays={
                    "boards/shields/my_macropad/my_macropad.overlay": """
/ {
    kscan0: kscan {
        row-gpios = <&pro_micro 4 GPIO_ACTIVE_HIGH>, <&pro_micro 5 GPIO_ACTIVE_HIGH>;
        col-gpios = <&pro_micro 6 GPIO_ACTIVE_HIGH>, <&pro_micro 7 GPIO_ACTIVE_HIGH>;
    };
};
"""
                },
            )

            # Inspect detects unpinned main + 3 free ADC pins
            ins = run_cli("inspect", "--target", str(repo), "--offline", "--json")
            self.assertEqual(ins.returncode, 0, ins.stdout + ins.stderr)
            ins_data = json.loads(ins.stdout)
            self.assertFalse(ins_data["topology"]["is_split"])
            self.assertTrue(ins_data["targets"][0]["can_wire_2_axis_directly"])
            self.assertEqual([p["ain"] for p in ins_data["targets"][0]["available_adc_pins"]], [5, 7, 0])
            self.assertTrue(any(w["code"] == "UNPINNED_ZMK_MAIN" for w in ins_data["warnings"]))

            # Dry-run writes nothing
            dry = run_cli(
                "apply", "--target", str(repo), "--scroll-layer", "2", "--pin-zmk", "v0.3", "--dry-run", "--offline", "--json"
            )
            self.assertEqual(dry.returncode, 0, dry.stdout + dry.stderr)
            dry_data = json.loads(dry.stdout)
            self.assertTrue(dry_data["dry_run"])
            self.assertIn("config/west.yml", dry_data["changed_files"])
            self.assertIn("build.yaml", dry_data["changed_files"])
            self.assertIn(".github/workflows/build.yml", dry_data["changed_files"])
            self.assertIn("config/my_macropad.overlay", dry_data["changed_files"])
            self.assertFalse((repo / "config" / "my_macropad.overlay").exists())

            # Real apply
            app = run_cli(
                "apply", "--target", str(repo), "--scroll-layer", "2", "--pin-zmk", "v0.3", "--offline", "--json"
            )
            self.assertEqual(app.returncode, 0, app.stdout + app.stderr)
            self.assertIn("my_macropad zmk_joystick_addon", (repo / "build.yaml").read_text())
            self.assertIn("revision: v0.3", (repo / "config" / "west.yml").read_text())
            self.assertIn("build-user-config.yml@v0.3", (repo / ".github" / "workflows" / "build.yml").read_text())
            self.assertIn("layers = <2>;", (repo / "config" / "my_macropad.overlay").read_text())

            # Second apply is completely idempotent
            app2 = run_cli(
                "apply", "--target", str(repo), "--scroll-layer", "2", "--pin-zmk", "v0.3", "--offline", "--json"
            )
            self.assertEqual(app2.returncode, 0)
            self.assertEqual(json.loads(app2.stdout)["changed_files"], [])

            # Validate passes with zero errors & zero warnings
            val = run_cli("validate", "--target", str(repo), "--offline", "--json")
            self.assertEqual(val.returncode, 0, val.stdout + val.stderr)
            val_data = json.loads(val.stdout)
            self.assertTrue(val_data["ok"])
            self.assertEqual(val_data["errors"], [])

    def test_in_tree_corne_pin_collision_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = create_mock_repo(
                Path(tmp),
                build_yaml=(
                    "include:\n"
                    "  - board: nice_nano_v2\n"
                    "    shield: corne_left\n"
                    "  - board: nice_nano_v2\n"
                    "    shield: corne_right\n"
                ),
            )
            ins = run_cli("inspect", "--target", str(repo), "--offline", "--json")
            self.assertEqual(ins.returncode, 0)
            data = json.loads(ins.stdout)
            self.assertTrue(data["topology"]["is_split"])
            self.assertFalse(data["targets"][0]["can_wire_2_axis_directly"])
            colliding_ains = {p["ain"] for p in data["targets"][0]["colliding_adc_pins"]}
            self.assertEqual(colliding_ains, {0, 5, 7})

            # Apply must fail cleanly without --force
            app = run_cli("apply", "--target", str(repo), "--mode", "split-central", "--offline", "--json")
            self.assertEqual(app.returncode, 1)
            app_data = json.loads(app.stdout)
            self.assertFalse(app_data["ok"])
            self.assertEqual(len(app_data["pin_conflicts"]), 2)

    def test_split_peripheral_lily58_has_ain5_and_ain7_free(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = create_mock_repo(
                Path(tmp),
                build_yaml=(
                    "include:\n"
                    "  - board: nice_nano_v2\n"
                    "    shield: lily58_left\n"
                    "  - board: nice_nano_v2\n"
                    "    shield: lily58_right\n"
                ),
            )
            # Lily58 uses pro_micro 19 (AIN0), leaving AIN5 (20) and AIN7 (21) FREE!
            ins = run_cli("inspect", "--target", str(repo), "--offline", "--json")
            self.assertEqual(ins.returncode, 0)
            data = json.loads(ins.stdout)
            self.assertTrue(data["topology"]["is_split"])
            right = next(t for t in data["targets"] if t["primary_shield"] == "lily58_right")
            self.assertTrue(right["can_wire_2_axis_directly"])
            self.assertEqual([p["ain"] for p in right["available_adc_pins"]], [5, 7])

            app = run_cli(
                "apply",
                "--target",
                str(repo),
                "--mode",
                "split-peripheral",
                "--scroll-layer",
                "3",
                "--scale-divisor",
                "100",
                "--offline",
                "--json",
            )
            self.assertEqual(app.returncode, 0, app.stdout + app.stderr)
            build_txt = (repo / "build.yaml").read_text()
            self.assertIn("lily58_left zmk_joystick_central", build_txt)
            self.assertIn("lily58_right zmk_joystick_peripheral", build_txt)
            # Axis override on peripheral, scroll layer override on central!
            self.assertIn("scale-divisor = <100>;", (repo / "config" / "lily58_right.overlay").read_text())
            self.assertIn("layers = <3>;", (repo / "config" / "lily58_left.overlay").read_text())

            val = run_cli("validate", "--target", str(repo), "--offline", "--json")
            self.assertEqual(val.returncode, 0, val.stdout + val.stderr)
            self.assertTrue(json.loads(val.stdout)["ok"])

    def test_local_pin_collision_and_remap_to_ain0_ain7(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = create_mock_repo(
                Path(tmp),
                build_yaml="include:\n  - board: nice_nano_v2\n    shield: custom_pad\n",
                overlays={
                    "boards/shields/custom_pad/custom_pad.overlay": """
/ {
    kscan0: kscan {
        row-gpios = <&pro_micro 20 GPIO_ACTIVE_HIGH>; /* P0.29 / AIN5 claimed! */
        col-gpios = <&pro_micro 10 GPIO_ACTIVE_HIGH>;
    };
};
"""
                },
            )
            # Default x-adc=5 collides -> fails
            fail = run_cli("apply", "--target", str(repo), "--offline", "--json")
            self.assertEqual(fail.returncode, 1)

            # Remapping x-adc=0, y-adc=7 succeeds!
            ok = run_cli("apply", "--target", str(repo), "--x-adc", "0", "--y-adc", "7", "--offline", "--json")
            self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
            self.assertIn("io-channels = <&adc 0>;", (repo / "config" / "custom_pad.overlay").read_text())


if __name__ == "__main__":
    unittest.main()
