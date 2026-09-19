"""Evidence-grade rectification inspection for the #8 stereo workbench.

This module consumes an already-generated stereo calibration artifact. It does
not solve or promote calibration. Optional ChArUco observations add pair-specific
vertical epipolar residual evidence without introducing default thresholds.
"""
from __future__ import annotations

from pathlib import Path

from .stereo_calibration_common import Error, TARGET, board, cv, detect, dist, load, now, save, sha
from .stereo_calibration_solve import validate

SCHEMA = "bividi.calibration.stereo_rectification_inspection.v1"
TOOL_VERSION = "1"


def _binding(path: Path) -> dict:
    resolved = path.resolve()
    return {"path": str(resolved), "sha256": sha(resolved)}


def _verified_target(path: Path, artifact: dict) -> dict:
    target_path = path.resolve()
    target = load(target_path)
    if target.get("schema") != TARGET:
        raise Error(f"target must use {TARGET}")
    if target.get("family") != "charuco":
        raise Error("pair-specific rectification inspection currently supports ChArUco target evidence")

    calibration_target = artifact.get("target", {})
    if target.get("target_id") != calibration_target.get("target_id"):
        raise Error("target_id differs from calibration artifact")
    if target.get("family") != calibration_target.get("family"):
        raise Error("target family differs from calibration artifact")
    if sha(target_path) != calibration_target.get("sha256"):
        raise Error("target SHA-256 differs from calibration artifact")
    return target


def _gray(cv2, image):
    if len(image.shape) == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def _draw_label(cv2, image, text: str) -> None:
    cv2.putText(image, text, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, cv2.LINE_AA)


def _draw_points(cv2, image, points) -> None:
    for x, y in points:
        cv2.circle(image, (int(round(float(x))), int(round(float(y)))), 4, (0, 0, 255), -1, cv2.LINE_AA)


def _empty_distribution() -> dict:
    return {"count": 0, "min": None, "max": None, "mean": None, "median": None, "p95": None}


