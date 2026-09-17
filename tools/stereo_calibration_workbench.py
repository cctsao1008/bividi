#!/usr/bin/env python3
"""CLI entry point for the Bividi #8 stereo calibration workbench."""
import argparse
import math
from pathlib import Path

from stereo_calibration_common import *
from stereo_calibration_recorder import recorder_self_test, session_from_recorder
from stereo_calibration_solve import *


def self_test():
    assert abs(coverage([[0, 0], [99, 0], [99, 99], [0, 99]], 100, 100) - 1) < 1e-12
    K = [[700.0, 0.0, 640.0], [0.0, 700.0, 360.0], [0.0, 0.0, 1.0]]
    identity = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    artifact = {
        "schema": CALIB,
        "calibration_id": "synthetic-contract-test",
        "provenance": {"kind": "synthetic", "source_session_sha256": "0" * 64},
        "device": {"model": "synthetic", "serial": "synthetic-001"},
        "capture": {
            "mode_index": 0, "pixel_format": "mono8_png", "width": 1280, "height": 720,
            "camera_a_identity": "camera_a", "camera_b_identity": "camera_b",
        },
        "image": {"width": 1280, "height": 720},
        "target": {"target_id": "synthetic-target", "family": "charuco", "sha256": "1" * 64},
        "camera_model": {"projection": "pinhole", "distortion": "opencv5"},
        "cameras": {
            "camera_a": {"K": K, "D": [0, 0, 0, 0, 0], "mono_rms_px": 0.1, "per_view_reprojection_rms_px": [0.1, 0.1, 0.1], "pinhole_fov_deg": {"x": 84.9, "y": 54.4}},
            "camera_b": {"K": K, "D": [0, 0, 0, 0, 0], "mono_rms_px": 0.1, "per_view_reprojection_rms_px": [0.1, 0.1, 0.1], "pinhole_fov_deg": {"x": 84.9, "y": 54.4}},
        },
        "stereo": {
            "R_camera_b_from_camera_a": identity,
            "T_camera_b_from_camera_a_m": [-0.08, 0.0, 0.0],
            "baseline_m": 0.08,
            "E": [[0.0, 0.0, 0.0], [0.0, 0.0, 0.08], [0.0, -0.08, 0.0]],
            "F": [[0.0, 0.0, 0.0], [0.0, 0.0, 0.001], [0.0, -0.001, 0.0]],
            "stereo_rms_px": 0.1,
            "valid_pair_count": 3,
        },
        "rectification": {
            "R1": identity, "R2": identity,
            "P1": [[700.0, 0.0, 640.0, 0.0], [0.0, 700.0, 360.0, 0.0], [0.0, 0.0, 1.0, 0.0]],
            "P2": [[700.0, 0.0, 640.0, -56.0], [0.0, 700.0, 360.0, 0.0], [0.0, 0.0, 1.0, 0.0]],
            "Q": [[1.0, 0.0, 0.0, -640.0], [0.0, 1.0, 0.0, -360.0], [0.0, 0.0, 0.0, 700.0], [0.0, 0.0, 12.5, 0.0]],
            "valid_roi_camera_a": [0, 0, 1280, 720], "valid_roi_camera_b": [0, 0, 1280, 720],
            "vertical_epipolar_abs_px": {"count": 3, "min": 0.0, "max": 0.1, "mean": 0.05, "median": 0.05, "p95": 0.095},
        },
        "quality": {"status": "EVIDENCE_ONLY_NO_THRESHOLDS", "gates": {}, "policy_source": None},
    }
    assert not validate(artifact), validate(artifact)
    broken = dict(artifact)
    broken.pop("calibration_id")
    assert "calibration_id required" in validate(broken)
    recorder_self_test()
    print("Stereo calibration workbench dependency-free self-test: PASS")


def self_test_cv():
    cv2, np = cv()
    width, height = 1280, 720
    K = np.asarray([[760.0, 0, 640], [0, 758.0, 360], [0, 0, 1]], np.float64)
    D = np.zeros((5, 1))
    baseline = 0.08
    obj = np.asarray([[x * 0.035, y * 0.035, 0] for y in range(5) for x in range(7)], np.float32)
    mono = {camera: {"o": [], "i": []} for camera in CAMS}
    stereo = []
    for i in range(10):
        rvec = np.asarray([[0.03 * math.sin(i)], [0.05 * math.cos(i * 0.7)], [0.02 * math.sin(i * 0.4)]])
        tvec = np.asarray([[-0.10 + 0.02 * i], [-0.06 + 0.012 * (i % 4)], [0.75 + 0.03 * (i % 3)]])
        Ra, _ = cv2.Rodrigues(rvec)
        tb = tvec + np.asarray([[-baseline], [0], [0]])
        rb, _ = cv2.Rodrigues(Ra)
        pa, _ = cv2.projectPoints(obj, rvec, tvec, K, D)
        pb, _ = cv2.projectPoints(obj, rb, tb, K, D)
        pa, pb = pa.astype(np.float32), pb.astype(np.float32)
        for camera, points in (("camera_a", pa), ("camera_b", pb)):
            mono[camera]["o"].append(obj.copy())
            mono[camera]["i"].append(points)
        stereo.append((obj.copy(), pa, pb))
    _, stereo_result, _, residuals = solve_core(cv2, np, (width, height), mono, stereo)
    assert abs(float(np.linalg.norm(stereo_result[6])) - baseline) < 2e-3
    assert (pctile(residuals, 0.95) or 99) < 0.05
    print("Stereo calibration OpenCV synthetic solver self-test: PASS")


