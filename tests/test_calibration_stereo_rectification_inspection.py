from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bividi.calibration import contract
from bividi.calibration import stereo_calibration_common as common
from bividi.calibration import stereo_rectification_inspection as inspection
from bividi.calibration import stereo_calibration_workbench as workbench
from bividi.calibration import stereo_workbench_command as command


class StereoRectificationInspectionTests(unittest.TestCase):
    def test_schema_and_tool_identity_are_versioned(self):
        self.assertEqual(
            inspection.SCHEMA,
            "bividi.calibration.stereo_rectification_inspection.v1",
        )
        self.assertEqual(inspection.TOOL_VERSION, "1")
        self.assertEqual(Path(inspection.__file__).name, "stereo_rectification_inspection.py")

    def test_rectify_parser_exposes_optional_evidence_controls(self):
        parsed = workbench.args(
            [
                "rectify",
                "--calibration",
                "calibration.json",
                "--camera-a",
                "a.png",
                "--camera-b",
                "b.png",
                "--output",
                "inspection.png",
                "--include-originals",
                "--target",
                "target.json",
                "--evidence-output",
                "inspection.json",
            ]
        )
        self.assertTrue(parsed.include_originals)
        self.assertEqual(parsed.target, Path("target.json"))
        self.assertEqual(parsed.evidence_output, Path("inspection.json"))

    def test_default_rectify_path_remains_the_historical_renderer(self):
        argv = [
            "rectify",
            "--calibration",
            "calibration.json",
            "--camera-a",
            "a.png",
            "--camera-b",
            "b.png",
            "--output",
            "rectified.png",
        ]
        with mock.patch.object(workbench, "rectify_cmd") as historical, mock.patch.object(
            workbench, "inspect_rectification"
        ) as evidence:
            self.assertEqual(workbench.main(argv), 0)
        historical.assert_called_once()
        evidence.assert_not_called()

    def test_any_evidence_option_routes_to_inspector(self):
        base = [
            "rectify",
            "--calibration",
            "calibration.json",
            "--camera-a",
            "a.png",
            "--camera-b",
            "b.png",
            "--output",
            "inspection.png",
        ]
        for extra in (
            ["--include-originals"],
            ["--target", "target.json"],
            ["--evidence-output", "inspection.json"],
        ):
            with self.subTest(extra=extra), mock.patch.object(
                workbench, "rectify_cmd"
            ) as historical, mock.patch.object(workbench, "inspect_rectification") as evidence:
                self.assertEqual(workbench.main(base + extra), 0)
                historical.assert_not_called()
                evidence.assert_called_once()

    def test_target_binding_rejects_identity_and_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_path = root / "target.json"
            target = {
                "schema": common.TARGET,
                "target_id": "grid-v1",
                "family": "charuco",
                "charuco": {
                    "dictionary": "DICT_5X5_1000",
                    "squares_x": 8,
                    "squares_y": 6,
                    "square_length_mm": 30.0,
                    "marker_length_mm": 22.0,
                },
            }
            target_path.write_text(json.dumps(target), encoding="utf-8")
            artifact = {
                "target": {
                    "target_id": "grid-v1",
                    "family": "charuco",
                    "sha256": common.sha(target_path),
                }
            }
            self.assertEqual(inspection._verified_target(target_path, artifact), target)

            artifact["target"]["target_id"] = "other"
            with self.assertRaisesRegex(common.Error, "target_id differs"):
                inspection._verified_target(target_path, artifact)
            artifact["target"]["target_id"] = "grid-v1"
            artifact["target"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(common.Error, "SHA-256 differs"):
                inspection._verified_target(target_path, artifact)

    def test_no_target_evidence_uses_null_distributions_not_zero_fabrication(self):
        empty = inspection._empty_distribution()
        self.assertEqual(empty["count"], 0)
        for key in ("min", "max", "mean", "median", "p95"):
            self.assertIsNone(empty[key])

    def test_rectification_inspection_never_uses_evaluated_fail_exit(self):
        parsed = argparse.Namespace(cmd="rectify", output=Path("inspection.png"))
        with mock.patch.object(workbench, "args", return_value=parsed), mock.patch.object(
            workbench, "main", return_value=0
        ):
            self.assertEqual(command.entrypoint(["rectify"]), contract.EXIT_OK)

        self.assertIsNone(contract.contract_for("stereo", "rectify").evaluated_fail_exit)

    def test_missing_rectification_inputs_map_to_domain_error(self):
        rc = command.entrypoint(
            [
                "rectify",
                "--calibration",
                "/definitely/missing/calibration.json",
                "--camera-a",
                "/definitely/missing/a.png",
                "--camera-b",
                "/definitely/missing/b.png",
                "--output",
                "inspection.png",
                "--evidence-output",
                "inspection.json",
            ]
        )
        self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)


if __name__ == "__main__":
    unittest.main()
