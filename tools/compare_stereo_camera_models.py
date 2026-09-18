#!/usr/bin/env python3
"""Compare plausible stereo camera models on the same #8 session evidence.

This is a model-selection evidence laboratory, not an automatic model picker.
Without an explicit selected model and named policy source the result remains
INSUFFICIENT_EVIDENCE_NO_SELECTION_POLICY even when one model has lower fit RMS.
"""
from __future__ import annotations

import argparse
import json
import math
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from stereo_calibration_common import CAMS, Error, cv, dist, load, now, pctile, save, sha, verified_session
from stereo_calibration_solve import collect, solve_core

REPORT_SCHEMA = "bividi.calibration.stereo_model_comparison.v1"
TOOL_VERSION = "1"
MODELS = ("opencv5", "opencv-rational", "opencv-fisheye4")


class ModelComparisonError(ValueError):
    pass


def _as_obj(np, value):
    return np.asarray(value, np.float64).reshape(-1, 1, 3)


def _as_img(np, value):
    return np.asarray(value, np.float64).reshape(-1, 1, 2)


def _mat(value):
    return [[float(v) for v in row] for row in value.tolist()]


def _vec(value):
    return [float(v) for v in value.reshape(-1).tolist()]


def _remap_valid_fraction(np, map_x, map_y, size):
    width, height = size
    valid = (
        np.isfinite(map_x)
        & np.isfinite(map_y)
        & (map_x >= 0.0)
        & (map_y >= 0.0)
        & (map_x <= float(width - 1))
        & (map_y <= float(height - 1))
    )
    return float(np.mean(valid))


def _outer_quartile_distribution(samples):
    """Residuals for the raw-image points in the outermost radius quartile.

    This is a descriptive metric, not an acceptance threshold. The quartile is
    derived from the observed points themselves, so no seller FOV or arbitrary
    pixel radius is introduced by the tool.
    """
    if not samples:
        return dist([])
    ordered = sorted((float(radius), float(error)) for radius, error in samples)
    cutoff = pctile([item[0] for item in ordered], 0.75)
    return dist([error for radius, error in ordered if cutoff is not None and radius >= cutoff])


def _point_error_samples(np, observed, projected, size):
    raw = np.asarray(observed, np.float64).reshape(-1, 2)
    pred = np.asarray(projected, np.float64).reshape(-1, 2)
    errors = np.sqrt(np.sum((raw - pred) ** 2, axis=1))
    width, height = size
    cx, cy = (width - 1) * 0.5, (height - 1) * 0.5
    max_radius = max(math.hypot(cx, cy), 1.0)
    radii = np.sqrt((raw[:, 0] - cx) ** 2 + (raw[:, 1] - cy) ** 2) / max_radius
    return [(float(radius), float(error)) for radius, error in zip(radii, errors)]


