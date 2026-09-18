"""Render a human-readable review report from #8 stereo evidence JSON files.

This is the installed implementation for the legacy
``tools/render_stereo_calibration_report.py`` compatibility entry point. The
renderer is presentation only: moving it into the package must not change the
input schema requirements, Markdown content, interpretation boundary, or
historical exit-code behavior.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

SCHEMAS = {
    "target_scale": "bividi.calibration.stereo_target_scale_review.v1",
    "dataset_quality": "bividi.calibration.stereo_dataset_quality.v1",
    "calibration": "bividi.calibration.stereo.v1",
    "geometry": "bividi.calibration.stereo_geometry_review.v1",
    "repeatability": "bividi.calibration.stereo_repeatability.v1",
}


class ReportError(ValueError):
    pass


def load(path: Path, schema: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReportError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != schema:
        raise ReportError(f"{path}: expected {schema}")
    return value


def format_value(value: Any, digits: int = 4) -> str:
    return "n/a" if value is None else f"{float(value):.{digits}f}"


def render(paths: dict[str, Path]) -> str:
    evidence = {key: load(paths[key], SCHEMAS[key]) for key in SCHEMAS}
    calibration = evidence["calibration"]
    quality = evidence["dataset_quality"]
    geometry = evidence["geometry"]
    repeatability = evidence["repeatability"]
    target_scale = evidence["target_scale"]

    lines = [
        "# Stereo calibration evidence report",
        "",
        f"Calibration: `{calibration.get('calibration_id', 'unknown')}`  ",
        f"Specimen: `{calibration.get('device', {}).get('model', '?')}` / `{calibration.get('device', {}).get('serial', '?')}`  ",
        f"Mode: `{calibration.get('capture', {}).get('mode_index', '?')}`  ",
        f"Image: `{calibration.get('image', {}).get('width', '?')}x{calibration.get('image', {}).get('height', '?')}`",
        "",
        "## Evidence disposition",
        "",
        "| Evidence | Status | Policy |",
        "|---|---|---|",
        f"| Printed target scale | {target_scale.get('status')} | {target_scale.get('policy_source') or 'none'} |",
        f"| Dataset quality | {quality.get('status')} | {quality.get('policy_source') or 'none'} |",
        f"| Calibration fit | {calibration.get('quality', {}).get('status')} | {calibration.get('quality', {}).get('policy_source') or 'none'} |",
        f"| Physical geometry | {geometry.get('status')} | {geometry.get('policy_source') or 'none'} |",
        f"| Repeatability | {repeatability.get('status')} | {repeatability.get('policy_source') or 'none'} |",
        "",
        "## Intrinsics and reprojection",
        "",
        "| Camera | fx | fy | cx | cy | mono RMS px | FOV x/y deg |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]

    for camera in ("camera_a", "camera_b"):
        camera_data = calibration["cameras"][camera]
        intrinsic = camera_data["K"]
        fov = camera_data.get("pinhole_fov_deg", {})
        lines.append(
            f"| {camera} | {format_value(intrinsic[0][0])} | {format_value(intrinsic[1][1])} | "
            f"{format_value(intrinsic[0][2])} | {format_value(intrinsic[1][2])} | "
            f"{format_value(camera_data.get('mono_rms_px'))} | "
            f"{format_value(fov.get('x'), 2)} / {format_value(fov.get('y'), 2)} |"
        )

    vertical_epipolar = calibration.get("rectification", {}).get(
        "vertical_epipolar_abs_px", {}
    )
    lines += [
        "",
        "## Stereo geometry / rectification",
        "",
        f"- Stereo RMS: `{format_value(calibration.get('stereo', {}).get('stereo_rms_px'))} px`",
        f"- Baseline: `{format_value(calibration.get('stereo', {}).get('baseline_m'), 6)} m`",
        f"- Vertical epipolar residual p95: `{format_value(vertical_epipolar.get('p95'))} px`",
        f"- Vertical epipolar residual max: `{format_value(vertical_epipolar.get('max'))} px`",
        f"- Physical baseline delta: `{format_value(geometry.get('comparison', {}).get('absolute_delta_mm'))} mm`",
        "",
        "## Dataset coverage",
        "",
    ]

    for camera in ("camera_a", "camera_b"):
        camera_quality = quality.get("cameras", {}).get(camera, {})
        lines.append(
            f"- {camera}: global hull `{format_value(camera_quality.get('global_image_plane_hull_fraction'))}`, "
            f"target-corner fraction `{format_value(camera_quality.get('target_corner_fraction'))}`, "
            f"centroid span x/y `{format_value(camera_quality.get('centroid_x_span_fraction'))}` / "
            f"`{format_value(camera_quality.get('centroid_y_span_fraction'))}`"
        )

    repeatability_summary = repeatability.get("summary", {})
    lines += [
        "",
        "## Independent-session repeatability",
        "",
        f"- Compared artifacts: `{repeatability_summary.get('artifact_count', '?')}`",
        f"- Max rotation delta: `{format_value(repeatability_summary.get('max_rotation_delta_deg'))} deg`",
        f"- Max baseline delta: `{format_value(repeatability_summary.get('max_baseline_delta_mm'))} mm`",
        f"- Max translation-direction delta: `{format_value(repeatability_summary.get('max_translation_direction_delta_deg'))} deg`",
        f"- Max focal delta: `{format_value(repeatability_summary.get('max_focal_delta_percent'))} %`",
        f"- Max principal-point delta: `{format_value(repeatability_summary.get('max_principal_point_delta_px'))} px`",
        "",
        "## Interpretation boundary",
        "",
        "This report is a rendering of machine-readable evidence. It does not create new acceptance evidence, replace the final provenance gate, or prove physical accuracy by itself.",
        "",
    ]
    return "\n".join(lines)


def self_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        documents = {
            "target_scale": {
                "schema": SCHEMAS["target_scale"],
                "status": "PASS",
                "policy_source": "lab",
            },
            "dataset_quality": {
                "schema": SCHEMAS["dataset_quality"],
                "status": "PASS",
                "policy_source": "lab",
                "cameras": {"camera_a": {}, "camera_b": {}},
            },
            "calibration": {
                "schema": SCHEMAS["calibration"],
                "calibration_id": "c",
                "device": {"model": "M", "serial": "S"},
                "capture": {"mode_index": 0},
                "image": {"width": 640, "height": 480},
                "cameras": {
                    "camera_a": {
                        "K": [[500, 0, 320], [0, 500, 240], [0, 0, 1]],
                        "mono_rms_px": 0.1,
                    },
                    "camera_b": {
                        "K": [[500, 0, 320], [0, 500, 240], [0, 0, 1]],
                        "mono_rms_px": 0.1,
                    },
                },
                "stereo": {"baseline_m": 0.08, "stereo_rms_px": 0.2},
                "rectification": {
                    "vertical_epipolar_abs_px": {"p95": 0.1, "max": 0.2}
                },
                "quality": {"status": "PASS", "policy_source": "lab"},
            },
            "geometry": {
                "schema": SCHEMAS["geometry"],
                "status": "PASS",
                "policy_source": "lab",
                "comparison": {"absolute_delta_mm": 0.5},
            },
            "repeatability": {
                "schema": SCHEMAS["repeatability"],
                "status": "PASS",
                "policy_source": "lab",
                "summary": {"artifact_count": 2},
            },
        }
        paths: dict[str, Path] = {}
        for key, value in documents.items():
            path = root / f"{key}.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            paths[key] = path
        text = render(paths)
        assert "Stereo calibration evidence report" in text
        assert "0.080000" in text
    print("Stereo calibration human-report renderer self-test: PASS")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    for key in SCHEMAS:
        parser.add_argument("--" + key.replace("_", "-"), dest=key, type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        self_test()
        return 0

    paths = {key: getattr(args, key) for key in SCHEMAS}
    if any(value is None for value in paths.values()) or args.output is None:
        raise ReportError("all evidence inputs and --output are required")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(paths), encoding="utf-8")
    print(args.output)
    return 0


def entrypoint(argv: Sequence[str] | None = None) -> int:
    """CLI wrapper preserving the historical error/exit-code contract."""

    try:
        return main(argv)
    except ReportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(entrypoint())
