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
from bividi.calibration import contract, imu_allan, imu_allan_command


class ImuAllanPackageMigrationTests(unittest.TestCase):
    def test_cli_routes_installed_command_without_source_checkout(self):
        invocation = calib_cli.build_invocation(
            "imu",
            "allan",
            ["--self-test"],
            source_root=Path("/definitely/not/a/bividi/checkout"),
        )
        self.assertEqual(
            invocation,
            [sys.executable, "-m", "bividi.calibration.imu_allan_command", "--self-test"],
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
                        "allan",
                        "--self-test",
                    ]
                )
            finally:
                os.chdir(previous)
        self.assertEqual(rc, contract.EXIT_OK)

    def test_characterized_estimator_self_test_is_preserved(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = imu_allan.self_test()
        self.assertEqual(rc, contract.EXIT_OK)
        self.assertIn("IMU Allan laboratory self-test: PASS", stdout.getvalue())

    def test_report_schema_outputs_and_candidate_boundary_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace = root / "imu.csv"
            prefix = root / "allan"
            imu_allan.write_fixture(trace)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = imu_allan_command.entrypoint(
                    [
                        str(trace),
                        "--min-pairs",
                        "2",
                        "--accel-g-per-count",
                        str(1.0 / 8192.0),
                        "--gyro-dps-per-count",
                        str(1.0 / 32.768),
                        "--scale-source",
                        "synthetic verified scale",
                        "--output-prefix",
                        str(prefix),
                    ]
                )
            self.assertEqual(rc, contract.EXIT_OK)
            json_path = Path(str(prefix) + ".allan.json")
            csv_path = Path(str(prefix) + ".allan.csv")
            markdown_path = Path(str(prefix) + ".allan.md")
            self.assertTrue(json_path.is_file())
            self.assertTrue(csv_path.is_file())
            self.assertTrue(markdown_path.is_file())

            report = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(report["schema"], imu_allan.REPORT_SCHEMA)
            self.assertEqual(
                report["method"]["name"],
                "streaming_dyadic_nonoverlapping_allan_deviation",
            )
            self.assertEqual(report["sample_period"]["source"], "measured first-to-last effective rate")
            self.assertEqual(report["scale_conversion"]["source"], "synthetic verified scale")
            self.assertIsNone(report["kalibr_candidate"])
            self.assertIn("candidate noise model is evidence", " ".join(report["guardrails"]))
            self.assertIn("IMU Allan Deviation / Noise Laboratory", stdout.getvalue())
            self.assertIn("IMU Allan Deviation / Noise Laboratory", markdown_path.read_text(encoding="utf-8"))

    def test_explicit_fit_windows_and_axis_policy_create_candidate_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace = Path(tmp) / "imu.csv"
            imu_allan.write_fixture(trace)
            report = imu_allan.analyze(
                trace,
                min_pairs=2,
                accel_g_per_count=1.0 / 8192.0,
                gyro_dps_per_count=1.0 / 32.768,
                scale_source="synthetic verified scale",
                white_window=(0.01, 0.04),
                random_walk_window=(0.08, 0.32),
                kalibr_axis_policy="max",
                sample_rate_hz=None,
                allow_invalid_samples=False,
                allow_timing_anomalies=False,
            )
            candidate = report["kalibr_candidate"]
            self.assertIsNotNone(candidate)
            self.assertEqual(candidate["status"], "candidate_only_not_promoted_to_calibration_artifact")
            self.assertEqual(candidate["axis_policy"], "max")
            self.assertEqual(report["fits_si"]["white_noise"]["accelerometer"]["expected_slope"], -0.5)
            self.assertEqual(report["fits_si"]["random_walk"]["gyroscope"]["expected_slope"], 0.5)

    def test_domain_errors_use_exit_two_not_evaluated_fail(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rc = imu_allan_command.entrypoint([])
        self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)
        self.assertNotEqual(rc, contract.EXIT_EVALUATED_FAIL)
        self.assertIn("IMU trace CSV path is required", stderr.getvalue())

        with tempfile.TemporaryDirectory() as tmp:
            trace = Path(tmp) / "imu.csv"
            imu_allan.write_fixture(trace)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rc = imu_allan_command.entrypoint(
                    [str(trace), "--accel-g-per-count", str(1.0 / 8192.0)]
                )
            self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)
            self.assertIn("scale-source", stderr.getvalue())

    def test_contract_metadata_matches_route_and_existing_semantics(self):
        self.assertEqual(len(contract.IMU_NOISE_COMMAND_CONTRACTS), 1)
        item = contract.IMU_NOISE_COMMAND_CONTRACTS[0]
        self.assertEqual(item.key, ("imu", "allan"))
        self.assertEqual(item.module, "bividi.calibration.imu_allan_command")
        self.assertEqual(item.compatibility_tool, "analyze_imu_allan.py")
        self.assertEqual(item.output_role, "machine-evidence-json-and-human-markdown")
        self.assertEqual(item.policy_role, "explicit-analysis-parameters-no-acceptance-gate")
        self.assertFalse(item.emits_versioned_provenance)
        self.assertIsNone(item.evaluated_fail_exit)
        self.assertEqual(contract.contract_for("imu", "allan"), item)


if __name__ == "__main__":
    unittest.main()