def _pinhole_candidate(cv2, np, size, mono, stereo, model):
    flags = cv2.CALIB_RATIONAL_MODEL if model == "opencv-rational" else 0
    mono_result, stereo_result, rectification, epipolar = solve_core(
        cv2, np, size, mono, stereo, flags
    )
    stereo_rms, k1, d1, k2, d2, rotation, translation, _, _ = stereo_result
    r1, r2, p1, p2, _, _, _ = rectification

    edge_samples = {camera: [] for camera in CAMS}
    for camera, K, D in (("camera_a", k1, d1), ("camera_b", k2, d2)):
        # Re-estimate each target pose with fixed solved intrinsics so the
        # reported per-point edge evidence uses one common camera model.
        for obj, image in zip(mono[camera]["o"], mono[camera]["i"]):
            ok, rvec, tvec = cv2.solvePnP(
                np.asarray(obj, np.float64),
                np.asarray(image, np.float64),
                K,
                D,
                flags=cv2.SOLVEPNP_ITERATIVE,
            )
            if not ok:
                raise ModelComparisonError(f"{model}/{camera}: solvePnP failed")
            projected, _ = cv2.projectPoints(obj, rvec, tvec, K, D)
            edge_samples[camera].extend(_point_error_samples(np, image, projected, size))

    maps = []
    for K, D, R, P in ((k1, d1, r1, p1), (k2, d2, r2, p2)):
        map_x, map_y = cv2.initUndistortRectifyMap(
            K, D, R, P, size, cv2.CV_32FC1
        )
        maps.append(_remap_valid_fraction(np, map_x, map_y, size))

    return {
        "model": model,
        "projection": "pinhole",
        "distortion_parameter_count": int(d1.size),
        "cameras": {
            "camera_a": {
                "K": _mat(k1),
                "D": _vec(d1),
                "mono_rms_px": float(mono_result["camera_a"][0]),
                "per_view_reprojection_rms_px": [float(x) for x in mono_result["camera_a"][3]],
                "outer_image_quartile_reprojection_px": _outer_quartile_distribution(edge_samples["camera_a"]),
                "valid_rectification_map_fraction": maps[0],
            },
            "camera_b": {
                "K": _mat(k2),
                "D": _vec(d2),
                "mono_rms_px": float(mono_result["camera_b"][0]),
                "per_view_reprojection_rms_px": [float(x) for x in mono_result["camera_b"][3]],
                "outer_image_quartile_reprojection_px": _outer_quartile_distribution(edge_samples["camera_b"]),
                "valid_rectification_map_fraction": maps[1],
            },
        },
        "stereo": {
            "rms_px": float(stereo_rms),
            "R_camera_b_from_camera_a": _mat(rotation),
            "T_camera_b_from_camera_a_m": _vec(translation),
            "baseline_m": float(np.linalg.norm(translation)),
            "valid_pair_count": len(stereo),
        },
        "rectification": {
            "vertical_epipolar_abs_px": dist(epipolar),
            "valid_map_fraction_camera_a": maps[0],
            "valid_map_fraction_camera_b": maps[1],
        },
    }


def _fisheye_calibrate_camera(cv2, np, size, objects, images, label):
    object_points = [_as_obj(np, obj) for obj in objects]
    image_points = [_as_img(np, image) for image in images]
    K = np.eye(3, dtype=np.float64)
    K[0, 0] = K[1, 1] = max(size)
    K[0, 2] = (size[0] - 1) * 0.5
    K[1, 2] = (size[1] - 1) * 0.5
    D = np.zeros((4, 1), dtype=np.float64)
    flags = cv2.fisheye.CALIB_RECOMPUTE_EXTRINSIC | cv2.fisheye.CALIB_FIX_SKEW
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_COUNT, 100, 1e-7)
    try:
        rms, K, D, rvecs, tvecs = cv2.fisheye.calibrate(
            object_points,
            image_points,
            size,
            K,
            D,
            flags=flags,
            criteria=criteria,
        )
    except cv2.error as exc:
        raise ModelComparisonError(f"opencv-fisheye4/{label}: calibration failed: {exc}") from exc
    per_view = []
    samples = []
    for obj, image, rvec, tvec in zip(object_points, image_points, rvecs, tvecs):
        projected, _ = cv2.fisheye.projectPoints(obj, rvec, tvec, K, D)
        errors = np.asarray(image).reshape(-1, 2) - projected.reshape(-1, 2)
        per_view.append(float(np.sqrt(np.mean(np.sum(errors * errors, axis=1)))))
        samples.extend(_point_error_samples(np, image, projected, size))
    return float(rms), K, D, rvecs, tvecs, per_view, samples


