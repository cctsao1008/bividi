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
from bividi.calibration import contract, imu_stationary, imu_timing


class ImuPackageMigrationTests(unittest.TestCase):
    def test_cli_routes_package_native_modules_without_source_checkout(self):
        expected = {
            "timing-audit": "bividi.calibration.imu_timing",
            "stationary": "bividi.calibration.imu_stationary",
        }
        for command, module in expected.items():
            with self.subTest(command=command):
                invocation = calib_cli.build_invocation(
                    "imu",
                    command,
                    ["--self-test"],
                    source_root=Path("/definitely/not/a/bividi/checkout"),
                )
                self.assertEqual(invocation, [sys.executable, "-m", module, "--self-test"])

    def test_cli_executes_both_modules_outside_source_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = Path.cwd()
            os.chdir(tmp)
            try:
                for command in ("timing-audit", "stationary"):
                    with self.subTest(command=command):
                        rc = calib_cli.main(
                            [
                                "--source-root",
                                "/definitely/not/a/bividi/checkout",
                                "imu",
                                command,
                                "--self-test",
                            ]
                        )
                        self.assertEqual(rc, 0)
            finally:
                os.chdir(previous)

    def test_timing_audit_preserves_schema_and_interpretation_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace = root / "imu.csv"
            json_out = root / "timing.json"
            markdown_out = root / "timing.md"
            imu_timing.write_fixture(trace)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = imu_timing.entrypoint(
                    [
                        str(trace),
                        "--gap-threshold-us",
                        "3000",
                        "--json-out",
                        str(json_out),
                        "--markdown-out",
                        str(markdown_out),
                    ]
                )
            self.assertEqual(rc, contract.EXIT_OK)
            report = json.loads(json_out.read_text(encoding="utf-8"))
            self.assertEqual(report["schema"], imu_timing.REPORT_SCHEMA)
            self.assertEqual(report["imu"]["interval_us"]["p50"], 2500.0)
            self.assertEqual(report["imu"]["gaps_over_threshold"], 0)
            self.assertEqual(
                report["nearest_imu_to_exposure_end"]["absolute_us"]["p50"],
                500.0,
            )
            self.assertIn("not by themselves a calibrated camera-IMU temporal offset", report["interpretation_note"])
            self.assertIn("Camera↔IMU Timestamp Audit", markdown_out.read_text(encoding="utf-8"))
            self.assertIn("Camera↔IMU Timestamp Audit", stdout.getvalue())

    def test_stationary_uses_packaged_timing_and_requires_explicit_scale_source(self):
        self.assertEqual(imu_stationary.imu_timing.__name__, "bividi.calibration.imu_timing")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace = root / "stationary.csv"
            json_out = root / "stationary.json"
            imu_stationary.write_fixture(trace)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = imu_stationary.entrypoint(
                    [
                        str(trace),
                        "--accel-g-per-count",
                        str(1.0 / 8192.0),
                        "--gyro-dps-per-count",
                        str(1.0 / 32.768),
                        "--scale-source",
                        "fixture scale",
                        "--json-out",
                        str(json_out),
                    ]
                )
            self.assertEqual(rc, contract.EXIT_OK)
            report = json.loads(json_out.read_text(encoding="utf-8"))
            self.assertEqual(report["schema"], imu_stationary.REPORT_SCHEMA)
            self.assertEqual(report["sample_count"], 8)
            self.assertEqual(report["scale_conversion"]["source"], "fixture scale")
            self.assertAlmostEqual(
                report["scale_conversion"]["accelerometer_m_s2"]["z"]["mean"],
                imu_stationary.GRAVITY_M_S2,
            )
            self.assertIn("contains gravity", report["interpretation_note"])

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rc = imu_stationary.entrypoint(
                    [str(trace), "--accel-g-per-count", str(1.0 / 8192.0)]
                )
            self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)
            self.assertIn("scale-source", stderr.getvalue())

    def test_domain_errors_use_exit_two_not_evaluated_fail(self):
        for module in (imu_timing, imu_stationary):
            with self.subTest(module=module.__name__):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    rc = module.entrypoint([])
                self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)
                self.assertNotEqual(rc, contract.EXIT_EVALUATED_FAIL)
                self.assertTrue(stderr.getvalue())

    def test_imu_contract_metadata_matches_routes_and_semantics(self):
        by_name = {item.name: item for item in contract.IMU_COMMAND_CONTRACTS}
        self.assertEqual(set(by_name), {"timing-audit", "stationary"})
        for name, item in by_name.items():
            with self.subTest(command=name):
                routed = calib_cli.resolve_command("imu", name)
                self.assertIsNone(routed.script)
                self.assertEqual(routed.module, item.module)
                self.assertEqual(
                    item.output_role,
                    "machine-evidence-json-and-human-markdown",
                )
                self.assertFalse(item.emits_versioned_provenance)
                self.assertIsNone(item.evaluated_fail_exit)

        self.assertEqual(
            by_name["timing-audit"].policy_role,
            "analysis-parameter-no-acceptance-gate",
        )
        self.assertEqual(
            by_name["stationary"].policy_role,
            "explicit-scale-source-no-acceptance-gate",
        )
        self.assertEqual(
            contract.contract_for("imu", "timing-audit").module,
            "bividi.calibration.imu_timing",
        )


if __name__ == "__main__":
    unittest.main()
