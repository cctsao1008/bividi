from __future__ import annotations

import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from bividi.calibration import target_scale


class TargetScaleModuleTests(unittest.TestCase):
    def _target(self, root: Path) -> Path:
        path = root / "target.json"
        path.write_text(
            json.dumps(
                {
                    "schema": target_scale.TARGET_SCHEMA,
                    "target_id": "fixture-target",
                    "physical_size_mm": {"width": 240.0, "height": 180.0},
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_review_preserves_legacy_provenance_and_evidence_only_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._target(Path(tmp))
            args = argparse.Namespace(
                measured_width_mm=239.5,
                measured_height_mm=None,
                max_abs_delta_percent=None,
                policy_source=None,
                measurement_source="caliper-fixture",
                method="caliper",
            )
            result = target_scale.review(path, args)
            self.assertEqual(result["schema"], target_scale.REPORT_SCHEMA)
            self.assertEqual(result["status"], "EVIDENCE_ONLY_NO_THRESHOLDS")
            self.assertEqual(
                result["provenance"]["tool"],
                "review_calibration_target_scale.py",
            )

    def test_explicit_gate_requires_policy_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._target(Path(tmp))
            args = argparse.Namespace(
                measured_width_mm=239.5,
                measured_height_mm=None,
                max_abs_delta_percent=1.0,
                policy_source=None,
                measurement_source="caliper-fixture",
                method="caliper",
            )
            with self.assertRaises(target_scale.TargetScaleError):
                target_scale.review(path, args)

    def test_gate_failure_preserves_exit_code_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self._target(root)
            output = root / "review.json"
            rc = target_scale.entrypoint(
                [
                    str(path),
                    "--measured-width-mm",
                    "220",
                    "--measurement-source",
                    "caliper-fixture",
                    "--method",
                    "caliper",
                    "--max-abs-delta-percent",
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
            rc = target_scale.entrypoint([])
        self.assertEqual(rc, 2)
        self.assertIn("target, --measurement-source, and --method are required", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
