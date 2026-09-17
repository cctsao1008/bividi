#!/usr/bin/env python3
"""Export exact ETH Kalibr AprilGrid detections from a prepared Bividi session.

This adapter must run inside the pinned Kalibr environment. It deliberately reuses
Kalibr's GridDetector + GridCalibrationTargetObservation APIs instead of running an
independent OpenCV/AprilTag detector whose corner semantics could differ.

Normal Bividi CI exercises only dependency-free contract helpers via --self-test;
real extraction requires the external Kalibr runtime and Python OpenCV.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence

SESSION_SCHEMA = "bividi.calibration.kalibr_dynamic_session.v1"
OUTPUT_SCHEMA = "bividi.calibration.kalibr_target_observations.v1"
PINNED_KALIBR_REVISION = "1f60227442d25e36365ef5f72cd80b9666d73467"
TOOL_VERSION = "1"
CAMERAS = (("camera_a", 0), ("camera_b", 1))


class ExportError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExportError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ExportError(f"{path}: expected JSON object")
    return value


def resolve_session_path(session_path: Path, text: str) -> Path:
    path = Path(text)
    return path if path.is_absolute() else (session_path.parent / path).resolve()


def staged_file(session: dict[str, Any], session_path: Path, key: str) -> Path:
    staged = session.get("staged")
    if not isinstance(staged, dict) or not isinstance(staged.get(key), str):
        raise ExportError(f"{session_path}: staged.{key} is required")
    path = resolve_session_path(session_path, staged[key])
    if not path.is_file():
        raise ExportError(f"{session_path}: missing staged file {path}")
    return path


def read_camera_index(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"timestamp_ns", "image_path", "frame_index", "frame_sequence"}
        if reader.fieldnames is None or required - set(reader.fieldnames):
            raise ExportError(f"{path}: missing required columns {sorted(required)}")
        previous = None
        for line, row in enumerate(reader, start=2):
            try:
                timestamp_ns = int(row["timestamp_ns"], 10)
                frame_index = int(row["frame_index"], 10)
                frame_sequence = int(row["frame_sequence"], 10)
            except ValueError as exc:
                raise ExportError(f"{path}:{line}: invalid integer field") from exc
            if previous is not None and timestamp_ns <= previous:
                raise ExportError(f"{path}:{line}: non-increasing timestamp")
            previous = timestamp_ns
            image = Path(row["image_path"])
            if not image.is_absolute():
                image = (path.parent / image).resolve()
            if not image.is_file():
                raise ExportError(f"{path}:{line}: missing image {image}")
            rows.append({
                "timestamp_ns": timestamp_ns,
                "image_path": image,
                "frame_index": frame_index,
                "frame_sequence": frame_sequence,
            })
    if not rows:
        raise ExportError(f"{path}: no camera frames")
    return rows


def require_stereo_identity(a: Sequence[dict[str, Any]], b: Sequence[dict[str, Any]]) -> None:
    if len(a) != len(b):
        raise ExportError(f"staged stereo frame count differs: camera_a={len(a)} camera_b={len(b)}")
    for idx, (left, right) in enumerate(zip(a, b)):
        key_a = (left["timestamp_ns"], left["frame_index"], left["frame_sequence"])
        key_b = (right["timestamp_ns"], right["frame_index"], right["frame_sequence"])
        if key_a != key_b:
            raise ExportError(f"staged stereo identity mismatch at row {idx}: {key_a} != {key_b}")


def bbox_summary(points: Sequence[Sequence[float]]) -> dict[str, float | int | None]:
    if not points:
        return {"corner_count": 0, "min_x_px": None, "max_x_px": None, "min_y_px": None, "max_y_px": None,
                "centroid_x_px": None, "centroid_y_px": None}
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    if not all(math.isfinite(v) for v in xs + ys):
        raise ExportError("non-finite corner coordinate returned by Kalibr")
    return {
        "corner_count": len(points),
        "min_x_px": min(xs), "max_x_px": max(xs),
        "min_y_px": min(ys), "max_y_px": max(ys),
        "centroid_x_px": sum(xs) / len(xs),
        "centroid_y_px": sum(ys) / len(ys),
    }


def load_kalibr_runtime():
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
        import aslam_cv as acv  # type: ignore
        import aslam_cameras_april as acv_april  # type: ignore
        import kalibr_common as kc  # type: ignore
    except ImportError as exc:
        raise ExportError(
            "Kalibr runtime unavailable. Run this adapter inside the pinned ETH Kalibr environment "
            "with kalibr_common, aslam_cv, aslam_cameras_april, numpy, and cv2 installed."
        ) from exc
    return cv2, np, acv, acv_april, kc


def build_detector(kc, acv, acv_april, camchain_path: Path, target_path: Path, camera_index: int):
    chain = kc.ConfigReader.CameraChainParameters(str(camchain_path))
    camera_config = chain.getCameraParameters(camera_index)
    camera = kc.ConfigReader.AslamCamera.fromParameters(camera_config)
    target_config = kc.ConfigReader.CalibrationTargetParameters(str(target_path))
    if target_config.getTargetType() != "aprilgrid":
        raise ExportError("target coverage adapter currently requires target_type: aprilgrid")
    params = target_config.getTargetParams()
    options = acv_april.AprilgridOptions()
    options.showExtractionVideo = False
    options.minTagsForValidObs = int(max(params["tagRows"], params["tagCols"]) + 1)
    grid = acv_april.GridCalibrationTargetAprilgrid(
        params["tagRows"], params["tagCols"], params["tagSize"], params["tagSpacing"], options
    )
    detector_options = acv.GridDetectorOptions()
    detector_options.imageStepping = False
    detector_options.plotCornerReprojection = False
    detector_options.filterCornerOutliers = True
    detector = acv.GridDetector(camera.geometry, grid, detector_options)
    return detector, int(grid.size()), {
        "tag_rows": int(params["tagRows"]),
        "tag_cols": int(params["tagCols"]),
        "tag_size_m": float(params["tagSize"]),
        "tag_spacing_ratio": float(params["tagSpacing"]),
        "min_tags_for_valid_observation": int(options.minTagsForValidObs),
        "filter_corner_outliers": True,
    }


def extract_camera(camera_name: str, rows: Sequence[dict[str, Any]], detector, cv2, np,
                   detections_writer, corners_writer) -> tuple[dict[str, Any], int]:
    success_count = 0
    total_corners = 0
    image_shape = None
    target_corner_count = None
    for row in rows:
        image = cv2.imread(str(row["image_path"]), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise ExportError(f"cannot decode image {row['image_path']}")
        height, width = int(image.shape[0]), int(image.shape[1])
        if image_shape is None:
            image_shape = (width, height)
        elif image_shape != (width, height):
            raise ExportError(f"{camera_name}: image dimensions changed {image_shape} -> {(width, height)}")
        success, observation = detector.findTarget(np.array(image))
        points: list[list[float]] = []
        corner_ids: list[int] = []
        if bool(success):
            point_array = np.asarray(observation.getCornersImageFrame())
            id_array = np.asarray(observation.getCornersIdx()).reshape(-1)
            if point_array.ndim != 2 or point_array.shape[1] != 2 or len(point_array) != len(id_array):
                raise ExportError(f"{camera_name}: Kalibr observation corner shape mismatch")
            points = [[float(p[0]), float(p[1])] for p in point_array]
            corner_ids = [int(v) for v in id_array]
            if len(set(corner_ids)) != len(corner_ids):
                raise ExportError(f"{camera_name}: duplicate corner ids in one Kalibr observation")
            success_count += 1
            total_corners += len(points)
        summary = bbox_summary(points)
        detections_writer.writerow([
            camera_name, row["timestamp_ns"], row["frame_index"], row["frame_sequence"],
            width, height, "true" if bool(success) else "false", summary["corner_count"],
            summary["min_x_px"], summary["max_x_px"], summary["min_y_px"], summary["max_y_px"],
            summary["centroid_x_px"], summary["centroid_y_px"],
        ])
        for corner_id, point in zip(corner_ids, points):
            corners_writer.writerow([
                camera_name, row["timestamp_ns"], row["frame_index"], row["frame_sequence"],
                width, height, corner_id, f"{point[0]:.17g}", f"{point[1]:.17g}",
            ])
    return {
        "frames": len(rows),
        "successful_frames": success_count,
        "failed_frames": len(rows) - success_count,
        "total_observed_corners": total_corners,
        "image_width": image_shape[0] if image_shape else None,
        "image_height": image_shape[1] if image_shape else None,
    }, int(target_corner_count or 0)


def export(args: argparse.Namespace) -> dict[str, Any]:
    session_path = args.session_json.resolve()
    session = load_json(session_path)
    if session.get("schema") != SESSION_SCHEMA:
        raise ExportError(f"{session_path}: expected schema {SESSION_SCHEMA!r}")
    kalibr = session.get("kalibr")
    revision = kalibr.get("revision") if isinstance(kalibr, dict) else None
    if revision != PINNED_KALIBR_REVISION and not args.allow_unreviewed_kalibr_revision:
        raise ExportError(
            f"session Kalibr revision {revision!r} is not reviewed pin {PINNED_KALIBR_REVISION}; "
            "pass --allow-unreviewed-kalibr-revision only after reviewing detector/API changes"
        )

    camera_a_path = staged_file(session, session_path, "camera_a_csv")
    camera_b_path = staged_file(session, session_path, "camera_b_csv")
    camchain_path = staged_file(session, session_path, "camchain_yaml")
    target_path = staged_file(session, session_path, "target_yaml")
    indexes = {
        "camera_a": read_camera_index(camera_a_path),
        "camera_b": read_camera_index(camera_b_path),
    }
    require_stereo_identity(indexes["camera_a"], indexes["camera_b"])

    prefix = args.output_prefix.resolve()
    prefix.parent.mkdir(parents=True, exist_ok=True)
    detections_path = Path(str(prefix) + ".target-detections.csv")
    corners_path = Path(str(prefix) + ".target-corners.csv")
    manifest_path = Path(str(prefix) + ".target-observations.json")

    cv2, np, acv, acv_april, kc = load_kalibr_runtime()
    camera_stats: dict[str, Any] = {}
    target_counts: list[int] = []
    detector_contract: dict[str, Any] | None = None
    with detections_path.open("w", encoding="utf-8", newline="") as det_stream, corners_path.open("w", encoding="utf-8", newline="") as cor_stream:
        detections_writer = csv.writer(det_stream)
        detections_writer.writerow([
            "camera", "timestamp_ns", "frame_index", "frame_sequence", "image_width", "image_height",
            "success", "corner_count", "min_x_px", "max_x_px", "min_y_px", "max_y_px",
            "centroid_x_px", "centroid_y_px",
        ])
        corners_writer = csv.writer(cor_stream)
        corners_writer.writerow([
            "camera", "timestamp_ns", "frame_index", "frame_sequence", "image_width", "image_height",
            "corner_id", "x_px", "y_px",
        ])
        for camera_name, camera_index in CAMERAS:
            detector, target_count, contract = build_detector(kc, acv, acv_april, camchain_path, target_path, camera_index)
            stats, _ = extract_camera(
                camera_name, indexes[camera_name], detector, cv2, np, detections_writer, corners_writer
            )
            camera_stats[camera_name] = stats
            target_counts.append(target_count)
            detector_contract = contract if detector_contract is None else detector_contract
    if len(set(target_counts)) != 1:
        raise ExportError(f"Kalibr target size differs across cameras: {target_counts}")

    manifest = {
        "schema": OUTPUT_SCHEMA,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "session": {"path": str(session_path), "sha256": sha256_file(session_path)},
        "kalibr": {
            "backend": "ethz-asl/kalibr",
            "revision": revision,
            "reviewed_revision": revision == PINNED_KALIBR_REVISION,
            "source_contract": {
                "extraction": "kalibr_common.TargetExtractor.extractCornersFromDataset -> GridDetector.findTarget",
                "corner_coordinates": "GridCalibrationTargetObservation.getCornersImageFrame",
                "corner_ids": "GridCalibrationTargetObservation.getCornersIdx",
                "camera_setup": "IccSensors.IccCamera.setupCalibrationTarget",
            },
        },
        "target": {**(detector_contract or {}), "corner_count": target_counts[0]},
        "sources": {
            "camera_a_index": {"path": str(camera_a_path), "sha256": sha256_file(camera_a_path)},
            "camera_b_index": {"path": str(camera_b_path), "sha256": sha256_file(camera_b_path)},
            "camchain_yaml": {"path": str(camchain_path), "sha256": sha256_file(camchain_path)},
            "target_yaml": {"path": str(target_path), "sha256": sha256_file(target_path)},
        },
        "artifacts": {
            "detections_csv": {"path": str(detections_path), "sha256": sha256_file(detections_path)},
            "corners_csv": {"path": str(corners_path), "sha256": sha256_file(corners_path)},
        },
        "camera_statistics": camera_stats,
        "stereo_identity": "camera_a and camera_b staged timestamp/frame identities matched exactly before extraction",
        "provenance": {"tool": Path(__file__).name, "tool_version": TOOL_VERSION},
        "status": "KALIBR_DETECTIONS_EXPORTED",
        "guardrails": [
            "These are exact observations returned by the pinned Kalibr detector path, not an independent detector.",
            "Detection success and image-plane coverage are evidence, not calibration accuracy or formal observability proof.",
            "camera_a/camera_b remain topology names and are not assumed physical left/right.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name in ("a0.png", "a1.png", "b0.png", "b1.png"):
            (root / name).write_bytes(b"synthetic")
        for camera in ("camera_a", "camera_b"):
            path = root / f"{camera}.csv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["timestamp_ns", "image_path", "frame_index", "frame_sequence"])
                prefix = "a" if camera == "camera_a" else "b"
                writer.writerow([1000, f"{prefix}0.png", 0, 10])
                writer.writerow([2000, f"{prefix}1.png", 1, 11])
        a = read_camera_index(root / "camera_a.csv")
        b = read_camera_index(root / "camera_b.csv")
        require_stereo_identity(a, b)
        summary = bbox_summary([[10.0, 20.0], [30.0, 40.0]])
        assert summary["corner_count"] == 2
        assert summary["centroid_x_px"] == 20.0
        b[1]["frame_sequence"] = 12
        try:
            require_stereo_identity(a, b)
        except ExportError:
            pass
        else:
            raise AssertionError("stereo identity mismatch was not rejected")
    print("Kalibr target-observation adapter contract self-test: PASS")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_json", nargs="?", type=Path)
    parser.add_argument("--output-prefix", type=Path)
    parser.add_argument("--allow-unreviewed-kalibr-revision", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return args
    if args.session_json is None or args.output_prefix is None:
        parser.error("session_json and --output-prefix are required unless --self-test is used")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    try:
        report = export(args)
    except ExportError as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps({"status": report["status"], "camera_statistics": report["camera_statistics"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
