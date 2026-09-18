from __future__ import annotations

import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from bividi.calibration import stereo_geometry


class StereoGeometryModuleTests(unittest.TestCase):
    def _calibration(self, root: Path) -> Path:
        path = root / "calibration.json"
        path.write_text(
            json.dumps(
                {
                    "schema": stereo_geometry.SCHEMA,
                    "calibration_id": "fixture-calibration",
                    "stereo": {
                        "T_camera_b_from_camera_a_m": [-0.08, 0.0, 0.0],
                    },
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_review_preserves_legacy_provenance_and_evidence_only_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._calibration(Path(tmp))
            args = argparse.Namespace(
                physical_baseline_mm=80.5,
                measurement_source="caliper-fixture",
                method="caliper",
                max_abs_delta_mm=None,
                max_abs_delta_percent=None,
                policy_source=None,
            )
            result = stereo_geometry.review(path, args)
            self.assertEqual(result["schema"], stereo_geometry.REPORT_SCHEMA)
            self.assertEqual(result["status"], "EVIDENCE_ONLY_NO_THRESHOLDS")
            self.assertAlmostEqual(result["calibrated"]["baseline_mm"], 80.0)
            self.assertAlmostEqual(result["comparison"]["absolute_delta_mm"], 0.5)
            self.assertEqual(
                result["provenance"]["tool"],
                "review_stereo_geometry.py",
            )

    def test_explicit_gate_requires_policy_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._calibration(Path(tmp))
            args = argparse.Namespace(
                physical_baseline_mm=80.5,
                measurement_source="caliper-fixture",
                method="caliper",
                max_abs_delta_mm=1.0,
                max_abs_delta_percent=None,
                policy_source=None,
            )
            with self.assertRaises(stereo_geometry.ReviewError):
                stereo_geometry.review(path, args)

    def test_gate_failure_preserves_exit_code_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self._calibration(root)
            output = root / "review.json"
            rc = stereo_geometry.entrypoint(
                [
                    str(path),
                    "--physical-baseline-mm",
                    "85",
                    "--measurement-source",
                    "caliper-fixture",
                    "--method",
                    "caliper",
                    "--max-abs-delta-mm",
                    "1",
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
            rc = stereo_geometry.entrypoint([])
        self.assertEqual(rc, 2)
        self.assertIn(
            "calibration, physical baseline, measurement source, and method are required",
            stderr.getvalue(),
        )


if __name__ == "__main__":
    unittest.main()
