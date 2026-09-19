"""Compare stereo camera-model candidates on identical calibration evidence.

Pinhole candidates use ``bividi.calibration.stereo.v1``. OpenCV fisheye uses a
separate candidate schema because pinhole-only E/F/FOV/ROI fields must not be
fabricated. This comparator normalizes only explicitly named common metrics and
records the valid-area measurement method for each model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from .stereo_calibration_solve import validate
from .stereo_fisheye_candidate import SCHEMA as FISHEYE_SCHEMA, validate_candidate

PINHOLE_SCHEMA = "bividi.calibration.stereo.v1"
REPORT_SCHEMA = "bividi.calibration.stereo_model_comparison.v1"
TOOL_VERSION = "1"
COMPATIBILITY_TOOL_NAME = "compare_stereo_camera_models.py"
SUPPORTED_MODELS = ("opencv5", "opencv-rational", "opencv-fisheye")
CAMERAS = ("camera_a", "camera_b")


class CompareError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_artifact(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompareError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CompareError(f"{path}: expected JSON object")
    schema = value.get("schema")
    if schema == PINHOLE_SCHEMA:
        errors = validate(value)
        if errors:
            raise CompareError(f"{path}: invalid stereo artifact: {'; '.join(errors)}")
    elif schema == FISHEYE_SCHEMA:
        errors = validate_candidate(value)
        if errors:
            raise CompareError(f"{path}: invalid fisheye candidate: {'; '.join(errors)}")
    else:
        raise CompareError(f"{path}: unsupported candidate schema {schema!r}")
    model = value.get("camera_model", {}).get("distortion")
    if model not in SUPPORTED_MODELS:
        raise CompareError(f"{path}: unsupported distortion model {model!r}")
    return value


def evidence_identity(data: Mapping[str, Any]) -> dict[str, Any]:
    capture = data.get("capture", {})
    image = data.get("image", {})
    target = data.get("target", {})
    provenance = data.get("provenance", {})
    device = data.get("device", {})
    # Projection/model identity is deliberately excluded: this function answers
    # whether candidates were generated from the same evidence, not whether they
    # use the same mathematical model.
    return {
        "source_session_sha256": provenance.get("source_session_sha256"),
        "provenance_kind": provenance.get("kind"),
        "device_model": device.get("model"),
        "device_serial": device.get("serial"),
        "mode_index": capture.get("mode_index"),
        "pixel_format": capture.get("pixel_format"),
        "capture_width": capture.get("width"),
        "capture_height": capture.get("height"),
        "image_width": image.get("width"),
        "image_height": image.get("height"),
        "camera_a_identity": capture.get("camera_a_identity"),
        "camera_b_identity": capture.get("camera_b_identity"),
        "target_id": target.get("target_id"),
        "target_family": target.get("family"),
        "target_sha256": target.get("sha256"),
    }


def _roi_fraction(roi: Sequence[Any], width: int, height: int) -> float:
    if width <= 0 or height <= 0:
        raise CompareError("invalid image geometry")
    return float(roi[2]) * float(roi[3]) / float(width * height)


def candidate_metrics(document: Mapping[str, Any]) -> dict[str, Any]:
    width = int(document["image"]["width"])
    height = int(document["image"]["height"])
    rect = document["rectification"]
    cameras = document["cameras"]
    model = document["camera_model"]["distortion"]
    if document["schema"] == PINHOLE_SCHEMA:
        valid_a = _roi_fraction(rect["valid_roi_camera_a"], width, height)
        valid_b = _roi_fraction(rect["valid_roi_camera_b"], width, height)
        valid_method = "pinhole_valid_roi_area_fraction"
    else:
        valid_a = float(rect["camera_a_map_valid_fraction"])
        valid_b = float(rect["camera_b_map_valid_fraction"])
        valid_method = "fisheye_inverse_map_in_source_domain_fraction"
    return {
        "schema": document["schema"],
        "model": model,
        "projection": document["camera_model"]["projection"],
        "candidate_id": document.get("calibration_id", document.get("candidate_id")),
        "camera_a_mono_rms_px": float(cameras["camera_a"]["mono_rms_px"]),
        "camera_b_mono_rms_px": float(cameras["camera_b"]["mono_rms_px"]),
        "max_mono_rms_px": max(float(cameras["camera_a"]["mono_rms_px"]), float(cameras["camera_b"]["mono_rms_px"])),
        "stereo_rms_px": float(document["stereo"]["stereo_rms_px"]),
        "epipolar_p95_px": float(rect["vertical_epipolar_abs_px"]["p95"]),
        "epipolar_max_px": float(rect["vertical_epipolar_abs_px"]["max"]),
        "baseline_m": float(document["stereo"]["baseline_m"]),
        "camera_a_valid_area_fraction": valid_a,
        "camera_b_valid_area_fraction": valid_b,
        "min_valid_area_fraction": min(valid_a, valid_b),
        "valid_area_method": valid_method,
        "camera_a_distortion_parameter_count": len(cameras["camera_a"]["D"]),
        "camera_b_distortion_parameter_count": len(cameras["camera_b"]["D"]),
        "distortion_parameter_count_total": len(cameras["camera_a"]["D"]) + len(cameras["camera_b"]["D"]),
        "valid_pair_count": int(document["stereo"]["valid_pair_count"]),
    }


def _delta(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        "model_a": a["model"],
        "model_b": b["model"],
        "max_mono_rms_delta_px": abs(float(a["max_mono_rms_px"]) - float(b["max_mono_rms_px"])),
        "stereo_rms_delta_px": abs(float(a["stereo_rms_px"]) - float(b["stereo_rms_px"])),
        "epipolar_p95_delta_px": abs(float(a["epipolar_p95_px"]) - float(b["epipolar_p95_px"])),
        "baseline_delta_mm": abs(float(a["baseline_m"]) - float(b["baseline_m"])) * 1000.0,
        "distortion_parameter_count_delta": abs(int(a["distortion_parameter_count_total"]) - int(b["distortion_parameter_count_total"])),
        "valid_area_methods_comparable": a["valid_area_method"] == b["valid_area_method"],
    }
    if result["valid_area_methods_comparable"]:
        result["min_valid_area_fraction_delta"] = abs(float(a["min_valid_area_fraction"]) - float(b["min_valid_area_fraction"]))
    else:
        result["min_valid_area_fraction_delta"] = None
    return result


def _selection_gates(args: argparse.Namespace, selected: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    gates: dict[str, dict[str, Any]] = {}
    for name, limit, metric, relation in (
        ("max_mono_rms_px", args.max_mono_rms_px, "max_mono_rms_px", "max"),
        ("max_stereo_rms_px", args.max_stereo_rms_px, "stereo_rms_px", "max"),
        ("max_epipolar_p95_px", args.max_epipolar_p95_px, "epipolar_p95_px", "max"),
        ("min_valid_area_fraction", args.min_valid_area_fraction, "min_valid_area_fraction", "min"),
    ):
        if limit is None:
            continue
        observed = float(selected[metric])
        passed = observed <= float(limit) if relation == "max" else observed >= float(limit)
        gates[name] = {
            "limit": float(limit),
            "observed": observed,
            "pass": passed,
            **({"measurement_method": selected["valid_area_method"]} if metric == "min_valid_area_fraction" else {}),
        }
    if args.min_valid_roi_fraction is not None:
        if selected["valid_area_method"] != "pinhole_valid_roi_area_fraction":
            raise CompareError("--min-valid-roi-fraction is pinhole-only; use --min-valid-area-fraction for a fisheye candidate")
        observed = float(selected["min_valid_area_fraction"])
        gates["min_valid_roi_fraction"] = {
            "limit": float(args.min_valid_roi_fraction),
            "observed": observed,
            "pass": observed >= float(args.min_valid_roi_fraction),
            "measurement_method": selected["valid_area_method"],
        }
    return gates


def compare(paths: Sequence[Path], args: argparse.Namespace) -> dict[str, Any]:
    if len(paths) < 2:
        raise CompareError("at least two calibration artifacts are required")
    resolved = [path.resolve() for path in paths]
    documents = [load_artifact(path) for path in resolved]
    identity = evidence_identity(documents[0])
    for path, document in zip(resolved[1:], documents[1:]):
        if evidence_identity(document) != identity:
            raise CompareError(f"{path}: candidates are not bound to identical source evidence")
    metrics = [candidate_metrics(document) for document in documents]
    models = [item["model"] for item in metrics]
    if len(models) != len(set(models)):
        raise CompareError("candidate distortion models must be distinct")
    artifacts = [
        {
            "path": str(path),
            "sha256": sha256_file(path),
            "candidate_id": document.get("calibration_id", document.get("candidate_id")),
            "schema": document["schema"],
            "model": document["camera_model"]["distortion"],
            "provenance_kind": document["provenance"]["kind"],
        }
        for path, document in zip(resolved, documents)
    ]
    pairwise = [_delta(metrics[i], metrics[j]) for i in range(len(metrics)) for j in range(i + 1, len(metrics))]
    gate_values_present = any(value is not None for value in (
        args.max_mono_rms_px,
        args.max_stereo_rms_px,
        args.max_epipolar_p95_px,
        args.min_valid_area_fraction,
        args.min_valid_roi_fraction,
    ))
    if gate_values_present and not args.selected_model:
        raise CompareError("selection gates require --selected-model")
    if args.selected_model and not gate_values_present:
        raise CompareError("--selected-model requires at least one explicit selection gate")
    if args.selected_model and not args.policy_source:
        raise CompareError("explicit model selection requires --policy-source")
    selected = None
    gates: dict[str, dict[str, Any]] = {}
    status = "INSUFFICIENT_EVIDENCE"
    if args.selected_model:
        matches = [item for item in metrics if item["model"] == args.selected_model]
        if not matches:
            raise CompareError(f"selected model {args.selected_model!r} is not among candidates")
        selected = args.selected_model
        gates = _selection_gates(args, matches[0])
        status = "PASS" if all(item["pass"] for item in gates.values()) else "FAIL"
    return {
        "schema": REPORT_SCHEMA,
        "provenance": {"tool": COMPATIBILITY_TOOL_NAME, "tool_version": TOOL_VERSION},
        "evidence_identity": identity,
        "artifacts": artifacts,
        "candidates": metrics,
        "pairwise_deltas": pairwise,
        "selection": {"status": status, "selected_model": selected, "policy_source": args.policy_source, "gates": gates},
        "guardrails": [
            "Lowest training RMS alone is not a camera-model selection policy.",
            "Candidates are compared only when bound to identical source evidence.",
            "Valid-area fractions with different measurement methods are reported but not differenced as equivalent quantities.",
            "Synthetic comparison success is not measured AR0234 model-selection evidence.",
            "No default numerical thresholds are owned by this comparator.",
        ],
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Stereo Camera-Model Comparison", "",
        f"Selection status: `{report['selection']['status']}`",
        f"Selected model: `{report['selection']['selected_model'] or 'none'}`", "",
        "| Model | Max mono RMS (px) | Stereo RMS (px) | Epipolar p95 (px) | Min valid area | Valid-area method | Baseline (mm) | D params |",
        "| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: |",
    ]
    for item in report["candidates"]:
        lines.append(
            f"| {item['model']} | {item['max_mono_rms_px']:.6g} | {item['stereo_rms_px']:.6g} | "
            f"{item['epipolar_p95_px']:.6g} | {item['min_valid_area_fraction']:.6g} | {item['valid_area_method']} | "
            f"{item['baseline_m'] * 1000.0:.6g} | {item['distortion_parameter_count_total']} |"
        )
    lines.extend(["", "## Selection policy", ""])
    if not report["selection"]["gates"]:
        lines.append("No explicit selection gates. Result remains `INSUFFICIENT_EVIDENCE`.")
    else:
        lines.append(f"Policy source: `{report['selection']['policy_source']}`")
        for name, gate in report["selection"]["gates"].items():
            method = f", method={gate['measurement_method']}" if "measurement_method" in gate else ""
            lines.append(f"- `{name}`: observed={gate['observed']:.6g}, limit={gate['limit']:.6g}, pass={gate['pass']}{method}")
    lines.extend(["", "## Guardrails", ""])
    lines.extend(f"- {item}" for item in report["guardrails"])
    return "\n".join(lines) + "\n"


def _synthetic_artifact(model: str, calibration_id: str, stereo_rms: float) -> dict[str, Any]:
    d_len = 5 if model == "opencv5" else 8
    identity = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    K = [[700.0, 0.0, 640.0], [0.0, 700.0, 360.0], [0.0, 0.0, 1.0]]
    return {
        "schema": PINHOLE_SCHEMA,
        "calibration_id": calibration_id,
        "provenance": {"kind": "synthetic", "source_session_sha256": "0" * 64},
        "device": {"model": "synthetic", "serial": "SYN-001"},
        "capture": {"mode_index": 0, "pixel_format": "mono8_png", "width": 1280, "height": 720, "camera_a_identity": "camera_a", "camera_b_identity": "camera_b"},
        "image": {"width": 1280, "height": 720},
        "target": {"target_id": "target", "family": "charuco", "sha256": "1" * 64},
        "camera_model": {"projection": "pinhole", "distortion": model},
        "cameras": {
            "camera_a": {"K": K, "D": [0.0] * d_len, "mono_rms_px": 0.12, "per_view_reprojection_rms_px": [0.1, 0.12, 0.14], "pinhole_fov_deg": {"x": 84.9, "y": 54.4}},
            "camera_b": {"K": K, "D": [0.0] * d_len, "mono_rms_px": 0.13, "per_view_reprojection_rms_px": [0.11, 0.13, 0.15], "pinhole_fov_deg": {"x": 84.9, "y": 54.4}},
        },
        "stereo": {"R_camera_b_from_camera_a": identity, "T_camera_b_from_camera_a_m": [-0.08, 0.0, 0.0], "baseline_m": 0.08, "E": [[0.0, 0.0, 0.0], [0.0, 0.0, 0.08], [0.0, -0.08, 0.0]], "F": [[0.0, 0.0, 0.0], [0.0, 0.0, 0.001], [0.0, -0.001, 0.0]], "stereo_rms_px": stereo_rms, "valid_pair_count": 10},
        "rectification": {"R1": identity, "R2": identity, "P1": [[700.0, 0.0, 640.0, 0.0], [0.0, 700.0, 360.0, 0.0], [0.0, 0.0, 1.0, 0.0]], "P2": [[700.0, 0.0, 640.0, -56.0], [0.0, 700.0, 360.0, 0.0], [0.0, 0.0, 1.0, 0.0]], "Q": [[1.0, 0.0, 0.0, -640.0], [0.0, 1.0, 0.0, -360.0], [0.0, 0.0, 0.0, 700.0], [0.0, 0.0, 12.5, 0.0]], "valid_roi_camera_a": [0, 0, 1280, 720], "valid_roi_camera_b": [0, 0, 1280, 720], "vertical_epipolar_abs_px": {"count": 10, "min": 0.01, "max": 0.2, "mean": 0.08, "median": 0.07, "p95": 0.18}},
        "quality": {"status": "EVIDENCE_ONLY_NO_THRESHOLDS", "gates": {}, "policy_source": None},
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        a = root / "opencv5.json"
        b = root / "rational.json"
        a.write_text(json.dumps(_synthetic_artifact("opencv5", "a", 0.20)), encoding="utf-8")
        b.write_text(json.dumps(_synthetic_artifact("opencv-rational", "b", 0.18)), encoding="utf-8")
        args = argparse.Namespace(selected_model=None, policy_source=None, max_mono_rms_px=None, max_stereo_rms_px=None, max_epipolar_p95_px=None, min_valid_area_fraction=None, min_valid_roi_fraction=None)
        report = compare([a, b], args)
        assert report["selection"]["status"] == "INSUFFICIENT_EVIDENCE"
        assert len(report["pairwise_deltas"]) == 1
        args.selected_model = "opencv-rational"
        args.policy_source = "synthetic policy"
        args.max_stereo_rms_px = 0.19
        report = compare([a, b], args)
        assert report["selection"]["status"] == "PASS"
        assert "Stereo Camera-Model Comparison" in render_markdown(report)
    print("Stereo camera-model comparator self-test: PASS")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("artifacts", nargs="*", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--selected-model", choices=SUPPORTED_MODELS)
    parser.add_argument("--policy-source")
    parser.add_argument("--max-mono-rms-px", type=float)
    parser.add_argument("--max-stereo-rms-px", type=float)
    parser.add_argument("--max-epipolar-p95-px", type=float)
    parser.add_argument("--min-valid-area-fraction", type=float)
    parser.add_argument("--min-valid-roi-fraction", type=float, help="legacy pinhole-only valid ROI gate")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    report = compare(args.artifacts, args)
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(report), encoding="utf-8")
    return 3 if report["selection"]["status"] == "FAIL" else 0


def entrypoint(argv: Sequence[str] | None = None) -> int:
    try:
        return main(argv)
    except (CompareError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except SystemExit as exc:
        return 0 if exc.code in (None, 0) else 2


if __name__ == "__main__":
    raise SystemExit(entrypoint())
