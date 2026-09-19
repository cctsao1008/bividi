from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bividi import vio_kimera_config as kimera


class KimeraTranslationPlanTests(unittest.TestCase):
    def fixtures(self, root: Path):
        identity = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        K = [[400.0, 0.0, 320.0], [0.0, 400.0, 240.0], [0.0, 0.0, 1.0]]
        stereo = {
            "schema": "bividi.calibration.stereo.v1",
            "calibration_id": "stereo-syn",
            "provenance": {"kind": "synthetic", "source_session_sha256": "0" * 64},
            "device": {"model": "synthetic-stereo", "serial": "SYN-1"},
            "capture": {"mode_index": 0, "pixel_format": "GRAY8", "width": 640, "height": 480, "camera_a_identity": "camera_a", "camera_b_identity": "camera_b"},
            "image": {"width": 640, "height": 480},
            "target": {"target_id": "target", "family": "charuco", "sha256": "1" * 64},
            "camera_model": {"projection": "pinhole", "distortion": "opencv5"},
            "cameras": {
                "camera_a": {"K": K, "D": [0.0] * 5, "mono_rms_px": 0.1, "per_view_reprojection_rms_px": [0.1, 0.1, 0.1], "pinhole_fov_deg": {"x": 77.3, "y": 61.9}},
                "camera_b": {"K": K, "D": [0.0] * 5, "mono_rms_px": 0.1, "per_view_reprojection_rms_px": [0.1, 0.1, 0.1], "pinhole_fov_deg": {"x": 77.3, "y": 61.9}},
            },
            "stereo": {"R_camera_b_from_camera_a": identity, "T_camera_b_from_camera_a_m": [-0.1, 0.0, 0.0], "baseline_m": 0.1, "E": [[0.0,0.0,0.0],[0.0,0.0,0.1],[0.0,-0.1,0.0]], "F": [[0.0,0.0,0.0],[0.0,0.0,0.001],[0.0,-0.001,0.0]], "stereo_rms_px": 0.1, "valid_pair_count": 3},
            "rectification": {"R1": identity, "R2": identity, "P1": [[400.0,0.0,320.0,0.0],[0.0,400.0,240.0,0.0],[0.0,0.0,1.0,0.0]], "P2": [[400.0,0.0,320.0,-40.0],[0.0,400.0,240.0,0.0],[0.0,0.0,1.0,0.0]], "Q": [[1.0,0.0,0.0,-320.0],[0.0,1.0,0.0,-240.0],[0.0,0.0,0.0,400.0],[0.0,0.0,10.0,0.0]], "valid_roi_camera_a": [0,0,640,480], "valid_roi_camera_b": [0,0,640,480], "vertical_epipolar_abs_px": {"count": 3, "min": 0.0, "max": 0.1, "mean": 0.05, "median": 0.05, "p95": 0.095}},
            "quality": {"status": "EVIDENCE_ONLY_NO_THRESHOLDS", "gates": {}, "policy_source": None},
        }
        imu = {
            "schema": "bividi.calibration.imu.v1", "calibration_id": "imu-syn", "created_utc": "2026-09-19T00:00:00+00:00",
            "device": {"model": "synthetic-imu", "serial": "SYN-1"},
            "imu": {"model": "imu", "frame": "imu", "sample_rate_hz_measured": 600.0},
            "frames": {"handedness": "right", "imu_axes": "synthetic"},
            "noise": {"gyroscope_noise_density_rad_s_sqrt_hz": 0.001, "accelerometer_noise_density_m_s2_sqrt_hz": 0.01, "gyroscope_bias_random_walk_rad_s2_sqrt_hz": 0.0001, "accelerometer_bias_random_walk_m_s3_sqrt_hz": 0.001, "method": "synthetic"},
            "provenance": {"kind": "synthetic", "tool": "unit-test"},
        }
        camera_imu = {
            "schema": "bividi.calibration.camera_imu.v1", "calibration_id": "cam-imu-syn", "created_utc": "2026-09-19T00:00:00+00:00",
            "device": {"model": "synthetic-imu", "serial": "SYN-1"},
            "camera_reference": {"camera_id": "camera_a", "frame": "camera_a_optical", "width": 640, "height": 480},
            "imu_reference": {"model": "imu", "frame": "imu", "imu_calibration_id": "imu-syn"},
            "transform": {"from_frame": "imu", "to_frame": "camera_a_optical", "matrix": [[1.0,0.0,0.0,0.03],[0.0,1.0,0.0,0.0],[0.0,0.0,1.0,0.01],[0.0,0.0,0.0,1.0]], "translation_unit": "m"},
            "time_offset": {"definition": kimera.TIME_OFFSET_DEFINITION, "camera_time_reference": "exposure_end", "offset_s": 0.002, "method": "synthetic"},
            "frames": {"handedness": "right", "camera_axes": "synthetic", "imu_axes": "synthetic"},
            "provenance": {"kind": "synthetic", "tool": "unit-test"},
        }
        paths = [root / "stereo.json", root / "imu.json", root / "camera-imu.json"]
        for path, doc in zip(paths, (stereo, imu, camera_imu)):
            path.write_text(json.dumps(doc), encoding="utf-8")
        return paths

    def test_plan_hash_transform_noise_and_time_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            stereo, imu, camera_imu = self.fixtures(Path(tmp))
            plan = kimera.build_plan(stereo, imu, camera_imu)
        self.assertEqual(kimera.validate_plan(plan), [])
        self.assertEqual(plan["upstream"]["revision"], kimera.KIMERA_REVISION)
        self.assertTrue(all(len(item["sha256"]) == 64 for item in plan["sources"].values()))
        self.assertEqual(plan["kimera_imu_params"]["rate_source"], "imu.sample_rate_hz_measured")
        self.assertEqual(plan["time_alignment"]["mapping"], "direct_same_sign_no_negation")
        self.assertEqual(plan["time_alignment"]["kimera_imu_time_shift_s"], 0.002)
        left = plan["kimera_camera_params"]["left"]["T_BS_body_Pose_cam"]
        right = plan["kimera_camera_params"]["right"]["T_BS_body_Pose_cam"]
        self.assertAlmostEqual(left[0][3], -0.03)
        self.assertAlmostEqual(right[0][3], 0.07)
        self.assertAlmostEqual(left[2][3], -0.01)
        self.assertAlmostEqual(right[2][3], -0.01)
        self.assertIsNone(plan["kimera_camera_params"]["left"]["rate_hz"]["value"])

    def test_negative_offset_keeps_same_sign(self):
        with tempfile.TemporaryDirectory() as tmp:
            stereo, imu, camera_imu = self.fixtures(Path(tmp))
            doc = json.loads(camera_imu.read_text(encoding="utf-8"))
            doc["time_offset"]["offset_s"] = -0.003
            camera_imu.write_text(json.dumps(doc), encoding="utf-8")
            plan = kimera.build_plan(stereo, imu, camera_imu)
        self.assertEqual(plan["time_alignment"]["kimera_imu_time_shift_s"], -0.003)

    def test_rational_preserves_opencv_14_vector(self):
        with tempfile.TemporaryDirectory() as tmp:
            stereo, imu, camera_imu = self.fixtures(Path(tmp))
            doc = json.loads(stereo.read_text(encoding="utf-8"))
            doc["camera_model"]["distortion"] = "opencv-rational"
            doc["cameras"]["camera_a"]["D"] = [0.0] * 14
            doc["cameras"]["camera_b"]["D"] = [0.0] * 14
            stereo.write_text(json.dumps(doc), encoding="utf-8")
            plan = kimera.build_plan(stereo, imu, camera_imu)
        self.assertEqual(plan["kimera_camera_params"]["left"]["distortion_model"], "radtan")
        self.assertEqual(len(plan["kimera_camera_params"]["left"]["distortion_coefficients"]), 14)

    def test_missing_noise_rate_and_identity_mismatch_block_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            stereo, imu, camera_imu = self.fixtures(Path(tmp))
            doc = json.loads(imu.read_text(encoding="utf-8"))
            doc["noise"].pop("gyroscope_noise_density_rad_s_sqrt_hz")
            imu.write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaises(kimera.KimeraTranslationError):
                kimera.build_plan(stereo, imu, camera_imu)
        with tempfile.TemporaryDirectory() as tmp:
            stereo, imu, camera_imu = self.fixtures(Path(tmp))
            doc = json.loads(imu.read_text(encoding="utf-8"))
            doc["imu"].pop("sample_rate_hz_measured")
            imu.write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaisesRegex(kimera.KimeraTranslationError, "sample-rate"):
                kimera.build_plan(stereo, imu, camera_imu)
        with tempfile.TemporaryDirectory() as tmp:
            stereo, imu, camera_imu = self.fixtures(Path(tmp))
            doc = json.loads(camera_imu.read_text(encoding="utf-8"))
            doc["device"]["serial"] = "OTHER"
            camera_imu.write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaisesRegex(kimera.KimeraTranslationError, "same device"):
                kimera.build_plan(stereo, imu, camera_imu)

    def test_wrapper_is_thin_and_self_test_passes(self):
        root = Path(__file__).resolve().parents[1]
        wrapper = root / "tools" / "prepare_kimera_vio_translation.py"
        text = wrapper.read_text(encoding="utf-8")
        self.assertIn("bividi.vio_kimera_config", text)
        self.assertNotIn("def build_plan", text)
        completed = subprocess.run([sys.executable, str(wrapper), "--self-test"], cwd=root, capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("Kimera VIO translation-plan self-test: PASS", completed.stdout)


if __name__ == "__main__":
    unittest.main()
