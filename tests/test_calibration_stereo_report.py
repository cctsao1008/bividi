from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from bividi.calibration import stereo_report


class StereoReportModuleTests(unittest.TestCase):
    def _evidence(self, root: Path) -> dict[str, Path]:
        documents = {
            "target_scale": {
                "schema": stereo_report.SCHEMAS["target_scale"],
                "status": "PASS",
                "policy_source": "lab-policy",
            },
            "dataset_quality": {
                "schema": stereo_report.SCHEMAS["dataset_quality"],
                "status": "EVIDENCE_ONLY_NO_THRESHOLDS",
                "policy_source": None,
                "cameras": {
                    "camera_a": {
                        "global_image_plane_hull_fraction": 0.75,
                        "target_corner_fraction": 0.80,
                        "centroid_x_span_fraction": 0.50,
                        "centroid_y_span_fraction": 0.40,
                    },
                    "camera_b": {
                        "global_image_plane_hull_fraction": 0.74,
                        "target_corner_fraction": 0.79,
                        "centroid_x_span_fraction": 0.49,
                        "centroid_y_span_fraction": 0.39,
                    },
                },
            },
            "calibration": {
                "schema": stereo_report.SCHEMAS["calibration"],
                "calibration_id": "fixture-cal",
                "device": {"model": "fixture-model", "serial": "fixture-serial"},
                "capture": {"mode_index": 3},
                "image": {"width": 1920, "height": 1200},
                "cameras": {
                    "camera_a": {
                        "K": [[1000, 0, 960], [0, 1001, 600], [0, 0, 1]],
                        "mono_rms_px": 0.15,
                        "pinhole_fov_deg": {"x": 87.0, "y": 62.0},
                    },
                    "camera_b": {
                        "K": [[999, 0, 959], [0, 1000, 601], [0, 0, 1]],
                        "mono_rms_px": 0.16,
                        "pinhole_fov_deg": {"x": 87.1, "y": 62.1},
                    },
                },
                "stereo": {"baseline_m": 0.08, "stereo_rms_px": 0.25},
                "rectification": {
                    "vertical_epipolar_abs_px": {"p95": 0.20, "max": 0.70}
                },
                "quality": {"status": "PASS", "policy_source": "fit-policy"},
            },
            "geometry": {
                "schema": stereo_report.SCHEMAS["geometry"],
                "status": "PASS",
                "policy_source": "geometry-policy",
                "comparison": {"absolute_delta_mm": 0.4},
            },
            "repeatability": {
                "schema": stereo_report.SCHEMAS["repeatability"],
                "status": "PASS",
                "policy_source": "repeatability-policy",
                "summary": {
                    "artifact_count": 3,
                    "max_rotation_delta_deg": 0.2,
                    "max_baseline_delta_mm": 0.5,
                    "max_translation_direction_delta_deg": 0.1,
                    "max_focal_delta_percent": 0.3,
                    "max_principal_point_delta_px": 0.8,
                },
            },
        }
        paths: dict[str, Path] = {}
        for key, document in documents.items():
            path = root / f"{key}.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            paths[key] = path
        return paths

    def test_render_preserves_human_report_sections_and_interpretation_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._evidence(Path(tmp))
            text = stereo_report.render(paths)
            self.assertIn("# Stereo calibration evidence report", text)
            self.assertIn("Calibration: `fixture-cal`", text)
            self.assertIn("Image: `1920x1200`", text)
            self.assertIn("| Printed target scale | PASS | lab-policy |", text)
            self.assertIn(
                "| Dataset quality | EVIDENCE_ONLY_NO_THRESHOLDS | none |", text
            )
            self.assertIn("- Baseline: `0.080000 m`", text)
            self.assertIn("- Max baseline delta: `0.5000 mm`", text)
            self.assertIn("## Interpretation boundary", text)
            self.assertIn("does not create new acceptance evidence", text)

    def test_schema_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._evidence(root)
            bad = json.loads(paths["geometry"].read_text(encoding="utf-8"))
            bad["schema"] = "wrong.schema"
            paths["geometry"].write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(stereo_report.ReportError):
                stereo_report.render(paths)

    def test_cli_writes_markdown_and_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._evidence(root)
            output = root / "nested" / "report.md"
            argv: list[str] = []
            for key in stereo_report.SCHEMAS:
                argv.extend(["--" + key.replace("_", "-"), str(paths[key])])
            argv.extend(["--output", str(output)])
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = stereo_report.entrypoint(argv)
            self.assertEqual(rc, 0)
            self.assertTrue(output.is_file())
            self.assertIn("Stereo calibration evidence report", output.read_text(encoding="utf-8"))
            self.assertIn(str(output), stdout.getvalue())

    def test_missing_inputs_preserve_exit_code_two(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rc = stereo_report.entrypoint([])
        self.assertEqual(rc, 2)
        self.assertIn("all evidence inputs and --output are required", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