def _fisheye_candidate(cv2, np, size, mono, stereo):
    if min(len(mono[camera]["o"]) for camera in CAMS) < 3:
        raise ModelComparisonError("opencv-fisheye4: need >=3 mono views")
    if len(stereo) < 3:
        raise ModelComparisonError("opencv-fisheye4: need >=3 stereo views")

    mono_result = {}
    for camera in CAMS:
        mono_result[camera] = _fisheye_calibrate_camera(
            cv2, np, size, mono[camera]["o"], mono[camera]["i"], camera
        )

    object_points = [_as_obj(np, item[0]) for item in stereo]
    points_a = [_as_img(np, item[1]) for item in stereo]
    points_b = [_as_img(np, item[2]) for item in stereo]
    k1, d1 = mono_result["camera_a"][1], mono_result["camera_a"][2]
    k2, d2 = mono_result["camera_b"][1], mono_result["camera_b"][2]
    flags = cv2.fisheye.CALIB_FIX_INTRINSIC
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_COUNT, 100, 1e-7)
    try:
        stereo_result = cv2.fisheye.stereoCalibrate(
            object_points,
            points_a,
            points_b,
            k1,
            d1,
            k2,
            d2,
            size,
            flags=flags,
            criteria=criteria,
        )
    except cv2.error as exc:
        raise ModelComparisonError(f"opencv-fisheye4: stereo calibration failed: {exc}") from exc

    stereo_rms, k1, d1, k2, d2, rotation, translation = stereo_result
    try:
        r1, r2, p1, p2, _ = cv2.fisheye.stereoRectify(
            k1,
            d1,
            k2,
            d2,
            size,
            rotation,
            translation,
            flags=cv2.CALIB_ZERO_DISPARITY,
            newImageSize=size,
            balance=0.0,
            fov_scale=1.0,
        )
    except cv2.error as exc:
        raise ModelComparisonError(f"opencv-fisheye4: stereoRectify failed: {exc}") from exc

    epipolar = []
    for _, camera_a, camera_b in stereo:
        aa = cv2.fisheye.undistortPoints(
            _as_img(np, camera_a), k1, d1, R=r1, P=p1[:, :3]
        ).reshape(-1, 2)
        bb = cv2.fisheye.undistortPoints(
            _as_img(np, camera_b), k2, d2, R=r2, P=p2[:, :3]
        ).reshape(-1, 2)
        epipolar.extend(abs(float(y_a) - float(y_b)) for y_a, y_b in zip(aa[:, 1], bb[:, 1]))

    maps = []
    for K, D, R, P in ((k1, d1, r1, p1), (k2, d2, r2, p2)):
        map_x, map_y = cv2.fisheye.initUndistortRectifyMap(
            K, D, R, P[:, :3], size, cv2.CV_32FC1
        )
        maps.append(_remap_valid_fraction(np, map_x, map_y, size))

    return {
        "model": "opencv-fisheye4",
        "projection": "fisheye",
        "distortion_parameter_count": 4,
        "cameras": {
            "camera_a": {
                "K": _mat(k1),
                "D": _vec(d1),
                "mono_rms_px": mono_result["camera_a"][0],
                "per_view_reprojection_rms_px": [float(x) for x in mono_result["camera_a"][5]],
                "outer_image_quartile_reprojection_px": _outer_quartile_distribution(mono_result["camera_a"][6]),
                "valid_rectification_map_fraction": maps[0],
            },
            "camera_b": {
                "K": _mat(k2),
                "D": _vec(d2),
                "mono_rms_px": mono_result["camera_b"][0],
                "per_view_reprojection_rms_px": [float(x) for x in mono_result["camera_b"][5]],
                "outer_image_quartile_reprojection_px": _outer_quartile_distribution(mono_result["camera_b"][6]),
                "valid_rectification_map_fraction": maps[1],
            },
        },
        "stereo": {
            "rms_px": float(stereo_rms),
            "R_camera_b_from_camera_a": _mat(rotation),
            "T_camera_b_from_camera_a_m": _vec(translation),
            "baseline_m": float(np.linalg.norm(translation)),
            "valid_pair_count": len(stereo),
        },
        "rectification": {
            "vertical_epipolar_abs_px": dist(epipolar),
            "valid_map_fraction_camera_a": maps[0],
            "valid_map_fraction_camera_b": maps[1],
        },
    }


def solve_candidate(cv2, np, size, mono, stereo, model):
    if model == "opencv5":
        return _pinhole_candidate(cv2, np, size, mono, stereo, model)
    if model == "opencv-rational":
        return _pinhole_candidate(cv2, np, size, mono, stereo, model)
    if model == "opencv-fisheye4":
        return _fisheye_candidate(cv2, np, size, mono, stereo)
    raise ModelComparisonError(f"unsupported camera model: {model}")


