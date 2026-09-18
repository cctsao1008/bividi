from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import tempfile
import unittest
from pathlib import Path

from bividi.calibration import stereo_repeatability


class StereoRepeatabilityModuleTests(unittest.TestCase):
    def _document(self, calibration_id: str, baseline_m: float) -> dict:
        return {
            "schema": stereo_repeatability.SCHEMA,
            "calibration_id": calibration_id,
            "device": {"model": "fixture", "serial": "A"},
            "capture": {"mode_index": 0, "pixel_format": "GRAY8"},
            "image": {"width": 1280, "height": 720},
            "target": {"target_id": "target", "sha256": "abc"},
            "camera_model": {"projection": "pinhole", "distortion": "opencv5"},
            "provenance": {"kind": "synthetic"},
            "cameras": {
                "camera_a": {"K": [[700, 0, 640], [0, 700, 360], [0, 0, 1]]},
                "camera_b": {"K": [[701, 0, 640], [0, 701, 360], [0, 0, 1]]},
            },
            "stereo": {
                "R_camera_b_from_camera_a": [
                    [1.0, 0.0, 0.0],
                    [0.0, 1.0, 0.0],
                    [0.0, 0.0, 1.0],
                ],
                "T_camera_b_from_camera_a_m": [-baseline_m, 0.0, 0.0],
            },
        }

    def _pair(self, root: Path) -> tuple[Path, Path]:
        first = self._document("cal-a", 0.0800)
        second = self._document("cal-b", 0.0805)
        angle = math.radians(0.2)
        cosine = math.cos(angle)
        sine = math.sin(angle)
        second["stereo"]["R_camera_b_from_camera_a"] = [
            [cosine, -sine, 0.0],
            [sine, cosine, 0.0],
            [0.0, 0.0, 1.0],
        ]
        first_path = root / "first.json"
        second_path = root / "second.json"
        first_path.write_text(json.dumps(first), encoding="utf-8")
        second_path.write_text(json.dumps(second), encoding="utf-8")
        return first_path, second_path

    def _args(self, **overrides):
        values = {
            "max_rotation_delta_deg": None,
            "max_baseline_delta_mm": None,
            "max_translation_direction_delta_deg": None,
            "max_focal_delta_percent": None,
            "max_principal_point_delta_px": None,
            "policy_source": None,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_compare_preserves_metrics_provenance_and_evidence_only_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = self._pair(Path(tmp))
            result = stereo_repeatability.compare([first, second], self._args())
            self.assertEqual(result["schema"], stereo_repeatability.REPORT_SCHEMA)
            self.assertEqual(result["status"], "EVIDENCE_ONLY_NO_THRESHOLDS")
            self.assertAlmostEqual(result["summary"]["max_baseline_delta_mm"], 0.5)
            self.assertAlmostEqual(result["summary"]["max_rotation_delta_deg"], 0.2)
            self.assertEqual(
                result["provenance"]["tool"],
                "compare_stereo_calibrations.py",
            )

    def test_explicit_gate_requires_policy_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = self._pair(Path(tmp))
            with self.assertRaises(stereo_repeatability.CompareError):
                stereo_repeatability.compare(
                    [first, second],
                    self._args(max_baseline_delta_mm=1.0),
                )

    def test_incompatible_identity_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first, second = self._pair(root)
            modified = json.loads(second.read_text(encoding="utf-8"))
            modified["device"]["serial"] = "B"
            second.write_text(json.dumps(modified), encoding="utf-8")
            with self.assertRaises(stereo_repeatability.CompareError):
                stereo_repeatability.compare([first, second], self._args())

    def test_gate_failure_preserves_exit_code_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first, second = self._pair(root)
            output = root / "repeatability.json"
            rc = stereo_repeatability.entrypoint(
                [
                    str(first),
                    str(second),
                    "--max-baseline-delta-mm",
                    "0.1",
                    "--policy-source",
                    "fixture-policy",
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(rc, 3)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["policy_source"], "fixture-policy")

    def test_usage_error_preserves_exit_code_two(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rc = stereo_repeatability.entrypoint([])
        self.assertEqual(rc, 2)
        self.assertIn("at least two calibration artifacts are required", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
