"""Evaluate an OpenCV fisheye stereo candidate without changing stereo.v1.

The durable ``bividi.calibration.stereo.v1`` contract is pinhole-oriented. This
module therefore emits a separate candidate artifact for #61 model evaluation.
It intentionally does not manufacture pinhole FOV, classical pixel-space F/E,
or pinhole valid-ROI fields.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from .stereo_calibration_common import CAMS, Error, cv, dist, now, save, sha, verified_session
from .stereo_calibration_solve import collect, mat, rot_ok, vec

SCHEMA = "bividi.calibration.stereo_fisheye_candidate.v1"
TOOL_VERSION = "1"
COMPATIBILITY_TOOL_NAME = "evaluate_stereo_fisheye.py"
MODEL = {"projection": "fisheye", "distortion": "opencv-fisheye"}


class CandidateError(ValueError):
    pass


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _matrix(value: Any, rows: int, cols: int) -> bool:
    return isinstance(value, list) and len(value) == rows and all(
        isinstance(row, list) and len(row) == cols and all(_finite(item) for item in row)
        for row in value
    )


def _vector(value: Any, length: int) -> bool:
    return isinstance(value, list) and len(value) == length and all(_finite(item) for item in value)


def _sha256_text(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in value)


def _distribution_ok(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    count = value.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        return False
    return all(_finite(value.get(key)) for key in ("min", "max", "mean", "median", "p95"))


def validate_candidate(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, Mapping):
        return ["candidate must be an object"]
    if data.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    if not isinstance(data.get("candidate_id"), str) or not data.get("candidate_id", "").strip():
        errors.append("candidate_id required")
    provenance = data.get("provenance")
    if not isinstance(provenance, Mapping):
        errors.append("provenance required")
    else:
        if provenance.get("kind") not in ("synthetic", "measured", "imported"):
            errors.append("provenance.kind invalid")
        if not _sha256_text(provenance.get("source_session_sha256")):
            errors.append("provenance.source_session_sha256 invalid")
    if data.get("camera_model") != MODEL:
        errors.append("camera_model must be OpenCV fisheye")
    image = data.get("image")
    if not isinstance(image, Mapping) or not all(
        isinstance(image.get(key), int) and not isinstance(image.get(key), bool) and image.get(key, 0) > 0
        for key in ("width", "height")
    ):
        errors.append("image geometry invalid")
    cameras = data.get("cameras")
    if not isinstance(cameras, Mapping):
        errors.append("cameras required")
    else:
        for cam in CAMS:
            item = cameras.get(cam)
            if not isinstance(item, Mapping):
                errors.append(f"{cam} required")
                continue
            if not _matrix(item.get("K"), 3, 3):
                errors.append(f"{cam}.K invalid")
            if not _vector(item.get("D"), 4):
                errors.append(f"{cam}.D must contain four fisheye coefficients")
            if not _finite(item.get("mono_rms_px")) or float(item.get("mono_rms_px", -1)) < 0:
                errors.append(f"{cam}.mono_rms_px invalid")
            per_view = item.get("per_view_reprojection_rms_px")
            if not isinstance(per_view, list) or not per_view or not all(_finite(x) and float(x) >= 0 for x in per_view):
                errors.append(f"{cam}.per_view_reprojection_rms_px invalid")
            if "pinhole_fov_deg" in item:
                errors.append(f"{cam}.pinhole_fov_deg must not appear in fisheye candidate")
    stereo = data.get("stereo")
    if not isinstance(stereo, Mapping):
        errors.append("stereo required")
    else:
        if not rot_ok(stereo.get("R_camera_b_from_camera_a")):
            errors.append("stereo rotation invalid")
        translation = stereo.get("T_camera_b_from_camera_a_m")
        if not _vector(translation, 3):
            errors.append("stereo translation invalid")
        else:
            norm = math.sqrt(sum(float(x) ** 2 for x in translation))
            baseline = stereo.get("baseline_m")
            if norm <= 0 or not _finite(baseline) or abs(float(baseline) - norm) > max(1e-9, norm * 1e-6):
                errors.append("stereo baseline/translation mismatch")
        if not _finite(stereo.get("stereo_rms_px")) or float(stereo.get("stereo_rms_px", -1)) < 0:
            errors.append("stereo.stereo_rms_px invalid")
        if not isinstance(stereo.get("valid_pair_count"), int) or stereo.get("valid_pair_count", 0) < 3:
            errors.append("stereo.valid_pair_count invalid")
        if "E" in stereo or "F" in stereo:
            errors.append("fisheye candidate must not manufacture classical E/F fields")
    rect = data.get("rectification")
    if not isinstance(rect, Mapping):
        errors.append("rectification required")
    else:
        for key in ("R1", "R2"):
            if not rot_ok(rect.get(key)):
                errors.append(f"{key} invalid")
        for key, rows, cols in (("P1", 3, 4), ("P2", 3, 4), ("Q", 4, 4)):
            if not _matrix(rect.get(key), rows, cols):
                errors.append(f"{key} invalid")
        for key in ("camera_a_map_valid_fraction", "camera_b_map_valid_fraction"):
            if not _finite(rect.get(key)) or not 0.0 <= float(rect.get(key, -1)) <= 1.0:
                errors.append(f"{key} invalid")
        if not _distribution_ok(rect.get("vertical_epipolar_abs_px")):
            errors.append("rectification.vertical_epipolar_abs_px invalid")
        if "valid_roi_camera_a" in rect or "valid_roi_camera_b" in rect:
            errors.append("fisheye candidate must not manufacture pinhole valid ROI fields")
    return errors


def _fisheye_points(np, object_sets, image_sets):
    objects = [np.asarray(item, np.float64).reshape(-1, 1, 3) for item in object_sets]
    images = [np.asarray(item, np.float64).reshape(-1, 1, 2) for item in image_sets]
    return objects, images


def _map_valid_fraction(cv2, np, K, D, R, P, size) -> float:
    map_x, map_y = cv2.fisheye.initUndistortRectifyMap(K, D, R, P, size, cv2.CV_32FC1)
    width, height = size
    valid = (
        np.isfinite(map_x) & np.isfinite(map_y)
        & (map_x >= 0.0) & (map_x <= float(width - 1))
        & (map_y >= 0.0) & (map_y <= float(height - 1))
    )
    return float(np.mean(valid))


def solve_fisheye_core(cv2, np, size, mono, stereo):
    mono_result: dict[str, tuple[Any, ...]] = {}
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_COUNT, 200, 1e-8)
    mono_flags = cv2.fisheye.CALIB_RECOMPUTE_EXTRINSIC | cv2.fisheye.CALIB_FIX_SKEW
    for cam in CAMS:
        if len(mono[cam]["o"]) < 3:
            raise CandidateError(f"{cam}: need >=3 views")
        objects, images = _fisheye_points(np, mono[cam]["o"], mono[cam]["i"])
        K = np.eye(3, dtype=np.float64)
        K[0, 0] = max(size)
        K[1, 1] = max(size)
        K[0, 2] = size[0] / 2.0
        K[1, 2] = size[1] / 2.0
        D = np.zeros((4, 1), np.float64)
        try:
            rms, K, D, rvecs, tvecs = cv2.fisheye.calibrate(
                objects, images, size, K, D, None, None,
                flags=mono_flags, criteria=criteria,
            )
        except cv2.error as exc:
            raise CandidateError(f"{cam}: OpenCV fisheye calibration failed: {exc}") from exc
        per_view: list[float] = []
        for obj, image, rvec, tvec in zip(objects, images, rvecs, tvecs):
            projected, _ = cv2.fisheye.projectPoints(obj, rvec, tvec, K, D)
            error = image.reshape(-1, 2) - projected.reshape(-1, 2)
            per_view.append(float(np.sqrt(np.mean(np.sum(error * error, axis=1)))))
        mono_result[cam] = (float(rms), K, D, per_view)

    if len(stereo) < 3:
        raise CandidateError("need >=3 stereo views with common corners")
    objects, images_a = _fisheye_points(np, [x[0] for x in stereo], [x[1] for x in stereo])
    _, images_b = _fisheye_points(np, [x[0] for x in stereo], [x[2] for x in stereo])
    K1, D1 = mono_result["camera_a"][1], mono_result["camera_a"][2]
    K2, D2 = mono_result["camera_b"][1], mono_result["camera_b"][2]
    try:
        stereo_output = cv2.fisheye.stereoCalibrate(
            objects, images_a, images_b, K1, D1, K2, D2, size,
            flags=cv2.fisheye.CALIB_FIX_INTRINSIC, criteria=criteria,
        )
        # OpenCV Python bindings differ by release: some return only the seven
        # documented stereo values, newer releases append per-view rvec/tvec
        # tuples. The first seven values are stable.
        stereo_rms, K1, D1, K2, D2, R, T = stereo_output[:7]
        R1, R2, P1, P2, Q = cv2.fisheye.stereoRectify(
            K1, D1, K2, D2, size, R, T,
            flags=cv2.CALIB_ZERO_DISPARITY, balance=0.0, fov_scale=1.0,
        )
    except cv2.error as exc:
        raise CandidateError(f"OpenCV fisheye stereo calibration failed: {exc}") from exc

    residuals: list[float] = []
    for camera_a, camera_b in zip(images_a, images_b):
        aa = cv2.fisheye.undistortPoints(camera_a, K1, D1, R=R1, P=P1).reshape(-1, 2)
        bb = cv2.fisheye.undistortPoints(camera_b, K2, D2, R=R2, P=P2).reshape(-1, 2)
        residuals.extend(abs(float(y_a) - float(y_b)) for y_a, y_b in zip(aa[:, 1], bb[:, 1]))
    valid_a = _map_valid_fraction(cv2, np, K1, D1, R1, P1, size)
    valid_b = _map_valid_fraction(cv2, np, K2, D2, R2, P2, size)
    return mono_result, (float(stereo_rms), K1, D1, K2, D2, R, T), (R1, R2, P1, P2, Q, valid_a, valid_b), residuals


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    cv2, np = cv()
    session_path = args.session.resolve()
    session, target_path, target, pairs = verified_session(session_path)
    if target.get("family") != "charuco":
        raise CandidateError("native fisheye evaluation currently supports ChArUco")
    size = (int(session["capture"]["width"]), int(session["capture"]["height"]))
    mono, stereo = collect(session, session_path, target, pairs, cv2, np)
    mono_result, stereo_result, rectification_result, residuals = solve_fisheye_core(cv2, np, size, mono, stereo)
    stereo_rms, K1, D1, K2, D2, R, T = stereo_result
    R1, R2, P1, P2, Q, valid_a, valid_b = rectification_result
    artifact = {
        "schema": SCHEMA,
        "candidate_id": args.candidate_id,
        "created_utc": now(),
        "provenance": {
            "kind": args.provenance,
            "tool": COMPATIBILITY_TOOL_NAME,
            "tool_version": TOOL_VERSION,
            "opencv_version": cv2.__version__,
            "source_session_path": str(session_path),
            "source_session_sha256": sha(session_path),
        },
        "device": session["device"],
        "capture": session["capture"],
        "image": {"width": size[0], "height": size[1]},
        "target": {"target_id": target["target_id"], "family": target["family"], "path": str(target_path), "sha256": sha(target_path)},
        "camera_model": dict(MODEL),
        "cameras": {
            "camera_a": {"K": mat(K1), "D": vec(D1), "mono_rms_px": mono_result["camera_a"][0], "per_view_reprojection_rms_px": mono_result["camera_a"][3]},
            "camera_b": {"K": mat(K2), "D": vec(D2), "mono_rms_px": mono_result["camera_b"][0], "per_view_reprojection_rms_px": mono_result["camera_b"][3]},
        },
        "stereo": {
            "frame_convention": "R/T transform points from camera_a into camera_b",
            "R_camera_b_from_camera_a": mat(R),
            "T_camera_b_from_camera_a_m": vec(T),
            "baseline_m": float(np.linalg.norm(T)),
            "stereo_rms_px": stereo_rms,
            "valid_pair_count": len(stereo),
        },
        "rectification": {
            "R1": mat(R1), "R2": mat(R2), "P1": mat(P1), "P2": mat(P2), "Q": mat(Q),
            "camera_a_map_valid_fraction": valid_a,
            "camera_b_map_valid_fraction": valid_b,
            "vertical_epipolar_abs_px": dist(residuals),
        },
        "guardrails": [
            "Candidate evaluation only; this is not a promoted stereo.v1 calibration artifact.",
            "No classical E/F fields are asserted for distorted fisheye pixel coordinates.",
            "No pinhole FOV or pinhole validROI semantics are manufactured.",
            "camera_a/camera_b naming is preserved until physical mapping evidence exists.",
        ],
    }
    errors = validate_candidate(artifact)
    if errors:
        raise CandidateError("generated fisheye candidate invalid: " + "; ".join(errors))
    return artifact


def _synthetic_core_fixture(cv2, np):
    size = (1280, 720)
    K = np.asarray([[620.0, 0.0, 640.0], [0.0, 618.0, 360.0], [0.0, 0.0, 1.0]], np.float64)
    D = np.asarray([[-0.03], [0.004], [-0.0005], [0.00008]], np.float64)
    baseline = 0.08
    obj = np.asarray([[x * 0.04, y * 0.04, 0.0] for y in range(5) for x in range(7)], np.float64).reshape(-1, 1, 3)
    mono = {camera: {"o": [], "i": []} for camera in CAMS}
    stereo = []
    for i in range(12):
        rvec = np.asarray([[0.04 * math.sin(i * 0.7)], [0.05 * math.cos(i * 0.5)], [0.025 * math.sin(i * 0.3)]], np.float64)
        tvec_a = np.asarray([[-0.12 + 0.02 * (i % 6)], [-0.07 + 0.025 * (i % 5)], [0.75 + 0.04 * (i % 4)]], np.float64)
        rotation_a, _ = cv2.Rodrigues(rvec)
        tvec_b = tvec_a + np.asarray([[-baseline], [0.0], [0.0]], np.float64)
        rvec_b, _ = cv2.Rodrigues(rotation_a)
        camera_a, _ = cv2.fisheye.projectPoints(obj, rvec, tvec_a, K, D)
        camera_b, _ = cv2.fisheye.projectPoints(obj, rvec_b, tvec_b, K, D)
        for camera, points in (("camera_a", camera_a), ("camera_b", camera_b)):
            mono[camera]["o"].append(obj.reshape(-1, 3).astype(np.float32))
            mono[camera]["i"].append(points.astype(np.float32))
        stereo.append((obj.reshape(-1, 3).astype(np.float32), camera_a.astype(np.float32), camera_b.astype(np.float32)))
    return size, mono, stereo, baseline


def self_test_opencv() -> None:
    cv2, np = cv()
    size, mono, stereo, baseline = _synthetic_core_fixture(cv2, np)
    _, stereo_result, rectification, residuals = solve_fisheye_core(cv2, np, size, mono, stereo)
    recovered = float(np.linalg.norm(stereo_result[6]))
    if abs(recovered - baseline) >= 3e-3:
        raise AssertionError(f"fisheye baseline recovery error: expected {baseline}, got {recovered}")
    if (dist(residuals)["p95"] or 99.0) >= 0.1:
        raise AssertionError("fisheye rectified epipolar p95 too large")
    if not (0.0 < rectification[5] <= 1.0 and 0.0 < rectification[6] <= 1.0):
        raise AssertionError("fisheye valid-map fraction invalid")
    print("Stereo fisheye candidate OpenCV self-test: PASS")


def self_test() -> None:
    identity = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    K = [[400.0, 0.0, 320.0], [0.0, 400.0, 240.0], [0.0, 0.0, 1.0]]
    fixture = {
        "schema": SCHEMA,
        "candidate_id": "synthetic-contract",
        "provenance": {"kind": "synthetic", "source_session_sha256": "0" * 64},
        "device": {"model": "S", "serial": "1"},
        "capture": {"mode_index": 0, "pixel_format": "mono8", "width": 640, "height": 480, "camera_a_identity": "camera_a", "camera_b_identity": "camera_b"},
        "image": {"width": 640, "height": 480},
        "target": {"target_id": "t", "family": "charuco", "sha256": "1" * 64},
        "camera_model": dict(MODEL),
        "cameras": {
            "camera_a": {"K": K, "D": [0.0] * 4, "mono_rms_px": 0.1, "per_view_reprojection_rms_px": [0.1] * 3},
            "camera_b": {"K": K, "D": [0.0] * 4, "mono_rms_px": 0.1, "per_view_reprojection_rms_px": [0.1] * 3},
        },
        "stereo": {"R_camera_b_from_camera_a": identity, "T_camera_b_from_camera_a_m": [-0.08, 0.0, 0.0], "baseline_m": 0.08, "stereo_rms_px": 0.1, "valid_pair_count": 3},
        "rectification": {
            "R1": identity, "R2": identity,
            "P1": [[400.0, 0.0, 320.0, 0.0], [0.0, 400.0, 240.0, 0.0], [0.0, 0.0, 1.0, 0.0]],
            "P2": [[400.0, 0.0, 320.0, -32.0], [0.0, 400.0, 240.0, 0.0], [0.0, 0.0, 1.0, 0.0]],
            "Q": [[1.0, 0.0, 0.0, -320.0], [0.0, 1.0, 0.0, -240.0], [0.0, 0.0, 0.0, 400.0], [0.0, 0.0, 12.5, 0.0]],
            "camera_a_map_valid_fraction": 0.9, "camera_b_map_valid_fraction": 0.9,
            "vertical_epipolar_abs_px": {"count": 3, "min": 0.0, "max": 0.1, "mean": 0.05, "median": 0.05, "p95": 0.095},
        },
    }
    assert not validate_candidate(fixture), validate_candidate(fixture)
    broken = json.loads(json.dumps(fixture))
    broken["stereo"]["F"] = [[0.0] * 3 for _ in range(3)]
    assert any("must not manufacture" in item for item in validate_candidate(broken))
    print("Stereo fisheye candidate contract self-test: PASS")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--self-test-opencv", action="store_true")
    parser.add_argument("session", nargs="?", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--candidate-id")
    parser.add_argument("--provenance", choices=("synthetic", "measured", "imported"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if args.self_test_opencv:
        self_test_opencv()
        return 0
    if args.session is None or args.output is None or not args.candidate_id or not args.provenance:
        raise CandidateError("session, --output, --candidate-id and --provenance are required")
    artifact = evaluate(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    save(args.output, artifact)
    print(args.output)
    return 0


def entrypoint(argv: Sequence[str] | None = None) -> int:
    try:
        return main(argv)
    except (CandidateError, Error, OSError, ValueError) as exc:
        print(f"fisheye candidate evaluation failed: {exc}", file=sys.stderr)
        return 2
    except SystemExit as exc:
        return 0 if exc.code in (None, 0) else 2


if __name__ == "__main__":
    raise SystemExit(entrypoint())