def inspect_rectification(args) -> dict:
    cv2, np = cv()
    calibration_path = args.calibration.resolve()
    artifact = load(calibration_path)
    errors = validate(artifact)
    if errors:
        raise Error("; ".join(errors))

    camera_a_path = args.camera_a.resolve()
    camera_b_path = args.camera_b.resolve()
    camera_a = cv2.imread(str(camera_a_path))
    camera_b = cv2.imread(str(camera_b_path))
    width, height = int(artifact["image"]["width"]), int(artifact["image"]["height"])
    if camera_a is None or camera_b is None:
        raise Error("cannot decode rectification input image")
    if (camera_a.shape[1], camera_a.shape[0]) != (width, height) or (camera_b.shape[1], camera_b.shape[0]) != (width, height):
        raise Error("rectification input geometry mismatch")

    n = lambda value: np.asarray(value, np.float64)
    K1 = n(artifact["cameras"]["camera_a"]["K"])
    D1 = n(artifact["cameras"]["camera_a"]["D"])
    K2 = n(artifact["cameras"]["camera_b"]["K"])
    D2 = n(artifact["cameras"]["camera_b"]["D"])
    R1 = n(artifact["rectification"]["R1"])
    R2 = n(artifact["rectification"]["R2"])
    P1 = n(artifact["rectification"]["P1"])
    P2 = n(artifact["rectification"]["P2"])

    map1x, map1y = cv2.initUndistortRectifyMap(K1, D1, R1, P1, (width, height), cv2.CV_32FC1)
    map2x, map2y = cv2.initUndistortRectifyMap(K2, D2, R2, P2, (width, height), cv2.CV_32FC1)
    rectified_a = cv2.remap(camera_a, map1x, map1y, cv2.INTER_LINEAR)
    rectified_b = cv2.remap(camera_b, map2x, map2y, cv2.INTER_LINEAR)

    original_a = camera_a.copy()
    original_b = camera_b.copy()
    rectified_a_overlay = rectified_a.copy()
    rectified_b_overlay = rectified_b.copy()

    target_entry = {
        "availability": "unavailable",
        "reason": "no explicit --target supplied",
    }
    pair_residuals = {
        "availability": "unavailable",
        "reason": "pair-specific target evidence was not supplied",
        "camera_a_detected_corner_count": 0,
        "camera_b_detected_corner_count": 0,
        "common_corner_count": 0,
        "signed_b_minus_a_px": _empty_distribution(),
        "absolute_px": _empty_distribution(),
        "correspondences": [],
    }

    target_path = getattr(args, "target", None)
    if isinstance(target_path, Path):
        target_path = target_path.resolve()
        target = _verified_target(target_path, artifact)
        target_entry = {
            "availability": "available",
            **_binding(target_path),
            "target_id": target.get("target_id"),
            "family": target.get("family"),
        }
        charuco = board(cv2, target)
        points_a, ids_a = detect(_gray(cv2, camera_a), charuco, cv2, np)
        points_b, ids_b = detect(_gray(cv2, camera_b), charuco, cv2, np)
        if len(set(ids_a)) != len(ids_a) or len(set(ids_b)) != len(ids_b):
            raise Error("target detector returned duplicate ChArUco corner IDs")

        map_a = {int(value): index for index, value in enumerate(ids_a)}
        map_b = {int(value): index for index, value in enumerate(ids_b)}
        common = sorted(set(map_a) & set(map_b))
        pair_residuals.update({
            "camera_a_detected_corner_count": len(ids_a),
            "camera_b_detected_corner_count": len(ids_b),
            "common_corner_count": len(common),
        })

        _draw_points(cv2, original_a, points_a)
        _draw_points(cv2, original_b, points_b)

        if common:
            source_a = np.asarray([points_a[map_a[key]] for key in common], np.float32).reshape(-1, 1, 2)
            source_b = np.asarray([points_b[map_b[key]] for key in common], np.float32).reshape(-1, 1, 2)
            rect_points_a = cv2.undistortPoints(source_a, K1, D1, R=R1, P=P1).reshape(-1, 2)
            rect_points_b = cv2.undistortPoints(source_b, K2, D2, R=R2, P=P2).reshape(-1, 2)
            signed = [float(pb[1]) - float(pa[1]) for pa, pb in zip(rect_points_a, rect_points_b)]
            absolute = [abs(value) for value in signed]
            correspondences = [
                {
                    "corner_id": int(key),
                    "camera_a_rectified_px": [float(pa[0]), float(pa[1])],
                    "camera_b_rectified_px": [float(pb[0]), float(pb[1])],
                    "vertical_residual_b_minus_a_px": float(value),
                }
                for key, pa, pb, value in zip(common, rect_points_a, rect_points_b, signed)
            ]
            pair_residuals.update({
                "availability": "available",
                "reason": None,
                "signed_b_minus_a_px": dist(signed),
                "absolute_px": dist(absolute),
                "correspondences": correspondences,
            })
            _draw_points(cv2, rectified_a_overlay, rect_points_a)
            _draw_points(cv2, rectified_b_overlay, rect_points_b)
        else:
            pair_residuals["reason"] = "no common detected ChArUco corners"

    rectified_canvas = np.hstack([rectified_a_overlay, rectified_b_overlay])
    spacing = max(20, int(args.line_spacing_px))
    for y in range(spacing // 2, height, spacing):
        cv2.line(rectified_canvas, (0, y), (rectified_canvas.shape[1] - 1, y), (0, 255, 0), 1)

    if pair_residuals["availability"] == "available":
        for item in pair_residuals["correspondences"]:
            ax, ay = item["camera_a_rectified_px"]
            bx, by = item["camera_b_rectified_px"]
            cv2.line(
                rectified_canvas,
                (int(round(ax)), int(round(ay))),
                (width + int(round(bx)), int(round(by))),
                (255, 0, 255),
                1,
                cv2.LINE_AA,
            )

    include_originals = bool(getattr(args, "include_originals", False))
    if include_originals:
        _draw_label(cv2, original_a, "original camera_a")
        _draw_label(cv2, original_b, "original camera_b")
        original_canvas = np.hstack([original_a, original_b])
        _draw_label(cv2, rectified_canvas, "rectified camera_a | camera_b")
        canvas = np.vstack([original_canvas, rectified_canvas])
        layout = "original_pair_over_rectified_pair"
    else:
        canvas = rectified_canvas
        layout = "rectified_pair"

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), canvas):
        raise Error(f"cannot write {output}")

    source_kind = artifact.get("provenance", {}).get("kind")
    evidence = {
        "schema": SCHEMA,
        "created_utc": now(),
        "provenance": {
            "tool": Path(__file__).name,
            "tool_version": TOOL_VERSION,
            "source_calibration_kind": source_kind,
        },
        "calibration": {
            **_binding(calibration_path),
            "calibration_id": artifact.get("calibration_id"),
        },
        "images": {
            "camera_a": _binding(camera_a_path),
            "camera_b": _binding(camera_b_path),
        },
        "target": target_entry,
        "inspection_image": {
            **_binding(output),
            "layout": layout,
            "width": int(canvas.shape[1]),
            "height": int(canvas.shape[0]),
        },
        "solver_rectification_vertical_epipolar_abs_px": artifact["rectification"]["vertical_epipolar_abs_px"],
        "pair_specific_rectified_vertical_residuals": pair_residuals,
        "quality": {
            "status": "EVIDENCE_ONLY_NO_THRESHOLDS",
            "gates": {},
            "policy_source": None,
        },
        "guardrails": [
            "Pair-specific residuals are inspection evidence, not a replacement for calibration-solve residuals.",
            "No default numerical acceptance thresholds are applied by the inspector.",
            "camera_a/camera_b naming is preserved; physical left/right identity is not inferred.",
            "Synthetic inspection evidence is not measured AR0234 calibration evidence.",
        ],
    }

    evidence_output = getattr(args, "evidence_output", None)
    if isinstance(evidence_output, Path):
        save(evidence_output.resolve(), evidence)
    return evidence
