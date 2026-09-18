from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bividi import calib_selftests


class CalibrationSelfTestRunnerTests(unittest.TestCase):
    def test_manifest_names_are_unique_and_expected_surfaces_exist(self):
        cases = calib_selftests.self_tests()
        names = [case.name for case in cases]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("stereo-workbench", names)
        self.assertIn("imu-allan", names)
        self.assertIn("camera-imu-solver-quality", names)

    def test_manifest_resolves_all_current_source_tools_and_schemas(self):
        root = calib_selftests.find_source_root()
        self.assertEqual(calib_selftests.validate_manifest(root), [])

    def test_select_tests_preserves_manifest_order(self):
        selected = calib_selftests.select_tests(["camera-imu-import", "imu-stationary"])
        self.assertEqual(
            [case.name for case in selected],
            ["imu-stationary", "camera-imu-import"],
        )

    def test_select_tests_rejects_unknown_name(self):
        with self.assertRaisesRegex(KeyError, "unknown calibration self-test"):
            calib_selftests.select_tests(["not-a-test"])

    def test_runner_propagates_leaf_failure_without_importing_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools = root / "tools"
            tools.mkdir()
            schema_dir = root / "calibration" / "schemas"
            schema_dir.mkdir(parents=True)
            (schema_dir / "fixture.schema.json").write_text('{"type":"object"}\n', encoding="utf-8")
            (root / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")

            passing = tools / "pass.py"
            passing.write_text("raise SystemExit(0)\n", encoding="utf-8")
            failing = tools / "fail.py"
            failing.write_text("raise SystemExit(7)\n", encoding="utf-8")

            cases = (
                calib_selftests.CalibrationSelfTest("pass", "pass.py", ("--fixture",), "pass fixture"),
                calib_selftests.CalibrationSelfTest("fail", "fail.py", ("--fixture",), "fail fixture"),
            )

            # run_tests validates the active manifest before execution, so use
            # a minimal monkeypatch only for this isolated process-control test.
            original_manifest = calib_selftests._SELF_TESTS
            try:
                calib_selftests._SELF_TESTS = cases
                self.assertEqual(calib_selftests.run_tests(cases, source_root=root), 1)
            finally:
                calib_selftests._SELF_TESTS = original_manifest


if __name__ == "__main__":
    unittest.main()
