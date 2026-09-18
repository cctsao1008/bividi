import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


TOOL_PATH = Path(__file__).resolve().parents[1] / "tools" / "generate_synthetic_sensorrig.py"
SPEC = importlib.util.spec_from_file_location("bividi_synthetic_sensorrig_tool", TOOL_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class SyntheticSensorRigTests(unittest.TestCase):
    def test_static_plane_is_deterministic_and_replay_layout_compatible(self):
        with tempfile.TemporaryDirectory() as a_tmp, tempfile.TemporaryDirectory() as b_tmp:
            a = Path(a_tmp) / "session"
            b = Path(b_tmp) / "session"
            ga = MODULE.generate(a, "static-plane", frames=4)
            gb = MODULE.generate(b, "static-plane", frames=4)

            self.assertEqual(MODULE.tree_digest(a), MODULE.tree_digest(b))
            self.assertEqual(MODULE.canonical_json(ga), MODULE.canonical_json(gb))
            self.assertEqual(ga["schema"], "bividi.synthetic_sensor_rig.v1")
            self.assertEqual(ga["provenance"]["kind"], "synthetic")
            self.assertFalse(ga["provenance"]["physical_hardware_evidence"])
            self.assertAlmostEqual(ga["scene"]["expected_disparity_px"], 4.0)

            capture = json.loads((a / "capture.json").read_text(encoding="utf-8"))
            self.assertEqual(capture["schema"], MODULE.CAPTURE_SCHEMA)
            self.assertEqual(capture["provenance"]["kind"], "synthetic")
            self.assertTrue((a / "frames.csv").is_file())
            self.assertTrue((a / "imu.csv").is_file())
            self.assertTrue((a / "camera_a" / "0000000000.pgm").is_file())
            self.assertTrue((a / "camera_b" / "0000000000.pgm").is_file())

    def test_moving_fixture_has_motion_and_nonconstant_acceleration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "moving"
            gt = MODULE.generate(root, "moving-rig", frames=12)
            self.assertEqual(gt["scenario"], "moving-rig")
            self.assertNotEqual(
                (root / "camera_a" / "0000000000.pgm").read_bytes(),
                (root / "camera_a" / "0000000010.pgm").read_bytes(),
            )

            rows = (root / "imu.csv").read_text(encoding="utf-8").splitlines()
            self.assertGreater(len(rows), 12)
            accel_y = {line.split(",")[12] for line in rows[1:]}
            self.assertGreater(len(accel_y), 1)

    def test_nonempty_output_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "session"
            root.mkdir()
            (root / "keep.txt").write_text("do not overwrite", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                MODULE.generate(root, "static-plane", frames=2)


if __name__ == "__main__":
    unittest.main()
