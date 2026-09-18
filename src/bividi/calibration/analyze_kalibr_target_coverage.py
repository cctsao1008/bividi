#!/usr/bin/env python3
"""Analyze image-plane and target-corner coverage from exported Kalibr detections.

The input must come from export_kalibr_target_observations.py so coverage is based on
exact Kalibr detector observations. This analyzer is dependency-free and does not
redetect AprilGrid corners.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import statistics
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence

INPUT_SCHEMA = "bividi.calibration.kalibr_target_observations.v1"
OUTPUT_SCHEMA = "bividi.calibration.kalibr_target_coverage.v1"
TOOL_VERSION = "1"
CAMERAS = ("camera_a", "camera_b")


class AnalysisError(ValueError):
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
        raise AnalysisError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AnalysisError(f"{path}: expected JSON object")
    return value


def resolve(owner: Path, text: str) -> Path:
    path = Path(text)
    return path if path.is_absolute() else (owner.parent / path).resolve()


def artifact_path(manifest: dict[str, Any], manifest_path: Path, key: str) -> Path:
    artifacts = manifest.get("artifacts")
    entry = artifacts.get(key) if isinstance(artifacts, dict) else None
    if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not isinstance(entry.get("sha256"), str):
        raise AnalysisError(f"{manifest_path}: artifacts.{key} path/SHA-256 required")
    path = resolve(manifest_path, entry["path"])
    if not path.is_file():
        raise AnalysisError(f"{manifest_path}: missing artifact {path}")
    observed = sha256_file(path)
    if observed != entry["sha256"]:
        raise AnalysisError(f"{manifest_path}: artifacts.{key} SHA-256 mismatch")
    return path


def parse_bool(text: str, path: Path, line: int) -> bool:
    value = text.strip().lower()
    if value == "true":
        return True
    if value == "false":
        return False
    raise AnalysisError(f"{path}:{line}: expected true/false; got {text!r}")


def read_detections(path: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {
            "camera", "timestamp_ns", "frame_index", "frame_sequence", "image_width", "image_height",
            "success", "corner_count", "min_x_px", "max_x_px", "min_y_px", "max_y_px",
            "centroid_x_px", "centroid_y_px",
        }
        if reader.fieldnames is None or required - set(reader.fieldnames):
            raise AnalysisError(f"{path}: missing required detection columns")
        for line, row in enumerate(reader, start=2):
            try:
                camera = row["camera"]
                timestamp_ns = int(row["timestamp_ns"], 10)
                frame_index = int(row["frame_index"], 10)
                frame_sequence = int(row["frame_sequence"], 10)
                width = int(row["image_width"], 10)
                height = int(row["image_height"], 10)
                corner_count = int(row["corner_count"], 10)
            except ValueError as exc:
                raise AnalysisError(f"{path}:{line}: invalid integer field") from exc
            if camera not in CAMERAS or width < 2 or height < 2 or corner_count < 0:
                raise AnalysisError(f"{path}:{line}: invalid camera/dimensions/corner_count")
            success = parse_bool(row["success"], path, line)
            values: dict[str, float | None] = {}
            for key in ("min_x_px", "max_x_px", "min_y_px", "max_y_px", "centroid_x_px", "centroid_y_px"):
                if row[key] == "" or row[key] is None:
                    values[key] = None
                else:
                    try:
                        value = float(row[key])
                    except ValueError as exc:
                        raise AnalysisError(f"{path}:{line}: invalid {key}") from exc
                    if not math.isfinite(value):
                        raise AnalysisError(f"{path}:{line}: non-finite {key}")
                    values[key] = value
            if success and corner_count == 0:
                raise AnalysisError(f"{path}:{line}: successful detection with zero corners")
            if not success and corner_count != 0:
                raise AnalysisError(f"{path}:{line}: failed detection has corners")
            result.append({
                "camera": camera, "timestamp_ns": timestamp_ns, "frame_index": frame_index,
                "frame_sequence": frame_sequence, "width": width, "height": height,
                "success": success, "corner_count": corner_count, **values,
            })
    if not result:
        raise AnalysisError(f"{path}: no detection rows")
    return result


def read_corners(path: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {
            "camera", "timestamp_ns", "frame_index", "frame_sequence", "image_width", "image_height",
            "corner_id", "x_px", "y_px",
        }
        if reader.fieldnames is None or required - set(reader.fieldnames):
            raise AnalysisError(f"{path}: missing required corner columns")
        for line, row in enumerate(reader, start=2):
            try:
                camera = row["camera"]
                timestamp_ns = int(row["timestamp_ns"], 10)
                frame_index = int(row["frame_index"], 10)
                frame_sequence = int(row["frame_sequence"], 10)
                width = int(row["image_width"], 10)
                height = int(row["image_height"], 10)
                corner_id = int(row["corner_id"], 10)
                x_px = float(row["x_px"])
                y_px = float(row["y_px"])
            except ValueError as exc:
                raise AnalysisError(f"{path}:{line}: invalid numeric field") from exc
            if camera not in CAMERAS or width < 2 or height < 2 or corner_id < 0:
                raise AnalysisError(f"{path}:{line}: invalid camera/dimensions/corner id")
            if not math.isfinite(x_px) or not math.isfinite(y_px):
                raise AnalysisError(f"{path}:{line}: non-finite corner coordinate")
            if x_px < 0.0 or y_px < 0.0 or x_px > width - 1 or y_px > height - 1:
                raise AnalysisError(f"{path}:{line}: corner outside image bounds")
            result.append({
                "camera": camera, "timestamp_ns": timestamp_ns, "frame_index": frame_index,
                "frame_sequence": frame_sequence, "width": width, "height": height,
                "corner_id": corner_id, "x_px": x_px, "y_px": y_px,
                "x_norm": x_px / (width - 1), "y_norm": y_px / (height - 1),
            })
    return result


def frame_key(row: dict[str, Any]) -> tuple[int, int, int]:
    return int(row["timestamp_ns"]), int(row["frame_index"]), int(row["frame_sequence"])


def validate_structure(detections: Sequence[dict[str, Any]], corners: Sequence[dict[str, Any]], target_count: int) -> None:
    if target_count <= 0:
        raise AnalysisError("target.corner_count must be > 0")
    by_cam = {camera: [row for row in detections if row["camera"] == camera] for camera in CAMERAS}
    if not all(by_cam.values()):
        raise AnalysisError("detections must contain camera_a and camera_b")
    keys_a = [frame_key(row) for row in by_cam["camera_a"]]
    keys_b = [frame_key(row) for row in by_cam["camera_b"]]
    if keys_a != keys_b:
        raise AnalysisError("camera_a/camera_b detection frame identities differ")
    for camera in CAMERAS:
        shapes = {(int(row["width"]), int(row["height"])) for row in by_cam[camera]}
        if len(shapes) != 1:
            raise AnalysisError(f"{camera}: image dimensions changed during session")
    corner_groups: dict[tuple[str, tuple[int, int, int]], list[dict[str, Any]]] = {}
    for corner in corners:
        if int(corner["corner_id"]) >= target_count:
            raise AnalysisError(f"corner id {corner['corner_id']} outside target size {target_count}")
        corner_groups.setdefault((corner["camera"], frame_key(corner)), []).append(corner)
    for row in detections:
        group = corner_groups.get((row["camera"], frame_key(row)), [])
        if len(group) != int(row["corner_count"]):
            raise AnalysisError(
                f"{row['camera']} frame {frame_key(row)}: detection corner_count={row['corner_count']} "
                f"but corners CSV has {len(group)}"
            )
        ids = [int(c["corner_id"]) for c in group]
        if len(ids) != len(set(ids)):
            raise AnalysisError(f"{row['camera']} frame {frame_key(row)}: duplicate corner ids")


def percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    w = pos - lo
    return ordered[lo] * (1.0 - w) + ordered[hi] * w


def distribution(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None, "p50": None, "p95": None}
    data = [float(v) for v in values]
    return {
        "count": len(data), "min": min(data), "max": max(data), "mean": statistics.fmean(data),
        "p50": percentile(data, 0.50), "p95": percentile(data, 0.95),
    }


def convex_hull(points: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    pts = sorted(set(points))
    if len(pts) <= 1:
        return pts
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def polygon_area(points: Sequence[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    return abs(sum(
        points[i][0] * points[(i + 1) % len(points)][1] - points[(i + 1) % len(points)][0] * points[i][1]
        for i in range(len(points))
    )) * 0.5


def camera_metrics(camera: str, detections: Sequence[dict[str, Any]], corners: Sequence[dict[str, Any]], target_count: int) -> dict[str, Any]:
    det = [row for row in detections if row["camera"] == camera]
    cor = [row for row in corners if row["camera"] == camera]
    successful = [row for row in det if row["success"]]
    unique_ids = sorted({int(row["corner_id"]) for row in cor})
    points = [(float(row["x_norm"]), float(row["y_norm"])) for row in cor]
    hull = convex_hull(points)
    centroids_x = [float(row["centroid_x_px"]) / (int(row["width"]) - 1) for row in successful]
    centroids_y = [float(row["centroid_y_px"]) / (int(row["height"]) - 1) for row in successful]
    bbox_areas: list[float] = []
    for row in successful:
        width = int(row["width"])
        height = int(row["height"])
        x_span = (float(row["max_x_px"]) - float(row["min_x_px"])) / (width - 1)
        y_span = (float(row["max_y_px"]) - float(row["min_y_px"])) / (height - 1)
        bbox_areas.append(max(0.0, x_span) * max(0.0, y_span))
    x_values = [p[0] for p in points]
    y_values = [p[1] for p in points]
    return {
        "frames": len(det),
        "successful_frames": len(successful),
        "detection_fraction": len(successful) / len(det),
        "observed_corners_per_successful_frame": distribution([float(row["corner_count"]) for row in successful]),
        "unique_target_corner_ids": len(unique_ids),
        "target_corner_fraction": len(unique_ids) / target_count,
        "image_plane": {
            "x_min_norm": min(x_values) if x_values else None,
            "x_max_norm": max(x_values) if x_values else None,
            "y_min_norm": min(y_values) if y_values else None,
            "y_max_norm": max(y_values) if y_values else None,
            "global_convex_hull_area_fraction": polygon_area(hull),
            "centroid_x_span_norm": (max(centroids_x) - min(centroids_x)) if centroids_x else 0.0,
            "centroid_y_span_norm": (max(centroids_y) - min(centroids_y)) if centroids_y else 0.0,
            "frame_target_bbox_area_fraction": distribution(bbox_areas),
            "scale_proxy_ratio_max_over_min_bbox_area": (
                max(bbox_areas) / min(v for v in bbox_areas if v > 0)
                if bbox_areas and any(v > 0 for v in bbox_areas) else None
            ),
        },
    }


def stereo_metrics(detections: Sequence[dict[str, Any]], corners: Sequence[dict[str, Any]]) -> dict[str, Any]:
    det_by_cam = {
        camera: {frame_key(row): row for row in detections if row["camera"] == camera}
        for camera in CAMERAS
    }
    corner_ids: dict[tuple[str, tuple[int, int, int]], set[int]] = {}
    for row in corners:
        corner_ids.setdefault((row["camera"], frame_key(row)), set()).add(int(row["corner_id"]))
    keys = list(det_by_cam["camera_a"].keys())
    common_success = []
    common_counts: list[float] = []
    for key in keys:
        a = det_by_cam["camera_a"][key]
        b = det_by_cam["camera_b"][key]
        if a["success"] and b["success"]:
            common_success.append(key)
            common_counts.append(float(len(
                corner_ids.get(("camera_a", key), set()) & corner_ids.get(("camera_b", key), set())
            )))
    return {
        "frames": len(keys),
        "both_cameras_detected_frames": len(common_success),
        "both_cameras_detection_fraction": len(common_success) / len(keys) if keys else 0.0,
        "common_corner_ids_per_joint_detection": distribution(common_counts),
    }


def apply_gates(report: dict[str, Any], args: argparse.Namespace) -> tuple[str, list[str]]:
    gates = [
        args.min_detection_fraction is not None,
        args.min_stereo_detection_fraction is not None,
        args.min_target_corner_fraction is not None,
        args.min_global_hull_area_fraction is not None,
        args.min_centroid_span_x is not None,
        args.min_centroid_span_y is not None,
        args.min_scale_proxy_ratio is not None,
    ]
    if not any(gates):
        return "EVIDENCE_ONLY_NO_THRESHOLDS", []
    failures: list[str] = []
    for camera in CAMERAS:
        metrics = report["cameras"][camera]
        if args.min_detection_fraction is not None and metrics["detection_fraction"] < args.min_detection_fraction:
            failures.append(f"{camera}.detection_fraction")
        if args.min_target_corner_fraction is not None and metrics["target_corner_fraction"] < args.min_target_corner_fraction:
            failures.append(f"{camera}.target_corner_fraction")
        image = metrics["image_plane"]
        if args.min_global_hull_area_fraction is not None and image["global_convex_hull_area_fraction"] < args.min_global_hull_area_fraction:
            failures.append(f"{camera}.global_convex_hull_area_fraction")
        if args.min_centroid_span_x is not None and image["centroid_x_span_norm"] < args.min_centroid_span_x:
            failures.append(f"{camera}.centroid_x_span_norm")
        if args.min_centroid_span_y is not None and image["centroid_y_span_norm"] < args.min_centroid_span_y:
            failures.append(f"{camera}.centroid_y_span_norm")
        if args.min_scale_proxy_ratio is not None:
            ratio = image["scale_proxy_ratio_max_over_min_bbox_area"]
            if ratio is None or ratio < args.min_scale_proxy_ratio:
                failures.append(f"{camera}.scale_proxy_ratio_max_over_min_bbox_area")
    if args.min_stereo_detection_fraction is not None and report["stereo"]["both_cameras_detection_fraction"] < args.min_stereo_detection_fraction:
        failures.append("stereo.both_cameras_detection_fraction")
    return ("FAIL" if failures else "PASS"), failures


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = args.observations_json.resolve()
    manifest = load_json(manifest_path)
    if manifest.get("schema") != INPUT_SCHEMA:
        raise AnalysisError(f"{manifest_path}: expected schema {INPUT_SCHEMA!r}")
    target = manifest.get("target")
    if not isinstance(target, dict) or not isinstance(target.get("corner_count"), int):
        raise AnalysisError(f"{manifest_path}: target.corner_count required")
    target_count = int(target["corner_count"])
    detections_path = artifact_path(manifest, manifest_path, "detections_csv")
    corners_path = artifact_path(manifest, manifest_path, "corners_csv")
    detections = read_detections(detections_path)
    corners = read_corners(corners_path)
    validate_structure(detections, corners, target_count)

    report: dict[str, Any] = {
        "schema": OUTPUT_SCHEMA,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": {"path": str(manifest_path), "sha256": sha256_file(manifest_path)},
        "source_artifacts": {
            "detections_csv": {"path": str(detections_path), "sha256": sha256_file(detections_path)},
            "corners_csv": {"path": str(corners_path), "sha256": sha256_file(corners_path)},
        },
        "kalibr": manifest.get("kalibr"),
        "target": target,
        "cameras": {camera: camera_metrics(camera, detections, corners, target_count) for camera in CAMERAS},
        "stereo": stereo_metrics(detections, corners),
        "metric_semantics": {
            "normalized_coordinates": "x/(width-1), y/(height-1)",
            "global_convex_hull_area_fraction": "area of convex hull of all detected normalized corners over the session",
            "centroid_span": "range of per-frame detected-corner centroids in normalized image coordinates",
            "frame_target_bbox_area_fraction": "axis-aligned detected-corner bounding-box area in normalized image coordinates",
            "scale_proxy": "max/min positive frame bounding-box area; perspective/clipping also affect this value",
            "target_corner_fraction": "unique Kalibr target corner IDs observed at least once / Kalibr target corner count",
        },
        "guardrails": [
            "Coverage is computed only from exact exported Kalibr observations; this tool does not redetect corners.",
            "Image-plane coverage is not optimizer residual quality, formal parameter observability, or physical calibration accuracy.",
            "Bounding-box area is a scale proxy, not a direct target distance estimate.",
            "No numeric acceptance threshold is implied unless supplied explicitly on the command line.",
        ],
        "provenance": {"tool": Path(__file__).name, "tool_version": TOOL_VERSION},
    }
    status, failures = apply_gates(report, args)
    report["assessment"] = {
        "status": status,
        "failed_gates": failures,
        "thresholds": {
            "min_detection_fraction": args.min_detection_fraction,
            "min_stereo_detection_fraction": args.min_stereo_detection_fraction,
            "min_target_corner_fraction": args.min_target_corner_fraction,
            "min_global_hull_area_fraction": args.min_global_hull_area_fraction,
            "min_centroid_span_x": args.min_centroid_span_x,
            "min_centroid_span_y": args.min_centroid_span_y,
            "min_scale_proxy_ratio": args.min_scale_proxy_ratio,
        },
    }
    return report


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Kalibr Target Coverage Report",
        "",
        f"Assessment: **{report['assessment']['status']}**",
        "",
        "| Metric | camera_a | camera_b |",
        "|---|---:|---:|",
    ]
    a = report["cameras"]["camera_a"]
    b = report["cameras"]["camera_b"]
    rows = [
        ("Detection fraction", a["detection_fraction"], b["detection_fraction"]),
        ("Target corner fraction", a["target_corner_fraction"], b["target_corner_fraction"]),
        ("Global image-plane hull area", a["image_plane"]["global_convex_hull_area_fraction"], b["image_plane"]["global_convex_hull_area_fraction"]),
        ("Centroid X span", a["image_plane"]["centroid_x_span_norm"], b["image_plane"]["centroid_x_span_norm"]),
        ("Centroid Y span", a["image_plane"]["centroid_y_span_norm"], b["image_plane"]["centroid_y_span_norm"]),
    ]
    for name, va, vb in rows:
        lines.append(f"| {name} | {va:.6g} | {vb:.6g} |")
    lines += [
        "",
        f"Stereo joint-detection fraction: **{report['stereo']['both_cameras_detection_fraction']:.6g}**",
        "",
        "## Interpretation boundaries",
        "",
    ]
    lines.extend(f"- {item}" for item in report["guardrails"])
    if report["assessment"]["failed_gates"]:
        lines += ["", "## Failed explicit gates", ""]
        lines.extend(f"- `{item}`" for item in report["assessment"]["failed_gates"])
    return "\n".join(lines) + "\n"


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        det = root / "detections.csv"
        cor = root / "corners.csv"
        with det.open("w", encoding="utf-8", newline="") as stream:
            w = csv.writer(stream)
            w.writerow(["camera","timestamp_ns","frame_index","frame_sequence","image_width","image_height","success","corner_count","min_x_px","max_x_px","min_y_px","max_y_px","centroid_x_px","centroid_y_px"])
            for camera in CAMERAS:
                w.writerow([camera,1000,0,10,101,101,"true",4,10,30,10,30,20,20])
                w.writerow([camera,2000,1,11,101,101,"true",4,60,90,60,90,75,75])
        with cor.open("w", encoding="utf-8", newline="") as stream:
            w = csv.writer(stream)
            w.writerow(["camera","timestamp_ns","frame_index","frame_sequence","image_width","image_height","corner_id","x_px","y_px"])
            points = {
                1000: [(0,10,10),(1,30,10),(2,30,30),(3,10,30)],
                2000: [(0,60,60),(1,90,60),(2,90,90),(3,60,90)],
            }
            for camera in CAMERAS:
                for frame_index, (stamp, seq) in enumerate(((1000,10),(2000,11))):
                    for cid, x, y in points[stamp]:
                        w.writerow([camera,stamp,frame_index,seq,101,101,cid,x,y])
        manifest = root / "observations.json"
        manifest.write_text(json.dumps({
            "schema": INPUT_SCHEMA,
            "target": {"corner_count": 4},
            "kalibr": {"revision": "test"},
            "artifacts": {
                "detections_csv": {"path": str(det), "sha256": sha256_file(det)},
                "corners_csv": {"path": str(cor), "sha256": sha256_file(cor)},
            },
        }), encoding="utf-8")
        args = argparse.Namespace(
            observations_json=manifest, output_prefix=root / "report",
            min_detection_fraction=None, min_stereo_detection_fraction=None,
            min_target_corner_fraction=None, min_global_hull_area_fraction=None,
            min_centroid_span_x=None, min_centroid_span_y=None, min_scale_proxy_ratio=None,
        )
        report = build_report(args)
        assert report["assessment"]["status"] == "EVIDENCE_ONLY_NO_THRESHOLDS"
        assert report["cameras"]["camera_a"]["target_corner_fraction"] == 1.0
        assert report["stereo"]["both_cameras_detection_fraction"] == 1.0
        assert report["cameras"]["camera_a"]["image_plane"]["global_convex_hull_area_fraction"] > 0.3
        args.min_detection_fraction = 1.01
        gated = build_report(args)
        assert gated["assessment"]["status"] == "FAIL"
    print("Kalibr target coverage analyzer self-test: PASS")


def fraction(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0.0 or parsed > 1.0:
        raise argparse.ArgumentTypeError("expected finite fraction in [0,1]")
    return parsed


def positive(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("expected finite value > 0")
    return parsed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("observations_json", nargs="?", type=Path)
    parser.add_argument("--output-prefix", type=Path)
    parser.add_argument("--min-detection-fraction", type=fraction)
    parser.add_argument("--min-stereo-detection-fraction", type=fraction)
    parser.add_argument("--min-target-corner-fraction", type=fraction)
    parser.add_argument("--min-global-hull-area-fraction", type=fraction)
    parser.add_argument("--min-centroid-span-x", type=fraction)
    parser.add_argument("--min-centroid-span-y", type=fraction)
    parser.add_argument("--min-scale-proxy-ratio", type=positive)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return args
    if args.observations_json is None or args.output_prefix is None:
        parser.error("observations_json and --output-prefix are required unless --self-test is used")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    try:
        report = build_report(args)
    except AnalysisError as exc:
        print(f"ERROR: {exc}")
        return 2
    prefix = args.output_prefix.resolve()
    prefix.parent.mkdir(parents=True, exist_ok=True)
    json_path = Path(str(prefix) + ".target-coverage.json")
    md_path = Path(str(prefix) + ".target-coverage.md")
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"status": report["assessment"]["status"], "json": str(json_path), "markdown": str(md_path)}, indent=2))
    return 3 if report["assessment"]["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
