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
from bividi.calibration import artifact_validator
from bividi.calibration import contract
from bividi.calibration import kalibr_camera_imu_import as importer
from bividi.calibration import kalibr_camera_imu_import_command


class KalibrCameraImuImportPackageMigrationTests(unittest.TestCase):
    def test_cli_routes_import_without_source_checkout(self):
        invocation = calib_cli.build_invocation(
            "camera-imu",
            "import-kalibr",
            ["--self-test"],
            source_root=Path("/definitely/not/a/bividi/checkout"),
        )
        self.assertEqual(
            invocation,
            [sys.executable, "-m", "bividi.calibration.kalibr_camera_imu_import_command", "--self-test"],
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
                        "import-kalibr",
                        "--self-test",
                    ]
                )
            finally:
                os.chdir(previous)
        self.assertEqual(rc, contract.EXIT_OK)

    def test_packaged_self_test_preserves_candidate_semantics(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            importer.self_test()
        self.assertIn("Kalibr camera-IMU result importer self-test: PASS", stdout.getvalue())

    def test_legacy_wrapper_still_runs_direct_self_test(self):
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(root / "tools" / "import_kalibr_camera_imu.py"), "--self-test"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("Kalibr camera-IMU result importer self-test: PASS", completed.stdout)

    def test_package_uses_package_native_artifact_validator(self):
        self.assertIs(importer.validate_calibration_artifact, artifact_validator)

    def test_candidate_artifact_and_sidecar_remain_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session, result = importer.write_fixture(root)
            artifact, sidecar = importer.build_artifact(
                session,
                result,
                camera="cam0",
                camera_frame=None,
                camera_axes="explicit synthetic right-handed camera convention",
                calibration_id="camera-imu-synth",
                external_container="kalibr:test-container",
                solver_report=None,
            )
        self.assertEqual(artifact["schema"], importer.OUTPUT_SCHEMA)
        self.assertEqual(artifact["transform"]["from_frame"], "imu")
        self.assertEqual(artifact["transform"]["to_frame"], "camera_a")
        self.assertEqual(artifact["transform"]["translation_unit"], "m")
        self.assertAlmostEqual(artifact["transform"]["matrix"][0][3], 0.01)
        self.assertEqual(artifact["time_offset"]["definition"], importer.TIME_OFFSET_DEFINITION)
        self.assertEqual(artifact["time_offset"]["camera_time_reference"], "exposure_midpoint")
        self.assertAlmostEqual(artifact["time_offset"]["offset_s"], -0.0015)
        self.assertEqual(artifact["provenance"]["kind"], "imported")
        self.assertEqual(artifact["provenance"]["tool"], "import_kalibr_camera_imu.py")
        self.assertEqual(artifact["provenance"]["tool_version"], "1")
        self.assertEqual(artifact["provenance"]["external_backend"], "ethz-asl/kalibr")
        self.assertEqual(artifact["provenance"]["external_backend_container"], "kalibr:test-container")
        self.assertEqual(sidecar["schema"], importer.IMPORT_SCHEMA)
        self.assertEqual(sidecar["status"], "imported_candidate_requires_review")
        self.assertIn("imu -> camera_a", sidecar["transform_definition"])

    def test_optional_solver_report_is_hash_bound_but_not_promoted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session, result = importer.write_fixture(root)
            solver_report = root / "solver-report.txt"
            solver_report.write_text("synthetic solver diagnostics\n", encoding="utf-8")
            artifact, sidecar = importer.build_artifact(
                session,
                result,
                camera="cam0",
                camera_frame=None,
                camera_axes="explicit synthetic right-handed camera convention",
                calibration_id="camera-imu-synth",
                external_container=None,
                solver_report=solver_report,
            )
            expected_hash = importer.sha256_file(solver_report)
        self.assertEqual(sidecar["solver_report"]["sha256"], expected_hash)
        self.assertTrue(any(expected_hash in note for note in artifact["quality"]["notes"]))
        self.assertEqual(sidecar["status"], "imported_candidate_requires_review")

    def test_domain_failure_is_exit_two_not_evaluated_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session, _ = importer.write_fixture(root)
            rc = kalibr_camera_imu_import_command.entrypoint(
                [
                    str(session),
                    str(root / "missing-result.yaml"),
                    "--camera-axes",
                    "explicit synthetic right-handed camera convention",
                    "--calibration-id",
                    "candidate",
                    "--output",
                    str(root / "candidate.json"),
                ]
            )
        self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)
        self.assertNotEqual(rc, contract.EXIT_EVALUATED_FAIL)

    def test_usage_failure_is_exit_two(self):
        rc = kalibr_camera_imu_import_command.entrypoint([])
        self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)

    def test_contract_metadata_records_candidate_import_boundary(self):
        item = contract.contract_for("camera-imu", "import-kalibr")
        self.assertEqual(item.module, "bividi.calibration.kalibr_camera_imu_import_command")
        self.assertEqual(item.compatibility_tool, "import_kalibr_camera_imu.py")
        self.assertEqual(item.output_role, "calibration-artifact-and-import-manifest")
        self.assertEqual(item.policy_role, "candidate-import-no-acceptance-gate")
        self.assertTrue(item.emits_versioned_provenance)
        self.assertEqual(item.tool_version, "1")
        self.assertIsNone(item.evaluated_fail_exit)


if __name__ == "__main__":
    unittest.main()
