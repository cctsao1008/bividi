from __future__ import annotations

import contextlib
import hashlib
import io
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from bividi import calib_cli
from bividi.calibration import contract
from bividi.calibration import ros2_mcap_command
from bividi.calibration import write_kalibr_rosbag as staged
from bividi.calibration import write_ros2_calibration_mcap as mcap


class Ros2McapPackageMigrationTests(unittest.TestCase):
    def test_cli_routes_without_source_checkout(self):
        invocation = calib_cli.build_invocation(
            "camera-imu",
            "ros2-mcap",
            ["--self-test"],
            source_root=Path("/definitely/not/a/bividi/checkout"),
        )
        self.assertEqual(
            invocation,
            [sys.executable, "-m", "bividi.calibration.ros2_mcap_command", "--self-test"],
        )

    def test_cli_executes_self_test_without_ros2_runtime(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = calib_cli.main(
                [
                    "--source-root",
                    "/definitely/not/a/bividi/checkout",
                    "camera-imu",
                    "ros2-mcap",
                    "--self-test",
                ]
            )
        self.assertEqual(rc, contract.EXIT_OK)

    def test_package_and_legacy_wrapper_self_tests(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            mcap.self_test()
        self.assertIn("ROS2 calibration MCAP adapter self-test: PASS", stdout.getvalue())

        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(root / "tools" / "write_ros2_calibration_mcap.py"), "--self-test"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("ROS2 calibration MCAP adapter self-test: PASS", completed.stdout)

    def test_frozen_schema_topics_provenance_and_package_helper(self):
        self.assertEqual(mcap.SESSION_SCHEMA, "bividi.calibration.kalibr_dynamic_session.v1")
        self.assertEqual(mcap.EXPORT_SCHEMA, "bividi.calibration.ros2_mcap_export.v1")
        self.assertEqual(mcap.TOOL_VERSION, "1")
        self.assertEqual(Path(mcap.__file__).name, "write_ros2_calibration_mcap.py")
        self.assertEqual(mcap.DEFAULT_CAMERA_A_TOPIC, "/cam0/image_raw")
        self.assertEqual(mcap.DEFAULT_CAMERA_B_TOPIC, "/cam1/image_raw")
        self.assertEqual(mcap.DEFAULT_IMU_TOPIC, "/imu0")
        self.assertIs(mcap.staged, staged)

    def test_topic_validation_and_topic_metadata_api_compatibility(self):
        self.assertEqual(mcap.normalize_topic("cam0/image_raw"), "/cam0/image_raw")
        self.assertEqual(mcap.normalize_topic(" /imu0 "), "/imu0")
        for value in ("", " ", "/"):
            with self.assertRaises(mcap.Ros2McapExportError):
                mcap.normalize_topic(value)

        class OldApi:
            class TopicMetadata:
                def __init__(self, name, type, serialization_format):
                    self.values = (name, type, serialization_format)

        old = mcap.topic_metadata(OldApi, "/imu0", "sensor_msgs/msg/Imu")
        self.assertEqual(old.values, ("/imu0", "sensor_msgs/msg/Imu", "cdr"))

        class NewApi:
            class TopicMetadata:
                def __init__(
                    self,
                    *,
                    id,
                    name,
                    type,
                    serialization_format,
                    offered_qos_profiles,
                    type_description_hash,
                ):
                    self.values = (id, name, type, serialization_format)

        new = mcap.topic_metadata(NewApi, "/cam0/image_raw", "sensor_msgs/msg/Image")
        self.assertEqual(new.values, (0, "/cam0/image_raw", "sensor_msgs/msg/Image", "cdr"))

    def test_schema_missing_file_distinct_topic_and_overwrite_reject_before_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = mcap.write_fixture(root)
            session_path = bundle / "session.json"
            original = session_path.read_text(encoding="utf-8")
            session_path.write_text('{"schema":"wrong","staged":{}}\n', encoding="utf-8")
            with self.assertRaises(mcap.Ros2McapExportError):
                mcap.resolve_staged_inputs(bundle)
            session_path.write_text(original, encoding="utf-8")

            with self.assertRaises(mcap.Ros2McapExportError):
                mcap.write_ros2_mcap(
                    bundle,
                    root / "out",
                    camera_a_topic="/same",
                    camera_b_topic="/same",
                    imu_topic="/imu0",
                )

            output = root / "existing"
            output.write_text("occupied\n", encoding="utf-8")
            with self.assertRaises(mcap.Ros2McapExportError):
                mcap.write_ros2_mcap(
                    bundle,
                    output,
                    camera_a_topic="/cam0/image_raw",
                    camera_b_topic="/cam1/image_raw",
                    imu_topic="/imu0",
                )

    def test_fake_ros2_runtime_proves_transport_and_manifest_semantics(self):
        class Stamp:
            def __init__(self):
                self.sec = 0
                self.nanosec = 0

        class Header:
            def __init__(self):
                self.stamp = Stamp()
                self.frame_id = ""

        class Vector:
            def __init__(self):
                self.x = 0.0
                self.y = 0.0
                self.z = 0.0

        class Image:
            def __init__(self):
                self.header = Header()
                self.height = 0
                self.width = 0
                self.encoding = ""
                self.is_bigendian = 0
                self.step = 0
                self.data = b""

        class Imu:
            def __init__(self):
                self.header = Header()
                self.angular_velocity = Vector()
                self.linear_acceleration = Vector()
                self.orientation_covariance = [0.0] * 9
                self.angular_velocity_covariance = [0.0] * 9
                self.linear_acceleration_covariance = [0.0] * 9

        class FakeImage:
            shape = (2, 3)

            def tobytes(self):
                return b"\x00" * 6

        fake_cv2 = types.ModuleType("cv2")
        fake_cv2.IMREAD_GRAYSCALE = 0
        fake_cv2.imread = lambda path, mode: FakeImage()

        class TopicMetadata:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class StorageOptions:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class ConverterOptions:
            def __init__(self, *args):
                self.args = args

        class Writer:
            def __init__(self):
                self.open_args = None
                self.topics = []
                self.writes = []

            def open(self, storage, converter):
                self.open_args = (storage, converter)

            def create_topic(self, topic):
                self.topics.append(topic)

            def write(self, topic, payload, stamp_ns):
                self.writes.append((topic, payload, stamp_ns))

        writer = Writer()
        fake_rosbag2 = types.ModuleType("rosbag2_py")
        fake_rosbag2.TopicMetadata = TopicMetadata
        fake_rosbag2.StorageOptions = StorageOptions
        fake_rosbag2.ConverterOptions = ConverterOptions
        fake_rosbag2.SequentialWriter = lambda: writer

        fake_rclpy = types.ModuleType("rclpy")
        fake_serialization = types.ModuleType("rclpy.serialization")
        fake_serialization.serialize_message = lambda msg: b"serialized"
        fake_sensor_msgs = types.ModuleType("sensor_msgs")
        fake_sensor_msgs_msg = types.ModuleType("sensor_msgs.msg")
        fake_sensor_msgs_msg.Image = Image
        fake_sensor_msgs_msg.Imu = Imu

        modules = {
            "cv2": fake_cv2,
            "rosbag2_py": fake_rosbag2,
            "rclpy": fake_rclpy,
            "rclpy.serialization": fake_serialization,
            "sensor_msgs": fake_sensor_msgs,
            "sensor_msgs.msg": fake_sensor_msgs_msg,
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = mcap.write_fixture(root)
            session_path = bundle / "session.json"
            expected_hash = hashlib.sha256(session_path.read_bytes()).hexdigest()
            with mock.patch.dict(sys.modules, modules, clear=False):
                report = mcap.write_ros2_mcap(
                    bundle,
                    root / "ros2_out",
                    camera_a_topic="cam0/image_raw",
                    camera_b_topic="cam1/image_raw",
                    imu_topic="imu0",
                )

        self.assertEqual(report["schema"], "bividi.calibration.ros2_mcap_export.v1")
        self.assertEqual(report["tool"], "write_ros2_calibration_mcap.py")
        self.assertEqual(report["tool_version"], "1")
        self.assertEqual(
            report["status"],
            "written_for_ros2_interoperability_not_authoritative_kalibr_input",
        )
        self.assertEqual(report["source_session"]["sha256"], expected_hash)
        self.assertEqual(report["storage"]["storage_id"], "mcap")
        self.assertEqual(report["storage"]["serialization_format"], "cdr")
        self.assertFalse(report["timestamp_contract"]["host_arrival_time_used"])
        self.assertEqual(
            report["timestamp_contract"]["rosbag2_record_timestamp"],
            "same numeric timestamp as message header.stamp",
        )
        self.assertEqual(report["messages"], {"camera_a": 2, "camera_b": 2, "imu": 2})
        self.assertEqual([item[2] for item in writer.writes], [100, 100, 200, 300, 300, 400])
        self.assertEqual(len(writer.topics), 3)

    def test_exit_normalization_never_treats_transport_failure_as_evaluated_fail(self):
        self.assertEqual(ros2_mcap_command.entrypoint([]), contract.EXIT_USAGE_OR_DOMAIN_ERROR)
        with mock.patch.object(mcap, "main", return_value=3):
            self.assertEqual(
                ros2_mcap_command.entrypoint(["unused"]),
                contract.EXIT_USAGE_OR_DOMAIN_ERROR,
            )

    def test_contract_metadata_records_versioned_interop_transport_no_gate(self):
        item = contract.contract_for("camera-imu", "ros2-mcap")
        self.assertEqual(item.module, "bividi.calibration.ros2_mcap_command")
        self.assertEqual(item.compatibility_tool, "write_ros2_calibration_mcap.py")
        self.assertEqual(item.output_role, "interop-transport-and-machine-manifest")
        self.assertEqual(item.policy_role, "external-runtime-transport-no-acceptance-gate")
        self.assertTrue(item.emits_versioned_provenance)
        self.assertEqual(item.tool_version, "1")
        self.assertIsNone(item.evaluated_fail_exit)


if __name__ == "__main__":
    unittest.main()
