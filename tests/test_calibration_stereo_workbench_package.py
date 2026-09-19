from __future__ import annotations

import argparse
import contextlib
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
from bividi.calibration import contract
from bividi.calibration import stereo_calibration_common as common
from bividi.calibration import stereo_calibration_recorder as recorder
from bividi.calibration import stereo_calibration_solve as solve
from bividi.calibration import stereo_calibration_workbench as workbench
from bividi.calibration import stereo_workbench_command as command


class StereoWorkbenchPackageMigrationTests(unittest.TestCase):
    def test_all_original_stereo_routes_are_package_native_outside_checkout(self):
        expected_prefixes = {
            "target": "target",
            "session": "session",
            "session-recorder": "session-recorder",
            "inspect": "inspect",
            "solve": "solve",
            "validate": "validate",
            "rectify": "rectify",
        }
        for name, prefix in expected_prefixes.items():
            with self.subTest(name=name):
                invocation = calib_cli.build_invocation(
                    "stereo",
                    name,
                    ["--help"],
                    source_root=Path("/definitely/not/a/bividi/checkout"),
                )
                self.assertEqual(
                    invocation,
                    [
                        sys.executable,
                        "-m",
                        "bividi.calibration.stereo_workbench_command",
                        prefix,
                        "--help",
                    ],
                )

    def test_package_dependency_free_self_test(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(command.entrypoint(["--self-test"]), contract.EXIT_OK)
        self.assertIn("Stereo calibration workbench dependency-free self-test: PASS", stdout.getvalue())

    def test_legacy_workbench_wrapper_runs_dependency_free_self_test(self):
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(root / "tools" / "stereo_calibration_workbench.py"), "--self-test"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("Stereo calibration workbench dependency-free self-test: PASS", completed.stdout)

    def test_historical_module_basenames_and_schema_versions_are_preserved(self):
        self.assertEqual(Path(common.__file__).name, "stereo_calibration_common.py")
        self.assertEqual(Path(recorder.__file__).name, "stereo_calibration_recorder.py")
        self.assertEqual(Path(solve.__file__).name, "stereo_calibration_solve.py")
        self.assertEqual(Path(workbench.__file__).name, "stereo_calibration_workbench.py")
        self.assertEqual(common.TARGET, "bividi.calibration.stereo_target.v1")
        self.assertEqual(common.SESSION, "bividi.calibration.stereo_session.v1")
        self.assertEqual(common.QUALITY, "bividi.calibration.stereo_dataset_quality.v1")
        self.assertEqual(common.CALIB, "bividi.calibration.stereo.v1")
        self.assertEqual(common.VERSION, "1")
        self.assertEqual(recorder.TOOL_VERSION, "1")

    def test_target_and_session_keep_historical_provenance_and_camera_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target.json"
            kalibr_yaml = root / "target.yaml"
            self.assertEqual(
                command.entrypoint(
                    [
                        "target",
                        "--family",
                        "aprilgrid",
                        "--target-id",
                        "grid-v1",
                        "--output",
                        str(target),
                        "--tag-rows",
                        "4",
                        "--tag-cols",
                        "5",
                        "--tag-size-mm",
                        "30",
                        "--tag-spacing-ratio",
                        "0.2",
                        "--kalibr-yaml",
                        str(kalibr_yaml),
                    ]
                ),
                contract.EXIT_OK,
            )
            target_data = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(target_data["schema"], common.TARGET)
            self.assertEqual(
                target_data["provenance"],
                {"tool": "stereo_calibration_common.py", "tool_version": "1"},
            )
            self.assertIn("target_type: 'aprilgrid'", kalibr_yaml.read_text(encoding="utf-8"))

            camera_a = root / "camera_a"
            camera_b = root / "camera_b"
            camera_a.mkdir()
            camera_b.mkdir()
            (camera_a / "pair-000.png").write_bytes(b"fixture-a")
            (camera_b / "pair-000.png").write_bytes(b"fixture-b")
            session = root / "session.json"
            self.assertEqual(
                command.entrypoint(
                    [
                        "session",
                        "--session-id",
                        "synthetic-session",
                        "--output",
                        str(session),
                        "--target",
                        str(target),
                        "--camera-a-dir",
                        str(camera_a),
                        "--camera-b-dir",
                        str(camera_b),
                        "--model",
                        "SYNTHETIC",
                        "--serial",
                        "SYN-001",
                        "--device",
                        "0",
                        "--mode",
                        "1",
                        "--pixel-format",
                        "mono8_png",
                        "--width",
                        "640",
                        "--height",
                        "480",
                        "--provenance",
                        "synthetic",
                    ]
                ),
                contract.EXIT_OK,
            )
            session_data = json.loads(session.read_text(encoding="utf-8"))
            self.assertEqual(session_data["schema"], common.SESSION)
            self.assertEqual(session_data["capture"]["camera_a_identity"], "camera_a")
            self.assertEqual(session_data["capture"]["camera_b_identity"], "camera_b")
            self.assertEqual(session_data["provenance"]["tool"], "stereo_calibration_common.py")
            self.assertEqual(session_data["provenance"]["tool_version"], "1")

    def test_recorder_self_test_runs_from_package(self):
        recorder.recorder_self_test()

    def test_malformed_artifact_validation_is_domain_error_not_policy_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "bad.json"
            artifact.write_text("{}\n", encoding="utf-8")
            self.assertEqual(
                command.entrypoint(["validate", str(artifact)]),
                contract.EXIT_USAGE_OR_DOMAIN_ERROR,
            )

    def _mock_completed_quality(self, cmd: str, payload: dict) -> int:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "quality.json"
            output.write_text(json.dumps(payload), encoding="utf-8")
            parsed = argparse.Namespace(cmd=cmd, output=output)
            with mock.patch.object(workbench, "args", return_value=parsed), mock.patch.object(
                workbench, "main", return_value=0
            ):
                return command.entrypoint([cmd])

    def test_explicit_leaf_quality_fail_maps_to_three(self):
        self.assertEqual(
            self._mock_completed_quality("inspect", {"status": "FAIL"}),
            contract.EXIT_EVALUATED_FAIL,
        )
        self.assertEqual(
            self._mock_completed_quality("solve", {"quality": {"status": "FAIL"}}),
            contract.EXIT_EVALUATED_FAIL,
        )

    def test_pass_and_evidence_only_quality_remain_success(self):
        self.assertEqual(
            self._mock_completed_quality("inspect", {"status": "PASS"}),
            contract.EXIT_OK,
        )
        self.assertEqual(
            self._mock_completed_quality(
                "solve", {"quality": {"status": "EVIDENCE_ONLY_NO_THRESHOLDS"}}
            ),
            contract.EXIT_OK,
        )

    def test_parser_and_missing_input_errors_map_to_two(self):
        self.assertEqual(command.entrypoint(["target"]), contract.EXIT_USAGE_OR_DOMAIN_ERROR)
        self.assertEqual(
            command.entrypoint(["validate", "/definitely/missing/stereo-calibration.json"]),
            contract.EXIT_USAGE_OR_DOMAIN_ERROR,
        )

    def test_seven_workbench_contracts_freeze_policy_ownership(self):
        expected = {
            "target": (None, "recorded-orchestration-metadata"),
            "session": (None, "recorded-orchestration-metadata"),
            "session-recorder": (None, "recorded-orchestration-metadata"),
            "inspect": (contract.EXIT_EVALUATED_FAIL, "explicit-operator-gates-no-default-thresholds"),
            "solve": (contract.EXIT_EVALUATED_FAIL, "explicit-operator-gates-no-default-thresholds"),
            "validate": (None, "structural-validation-no-acceptance-gate"),
            "rectify": (None, "presentation-only"),
        }
        for name, (evaluated_fail, policy_role) in expected.items():
            with self.subTest(name=name):
                item = contract.contract_for("stereo", name)
                self.assertEqual(item.module, "bividi.calibration.stereo_workbench_command")
                self.assertEqual(item.compatibility_tool, "stereo_calibration_workbench.py")
                self.assertEqual(item.policy_role, policy_role)
                self.assertEqual(item.evaluated_fail_exit, evaluated_fail)

    def test_package_imports_do_not_use_source_tree_sibling_names(self):
        recorder_source = Path(recorder.__file__).read_text(encoding="utf-8")
        solve_source = Path(solve.__file__).read_text(encoding="utf-8")
        workbench_source = Path(workbench.__file__).read_text(encoding="utf-8")
        self.assertIn("from .stereo_calibration_common import", recorder_source)
        self.assertIn("from .stereo_calibration_common import *", solve_source)
        self.assertIn("from .stereo_calibration_common import *", workbench_source)
        self.assertIn("from .stereo_calibration_recorder import", workbench_source)
        self.assertIn("from .stereo_calibration_solve import *", workbench_source)


if __name__ == "__main__":
    unittest.main()
