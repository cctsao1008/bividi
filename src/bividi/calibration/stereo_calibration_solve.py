#!/usr/bin/env python3
"""OpenCV solve/rectification helpers for stereo_calibration_workbench.py."""
from __future__ import annotations

from collections.abc import Mapping

from .stereo_calibration_common import *


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _matrix(value, rows, cols):
    return (
        isinstance(value, list)
        and len(value) == rows
        and all(isinstance(row, list) and len(row) == cols and all(_finite(x) for x in row) for row in value)
    )


def _vector(value, length=None, min_length=None):
    if not isinstance(value, list) or not all(_finite(x) for x in value):
        return False
    if length is not None and len(value) != length:
        return False
    if min_length is not None and len(value) < min_length:
        return False
    return True


def _sha256_text(value):
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in value)


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def _nonnegative(value):
    return _finite(value) and float(value) >= 0.0


def _distribution_ok(value, require_samples=False):
    if not isinstance(value, Mapping):
        return False
    count = value.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        return False
    if require_samples and count <= 0:
        return False
    for key in ("min", "max", "mean", "median", "p95"):
        item = value.get(key)
        if count == 0:
            if item is not None:
                return False
        elif not _finite(item):
            return False
    return True


def _verify_hash_entry(owner, entry, label):
    if not isinstance(entry, Mapping) or not _nonempty(entry.get("path")) or not _sha256_text(entry.get("sha256")):
        raise Error(f"{label}: invalid path/hash binding")
    path = resolve(owner, entry["path"])
    if not path.is_file():
        raise Error(f"{label}: missing {path}")
    if sha(path) != entry["sha256"]:
        raise Error(f"{label}: SHA-256 mismatch")
    return path


def verify_session_trace(session, session_path):
    trace = session.get("source_trace")
    if trace is None:
        return
    if not isinstance(trace, Mapping) or not _nonempty(trace.get("kind")):
        raise Error("session source_trace is malformed")
    artifacts = trace.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise Error("session source_trace.artifacts must be a non-empty array")
    roles = set()
    for entry in artifacts:
        role = entry.get("role") if isinstance(entry, Mapping) else None
        if not _nonempty(role) or role in roles:
            raise Error("session source_trace contains an invalid/duplicate role")
        roles.add(role)
        _verify_hash_entry(session_path, entry, f"source_trace.{role}")


def _verify_pair_file(meta, key, path):
    hash_key = key + "_sha256"
    if hash_key in meta:
        if not _sha256_text(meta[hash_key]):
            raise Error(f"{meta.get('pair_id', '<pair>')}: invalid {hash_key}")
        if sha(path) != meta[hash_key]:
            raise Error(f"{meta.get('pair_id', '<pair>')}: {key} SHA-256 mismatch")


def collect(s, sp, t, pairs, cv2, np):
    if t["family"] != "charuco":
        raise Error("native solve currently supports ChArUco")
    verify_session_trace(s, sp)
    b = board(cv2, t)
    obj = board_pts(b, np)
    expected_size = (int(s["capture"]["width"]), int(s["capture"]["height"]))
    mono = {c: {"o": [], "i": []} for c in CAMS}
    stereo = []
    for meta, pa, pb in pairs:
        detections = {}
        for cam, path in (("camera_a", pa), ("camera_b", pb)):
            _verify_pair_file(meta, cam, path)
            image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if image is None:
                raise Error(f"cannot decode calibration image: {path}")
            actual_size = (int(image.shape[1]), int(image.shape[0]))
            if actual_size != expected_size:
                raise Error(f"{path}: image geometry {actual_size} differs from session {expected_size}")
            points, ids = detect(image, b, cv2, np)
            if len(ids) != len(points):
                raise Error(f"{path}: detector returned mismatched corner IDs/points")
            if len(set(ids)) != len(ids) or any(k < 0 or k >= len(obj) for k in ids):
                raise Error(f"{path}: detector returned duplicate/out-of-range corner IDs")
            detections[cam] = (points, ids)
            if len(ids) >= 4:
                mono[cam]["o"].append(np.asarray([obj[k] for k in ids], np.float32))
                mono[cam]["i"].append(np.asarray(points, np.float32).reshape(-1, 1, 2))
        common = sorted(set(detections["camera_a"][1]) & set(detections["camera_b"][1]))
        if len(common) >= 4:
            ia = {value: i for i, value in enumerate(detections["camera_a"][1])}
            ib = {value: i for i, value in enumerate(detections["camera_b"][1])}
            stereo.append((
                np.asarray([obj[k] for k in common], np.float32),
                np.asarray([detections["camera_a"][0][ia[k]] for k in common], np.float32).reshape(-1, 1, 2),
                np.asarray([detections["camera_b"][0][ib[k]] for k in common], np.float32).reshape(-1, 1, 2),
            ))
    return mono, stereo


