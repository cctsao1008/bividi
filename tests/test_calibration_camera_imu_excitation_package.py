from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

from bividi import calib_cli
from bividi.calibration import camera_imu_excitation, camera_imu_excitation_command, contract


class CameraImuExcitationPackageMigrationTests(unittest.TestCase):
    def test_cli_routes_installed_excitation_without_source_checkout(self):
        invocation = calib_cli.build_invocation(
            "camera-imu",
            "excitation",
            ["--self-test"],
            source_root=Path("/definitely/not/a/bividi/checkout"),
        )
        self.assertEqual(
            invocation,
            [sys.executable, "-m", "bividi.calibration.camera_imu_excitation_command", "--self-test"],
        )

    def test_cli_executes_excitation_self_test_outside_source_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = Path.cwd()
            os.chdir(tmp)
            try:
                rc = calib_cli.main(
                    [
                        "--source-root",
                        "/definitely/not/a/bividi/checkout",
                        "camera-imu",
                        "excitation",
                        "--self-test",
                    ]
                )
            finally:
                os.chdir(previous)
        self.assertEqual(rc, contract.EXIT_OK)

    def test_packaged_evaluator_preserves_characterized_self_test(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            camera_imu_excitation.self_test()
        self.assertIn("Camera-IMU dynamic excitation laboratory self-test: PASS", stdout.getvalue())

    def test_evidence_only_and_provenance_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = camera_imu_excitation.write_fixture(Path(tmp))
            report = camera_imu_excitation.analyze(session, camera_imu_excitation.empty_args())
        self.assertEqual(report["schema"], camera_imu_excitation.SCHEMA)
        self.assertEqual(report["assessment"]["status"], "EVIDENCE_ONLY_NO_THRESHOLDS")
        self.assertEqual(
            report["interpretation"]["claim"],
            "excitation_and_coverage_proxy_evidence_not_formal_observability_proof",
        )
        self.assertEqual(report["provenance"]["tool"], "analyze_camera_imu_excitation.py")
        self.assertEqual(report["provenance"]["tool_version"], "1")

    def test_completed_explicit_fail_maps_to_exit_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = camera_imu_excitation.write_fixture(root, one_axis_gyro=True)
            rc = camera_imu_excitation_command.entrypoint(
                [
                    str(session),
                    "--min-gyro-smallest-energy-fraction",
                    "0.01",
                    "--output-prefix",
                    str(root / "failed"),
                ]
            )
        self.assertEqual(rc, contract.EXIT_EVALUATED_FAIL)

    def test_domain_failure_maps_to_exit_two(self):
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(stderr):
            rc = camera_imu_excitation_command.entrypoint([str(Path(tmp) / "missing.json")])
        self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)
        self.assertNotEqual(rc, contract.EXIT_EVALUATED_FAIL)
        self.assertIn("analysis failed", stderr.getvalue())

    def test_contract_metadata_records_excitation_boundary(self):
        item = contract.contract_for("camera-imu", "excitation")
        self.assertEqual(item.module, "bividi.calibration.camera_imu_excitation_command")
        self.assertEqual(item.compatibility_tool, "analyze_camera_imu_excitation.py")
        self.assertEqual(item.output_role, "machine-evidence-json-and-human-markdown")
        self.assertEqual(
            item.policy_role,
            "explicit-operator-gates-with-structural-fail-no-default-thresholds",
        )
        self.assertTrue(item.emits_versioned_provenance)
        self.assertEqual(item.tool_version, "1")
        self.assertEqual(item.evaluated_fail_exit, contract.EXIT_EVALUATED_FAIL)


if __name__ == "__main__":
    unittest.main()