def build_report(
    *,
    session_path: Path,
    session: Mapping[str, Any],
    target_path: Path,
    target: Mapping[str, Any],
    opencv_version: str,
    candidates: Sequence[Mapping[str, Any]],
    selected_model: str | None,
    policy_source: str | None,
):
    models = [str(candidate["model"]) for candidate in candidates]
    if len(models) < 2:
        raise ModelComparisonError("at least two camera models are required for comparison")
    if len(set(models)) != len(models):
        raise ModelComparisonError("duplicate camera models in comparison")
    if selected_model is not None and selected_model not in models:
        raise ModelComparisonError("--select-model must name one compared candidate")
    if selected_model is not None and not policy_source:
        raise ModelComparisonError("explicit model selection requires --policy-source")
    if policy_source and selected_model is None:
        raise ModelComparisonError("--policy-source requires --select-model for this v1 selection contract")

    selection = {
        "status": "INSUFFICIENT_EVIDENCE_NO_SELECTION_POLICY",
        "selected_model": None,
        "policy_source": None,
        "automatic_ranking": False,
    }
    if selected_model is not None:
        selection = {
            "status": "SELECTED_BY_EXPLICIT_POLICY",
            "selected_model": selected_model,
            "policy_source": policy_source,
            "automatic_ranking": False,
        }

    return {
        "schema": REPORT_SCHEMA,
        "created_utc": now(),
        "provenance": {
            "tool": Path(__file__).name,
            "tool_version": TOOL_VERSION,
            "opencv_version": opencv_version,
        },
        "session": {
            "path": str(session_path.resolve()),
            "sha256": sha(session_path.resolve()),
            "session_id": session.get("session_id"),
            "provenance_kind": session.get("provenance", {}).get("kind"),
        },
        "target": {
            "path": str(target_path.resolve()),
            "sha256": sha(target_path.resolve()),
            "target_id": target.get("target_id"),
            "family": target.get("family"),
        },
        "device": session.get("device"),
        "capture": session.get("capture"),
        "metric_contract": {
            "outer_image_quartile_reprojection_px": "raw detected points whose image-center radius is in the dataset's outermost quartile; descriptive evidence only",
            "valid_rectification_map_fraction": "fraction of output pixels whose rectification remap coordinates fall inside the source image",
            "vertical_epipolar_abs_px": "absolute rectified y-coordinate difference for common stereo target corners",
        },
        "candidates": list(candidates),
        "selection": selection,
        "guardrails": [
            "All candidates are solved from the same hash-bound session and target evidence.",
            "Lowest training/global RMS is not an automatic selection rule.",
            "Seller nominal FOV is not a camera-model selection input.",
            "Synthetic comparison success is software evidence, not measured AR0234 optics evidence.",
            "Repeatability and held-out evidence remain separate from single-session fit quality.",
        ],
    }


def compare_session(args):
    session_path = args.session.resolve()
    session, target_path, target, pairs = verified_session(session_path)
    if target.get("family") != "charuco":
        raise ModelComparisonError("native camera-model comparison currently requires a ChArUco session")
    cv2, np = cv()
    size = (int(session["capture"]["width"]), int(session["capture"]["height"]))
    mono, stereo = collect(session, session_path, target, pairs, cv2, np)
    models = list(args.models or MODELS)
    if len(models) < 2:
        raise ModelComparisonError("compare at least two --models")
    if len(set(models)) != len(models):
        raise ModelComparisonError("duplicate --models are not allowed")
    candidates = [solve_candidate(cv2, np, size, mono, stereo, model) for model in models]
    return build_report(
        session_path=session_path,
        session=session,
        target_path=target_path,
        target=target,
        opencv_version=cv2.__version__,
        candidates=candidates,
        selected_model=args.select_model,
        policy_source=args.policy_source,
    )