def solve_core(cv2, np, size, mono, stereo, flags=0):
    mono_result = {}
    for cam in CAMS:
        if len(mono[cam]["o"]) < 3:
            raise Error(f"{cam}: need >=3 views")
        rms, K, D, rvecs, tvecs = cv2.calibrateCamera(
            mono[cam]["o"], mono[cam]["i"], size, None, None, flags=flags
        )
        per_view = []
        for obj, image, rvec, tvec in zip(mono[cam]["o"], mono[cam]["i"], rvecs, tvecs):
            projected, _ = cv2.projectPoints(obj, rvec, tvec, K, D)
            error = image.reshape(-1, 2) - projected.reshape(-1, 2)
            per_view.append(float(np.sqrt(np.mean(np.sum(error * error, axis=1)))))
        mono_result[cam] = (float(rms), K, D, per_view)
    if len(stereo) < 3:
        raise Error("need >=3 stereo views with common corners")
    stereo_rms, K1, D1, K2, D2, R, T, E, F = cv2.stereoCalibrate(
        [x[0] for x in stereo],
        [x[1] for x in stereo],
        [x[2] for x in stereo],
        mono_result["camera_a"][1],
        mono_result["camera_a"][2],
        mono_result["camera_b"][1],
        mono_result["camera_b"][2],
        size,
        criteria=(cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_COUNT, 100, 1e-7),
        flags=cv2.CALIB_FIX_INTRINSIC,
    )
    R1, R2, P1, P2, Q, roi1, roi2 = cv2.stereoRectify(
        K1, D1, K2, D2, size, R, T, flags=cv2.CALIB_ZERO_DISPARITY, alpha=-1
    )
    residuals = []
    for _, camera_a, camera_b in stereo:
        aa = cv2.undistortPoints(camera_a, K1, D1, R=R1, P=P1).reshape(-1, 2)
        bb = cv2.undistortPoints(camera_b, K2, D2, R=R2, P=P2).reshape(-1, 2)
        residuals.extend(abs(float(y_a) - float(y_b)) for y_a, y_b in zip(aa[:, 1], bb[:, 1]))
    return (
        mono_result,
        (float(stereo_rms), K1, D1, K2, D2, R, T, E, F),
        (R1, R2, P1, P2, Q, list(map(int, roi1)), list(map(int, roi2))),
        residuals,
    )


def mat(value):
    return [[float(v) for v in row] for row in value.tolist()]


def vec(value):
    return [float(v) for v in value.reshape(-1).tolist()]


def rot_ok(rotation, tol=1e-5):
    if not _matrix(rotation, 3, 3):
        return False
    for i in range(3):
        for j in range(3):
            dot = sum(float(rotation[k][i]) * float(rotation[k][j]) for k in range(3))
            if abs(dot - (1.0 if i == j else 0.0)) > tol:
                return False
    determinant = (
        rotation[0][0] * (rotation[1][1] * rotation[2][2] - rotation[1][2] * rotation[2][1])
        - rotation[0][1] * (rotation[1][0] * rotation[2][2] - rotation[1][2] * rotation[2][0])
        + rotation[0][2] * (rotation[1][0] * rotation[2][1] - rotation[1][1] * rotation[2][0])
    )
    return abs(float(determinant) - 1.0) <= tol


