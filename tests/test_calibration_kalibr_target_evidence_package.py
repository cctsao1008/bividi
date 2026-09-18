from __future__ import annotations

import contextlib
import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bividi import calib_cli
from bividi.calibration import (
    analyze_kalibr_target_coverage as target_coverage,
    contract,
    export_kalibr_target_observations as target_observations,
    kalibr_target_coverage_command,
    kalibr_target_observations_command,
)


class KalibrTargetEvidencePackageMigrationTests(unittest.TestCase):
    def test_cli_routes_both_target_commands_without_source_checkout(self):
        source_root = Path("/definitely/not/a/bividi/checkout")
        observations = calib_cli.build_invocation(
            "camera-imu", "target-observations", ["--self-test"], source_root=source_root
        )
        coverage = calib_cli.build_invocation(
            "camera-imu", "target-coverage", ["--self-test"], source_root=source_root
        )
        self.assertEqual(
            observations,
            [sys.executable, "-m", "bividi.calibration.kalibr_target_observations_command", "--self-test"],
        )
        self.assertEqual(
            coverage,
            [sys.executable, "-m", "bividi.calibration.kalibr_target_coverage_command", "--self-test"],
        )

    def test_cli_executes_both_self_tests_outside_source_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = Path.cwd()
            os.chdir(tmp)
            try:
                observation_rc = calib_cli.main(
                    [
                        "--source-root",
                        "/definitely/not/a/bividi/checkout",
                        "camera-imu",
                        "target-observations",
                        "--self-test",
                    ]
                )
                coverage_rc = calib_cli.main(
                    [
                        "--source-root",
                        "/definitely/not/a/bividi/checkout",
                        "camera-imu",
                        "target-coverage",
                        "--self-test",
                    ]
                )
            finally:
                os.chdir(previous)
        self.assertEqual(observation_rc, contract.EXIT_OK)
        self.assertEqual(coverage_rc, contract.EXIT_OK)

    def test_packaged_self_tests_preserve_characterized_behavior(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            target_observations.self_test()
            target_coverage.self_test()
        text = stdout.getvalue()
        self.assertIn("Kalibr target-observation adapter contract self-test: PASS", text)
        self.assertIn("Kalibr target coverage analyzer self-test: PASS", text)

    def test_legacy_wrappers_still_run_direct_self_tests(self):
        root = Path(__file__).resolve().parents[1]
        for tool in ("export_kalibr_target_observations.py", "analyze_kalibr_target_coverage.py"):
            completed = subprocess.run(
                [sys.executable, str(root / "tools" / tool), "--self-test"],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("PASS", completed.stdout)

    def _write_observation_session(self, root: Path, *, revision: str | None = None) -> Path:
        for name in ("a0.png", "a1.png", "b0.png", "b1.png"):
            (root / name).write_bytes(b"synthetic")
        for camera, prefix in (("camera_a", "a"), ("camera_b", "b")):
            path = root / f"{camera}.csv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["timestamp_ns", "image_path", "frame_index", "frame_sequence"])
                writer.writerow([1000, f"{prefix}0.png", 0, 10])
                writer.writerow([2000, f"{prefix}1.png", 1, 11])
        (root / "camchain.yaml").write_text("synthetic\n", encoding="utf-8")
        (root / "target.yaml").write_text("synthetic\n", encoding="utf-8")
        session = root / "session.json"
        session.write_text(
            json.dumps(
                {
                    "schema": target_observations.SESSION_SCHEMA,
                    "kalibr": {
                        "revision": revision or target_observations.PINNED_KALIBR_REVISION,
                    },
                    "staged": {
                        "camera_a_csv": "camera_a.csv",
                        "camera_b_csv": "camera_b.csv",
                        "camchain_yaml": "camchain.yaml",
                        "target_yaml": "target.yaml",
                    },
                }
            ),
            encoding="utf-8",
        )
        return session

    def test_target_observation_external_runtime_failure_is_domain_exit_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = self._write_observation_session(root)
            stdout = io.StringIO()
            with mock.patch.object(
                target_observations,
                "load_kalibr_runtime",
                side_effect=target_observations.ExportError("Kalibr runtime unavailable for test"),
            ), contextlib.redirect_stdout(stdout):
                rc = kalibr_target_observations_command.entrypoint(
                    [str(session), "--output-prefix", str(root / "observations")]
                )
        self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)
        self.assertNotEqual(rc, contract.EXIT_EVALUATED_FAIL)
        self.assertIn("Kalibr runtime unavailable", stdout.getvalue())

    def test_target_observation_rejects_unreviewed_revision_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = self._write_observation_session(root, revision="unreviewed-test-revision")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = kalibr_target_observations_command.entrypoint(
                    [str(session), "--output-prefix", str(root / "observations")]
                )
        self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)
        self.assertIn("not reviewed pin", stdout.getvalue())

    def _write_coverage_fixture(self, root: Path) -> Path:
        detections = root / "detections.csv"
        corners = root / "corners.csv"
        with detections.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(
                [
                    "camera", "timestamp_ns", "frame_index", "frame_sequence", "image_width", "image_height",
                    "success", "corner_count", "min_x_px", "max_x_px", "min_y_px", "max_y_px",
                    "centroid_x_px", "centroid_y_px",
                ]
            )
            for camera in target_coverage.CAMERAS:
                writer.writerow([camera, 1000, 0, 10, 101, 101, "true", 4, 10, 30, 10, 30, 20, 20])
                writer.writerow([camera, 2000, 1, 11, 101, 101, "false", 0, "", "", "", "", "", ""])
        with corners.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(
                [
                    "camera", "timestamp_ns", "frame_index", "frame_sequence", "image_width", "image_height",
                    "corner_id", "x_px", "y_px",
                ]
            )
            points = [(0, 10, 10), (1, 30, 10), (2, 30, 30), (3, 10, 30)]
            for camera in target_coverage.CAMERAS:
                for corner_id, x_px, y_px in points:
                    writer.writerow([camera, 1000, 0, 10, 101, 101, corner_id, x_px, y_px])
        manifest = root / "observations.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema": target_coverage.INPUT_SCHEMA,
                    "target": {"corner_count": 4},
                    "kalibr": {"revision": "test"},
                    "artifacts": {
                        "detections_csv": {
                            "path": str(detections),
                            "sha256": target_coverage.sha256_file(detections),
                        },
                        "corners_csv": {
                            "path": str(corners),
                            "sha256": target_coverage.sha256_file(corners),
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        return manifest

    def test_target_coverage_completed_gate_fail_is_exit_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self._write_coverage_fixture(root)
            rc = kalibr_target_coverage_command.entrypoint(
                [
                    str(manifest),
                    "--output-prefix",
                    str(root / "coverage"),
                    "--min-detection-fraction",
                    "1.0",
                ]
            )
        self.assertEqual(rc, contract.EXIT_EVALUATED_FAIL)

    def test_target_coverage_domain_failure_is_exit_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = kalibr_target_coverage_command.entrypoint(
                [str(Path(tmp) / "missing.json"), "--output-prefix", str(Path(tmp) / "coverage")]
            )
        self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)
        self.assertNotEqual(rc, contract.EXIT_EVALUATED_FAIL)

    def test_historical_provenance_filenames_are_preserved(self):
        self.assertEqual(Path(target_observations.__file__).name, "export_kalibr_target_observations.py")
        self.assertEqual(Path(target_coverage.__file__).name, "analyze_kalibr_target_coverage.py")
        self.assertEqual(target_observations.TOOL_VERSION, "1")
        self.assertEqual(target_coverage.TOOL_VERSION, "1")

    def test_contract_metadata_records_target_boundaries(self):
        observations = contract.contract_for("camera-imu", "target-observations")
        self.assertEqual(observations.module, "bividi.calibration.kalibr_target_observations_command")
        self.assertEqual(observations.compatibility_tool, "export_kalibr_target_observations.py")
        self.assertEqual(observations.output_role, "observation-csv-and-machine-manifest")
        self.assertEqual(observations.policy_role, "reviewed-external-runtime-no-acceptance-gate")
        self.assertTrue(observations.emits_versioned_provenance)
        self.assertEqual(observations.tool_version, "1")
        self.assertIsNone(observations.evaluated_fail_exit)

        coverage = contract.contract_for("camera-imu", "target-coverage")
        self.assertEqual(coverage.module, "bividi.calibration.kalibr_target_coverage_command")
        self.assertEqual(coverage.compatibility_tool, "analyze_kalibr_target_coverage.py")
        self.assertEqual(coverage.output_role, "machine-evidence-json-and-human-markdown")
        self.assertEqual(coverage.policy_role, "explicit-operator-gates-no-default-thresholds")
        self.assertTrue(coverage.emits_versioned_provenance)
        self.assertEqual(coverage.tool_version, "1")
        self.assertEqual(coverage.evaluated_fail_exit, contract.EXIT_EVALUATED_FAIL)


if __name__ == "__main__":
    unittest.main()