def render_markdown(report):
    lines = [
        "# Stereo camera-model comparison",
        "",
        f"- Session: `{report['session'].get('session_id')}`",
        f"- Session SHA-256: `{report['session']['sha256']}`",
        f"- Target: `{report['target'].get('target_id')}`",
        f"- Selection status: **{report['selection']['status']}**",
    ]
    if report["selection"].get("selected_model"):
        lines.append(f"- Selected model: `{report['selection']['selected_model']}`")
        lines.append(f"- Policy source: `{report['selection']['policy_source']}`")
    lines += ["", "| Model | Projection | Mono RMS A/B (px) | Stereo RMS (px) | Outer-quartile p95 A/B (px) | Epipolar p95 (px) | Valid map A/B |", "|---|---|---:|---:|---:|---:|---:|"]
    for candidate in report["candidates"]:
        a = candidate["cameras"]["camera_a"]
        b = candidate["cameras"]["camera_b"]
        epi = candidate["rectification"]["vertical_epipolar_abs_px"].get("p95")
        edge_a = a["outer_image_quartile_reprojection_px"].get("p95")
        edge_b = b["outer_image_quartile_reprojection_px"].get("p95")
        lines.append(
            f"| `{candidate['model']}` | {candidate['projection']} | {a['mono_rms_px']:.4g} / {b['mono_rms_px']:.4g} | {candidate['stereo']['rms_px']:.4g} | {edge_a:.4g} / {edge_b:.4g} | {epi:.4g} | {a['valid_rectification_map_fraction']:.4f} / {b['valid_rectification_map_fraction']:.4f} |"
        )
    lines += [
        "",
        "## Interpretation boundary",
        "",
        "No row is automatically preferred by minimum RMS. Edge behavior, rectified epipolar residual, usable map area, and later cross-session/held-out evidence must be reviewed under a named policy before model promotion.",
        "",
    ]
    return "\n".join(lines)


def _fake_candidate(model, rms):
    d = {
        "count": 8,
        "min": rms * 0.5,
        "max": rms * 1.5,
        "mean": rms,
        "median": rms,
        "p95": rms * 1.4,
    }
    camera = {
        "K": [[700.0, 0.0, 640.0], [0.0, 700.0, 360.0], [0.0, 0.0, 1.0]],
        "D": [0.0, 0.0, 0.0, 0.0],
        "mono_rms_px": rms,
        "per_view_reprojection_rms_px": [rms] * 3,
        "outer_image_quartile_reprojection_px": d,
        "valid_rectification_map_fraction": 0.95,
    }
    return {
        "model": model,
        "projection": "fisheye" if model == "opencv-fisheye4" else "pinhole",
        "distortion_parameter_count": 4 if model == "opencv-fisheye4" else 5,
        "cameras": {"camera_a": dict(camera), "camera_b": dict(camera)},
        "stereo": {
            "rms_px": rms,
            "R_camera_b_from_camera_a": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            "T_camera_b_from_camera_a_m": [-0.08, 0.0, 0.0],
            "baseline_m": 0.08,
            "valid_pair_count": 3,
        },
        "rectification": {
            "vertical_epipolar_abs_px": d,
            "valid_map_fraction_camera_a": 0.95,
            "valid_map_fraction_camera_b": 0.95,
        },
    }


def self_test():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        session_path = root / "session.json"
        target_path = root / "target.json"
        session = {
            "session_id": "synthetic-model-comparison",
            "provenance": {"kind": "synthetic"},
            "device": {"model": "synthetic", "serial": "SYN"},
            "capture": {"mode_index": 0, "width": 1280, "height": 720},
        }
        target = {"target_id": "target", "family": "charuco"}
        session_path.write_text(json.dumps(session), encoding="utf-8")
        target_path.write_text(json.dumps(target), encoding="utf-8")
        candidates = [_fake_candidate("opencv5", 0.2), _fake_candidate("opencv-rational", 0.15)]
        report = build_report(
            session_path=session_path,
            session=session,
            target_path=target_path,
            target=target,
            opencv_version="synthetic",
            candidates=candidates,
            selected_model=None,
            policy_source=None,
        )
        assert report["selection"]["status"] == "INSUFFICIENT_EVIDENCE_NO_SELECTION_POLICY"
        # Lower RMS must not silently select the rational model.
        assert report["selection"]["selected_model"] is None
        selected = build_report(
            session_path=session_path,
            session=session,
            target_path=target_path,
            target=target,
            opencv_version="synthetic",
            candidates=candidates,
            selected_model="opencv5",
            policy_source="synthetic-explicit-policy",
        )
        assert selected["selection"]["selected_model"] == "opencv5"
        assert "opencv5" in render_markdown(selected)
        rejected = False
        try:
            build_report(
                session_path=session_path,
                session=session,
                target_path=target_path,
                target=target,
                opencv_version="synthetic",
                candidates=candidates,
                selected_model="opencv5",
                policy_source=None,
            )
        except ModelComparisonError:
            rejected = True
        assert rejected
    print("Stereo camera-model comparison contract self-test: PASS")