def validate(d):
    errors = []
    if not isinstance(d, Mapping):
        return ["artifact must be an object"]
    if d.get("schema") != CALIB:
        errors.append(f"schema must be {CALIB}")
    if not _nonempty(d.get("calibration_id")):
        errors.append("calibration_id required")

    provenance = d.get("provenance")
    if not isinstance(provenance, Mapping):
        errors.append("provenance required")
    else:
        if provenance.get("kind") not in ("synthetic", "measured", "imported"):
            errors.append("provenance.kind invalid")
        if not _sha256_text(provenance.get("source_session_sha256")):
            errors.append("provenance.source_session_sha256 invalid")

    device = d.get("device")
    if not isinstance(device, Mapping) or not _nonempty(device.get("model")) or not _nonempty(device.get("serial")):
        errors.append("device.model/device.serial required")

    capture = d.get("capture")
    if not isinstance(capture, Mapping):
        errors.append("capture required")
    else:
        if not isinstance(capture.get("mode_index"), int) or isinstance(capture.get("mode_index"), bool) or capture.get("mode_index", -1) < 0:
            errors.append("capture.mode_index invalid")
        if not _nonempty(capture.get("pixel_format")):
            errors.append("capture.pixel_format required")
        for key in ("width", "height"):
            if not isinstance(capture.get(key), int) or isinstance(capture.get(key), bool) or capture.get(key, 0) <= 0:
                errors.append(f"capture.{key} invalid")
        for key in ("camera_a_identity", "camera_b_identity"):
            if not _nonempty(capture.get(key)):
                errors.append(f"capture.{key} required")

    image = d.get("image")
    if not isinstance(image, Mapping):
        errors.append("image required")
    else:
        for key in ("width", "height"):
            if not isinstance(image.get(key), int) or isinstance(image.get(key), bool) or image.get(key, 0) <= 0:
                errors.append(f"image.{key} invalid")
        if isinstance(capture, Mapping) and image.get("width") != capture.get("width"):
            errors.append("image.width differs from capture.width")
        if isinstance(capture, Mapping) and image.get("height") != capture.get("height"):
            errors.append("image.height differs from capture.height")

    target = d.get("target")
    if not isinstance(target, Mapping):
        errors.append("target required")
    else:
        if not _nonempty(target.get("target_id")):
            errors.append("target.target_id required")
        if target.get("family") not in ("charuco", "aprilgrid"):
            errors.append("target.family invalid")
        if not _sha256_text(target.get("sha256")):
            errors.append("target.sha256 invalid")

    camera_model = d.get("camera_model")
    if not isinstance(camera_model, Mapping):
        errors.append("camera_model required")
    else:
        if camera_model.get("projection") != "pinhole":
            errors.append("camera_model.projection must be pinhole in stereo.v1")
        if camera_model.get("distortion") not in ("opencv5", "opencv-rational"):
            errors.append("camera_model.distortion invalid")

    cameras = d.get("cameras")
    if not isinstance(cameras, Mapping):
        errors.append("cameras required")
    else:
        for cam in CAMS:
            camera = cameras.get(cam)
            if not isinstance(camera, Mapping):
                errors.append(f"{cam} required")
                continue
            K = camera.get("K")
            D = camera.get("D")
            if not _matrix(K, 3, 3) or float(K[0][0]) <= 0 or float(K[1][1]) <= 0 or abs(float(K[2][2]) - 1.0) > 1e-6:
                errors.append(f"{cam}.K invalid")
            if not _vector(D, min_length=4):
                errors.append(f"{cam}.D invalid")
            if not _nonnegative(camera.get("mono_rms_px")):
                errors.append(f"{cam}.mono_rms_px invalid")
            per_view = camera.get("per_view_reprojection_rms_px")
            if not isinstance(per_view, list) or not per_view or not all(_nonnegative(x) for x in per_view):
                errors.append(f"{cam}.per_view_reprojection_rms_px invalid")
            fov = camera.get("pinhole_fov_deg")
            if not isinstance(fov, Mapping) or not all(_finite(fov.get(axis)) and 0.0 < float(fov[axis]) < 180.0 for axis in ("x", "y")):
                errors.append(f"{cam}.pinhole_fov_deg invalid")

    stereo = d.get("stereo")
    if not isinstance(stereo, Mapping):
        errors.append("stereo required")
    else:
        rotation = stereo.get("R_camera_b_from_camera_a")
        translation = stereo.get("T_camera_b_from_camera_a_m")
        if not rot_ok(rotation):
            errors.append("stereo rotation invalid")
        if not _vector(translation, length=3) or math.sqrt(sum(float(x) ** 2 for x in translation)) <= 0:
            errors.append("stereo translation invalid")
        else:
            norm = math.sqrt(sum(float(x) ** 2 for x in translation))
            baseline = stereo.get("baseline_m")
            if not _finite(baseline) or float(baseline) <= 0:
                errors.append("stereo.baseline_m invalid")
            elif abs(float(baseline) - norm) > max(1e-9, norm * 1e-6):
                errors.append("stereo.baseline_m differs from ||T||")
        if not _matrix(stereo.get("E"), 3, 3):
            errors.append("stereo.E invalid")
        if not _matrix(stereo.get("F"), 3, 3):
            errors.append("stereo.F invalid")
        if not _nonnegative(stereo.get("stereo_rms_px")):
            errors.append("stereo.stereo_rms_px invalid")
        if not isinstance(stereo.get("valid_pair_count"), int) or isinstance(stereo.get("valid_pair_count"), bool) or stereo.get("valid_pair_count", 0) < 3:
            errors.append("stereo.valid_pair_count invalid")

    rectification = d.get("rectification")
    if not isinstance(rectification, Mapping):
        errors.append("rectification required")
    else:
        for key in ("R1", "R2"):
            if not rot_ok(rectification.get(key)):
                errors.append(f"{key} invalid")
        for key, rows, cols in (("P1", 3, 4), ("P2", 3, 4), ("Q", 4, 4)):
            if not _matrix(rectification.get(key), rows, cols):
                errors.append(f"{key} invalid")
        for key in ("valid_roi_camera_a", "valid_roi_camera_b"):
            roi = rectification.get(key)
            if not isinstance(roi, list) or len(roi) != 4 or not all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in roi):
                errors.append(f"{key} invalid")
        if not _distribution_ok(rectification.get("vertical_epipolar_abs_px"), require_samples=True):
            errors.append("rectification.vertical_epipolar_abs_px invalid")

    quality = d.get("quality")
    if not isinstance(quality, Mapping):
        errors.append("quality required")
    else:
        status = quality.get("status")
        if status not in ("EVIDENCE_ONLY_NO_THRESHOLDS", "PASS", "FAIL"):
            errors.append("quality.status invalid")
        gates = quality.get("gates")
        if not isinstance(gates, Mapping):
            errors.append("quality.gates must be an object")
        elif status in ("PASS", "FAIL"):
            if not gates:
                errors.append("gated quality status requires at least one gate")
            if not _nonempty(quality.get("policy_source")):
                errors.append("gated quality status requires policy_source")
            for name, gate in gates.items():
                if not isinstance(gate, Mapping) or not isinstance(gate.get("pass"), bool):
                    errors.append(f"quality.gates.{name} invalid")
    return errors


