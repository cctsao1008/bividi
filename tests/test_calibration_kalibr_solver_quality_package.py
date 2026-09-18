from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bividi import calib_cli
from bividi.calibration import contract
from bividi.calibration import kalibr_solver_quality as solver_quality
from bividi.calibration import kalibr_solver_quality_command


class KalibrSolverQualityPackageMigrationTests(unittest.TestCase):
    def test_cli_routes_without_source_checkout(self):
        invocation = calib_cli.build_invocation(
            "camera-imu",
            "solver-quality",
            ["--self-test"],
            source_root=Path("/definitely/not/a/bividi/checkout"),
        )
        self.assertEqual(
            invocation,
            [sys.executable, "-m", "bividi.calibration.kalibr_solver_quality_command", "--self-test"],
        )

    def test_cli_executes_self_test_outside_source_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = Path.cwd()
            os.chdir(tmp)
            try:
                rc = calib_cli.main(
                    [
                        "--source-root",
                        "/definitely/not/a/bividi/checkout",
                        "camera-imu",
                        "solver-quality",
                        "--self-test",
                    ]
                )
            finally:
                os.chdir(previous)
        self.assertEqual(rc, contract.EXIT_OK)

    def test_packaged_self_test_preserves_characterized_behavior(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            solver_quality.self_test()
        self.assertIn("Kalibr IMU-camera solver quality self-test: PASS", stdout.getvalue())

    def test_legacy_wrapper_still_runs_direct_self_test(self):
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(root / "tools" / "analyze_kalibr_solver_quality.py"), "--self-test"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("Kalibr IMU-camera solver quality self-test: PASS", completed.stdout)

    def test_evidence_only_completion_is_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session, results = solver_quality.write_fixture(root)
            rc = kalibr_solver_quality_command.entrypoint(
                [str(session), str(results), "--output-prefix", str(root / "quality")]
            )
        self.assertEqual(rc, contract.EXIT_OK)

    def test_completed_explicit_gate_fail_is_exit_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session, results = solver_quality.write_fixture(root)
            rc = kalibr_solver_quality_command.entrypoint(
                [
                    str(session),
                    str(results),
                    "--output-prefix",
                    str(root / "quality"),
                    "--max-reprojection-mean-px",
                    "0.21",
                ]
            )
        self.assertEqual(rc, contract.EXIT_EVALUATED_FAIL)

    def test_structural_no_corners_fail_is_exit_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session, results = solver_quality.write_fixture(root, no_corners=True)
            rc = kalibr_solver_quality_command.entrypoint(
                [str(session), str(results), "--output-prefix", str(root / "quality")]
            )
        self.assertEqual(rc, contract.EXIT_EVALUATED_FAIL)

    def test_revision_domain_failure_is_exit_two_not_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session, results = solver_quality.write_fixture(root, revision="different")
            rc = kalibr_solver_quality_command.entrypoint(
                [str(session), str(results), "--output-prefix", str(root / "quality")]
            )
        self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)
        self.assertNotEqual(rc, contract.EXIT_EVALUATED_FAIL)

    def test_historical_schema_provenance_and_source_contract_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session, results = solver_quality.write_fixture(root)
            report = solver_quality.analyze(
                session,
                results,
                thresholds={
                    "max_reprojection_mean_px": None,
                    "max_reprojection_rms_px": None,
                    "max_gyro_mean_rad_s": None,
                    "max_gyro_rms_rad_s": None,
                    "max_accel_mean_m_s2": None,
                    "max_accel_rms_m_s2": None,
                    "max_normalized_reprojection_mean": None,
                    "max_normalized_gyro_mean": None,
                    "max_normalized_accel_mean": None,
                },
            )
        self.assertEqual(report["schema"], "bividi.calibration.kalibr_solver_quality.v1")
        self.assertEqual(report["provenance"]["tool"], "analyze_kalibr_solver_quality.py")
        self.assertEqual(report["provenance"]["tool_version"], "1")
        self.assertEqual(report["source_contract"]["backend"], "ethz-asl/kalibr")
        self.assertEqual(report["source_contract"]["verified_revision"], solver_quality.PINNED_REVISION)
        self.assertIn("printErrorStatistics", report["source_contract"]["source"])
        self.assertEqual(report["assessment"]["status"], "EVIDENCE_ONLY_NO_THRESHOLDS")

    def test_contract_metadata_records_solver_fit_boundary(self):
        item = contract.contract_for("camera-imu", "solver-quality")
        self.assertEqual(item.module, "bividi.calibration.kalibr_solver_quality_command")
        self.assertEqual(item.compatibility_tool, "analyze_kalibr_solver_quality.py")
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
