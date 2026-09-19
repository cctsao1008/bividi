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
from bividi.calibration import stereo_model_compare as compare


class StereoModelCompareTests(unittest.TestCase):
    def write_candidates(self, root: Path):
        a = root / "opencv5.json"
        b = root / "rational.json"
        a.write_text(json.dumps(compare._synthetic_artifact("opencv5", "opencv5", 0.20)), encoding="utf-8")
        b.write_text(json.dumps(compare._synthetic_artifact("opencv-rational", "rational", 0.18)), encoding="utf-8")
        return a, b

    def args(self, **updates):
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

    def test_cli_route_is_package_native_outside_checkout(self):
        invocation = calib_cli.build_invocation(
            "stereo", "model-compare", ["--self-test"],
            source_root=Path("/definitely/not/a/bividi/checkout"),
        )
        self.assertEqual(invocation, [sys.executable, "-m", "bividi.calibration.stereo_model_compare", "--self-test"])

    def test_cli_executes_self_test_outside_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = Path.cwd()
            os.chdir(tmp)
            try:
                rc = calib_cli.main([
                    "--source-root", "/definitely/not/a/bividi/checkout",
                    "stereo", "model-compare", "--self-test",
                ])
            finally:
                os.chdir(previous)
        self.assertEqual(rc, 0)

    def test_same_evidence_comparison_is_hash_bound_and_insufficient_without_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = self.write_candidates(Path(tmp))
            report = compare.compare([a, b], self.args())
        self.assertEqual(report["schema"], "bividi.calibration.stereo_model_comparison.v1")
        self.assertEqual(report["selection"]["status"], "INSUFFICIENT_EVIDENCE")
        self.assertIsNone(report["selection"]["selected_model"])
        self.assertEqual({item["model"] for item in report["candidates"]}, {"opencv5", "opencv-rational"})
        self.assertTrue(all(len(item["sha256"]) == 64 for item in report["artifacts"]))
        self.assertEqual(len(report["pairwise_deltas"]), 1)
        for item in report["candidates"]:
            for key in (
                "max_mono_rms_px", "stereo_rms_px", "epipolar_p95_px",
                "min_valid_area_fraction", "valid_area_method", "baseline_m",
                "distortion_parameter_count_total",
            ):
                self.assertIn(key, item)

    def test_explicit_policy_pass_and_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = self.write_candidates(Path(tmp))
            passed = compare.compare([a, b], self.args(
                selected_model="opencv-rational", policy_source="lab policy MODEL-001",
                max_stereo_rms_px=0.19, min_valid_roi_fraction=0.99,
            ))
            failed = compare.compare([a, b], self.args(
                selected_model="opencv-rational", policy_source="lab policy MODEL-001",
                max_stereo_rms_px=0.10,
            ))
        self.assertEqual(passed["selection"]["status"], "PASS")
        self.assertEqual(failed["selection"]["status"], "FAIL")

    def test_policy_fail_maps_to_three_domain_failures_to_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = self.write_candidates(Path(tmp))
            self.assertEqual(compare.entrypoint([
                str(a), str(b), "--selected-model", "opencv-rational",
                "--policy-source", "lab policy", "--max-stereo-rms-px", "0.10",
            ]), 3)
            self.assertEqual(compare.entrypoint([str(a), str(b), "--max-stereo-rms-px", "0.20"]), 2)
            self.assertEqual(compare.entrypoint([str(a)]), 2)

    def test_mismatched_session_device_and_target_are_rejected(self):
        mutations = [
            ("session", lambda d: d["provenance"].__setitem__("source_session_sha256", "2" * 64)),
            ("device", lambda d: d["device"].__setitem__("serial", "OTHER")),
            ("target", lambda d: d["target"].__setitem__("sha256", "3" * 64)),
        ]
        for name, mutate in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                a, b = self.write_candidates(root)
                document = json.loads(b.read_text(encoding="utf-8"))
                mutate(document)
                b.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaises(compare.CompareError):
                    compare.compare([a, b], self.args())

    def test_invalid_artifact_is_rejected_by_stereo_validator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a, b = self.write_candidates(root)
            document = json.loads(b.read_text(encoding="utf-8"))
            document["stereo"]["baseline_m"] = 0.5
            b.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(compare.CompareError):
                compare.compare([a, b], self.args())

    def test_wrapper_is_thin_and_runs_self_test(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "tools" / "compare_stereo_camera_models.py").read_text(encoding="utf-8")
        self.assertIn("bividi.calibration.stereo_model_compare", text)
        self.assertNotIn("def compare(", text)
        completed = subprocess.run(
            [sys.executable, str(root / "tools" / "compare_stereo_camera_models.py"), "--self-test"],
            cwd=root, check=False, capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("Stereo camera-model comparator self-test: PASS", completed.stdout)


if __name__ == "__main__":
    unittest.main()