def _synthetic_views(cv2, np, fisheye=False):
    size = (1280, 720)
    K = np.asarray([[650.0, 0.0, 640.0], [0.0, 648.0, 360.0], [0.0, 0.0, 1.0]], np.float64)
    D = np.asarray([-0.025, 0.004, -0.0005, 0.00005], np.float64).reshape(4, 1) if fisheye else np.zeros((5, 1), np.float64)
    baseline = 0.08
    obj = np.asarray([[x * 0.035, y * 0.035, 0.0] for y in range(6) for x in range(8)], np.float64)
    mono = {camera: {"o": [], "i": []} for camera in CAMS}
    stereo = []
    for index in range(14):
        rvec = np.asarray([[0.12 * math.sin(index * 0.41)], [0.16 * math.cos(index * 0.37)], [0.05 * math.sin(index * 0.23)]], np.float64)
        tvec = np.asarray([[-0.16 + 0.025 * (index % 7)], [-0.10 + 0.04 * (index % 5)], [0.58 + 0.055 * (index % 4)]], np.float64)
        rotation, _ = cv2.Rodrigues(rvec)
        camera_b_t = tvec + np.asarray([[-baseline], [0.0], [0.0]], np.float64)
        camera_b_r, _ = cv2.Rodrigues(rotation)
        if fisheye:
            pa, _ = cv2.fisheye.projectPoints(_as_obj(np, obj), rvec, tvec, K, D)
            pb, _ = cv2.fisheye.projectPoints(_as_obj(np, obj), camera_b_r, camera_b_t, K, D)
        else:
            pa, _ = cv2.projectPoints(obj, rvec, tvec, K, D)
            pb, _ = cv2.projectPoints(obj, camera_b_r, camera_b_t, K, D)
        pa = np.asarray(pa, np.float32).reshape(-1, 1, 2)
        pb = np.asarray(pb, np.float32).reshape(-1, 1, 2)
        obj32 = np.asarray(obj, np.float32)
        mono["camera_a"]["o"].append(obj32.copy())
        mono["camera_a"]["i"].append(pa.copy())
        mono["camera_b"]["o"].append(obj32.copy())
        mono["camera_b"]["i"].append(pb.copy())
        stereo.append((obj32.copy(), pa.copy(), pb.copy()))
    return size, baseline, mono, stereo


def self_test_opencv():
    cv2, np = cv()
    size, baseline, mono, stereo = _synthetic_views(cv2, np, fisheye=False)
    for model in ("opencv5", "opencv-rational"):
        result = solve_candidate(cv2, np, size, mono, stereo, model)
        assert abs(result["stereo"]["baseline_m"] - baseline) < 5e-3, (model, result["stereo"]["baseline_m"])
        assert result["rectification"]["vertical_epipolar_abs_px"]["p95"] < 0.2
        assert 0.0 < result["rectification"]["valid_map_fraction_camera_a"] <= 1.0

    fisheye_size, fisheye_baseline, fisheye_mono, fisheye_stereo = _synthetic_views(cv2, np, fisheye=True)
    result = solve_candidate(cv2, np, fisheye_size, fisheye_mono, fisheye_stereo, "opencv-fisheye4")
    assert abs(result["stereo"]["baseline_m"] - fisheye_baseline) < 1e-2, result["stereo"]["baseline_m"]
    assert result["rectification"]["vertical_epipolar_abs_px"]["p95"] < 0.5
    assert len(result["cameras"]["camera_a"]["D"]) == 4
    print("Stereo camera-model OpenCV path self-test: PASS")


def parser():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--self-test-opencv", action="store_true")
    ap.add_argument("session", nargs="?", type=Path)
    ap.add_argument("--output", type=Path)
    ap.add_argument("--markdown", type=Path)
    ap.add_argument("--models", nargs="+", choices=MODELS, default=list(MODELS))
    ap.add_argument("--select-model", choices=MODELS)
    ap.add_argument("--policy-source")
    return ap


def main(argv=None):
    args = parser().parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if args.self_test_opencv:
        self_test_opencv()
        return 0
    if args.session is None:
        raise ModelComparisonError("session is required")
    report = compare_session(args)
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (Error, ModelComparisonError) as exc:
        print(f"error: {exc}", file=__import__("sys").stderr)
        raise SystemExit(2)
