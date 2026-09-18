from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

from bividi import calib_cli


_MIGRATED_STEREO_MODULES = {
    "target-scale": "bividi.calibration.target_scale",
    "geometry-review": "bividi.calibration.stereo_geometry",
    "repeatability": "bividi.calibration.stereo_repeatability",
    "promote": "bividi.calibration.stereo_provenance",
    "report": "bividi.calibration.stereo_report",
    "campaign": "bividi.calibration.stereo_campaign",
}


class CalibrationCliTests(unittest.TestCase):
    def test_registry_has_unique_group_command_pairs(self):
        pairs = [(item.group, item.name) for item in calib_cli.commands()]
        self.assertEqual(len(pairs), len(set(pairs)))
        self.assertIn(("stereo", "solve"), pairs)
        self.assertIn(("imu", "allan"), pairs)
        self.assertIn(("camera-imu", "import-kalibr"), pairs)
        for item in calib_cli.commands():
            self.assertNotEqual(item.script is None, item.module is None)

    def test_find_source_root_accepts_explicit_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tools").mkdir()
            (root / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
            self.assertEqual(calib_cli.find_source_root(root), root.resolve())

    def test_build_invocation_preserves_tool_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tools").mkdir()
            (root / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
            script = root / "tools" / "stereo_calibration_workbench.py"
            script.write_text("print('fixture')\n", encoding="utf-8")

            invocation = calib_cli.build_invocation(
                "stereo",
                "solve",
                ["session.json", "--output", "calibration.json"],
                source_root=root,
            )

            self.assertEqual(invocation[0], sys.executable)
            self.assertEqual(Path(invocation[1]), script.resolve())
            self.assertEqual(invocation[2:], ["solve", "session.json", "--output", "calibration.json"])

    def test_migrated_modules_do_not_require_source_checkout(self):
        for command, module in _MIGRATED_STEREO_MODULES.items():
            with self.subTest(command=command):
                invocation = calib_cli.build_invocation(
                    "stereo",
                    command,
                    ["fixture.json", "--self-test"],
                    source_root=Path("/definitely/not/a/bividi/checkout"),
                )
                self.assertEqual(invocation[:3], [sys.executable, "-m", module])
                self.assertEqual(invocation[3], "fixture.json")

    def test_migrated_modules_execute_outside_source_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = Path.cwd()
            os.chdir(tmp)
            try:
                for command in _MIGRATED_STEREO_MODULES:
                    with self.subTest(command=command):
                        rc = calib_cli.main(
                            [
                                "--source-root",
                                "/definitely/not/a/bividi/checkout",
                                "stereo",
                                command,
                                "--self-test",
                            ]
                        )
                        self.assertEqual(rc, 0)
            finally:
                os.chdir(previous)

    def test_unknown_command_returns_explicit_error(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rc = calib_cli.main(["stereo", "not-a-command"])
        self.assertEqual(rc, 2)
        self.assertIn("unknown stereo command", stderr.getvalue())

    def test_group_help_and_list_are_dependency_free(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = calib_cli.main(["imu", "--help"])
        self.assertEqual(rc, 0)
        self.assertIn("stationary", stdout.getvalue())
        self.assertIn("allan", stdout.getvalue())

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = calib_cli.main(["--list"])
        self.assertEqual(rc, 0)
        output = stdout.getvalue()
        self.assertIn("stereo", output)
        self.assertIn("camera-imu", output)

    def test_dry_run_does_not_import_heavy_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tools").mkdir()
            (root / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
            script = root / "tools" / "analyze_imu_six_position.py"
            script.write_text("raise RuntimeError('must not execute')\n", encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = calib_cli.main(
                    ["--source-root", str(root), "--dry-run", "imu", "six-position", "trace.csv"]
                )
            self.assertEqual(rc, 0)
            self.assertIn("analyze_imu_six_position.py", stdout.getvalue())
            self.assertIn("trace.csv", stdout.getvalue())

    def test_migrated_module_dry_runs_are_source_tree_independent(self):
        for command, module in _MIGRATED_STEREO_MODULES.items():
            with self.subTest(command=command):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    rc = calib_cli.main(
                        [
                            "--source-root",
                            "/definitely/not/a/bividi/checkout",
                            "--dry-run",
                            "stereo",
                            command,
                            "--self-test",
                        ]
                    )
                self.assertEqual(rc, 0)
                output = stdout.getvalue()
                self.assertIn(f"-m {module}", output)
                self.assertNotIn("tools/", output)


if __name__ == "__main__":
    unittest.main()
