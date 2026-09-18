from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bividi import calib_cli
from bividi.calibration import camera_imu_temporal_review as temporal_review
from bividi.calibration import camera_imu_temporal_review_command
from bividi.calibration import contract


class CameraImuTemporalReviewPackageMigrationTests(unittest.TestCase):
    def test_cli_routes_without_source_checkout(self):
        invocation = calib_cli.build_invocation(
            "camera-imu",
            "temporal-review",
            ["--self-test"],
            source_root=Path("/definitely/not/a/bividi/checkout"),
        )
        self.assertEqual(
            invocation,
            [sys.executable, "-m", "bividi.calibration.camera_imu_temporal_review_command", "--self-test"],
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
                        "temporal-review",
                        "--self-test",
                    ]
                )
            finally:
                os.chdir(previous)
        self.assertEqual(rc, contract.EXIT_OK)

    def test_packaged_self_test_preserves_characterized_behavior(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            temporal_review.self_test()
        self.assertIn("Camera-IMU temporal evidence review self-test: PASS", stdout.getvalue())

    def test_legacy_wrapper_still_runs_direct_self_test(self):
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(root / "tools" / "review_camera_imu_time_offset.py"), "--self-test"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("Camera-IMU temporal evidence review self-test: PASS", completed.stdout)

    def test_package_uses_package_native_timing_and_validator(self):
        self.assertEqual(
            temporal_review.audit_imu_timing.__name__,
            "bividi.calibration.imu_timing",
        )
        self.assertEqual(
            temporal_review.validate_calibration_artifact.__name__,
            "bividi.calibration.artifact_validator",
        )

    def test_evidence_only_completion_is_exit_zero_and_preserves_time_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session, artifact = temporal_review.write_fixture(root)
            report = temporal_review.analyze(
                session,
                artifact,
                max_abs_shift_us=None,
                max_shifted_nearest_p95_us=None,
            )
            rc = camera_imu_temporal_review_command.entrypoint([str(session), str(artifact)])
        self.assertEqual(rc, contract.EXIT_OK)
        self.assertEqual(report["schema"], "bividi.calibration.camera_imu_time_review.v1")
        self.assertEqual(report["status"], "EVIDENCE_ONLY_NO_THRESHOLDS")
        self.assertEqual(report["clock_domain"], "DECXIN extended device microseconds")
        self.assertEqual(report["camera_time_reference"], "exposure_midpoint")
        self.assertEqual(
            report["time_offset"]["definition"],
            "t_imu_s = t_camera_reference_s + offset_s",
        )
        self.assertAlmostEqual(report["time_offset"]["kalibr_offset_us"], 250.0)
        self.assertIn("nearest_imu_before_shift", report)
        self.assertIn("nearest_imu_after_applying_kalibr_shift", report)

    def test_completed_explicit_gate_fail_is_exit_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session, artifact = temporal_review.write_fixture(root)
            rc = camera_imu_temporal_review_command.entrypoint(
                [str(session), str(artifact), "--max-abs-shift-us", "100"]
            )
        self.assertEqual(rc, contract.EXIT_EVALUATED_FAIL)

    def test_hash_domain_failure_is_exit_two_not_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session, artifact = temporal_review.write_fixture(root)
            session_data = json.loads(session.read_text(encoding="utf-8"))
            trace = Path(session_data["sources"]["raw_imu_csv"]["path"])
            trace.write_text(trace.read_text(encoding="utf-8") + "# tampered\n", encoding="utf-8")
            rc = camera_imu_temporal_review_command.entrypoint([str(session), str(artifact)])
        self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)
        self.assertNotEqual(rc, contract.EXIT_EVALUATED_FAIL)

    def test_timestamp_semantic_mismatch_is_exit_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session, artifact = temporal_review.write_fixture(root)
            artifact_data = json.loads(artifact.read_text(encoding="utf-8"))
            artifact_data["time_offset"]["camera_time_reference"] = "exposure_start"
            artifact.write_text(json.dumps(artifact_data), encoding="utf-8")
            rc = camera_imu_temporal_review_command.entrypoint([str(session), str(artifact)])
        self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)

    def test_output_write_failure_is_exit_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session, artifact = temporal_review.write_fixture(root)
            blocker = root / "blocker"
            blocker.write_text("not a directory", encoding="utf-8")
            rc = camera_imu_temporal_review_command.entrypoint(
                [
                    str(session),
                    str(artifact),
                    "--output-prefix",
                    str(blocker / "review"),
                ]
            )
        self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)

    def test_contract_metadata_records_temporal_evidence_boundary(self):
        item = contract.contract_for("camera-imu", "temporal-review")
        self.assertEqual(item.module, "bividi.calibration.camera_imu_temporal_review_command")
        self.assertEqual(item.compatibility_tool, "review_camera_imu_time_offset.py")
        self.assertEqual(item.output_role, "machine-evidence-json-and-human-markdown")
        self.assertEqual(item.policy_role, "explicit-operator-gates-no-default-thresholds")
        self.assertFalse(item.emits_versioned_provenance)
        self.assertIsNone(item.tool_version)
        self.assertEqual(item.evaluated_fail_exit, contract.EXIT_EVALUATED_FAIL)


if __name__ == "__main__":
    unittest.main()
