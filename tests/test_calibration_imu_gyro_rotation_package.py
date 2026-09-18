from __future__ import annotations

import contextlib
import io
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

from bividi import calib_cli
from bividi.calibration import contract, imu_gyro_rotation, imu_gyro_rotation_command


class ImuGyroRotationPackageMigrationTests(unittest.TestCase):
    def test_cli_routes_installed_command_without_source_checkout(self):
        invocation = calib_cli.build_invocation(
            "imu",
            "gyro-rotation",
            ["--self-test"],
            source_root=Path("/definitely/not/a/bividi/checkout"),
        )
        self.assertEqual(
            invocation,
            [sys.executable, "-m", "bividi.calibration.imu_gyro_rotation_command", "--self-test"],
        )

    def test_cli_executes_outside_source_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = Path.cwd()
            os.chdir(tmp)
            try:
                rc = calib_cli.main(
                    [
                        "--source-root",
                        "/definitely/not/a/bividi/checkout",
                        "imu",
                        "gyro-rotation",
                        "--self-test",
                    ]
                )
            finally:
                os.chdir(previous)
        self.assertEqual(rc, contract.EXIT_OK)

    def test_characterized_synthetic_self_test_is_preserved(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = imu_gyro_rotation.self_test()
        self.assertEqual(rc, contract.EXIT_OK)
        self.assertIn("controlled gyro rotation laboratory self-test: PASS", stdout.getvalue())

    def _fixture_set(self, root: Path) -> tuple[Path, dict[str, Path], list[list[float]]]:
        bias = [9.0, -13.0, 4.0]
        sensitivity = [
            [12.0, 18.0, -1000.0],
            [1024.0, -15.0, 10.0],
            [-20.0, -980.0, 14.0],
        ]
        angle_rad = math.pi / 2.0
        stationary = root / "stationary.csv"
        imu_gyro_rotation.write_fixture(
            stationary,
            bias=bias,
            sensitivity=sensitivity,
            target_axis=None,
            sign=0.0,
            angle_rad=angle_rad,
        )
        run_paths: dict[str, Path] = {}
        for run in imu_gyro_rotation.RUNS:
            axis = imu_gyro_rotation.AXES.index(run[-1])
            sign = 1.0 if run.startswith("plus") else -1.0
            path = root / f"{run}.csv"
            imu_gyro_rotation.write_fixture(
                path,
                bias=bias,
                sensitivity=sensitivity,
                target_axis=axis,
                sign=sign,
                angle_rad=angle_rad,
            )
            run_paths[run] = path
        return stationary, run_paths, sensitivity

    def test_axis_only_analysis_does_not_infer_absolute_sensitivity(self):
        with tempfile.TemporaryDirectory() as tmp:
            stationary, run_paths, _ = self._fixture_set(Path(tmp))
            report = imu_gyro_rotation.analyze(
                stationary,
                run_paths,
                expected_angle_deg=None,
                accelerometer_sixpos_json=None,
                allow_invalid_samples=False,
                allow_timing_anomalies=False,
            )
            self.assertEqual(report["schema"], imu_gyro_rotation.REPORT_SCHEMA)
            self.assertEqual(
                report["status"],
                "candidate_evidence_only_not_promoted_to_calibration_artifact",
            )
            mapping = report["rotation_model"]["axis_mapping"]["target_from_raw"]
            self.assertEqual((mapping["x"]["raw_axis"], mapping["x"]["sign"]), ("y", "+"))
            self.assertEqual((mapping["y"]["raw_axis"], mapping["y"]["sign"]), ("z", "-"))
            self.assertEqual((mapping["z"]["raw_axis"], mapping["z"]["sign"]), ("x", "-"))
            self.assertIsNone(report["rotation_model"]["sensitivity_raw_counts_per_rad_s_matrix"])
            self.assertIsNone(report["rotation_model"]["target_rad_s_per_raw_count_matrix"])
            self.assertIn(
                "Absolute gyro sensitivity is produced only when --expected-angle-deg is explicitly supplied.",
                report["guardrails"],
            )

    def test_explicit_angle_preserves_sensitivity_and_output_surfaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stationary, run_paths, sensitivity = self._fixture_set(root)
            report = imu_gyro_rotation.analyze(
                stationary,
                run_paths,
                expected_angle_deg=90.0,
                accelerometer_sixpos_json=None,
                allow_invalid_samples=False,
                allow_timing_anomalies=False,
            )
            recovered = report["rotation_model"]["sensitivity_raw_counts_per_rad_s_matrix"]
            self.assertIsNotNone(recovered)
            for actual_row, expected_row in zip(recovered, sensitivity):
                for actual, expected in zip(actual_row, expected_row):
                    self.assertAlmostEqual(actual, expected, places=8)
            for run in imu_gyro_rotation.RUNS:
                self.assertLess(report["rotation_model"]["run_angle_fit"][run]["residual_l2_deg"], 1e-8)

            prefix = root / "gyro"
            argv = ["--stationary", str(stationary), "--expected-angle-deg", "90", "--output-prefix", str(prefix)]
            for run in imu_gyro_rotation.RUNS:
                argv += [f"--{run.replace('_', '-')}", str(run_paths[run])]
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = imu_gyro_rotation_command.entrypoint(argv)
            self.assertEqual(rc, contract.EXIT_OK)
            csv_path = Path(str(prefix) + ".gyro.csv")
            json_path = Path(str(prefix) + ".gyro.json")
            markdown_path = Path(str(prefix) + ".gyro.md")
            self.assertTrue(csv_path.is_file())
            self.assertTrue(json_path.is_file())
            self.assertTrue(markdown_path.is_file())
            written = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(written["schema"], imu_gyro_rotation.REPORT_SCHEMA)
            self.assertIn("Controlled Gyroscope Rotation / Axis Laboratory", stdout.getvalue())

    def test_domain_errors_use_exit_two_not_evaluated_fail(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rc = imu_gyro_rotation_command.entrypoint([])
        self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)
        self.assertNotEqual(rc, contract.EXIT_EVALUATED_FAIL)
        self.assertIn("--stationary is required", stderr.getvalue())

    def test_contract_metadata_matches_route_and_candidate_semantics(self):
        items = {item.name: item for item in contract.IMU_AXIS_COMMAND_CONTRACTS}
        item = items["gyro-rotation"]
        self.assertEqual(item.module, "bividi.calibration.imu_gyro_rotation_command")
        self.assertEqual(item.compatibility_tool, "analyze_imu_gyro_rotation.py")
        self.assertEqual(item.output_role, "machine-evidence-json-and-human-markdown")
        self.assertEqual(item.policy_role, "candidate-analysis-no-acceptance-gate")
        self.assertFalse(item.emits_versioned_provenance)
        self.assertIsNone(item.evaluated_fail_exit)
        self.assertEqual(contract.contract_for("imu", "gyro-rotation"), item)


if __name__ == "__main__":
    unittest.main()