def solve_cmd(a):
    cv2, np = cv()
    session_path = a.session.resolve()
    session, target_path, target, pairs = verified_session(session_path)
    size = (session["capture"]["width"], session["capture"]["height"])
    mono, stereo = collect(session, session_path, target, pairs, cv2, np)
    flags = cv2.CALIB_RATIONAL_MODEL if a.distortion_model == "opencv-rational" else 0
    mono_result, stereo_result, rectification_result, residuals = solve_core(cv2, np, size, mono, stereo, flags)
    stereo_rms, K1, D1, K2, D2, R, T, E, F = stereo_result
    R1, R2, P1, P2, Q, roi1, roi2 = rectification_result
    baseline = float(np.linalg.norm(T))
    gates = {}
    artifact = {
        "schema": CALIB,
        "calibration_id": a.calibration_id,
        "created_utc": now(),
        "provenance": {
            "kind": a.provenance,
            "tool": Path(__file__).name,
            "tool_version": VERSION,
            "opencv_version": cv2.__version__,
            "source_session_path": str(session_path),
            "source_session_sha256": sha(session_path),
        },
        "device": session["device"],
        "capture": session["capture"],
        "image": {"width": size[0], "height": size[1]},
        "target": {
            "target_id": target["target_id"],
            "family": target["family"],
            "path": str(target_path),
            "sha256": sha(target_path),
        },
        "camera_model": {"projection": "pinhole", "distortion": a.distortion_model},
        "cameras": {
            "camera_a": {
                "K": mat(K1), "D": vec(D1), "mono_rms_px": mono_result["camera_a"][0],
                "per_view_reprojection_rms_px": mono_result["camera_a"][3],
                "pinhole_fov_deg": {
                    "x": math.degrees(2 * math.atan(size[0] / (2 * float(K1[0, 0])))),
                    "y": math.degrees(2 * math.atan(size[1] / (2 * float(K1[1, 1])))),
                },
            },
            "camera_b": {
                "K": mat(K2), "D": vec(D2), "mono_rms_px": mono_result["camera_b"][0],
                "per_view_reprojection_rms_px": mono_result["camera_b"][3],
                "pinhole_fov_deg": {
                    "x": math.degrees(2 * math.atan(size[0] / (2 * float(K2[0, 0])))),
                    "y": math.degrees(2 * math.atan(size[1] / (2 * float(K2[1, 1])))),
                },
            },
        },
        "stereo": {
            "frame_convention": "R/T transform points from camera_a into camera_b",
            "R_camera_b_from_camera_a": mat(R),
            "T_camera_b_from_camera_a_m": vec(T),
            "baseline_m": baseline,
            "E": mat(E), "F": mat(F),
            "stereo_rms_px": stereo_rms,
            "valid_pair_count": len(stereo),
        },
        "rectification": {
            "R1": mat(R1), "R2": mat(R2), "P1": mat(P1), "P2": mat(P2), "Q": mat(Q),
            "valid_roi_camera_a": roi1, "valid_roi_camera_b": roi2,
            "vertical_epipolar_abs_px": dist(residuals),
        },
        "quality": {"gates": {}, "policy_source": a.policy_source, "status": "EVIDENCE_ONLY_NO_THRESHOLDS"},
        "guardrails": [
            "camera_a/camera_b naming preserved until #35 mapping evidence exists.",
            "Vendor nominal FOV/baseline are not solver inputs.",
            "Low global RMS alone is not promotion evidence.",
        ],
    }
    if a.max_mono_rms_px is not None:
        for cam in CAMS:
            observed = artifact["cameras"][cam]["mono_rms_px"]
            gates[f"{cam}_max_mono_rms_px"] = {"limit": a.max_mono_rms_px, "observed": observed, "pass": observed <= a.max_mono_rms_px}
    if a.max_stereo_rms_px is not None:
        gates["max_stereo_rms_px"] = {"limit": a.max_stereo_rms_px, "observed": stereo_rms, "pass": stereo_rms <= a.max_stereo_rms_px}
    if a.max_epipolar_p95_px is not None:
        observed = artifact["rectification"]["vertical_epipolar_abs_px"]["p95"] or 0.0
        gates["max_vertical_epipolar_p95_px"] = {"limit": a.max_epipolar_p95_px, "observed": observed, "pass": observed <= a.max_epipolar_p95_px}
    if gates:
        if not a.policy_source:
            raise Error("explicit calibration gates require --policy-source")
        artifact["quality"] = {
            "gates": gates,
            "policy_source": a.policy_source,
            "status": "PASS" if all(item["pass"] for item in gates.values()) else "FAIL",
        }
    errors = validate(artifact)
    if errors:
        raise Error("generated artifact invalid: " + "; ".join(errors))
    save(a.output, artifact)


