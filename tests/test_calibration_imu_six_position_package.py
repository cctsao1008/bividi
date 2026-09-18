from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from bividi import calib_cli
from bividi.calibration import contract, imu_six_position, imu_six_position_command


class ImuSixPositionPackageMigrationTests(unittest.TestCase):
    def test_cli_routes_installed_command_without_source_checkout(self):
        invocation = calib_cli.build_invocation(
            "imu",
            "six-position",
            ["--self-test"],
            source_root=Path("/definitely/not/a/bividi/checkout"),
        )
        self.assertEqual(
            invocation,
            [sys.executable, "-m", "bividi.calibration.imu_six_position_command", "--self-test"],
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
                        "six-position",
                        "--self-test",
                    ]
                )
            finally:
                os.chdir(previous)
        self.assertEqual(rc, contract.EXIT_OK)

    def test_characterized_synthetic_self_test_is_preserved(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = imu_six_position.self_test()
        self.assertEqual(rc, contract.EXIT_OK)
        self.assertIn("six-position IMU laboratory self-test: PASS", stdout.getvalue())

    def test_report_schema_mapping_outputs_and_candidate_boundary_are_preserved(self):
        bias = [120.0, -75.0, 30.0]
        matrix = [
            [80.0, 50.0, -8200.0],
            [8192.0, -70.0, 40.0],
            [-60.0, -8100.0, 90.0],
        ]
        gyro_bias = [8.0, -11.0, 3.0]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pose_paths: dict[str, Path] = {}
            for seed, pose in enumerate(imu_six_position.POSES):
                expected = imu_six_position.POSE_VECTOR[pose]
                raw_mean = imu_six_position.vector_add(
                    bias,
                    imu_six_position.mat_vec(matrix, expected),
                )
                path = root / f"{pose}.csv"
                imu_six_position.write_fixture(path, raw_mean, gyro_bias, seed)
                pose_paths[pose] = path

            report = imu_six_position.analyze(
                pose_paths,
                allow_invalid_samples=False,
                allow_timing_anomalies=False,
            )
            self.assertEqual(report["schema"], imu_six_position.REPORT_SCHEMA)
            self.assertEqual(
                report["status"],
                "candidate_evidence_only_not_promoted_to_calibration_artifact",
            )
            mapping = report["accelerometer_axis_mapping"]["target_from_raw"]
            self.assertEqual((mapping["x"]["raw_axis"], mapping["x"]["sign"]), ("y", "+"))
            self.assertEqual((mapping["y"]["raw_axis"], mapping["y"]["sign"]), ("z", "-"))
            self.assertEqual((mapping["z"]["raw_axis"], mapping["z"]["sign"]), ("x", "-"))
            self.assertEqual(report["accelerometer_axis_mapping"]["signed_permutation_determinant"], 1.0)
            self.assertIn(
                "Static gravity does not identify gyroscope axis permutation or sign.",
                report["guardrails"],
            )

            prefix = root / "sixpos"
            args: list[str] = []
            for pose in imu_six_position.POSES:
                args += [f"--{pose.replace('_', '-')}", str(pose_paths[pose])]
            args += ["--output-prefix", str(prefix)]
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = imu_six_position_command.entrypoint(args)
            self.assertEqual(rc, contract.EXIT_OK)
            csv_path = Path(str(prefix) + ".sixpos.csv")
            json_path = Path(str(prefix) + ".sixpos.json")
            md_path = Path(str(prefix) + ".sixpos.md")
            self.assertTrue(csv_path.is_file())
            self.assertTrue(json_path.is_file())
            self.assertTrue(md_path.is_file())
            written = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(written["schema"], imu_six_position.REPORT_SCHEMA)
            self.assertIn("Six-Position IMU Gravity / Axis Laboratory", stdout.getvalue())

    def test_domain_errors_use_exit_two_not_evaluated_fail(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rc = imu_six_position_command.entrypoint([])
        self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)
        self.assertNotEqual(rc, contract.EXIT_EVALUATED_FAIL)
        self.assertIn("missing required pose trace", stderr.getvalue())

    def test_contract_metadata_matches_route_and_candidate_semantics(self):
        self.assertEqual(len(contract.IMU_AXIS_COMMAND_CONTRACTS), 1)
        item = contract.IMU_AXIS_COMMAND_CONTRACTS[0]
        self.assertEqual(item.key, ("imu", "six-position"))
        self.assertEqual(item.module, "bividi.calibration.imu_six_position_command")
        self.assertEqual(item.compatibility_tool, "analyze_imu_six_position.py")
        self.assertEqual(item.output_role, "machine-evidence-json-and-human-markdown")
        self.assertEqual(item.policy_role, "candidate-analysis-no-acceptance-gate")
        self.assertIsNone(item.evaluated_fail_exit)
        self.assertEqual(contract.contract_for("imu", "six-position"), item)


if __name__ == "__main__":
    unittest.main()
