from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bividi import calib_cli
from bividi.calibration import camera_imu_calibration_provenance as provenance
from bividi.calibration import camera_imu_provenance_command
from bividi.calibration import contract


class CameraImuPromotionPackageMigrationTests(unittest.TestCase):
    def test_cli_routes_without_source_checkout(self):
        invocation = calib_cli.build_invocation(
            "camera-imu",
            "promote",
            ["--self-test"],
            source_root=Path("/definitely/not/a/bividi/checkout"),
        )
        self.assertEqual(
            invocation,
            [sys.executable, "-m", "bividi.calibration.camera_imu_provenance_command", "--self-test"],
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
                        "promote",
                        "--self-test",
                    ]
                )
            finally:
                os.chdir(previous)
        self.assertEqual(rc, contract.EXIT_OK)

    def test_packaged_self_test_preserves_all_three_profiles_and_hash_guard(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            provenance.self_test()
        self.assertIn(
            "Camera-IMU calibration evidence promotion gate self-test: PASS",
            stdout.getvalue(),
        )

    def test_legacy_wrapper_still_runs_direct_self_test(self):
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(root / "tools" / "camera_imu_calibration_provenance.py"), "--self-test"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn(
            "Camera-IMU calibration evidence promotion gate self-test: PASS",
            completed.stdout,
        )

    def test_package_uses_package_native_artifact_validator(self):
        self.assertEqual(
            provenance.validate_calibration_artifact.__name__,
            "bividi.calibration.artifact_validator",
        )

    def test_exact_role_sets_remain_frozen(self):
        self.assertEqual(
            provenance.ROLE_SCHEMAS,
            {
                "dynamic_session": "bividi.calibration.kalibr_dynamic_session.v1",
                "excitation": "bividi.calibration.camera_imu_excitation.v1",
                "target_observations": "bividi.calibration.kalibr_target_observations.v1",
                "target_coverage": "bividi.calibration.kalibr_target_coverage.v1",
                "solver_quality": "bividi.calibration.kalibr_solver_quality.v1",
                "import_manifest": "bividi.calibration.kalibr_camera_imu_import.v1",
                "candidate": "bividi.calibration.camera_imu.v1",
                "time_review": "bividi.calibration.camera_imu_time_review.v1",
                "repeatability": "bividi.calibration.camera_imu_repeatability.v1",
            },
        )
        self.assertEqual(
            provenance.INPUT_ROLES,
            (
                "dynamic_session",
                "excitation",
                "target_coverage",
                "solver_quality",
                "import_manifest",
                "candidate",
                "time_review",
                "repeatability",
            ),
        )
        self.assertEqual(
            provenance.QUALITY_ROLES,
            ("excitation", "target_coverage", "solver_quality", "time_review", "repeatability"),
        )

    def test_historical_provenance_identity_is_preserved(self):
        self.assertEqual(Path(provenance.__file__).name, "camera_imu_calibration_provenance.py")
        self.assertEqual(provenance.TOOL_VERSION, "1")
        self.assertEqual(
            provenance.PINNED_KALIBR_REVISION,
            "1f60227442d25e36365ef5f72cd80b9666d73467",
        )

    def test_profile_semantics_preserve_integrity_review_promotion_boundary(self):
        evidence_only = {
            "excitation": {"assessment": {"status": "EVIDENCE_ONLY_NO_THRESHOLDS", "gates": []}},
            "target_coverage": {"assessment": {"status": "EVIDENCE_ONLY_NO_THRESHOLDS", "thresholds": {}}},
            "solver_quality": {
                "assessment": {"status": "EVIDENCE_ONLY_NO_THRESHOLDS", "gates": []},
                "source_contract": {"revision_mismatch_allowed": False},
            },
            "time_review": {"status": "EVIDENCE_ONLY_NO_THRESHOLDS", "gates": []},
            "repeatability": {"status": "EVIDENCE_ONLY_NO_THRESHOLDS", "gates": []},
            "target_observations": {
                "kalibr": {
                    "reviewed_revision": True,
                    "revision": provenance.PINNED_KALIBR_REVISION,
                }
            },
        }
        integrity = provenance.assess("integrity", evidence_only, "named policy")
        review = provenance.assess("review", evidence_only, "named policy")
        promotion = provenance.assess("promotion", evidence_only, "named policy")
        self.assertEqual(integrity["disposition"], "INTEGRITY_VERIFIED")
        self.assertEqual(review["disposition"], "REVIEW_READY")
        self.assertTrue(review["warnings"])
        self.assertEqual(promotion["status"], "FAIL")
        self.assertEqual(promotion["disposition"], "BLOCKED")
        self.assertTrue(any("explicit PASS" in item for item in promotion["failures"]))

    def test_promotion_requires_non_placeholder_policy_source(self):
        passing = {
            "excitation": {"assessment": {"status": "PASS", "gates": [{"name": "x"}]}},
            "target_coverage": {"assessment": {"status": "PASS", "thresholds": {"x": 1.0}}},
            "solver_quality": {
                "assessment": {"status": "PASS", "gates": [{"name": "x"}]},
                "source_contract": {"revision_mismatch_allowed": False},
            },
            "time_review": {"status": "PASS", "gates": [{"name": "x"}]},
            "repeatability": {"status": "PASS", "gates": [{"name": "x"}]},
            "target_observations": {
                "kalibr": {
                    "reviewed_revision": True,
                    "revision": provenance.PINNED_KALIBR_REVISION,
                }
            },
        }
        blocked = provenance.assess("promotion", passing, "TBD")
        ready = provenance.assess("promotion", passing, "lab policy CAMIMU-001")
        self.assertEqual(blocked["status"], "FAIL")
        self.assertTrue(any("policy_source" in item for item in blocked["failures"]))
        self.assertEqual(ready["disposition"], "PROMOTION_READY")

    def test_missing_manifest_domain_failure_maps_to_exit_two(self):
        rc = camera_imu_provenance_command.entrypoint(
            ["verify", "/definitely/missing/camera-imu-manifest.json", "--profile", "integrity"]
        )
        self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)

    def test_historical_completed_fail_exit_maps_to_three(self):
        with mock.patch.object(provenance, "main", return_value=4):
            rc = camera_imu_provenance_command.entrypoint(["verify", "unused"])
        self.assertEqual(rc, contract.EXIT_EVALUATED_FAIL)

    def test_historical_domain_exit_maps_to_two(self):
        with mock.patch.object(provenance, "main", return_value=3):
            rc = camera_imu_provenance_command.entrypoint(["verify", "unused"])
        self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)

    def test_contract_metadata_records_promotion_policy_ownership(self):
        item = contract.contract_for("camera-imu", "promote")
        self.assertEqual(item.module, "bividi.calibration.camera_imu_provenance_command")
        self.assertEqual(item.compatibility_tool, "camera_imu_calibration_provenance.py")
        self.assertEqual(item.output_role, "evidence-manifest-and-verification-report")
        self.assertEqual(item.policy_role, "promotion-requires-manifest-and-evidence-policy")
        self.assertTrue(item.emits_versioned_provenance)
        self.assertEqual(item.tool_version, "1")
        self.assertEqual(item.evaluated_fail_exit, contract.EXIT_EVALUATED_FAIL)


if __name__ == "__main__":
    unittest.main()