def rectify_cmd(a):
    cv2, np = cv()
    artifact = load(a.calibration.resolve())
    errors = validate(artifact)
    if errors:
        raise Error("; ".join(errors))
    camera_a = cv2.imread(str(a.camera_a.resolve()))
    camera_b = cv2.imread(str(a.camera_b.resolve()))
    width, height = artifact["image"]["width"], artifact["image"]["height"]
    if camera_a is None or camera_b is None:
        raise Error("cannot decode rectification input image")
    if (camera_a.shape[1], camera_a.shape[0]) != (width, height) or (camera_b.shape[1], camera_b.shape[0]) != (width, height):
        raise Error("rectification input geometry mismatch")
    n = lambda x: np.asarray(x, np.float64)
    K1, D1 = n(artifact["cameras"]["camera_a"]["K"]), n(artifact["cameras"]["camera_a"]["D"])
    K2, D2 = n(artifact["cameras"]["camera_b"]["K"]), n(artifact["cameras"]["camera_b"]["D"])
    R1, R2 = n(artifact["rectification"]["R1"]), n(artifact["rectification"]["R2"])
    P1, P2 = n(artifact["rectification"]["P1"]), n(artifact["rectification"]["P2"])
    map1x, map1y = cv2.initUndistortRectifyMap(K1, D1, R1, P1, (width, height), cv2.CV_32FC1)
    map2x, map2y = cv2.initUndistortRectifyMap(K2, D2, R2, P2, (width, height), cv2.CV_32FC1)
    canvas = np.hstack([
        cv2.remap(camera_a, map1x, map1y, cv2.INTER_LINEAR),
        cv2.remap(camera_b, map2x, map2y, cv2.INTER_LINEAR),
    ])
    for y in range(max(20, a.line_spacing_px) // 2, height, max(20, a.line_spacing_px)):
        cv2.line(canvas, (0, y), (canvas.shape[1] - 1, y), (0, 255, 0), 1)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(a.output), canvas):
        raise Error(f"cannot write {a.output}")
