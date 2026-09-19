from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bividi import calib_cli
from bividi.calibration import contract
from bividi.calibration import kalibr_rosbag_command
from bividi.calibration import write_kalibr_rosbag as rosbag_writer


class KalibrRos1BagPackageMigrationTests(unittest.TestCase):
    def test_cli_routes_without_source_checkout(self):
        invocation = calib_cli.build_invocation(
            "camera-imu",
            "ros1-bag",
            ["--self-test"],
            source_root=Path("/definitely/not/a/bividi/checkout"),
        )
        self.assertEqual(
            invocation,
            [sys.executable, "-m", "bividi.calibration.kalibr_rosbag_command", "--self-test"],
        )

    def test_cli_executes_self_test_without_ros1_runtime(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = calib_cli.main(
                [
                    "--source-root",
                    "/definitely/not/a/bividi/checkout",
                    "camera-imu",
                    "ros1-bag",
                    "--self-test",
                ]
            )
        self.assertEqual(rc, contract.EXIT_OK)

    def test_package_and_legacy_wrapper_self_tests(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rosbag_writer.self_test()
        self.assertIn("Kalibr ROS1 bag writer self-test: PASS", stdout.getvalue())

        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(root / "tools" / "write_kalibr_rosbag.py"), "--self-test"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("Kalibr ROS1 bag writer self-test: PASS", completed.stdout)

    def test_frozen_schemas_and_timestamp_split(self):
        self.assertEqual(
            rosbag_writer.SESSION_SCHEMA,
            "bividi.calibration.kalibr_dynamic_session.v1",
        )
        self.assertEqual(
            rosbag_writer.RECIPE_SCHEMA,
            "bividi.calibration.kalibr_rosbag_recipe.v1",
        )
        self.assertEqual(rosbag_writer.split_ns(1_234_567_890), (1, 234_567_890))
        with self.assertRaises(rosbag_writer.BagExportError):
            rosbag_writer.split_ns(-1)

    def test_stream_merge_order_and_per_stream_monotonicity_are_frozen(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "a.csv"
            b = root / "b.csv"
            imu = root / "imu.csv"
            a.write_text(
                "timestamp_ns,image_path\n100,a.png\n300,a2.png\n",
                encoding="utf-8",
            )
            b.write_text(
                "timestamp_ns,image_path\n100,b.png\n300,b2.png\n",
                encoding="utf-8",
            )
            imu.write_text(
                "timestamp_ns,omega_x,omega_y,omega_z,alpha_x,alpha_y,alpha_z\n"
                "200,0,0,0,0,0,9.8\n400,0,0,0,0,0,9.8\n",
                encoding="utf-8",
            )
            merged = [
                (stamp, kind)
                for stamp, kind, _ in rosbag_writer.merge_streams(
                    [
                        iter(rosbag_writer.image_rows(a, "camera_a")),
                        iter(rosbag_writer.image_rows(b, "camera_b")),
                        iter(rosbag_writer.imu_rows(imu)),
                    ]
                )
            ]
            self.assertEqual(
                merged,
                [
                    (100, "camera_a"),
                    (100, "camera_b"),
                    (200, "imu"),
                    (300, "camera_a"),
                    (300, "camera_b"),
                    (400, "imu"),
                ],
            )

            bad = root / "bad.csv"
            bad.write_text(
                "timestamp_ns,image_path\n100,a.png\n100,b.png\n",
                encoding="utf-8",
            )
            with self.assertRaises(rosbag_writer.BagExportError):
                list(rosbag_writer.image_rows(bad, "camera_a"))

    def test_nonfinite_imu_is_rejected_before_external_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "imu.csv"
            path.write_text(
                "timestamp_ns,omega_x,omega_y,omega_z,alpha_x,alpha_y,alpha_z\n"
                "200,nan,0,0,0,0,9.8\n",
                encoding="utf-8",
            )
            with self.assertRaises(rosbag_writer.BagExportError):
                list(rosbag_writer.imu_rows(path))

    def test_schema_failure_maps_to_domain_error_before_ros1_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp)
            (bundle / "session.json").write_text(
                '{"schema":"wrong"}\n',
                encoding="utf-8",
            )
            (bundle / "rosbag-recipe.json").write_text(
                '{"schema":"bividi.calibration.kalibr_rosbag_recipe.v1"}\n',
                encoding="utf-8",
            )
            rc = kalibr_rosbag_command.entrypoint([str(bundle)])
        self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)

    def test_exit_normalization_never_treats_transport_failure_as_evaluated_fail(self):
        self.assertEqual(
            kalibr_rosbag_command.entrypoint([]),
            contract.EXIT_USAGE_OR_DOMAIN_ERROR,
        )
        with mock.patch.object(rosbag_writer, "main", return_value=3):
            self.assertEqual(
                kalibr_rosbag_command.entrypoint(["unused"]),
                contract.EXIT_USAGE_OR_DOMAIN_ERROR,
            )

    def test_contract_metadata_marks_external_transport_no_gate(self):
        item = contract.contract_for("camera-imu", "ros1-bag")
        self.assertEqual(item.module, "bividi.calibration.kalibr_rosbag_command")
        self.assertEqual(item.compatibility_tool, "write_kalibr_rosbag.py")
        self.assertEqual(item.output_role, "interop-transport-artifact")
        self.assertEqual(
            item.policy_role,
            "external-runtime-transport-no-acceptance-gate",
        )
        self.assertFalse(item.emits_versioned_provenance)
        self.assertIsNone(item.tool_version)
        self.assertIsNone(item.evaluated_fail_exit)


if __name__ == "__main__":
    unittest.main()
