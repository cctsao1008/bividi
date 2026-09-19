from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bividi import calib_cli
from bividi.calibration import stereo_fisheye_candidate as fisheye
from bividi.calibration import stereo_model_compare as compare


class StereoFisheyeCandidateTests(unittest.TestCase):
    def fisheye_document(self) -> dict:
        pinhole = compare._synthetic_artifact("opencv5", "source", 0.20)
        document = {
            "schema": fisheye.SCHEMA,
            "candidate_id": "fisheye",
            "provenance": dict(pinhole["provenance"]),
            "device": dict(pinhole["device"]),
            "capture": dict(pinhole["capture"]),
            "image": dict(pinhole["image"]),
            "target": dict(pinhole["target"]),
            "camera_model": dict(fisheye.MODEL),
            "cameras": {},
            "stereo": {
                key: value for key, value in pinhole["stereo"].items()
                if key not in {"E", "F"}
            },
            "rectification": {
                key: value for key, value in pinhole["rectification"].items()
                if key not in {"valid_roi_camera_a", "valid_roi_camera_b"}
            },
        }
        for camera in ("camera_a", "camera_b"):
            source = pinhole["cameras"][camera]
            document["cameras"][camera] = {
                "K": source["K"],
                "D": [0.0, 0.0, 0.0, 0.0],
                "mono_rms_px": source["mono_rms_px"],
                "per_view_reprojection_rms_px": source["per_view_reprojection_rms_px"],
            }
        document["stereo"]["stereo_rms_px"] = 0.19
        document["rectification"]["camera_a_map_valid_fraction"] = 0.94
        document["rectification"]["camera_b_map_valid_fraction"] = 0.93
        return document

    def compare_args(self, **updates):
        values = dict(
            selected_model=None,
            policy_source=None,
            max_mono_rms_px=None,
            max_stereo_rms_px=None,
            max_epipolar_p95_px=None,
            min_valid_area_fraction=None,
            min_valid_roi_fraction=None,
        )
        values.update(updates)
        return argparse.Namespace(**values)

    def test_contract_schema_rejects_pinhole_only_fields(self):
        document = self.fisheye_document()
        self.assertEqual(fisheye.validate_candidate(document), [])
        document["stereo"]["F"] = [[0.0] * 3 for _ in range(3)]
        document["cameras"]["camera_a"]["pinhole_fov_deg"] = {"x": 100, "y": 80}
        document["rectification"]["valid_roi_camera_a"] = [0, 0, 1280, 720]
        errors = fisheye.validate_candidate(document)
        self.assertTrue(any("E/F" in item for item in errors))
        self.assertTrue(any("pinhole_fov" in item for item in errors))
        self.assertTrue(any("valid ROI" in item for item in errors))

    def test_cli_route_is_package_native_outside_checkout(self):
        invocation = calib_cli.build_invocation(
            "stereo", "fisheye-evaluate", ["--self-test"],
            source_root=Path("/definitely/not/a/bividi/checkout"),
        )
        self.assertEqual(
            invocation,
            [sys.executable, "-m", "bividi.calibration.stereo_fisheye_candidate", "--self-test"],
        )

    def test_cli_contract_self_test_executes_without_opencv(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = Path.cwd()
            os.chdir(tmp)
            try:
                rc = calib_cli.main([
                    "--source-root", "/definitely/not/a/bividi/checkout",
                    "stereo", "fisheye-evaluate", "--self-test",
                ])
            finally:
                os.chdir(previous)
        self.assertEqual(rc, 0)

    def test_domain_error_maps_to_two(self):
        self.assertEqual(fisheye.entrypoint([]), 2)
        self.assertEqual(fisheye.entrypoint(["--not-an-option"]), 2)

    def test_model_comparison_accepts_pinhole_and_fisheye_same_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pinhole_path = root / "pinhole.json"
            fisheye_path = root / "fisheye.json"
            pinhole_path.write_text(json.dumps(compare._synthetic_artifact("opencv5", "pinhole", 0.20)), encoding="utf-8")
            fisheye_path.write_text(json.dumps(self.fisheye_document()), encoding="utf-8")
            report = compare.compare([pinhole_path, fisheye_path], self.compare_args())
        self.assertEqual(report["selection"]["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual({item["model"] for item in report["candidates"]}, {"opencv5", "opencv-fisheye"})
        pair = report["pairwise_deltas"][0]
        self.assertFalse(pair["valid_area_methods_comparable"])
        self.assertIsNone(pair["min_valid_area_fraction_delta"])

    def test_explicit_fisheye_selection_uses_named_common_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "pinhole.json"
            f = root / "fisheye.json"
            p.write_text(json.dumps(compare._synthetic_artifact("opencv5", "pinhole", 0.20)), encoding="utf-8")
            f.write_text(json.dumps(self.fisheye_document()), encoding="utf-8")
            passed = compare.compare([p, f], self.compare_args(
                selected_model="opencv-fisheye",
                policy_source="model policy FISH-001",
                max_stereo_rms_px=0.20,
                min_valid_area_fraction=0.90,
            ))
            with self.assertRaises(compare.CompareError):
                compare.compare([p, f], self.compare_args(
                    selected_model="opencv-fisheye",
                    policy_source="model policy FISH-001",
                    min_valid_roi_fraction=0.90,
                ))
        self.assertEqual(passed["selection"]["status"], "PASS")
        self.assertEqual(
            passed["selection"]["gates"]["min_valid_area_fraction"]["measurement_method"],
            "fisheye_inverse_map_in_source_domain_fraction",
        )

    def test_evidence_mismatch_rejected_across_schema_families(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "pinhole.json"
            f = root / "fisheye.json"
            p.write_text(json.dumps(compare._synthetic_artifact("opencv5", "pinhole", 0.20)), encoding="utf-8")
            document = self.fisheye_document()
            document["provenance"]["source_session_sha256"] = "2" * 64
            f.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(compare.CompareError):
                compare.compare([p, f], self.compare_args())

    def test_wrapper_is_thin(self):
        root = Path(__file__).resolve().parents[1]
        wrapper = root / "tools" / "evaluate_stereo_fisheye.py"
        text = wrapper.read_text(encoding="utf-8")
        self.assertIn("bividi.calibration.stereo_fisheye_candidate", text)
        self.assertNotIn("def solve_fisheye_core", text)
        completed = subprocess.run(
            [sys.executable, str(wrapper), "--self-test"],
            cwd=root, check=False, capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("Stereo fisheye candidate contract self-test: PASS", completed.stdout)


if __name__ == "__main__":
    unittest.main()
