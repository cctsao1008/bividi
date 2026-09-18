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
from bividi.calibration import camera_imu_repeatability as repeatability
from bividi.calibration import camera_imu_repeatability_command
from bividi.calibration import contract


class CameraImuRepeatabilityPackageMigrationTests(unittest.TestCase):
    def test_cli_routes_without_source_checkout(self):
        invocation = calib_cli.build_invocation(
            "camera-imu",
            "repeatability",
            ["--self-test"],
            source_root=Path("/definitely/not/a/bividi/checkout"),
        )
        self.assertEqual(
            invocation,
            [sys.executable, "-m", "bividi.calibration.camera_imu_repeatability_command", "--self-test"],
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
                        "repeatability",
                        "--self-test",
                    ]
                )
            finally:
                os.chdir(previous)
        self.assertEqual(rc, contract.EXIT_OK)

    def test_packaged_self_test_preserves_characterized_behavior(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            repeatability.self_test()
        self.assertIn("Camera-IMU repeatability comparator self-test: PASS", stdout.getvalue())

    def test_legacy_wrapper_still_runs_direct_self_test(self):
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(root / "tools" / "compare_camera_imu_calibrations.py"), "--self-test"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("Camera-IMU repeatability comparator self-test: PASS", completed.stdout)

    def test_package_uses_package_native_artifact_validator(self):
        self.assertEqual(
            repeatability.validate_calibration_artifact.__name__,
            "bividi.calibration.artifact_validator",
        )

    @staticmethod
    def _three_runs(root: Path) -> list[Path]:
        paths = [root / f"run{i}.json" for i in range(3)]
        repeatability.fixture_artifact(paths[0], "run0", 0.0100, 0.00, -1500.0)
        repeatability.fixture_artifact(paths[1], "run1", 0.0104, 0.05, -1480.0)
        repeatability.fixture_artifact(paths[2], "run2", 0.0098, -0.04, -1525.0)
        return paths

    def test_evidence_only_preserves_pairwise_math_and_no_consensus(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._three_runs(Path(tmp))
            report = repeatability.compare(
                paths,
                allow_backend_revision_mismatch=False,
                max_pairwise_translation_mm=None,
                max_pairwise_rotation_deg=None,
                max_pairwise_time_offset_us=None,
            )
            rc = camera_imu_repeatability_command.entrypoint([str(path) for path in paths])
        self.assertEqual(rc, contract.EXIT_OK)
        self.assertEqual(report["schema"], "bividi.calibration.camera_imu_repeatability.v1")
        self.assertEqual(report["status"], "EVIDENCE_ONLY_NO_THRESHOLDS")
        self.assertEqual(report["run_count"], 3)
        self.assertEqual(report["pair_count"], 3)
        self.assertEqual(len(report["pairwise"]), 3)
        self.assertIn("pairwise_translation_mm", report["summary"])
        self.assertIn("pairwise_rotation_deg", report["summary"])
        self.assertIn("pairwise_time_offset_us", report["summary"])
        self.assertNotIn("consensus", report)
        self.assertNotIn("average_transform", report)

    def test_completed_explicit_gate_fail_maps_to_exit_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._three_runs(Path(tmp))
            rc = camera_imu_repeatability_command.entrypoint(
                [
                    *(str(path) for path in paths),
                    "--max-pairwise-translation-mm",
                    "0.1",
                ]
            )
        self.assertEqual(rc, contract.EXIT_EVALUATED_FAIL)

    def test_incompatible_specimen_is_domain_exit_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "a.json"
            b = root / "b.json"
            repeatability.fixture_artifact(a, "a", 0.0100, 0.0, -1500.0)
            repeatability.fixture_artifact(b, "b", 0.0101, 0.0, -1500.0, serial="OTHER")
            rc = camera_imu_repeatability_command.entrypoint([str(a), str(b)])
        self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)

    def test_duplicate_content_is_domain_exit_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "a.json"
            b = root / "b.json"
            repeatability.fixture_artifact(a, "same", 0.0100, 0.0, -1500.0)
            b.write_bytes(a.read_bytes())
            rc = camera_imu_repeatability_command.entrypoint([str(a), str(b)])
        self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)

    def test_backend_revision_mismatch_requires_explicit_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "a.json"
            b = root / "b.json"
            repeatability.fixture_artifact(a, "a", 0.0100, 0.0, -1500.0)
            repeatability.fixture_artifact(b, "b", 0.0101, 0.0, -1490.0)
            data = json.loads(b.read_text(encoding="utf-8"))
            data["provenance"]["external_backend_revision"] = "different"
            b.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            rejected = camera_imu_repeatability_command.entrypoint([str(a), str(b)])
            allowed = camera_imu_repeatability_command.entrypoint(
                [str(a), str(b), "--allow-backend-revision-mismatch"]
            )
        self.assertEqual(rejected, contract.EXIT_USAGE_OR_DOMAIN_ERROR)
        self.assertEqual(allowed, contract.EXIT_OK)

    def test_output_write_failure_is_domain_exit_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._three_runs(root)
            blocker = root / "blocker"
            blocker.write_text("not a directory", encoding="utf-8")
            rc = camera_imu_repeatability_command.entrypoint(
                [
                    *(str(path) for path in paths),
                    "--output-prefix",
                    str(blocker / "repeatability"),
                ]
            )
        self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)

    def test_contract_metadata_records_repeatability_boundary(self):
        item = contract.contract_for("camera-imu", "repeatability")
        self.assertEqual(item.module, "bividi.calibration.camera_imu_repeatability_command")
        self.assertEqual(item.compatibility_tool, "compare_camera_imu_calibrations.py")
        self.assertEqual(item.output_role, "machine-evidence-json-and-human-markdown")
        self.assertEqual(item.policy_role, "explicit-operator-gates-no-default-thresholds")
        self.assertFalse(item.emits_versioned_provenance)
        self.assertIsNone(item.tool_version)
        self.assertEqual(item.evaluated_fail_exit, contract.EXIT_EVALUATED_FAIL)


if __name__ == "__main__":
    unittest.main()
