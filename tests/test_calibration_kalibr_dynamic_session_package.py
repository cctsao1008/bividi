from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

from bividi import calib_cli
from bividi.calibration import contract, kalibr_dynamic_session, kalibr_dynamic_session_command


class KalibrDynamicSessionPackageMigrationTests(unittest.TestCase):
    def test_cli_routes_installed_prepare_without_source_checkout(self):
        invocation = calib_cli.build_invocation(
            "camera-imu",
            "prepare",
            ["--self-test"],
            source_root=Path("/definitely/not/a/bividi/checkout"),
        )
        self.assertEqual(
            invocation,
            [sys.executable, "-m", "bividi.calibration.kalibr_dynamic_session_command", "--self-test"],
        )

    def test_cli_executes_prepare_self_test_outside_source_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = Path.cwd()
            os.chdir(tmp)
            try:
                rc = calib_cli.main(
                    [
                        "--source-root",
                        "/definitely/not/a/bividi/checkout",
                        "camera-imu",
                        "prepare",
                        "--self-test",
                    ]
                )
            finally:
                os.chdir(previous)
        self.assertEqual(rc, contract.EXIT_OK)

    def test_packaged_preparer_preserves_characterized_self_test(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            kalibr_dynamic_session.self_test()
        self.assertIn("Kalibr dynamic-session preparation self-test: PASS", stdout.getvalue())

    def test_packaged_fixture_preserves_staging_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = kalibr_dynamic_session.fixture(root)
            report = kalibr_dynamic_session.build(args)
            self.assertEqual(report["schema"], kalibr_dynamic_session.OUTPUT_SCHEMA)
            self.assertEqual(report["camera_time_reference"]["kind"], "exposure_midpoint")
            self.assertEqual(report["camera_mapping"]["camera_a"], "cam0")
            self.assertEqual(report["camera_mapping"]["camera_b"], "cam1")
            self.assertEqual(report["statistics"]["camera_frames_per_camera"], 2)
            self.assertEqual(report["statistics"]["imu"]["valid_samples"], 6)
            self.assertEqual(
                report["raw_to_si"]["source"],
                "hash-bound six_position + known-angle gyro_rotation analyses",
            )
            self.assertEqual(
                report["status"],
                "prepared_for_external_ros1_bag_writer_and_kalibr",
            )
            self.assertEqual(report["provenance"]["tool"], "prepare_kalibr_dynamic_session.py")
            self.assertEqual(report["provenance"]["tool_version"], "1")
            self.assertTrue((args.output_dir / "rosbag-recipe.json").is_file())
            self.assertTrue((args.output_dir / "kalibr-command.txt").is_file())
            self.assertTrue((args.output_dir / "session.json").is_file())

    def test_domain_failure_uses_exit_two_not_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            argv = [
                str(root / "missing-capture.json"),
                "--imu-session",
                str(root / "missing-session.json"),
                "--imu-calibration",
                str(root / "missing-artifact.json"),
                "--camchain",
                str(root / "missing-camchain.yaml"),
                "--output-dir",
                str(root / "out"),
                "--camera-time-reference",
                "exposure_midpoint",
                "--tag-cols",
                "6",
                "--tag-rows",
                "6",
                "--tag-size-m",
                "0.088",
                "--tag-spacing",
                "0.3",
            ]
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rc = kalibr_dynamic_session_command.entrypoint(argv)
        self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)
        self.assertNotEqual(rc, contract.EXIT_EVALUATED_FAIL)
        self.assertIn("preparation failed", stderr.getvalue())

    def test_contract_metadata_records_staging_boundary(self):
        item = contract.contract_for("camera-imu", "prepare")
        self.assertEqual(item.module, "bividi.calibration.kalibr_dynamic_session_command")
        self.assertEqual(item.compatibility_tool, "prepare_kalibr_dynamic_session.py")
        self.assertEqual(item.output_role, "staging-bundle-and-machine-manifest")
        self.assertEqual(item.policy_role, "measured-evidence-required-synthetic-opt-in")
        self.assertTrue(item.emits_versioned_provenance)
        self.assertEqual(item.tool_version, "1")
        self.assertIsNone(item.evaluated_fail_exit)


if __name__ == "__main__":
    unittest.main()