def args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--self-test-opencv", action="store_true")
    sub = parser.add_subparsers(dest="cmd")

    command = sub.add_parser("target")
    command.add_argument("--family", choices=("charuco", "aprilgrid"), required=True)
    command.add_argument("--target-id", required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--render", type=Path)
    command.add_argument("--render-width-px", type=int, default=2400)
    command.add_argument("--render-height-px", type=int, default=1600)
    command.add_argument("--render-margin-px", type=int, default=40)
    command.add_argument("--dictionary", default="DICT_5X5_1000")
    command.add_argument("--squares-x", type=int, default=8)
    command.add_argument("--squares-y", type=int, default=6)
    command.add_argument("--square-mm", type=float, default=30.0)
    command.add_argument("--marker-mm", type=float, default=22.0)
    command.add_argument("--tag-family", default="tag36h11")
    command.add_argument("--tag-rows", type=int, default=6)
    command.add_argument("--tag-cols", type=int, default=6)
    command.add_argument("--tag-size-mm", type=float, default=36.0)
    command.add_argument("--tag-spacing-ratio", type=float, default=0.3)
    command.add_argument("--kalibr-yaml", type=Path)

    command = sub.add_parser("session")
    command.add_argument("--session-id", required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--target", type=Path, required=True)
    command.add_argument("--camera-a-dir", type=Path, required=True)
    command.add_argument("--camera-b-dir", type=Path, required=True)
    command.add_argument("--glob", default="*.png")
    command.add_argument("--allow-unpaired", action="store_true")
    command.add_argument("--model", required=True)
    command.add_argument("--serial", required=True)
    command.add_argument("--device", type=int, required=True)
    command.add_argument("--mode", type=int, required=True)
    command.add_argument("--pixel-format", required=True)
    command.add_argument("--width", type=int, required=True)
    command.add_argument("--height", type=int, required=True)
    command.add_argument("--camera-mapping-evidence")
    command.add_argument("--provenance", choices=("synthetic", "measured", "imported"), required=True)

    command = sub.add_parser("session-recorder")
    command.add_argument("--session-id", required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--target", type=Path, required=True)
    command.add_argument("--recorder-dir", type=Path, required=True)
    command.add_argument("--model", required=True)
    command.add_argument("--camera-mapping-evidence")

    command = sub.add_parser("inspect")
    command.add_argument("session", type=Path)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--policy-source")
    command.add_argument("--min-valid-pairs", type=int)
    command.add_argument("--min-common-corners", type=float)
    command.add_argument("--min-global-hull-fraction", type=float)
    command.add_argument("--min-sharpness", type=float)
    command.add_argument("--max-saturation-fraction", type=float)

    command = sub.add_parser("solve")
    command.add_argument("session", type=Path)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--calibration-id", required=True)
    command.add_argument("--provenance", choices=("synthetic", "measured", "imported"), required=True)
    command.add_argument("--distortion-model", choices=("opencv5", "opencv-rational"), default="opencv5")
    command.add_argument("--policy-source")
    command.add_argument("--max-mono-rms-px", type=float)
    command.add_argument("--max-stereo-rms-px", type=float)
    command.add_argument("--max-epipolar-p95-px", type=float)

    command = sub.add_parser("validate")
    command.add_argument("artifact", type=Path)

    command = sub.add_parser("rectify")
    command.add_argument("--calibration", type=Path, required=True)
    command.add_argument("--camera-a", type=Path, required=True)
    command.add_argument("--camera-b", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--line-spacing-px", type=int, default=60)
    return parser.parse_args(argv)


def main(argv=None):
    parsed = args(argv)
    if parsed.self_test:
        self_test()
        return 0
    if parsed.self_test_opencv:
        self_test_cv()
        return 0
    if parsed.cmd == "target":
        target_cmd(parsed)
    elif parsed.cmd == "session":
        session_cmd(parsed)
    elif parsed.cmd == "session-recorder":
        session_from_recorder(parsed)
    elif parsed.cmd == "inspect":
        inspect_cmd(parsed)
    elif parsed.cmd == "solve":
        solve_cmd(parsed)
    elif parsed.cmd == "validate":
        errors = validate(load(parsed.artifact.resolve()))
        if errors:
            for error in errors:
                print("ERROR:", error)
            return 2
        print("Stereo calibration artifact: VALID")
    elif parsed.cmd == "rectify":
        rectify_cmd(parsed)
    else:
        raise Error("choose command or --self-test")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Error as error:
        print(f"error: {error}", file=__import__("sys").stderr)
        raise SystemExit(2)
