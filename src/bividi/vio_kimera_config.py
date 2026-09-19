"""Build a hash-bound Bividi -> pinned Kimera-VIO calibration translation plan.

No Kimera, GTSAM, OpenCV, or runtime tuning dependency is introduced here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from .calibration import artifact_validator
from .calibration.stereo_calibration_solve import validate as validate_stereo

SCHEMA = "bividi.vio.kimera_translation_plan.v1"
TOOL_VERSION = "1"
COMPATIBILITY_TOOL_NAME = "prepare_kimera_vio_translation.py"
KIMERA_REPOSITORY = "MIT-SPARK/Kimera-VIO"
KIMERA_REVISION = "ce8c59b7b273ab5ac29db7e5572e1623760e19c7"
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
TIME_OFFSET_DEFINITION = "t_imu_s = t_camera_reference_s + offset_s"

UPSTREAM_PROVENANCE = (
    {
        "path": "include/kimera-vio/common/vio_types.h",
        "symbols": ["VIO::Timestamp", "VIO::FrameId", "VIO::ImuAccGyr"],
        "claims": ["Timestamp is signed int64", "FrameId is uint64", "IMU ordering is accel xyz then gyro xyz"],
    },
    {
        "path": "src/frontend/CameraParams.cpp",
        "symbols": ["CameraParams::parseBodyPoseCam", "CameraParams::stringToDistortionModel", "CameraParams::convertDistortionVectorToMatrix"],
        "claims": ["T_BS is body_Pose_cam", "pinhole radtan is supported", "distortion vectors preserve >=4 coefficients"],
    },
    {
        "path": "scripts/kalibr/kalibr_params_to_kimera_vio_params.py",
        "symbols": ["CAMERA_MAPPINGS", "IMU_MAPPINGS", "make_imu_config"],
        "claims": ["camera T_BS is inverse of T_cam_imu", "IMU rate/noise mapping", "time_offset maps directly to imu_time_shift"],
    },
    {
        "path": "include/kimera-vio/initial/TimeAlignerBase.h",
        "symbols": ["TimeAlignerBase::Result::imu_time_shift"],
        "claims": ["imu_time_shift is defined as t_imu = t_cam + imu_shift"],
    },
    {
        "path": "include/kimera-vio/dataprovider/DataProviderModule.h",
        "symbols": ["DataProviderModule::setImuTimeShift"],
        "claims": ["imu_time_shift input is seconds and is converted internally to nanoseconds"],
    },
)


class KimeraTranslationError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KimeraTranslationError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise KimeraTranslationError(f"{path}: root must be a JSON object")
    return value


def finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def matrix4(value: Any, label: str) -> list[list[float]]:
    if not isinstance(value, list) or len(value) != 4:
        raise KimeraTranslationError(f"{label}: expected finite 4x4 matrix")
    result: list[list[float]] = []
    for row in value:
        if not isinstance(row, list) or len(row) != 4 or not all(finite(item) for item in row):
            raise KimeraTranslationError(f"{label}: expected finite 4x4 matrix")
        result.append([float(item) for item in row])
    return result


def identity4() -> list[list[float]]:
    return [[1.0 if row == col else 0.0 for col in range(4)] for row in range(4)]


def rigid_inverse(matrix: list[list[float]]) -> list[list[float]]:
    rotation = [row[:3] for row in matrix[:3]]
    translation = [matrix[row][3] for row in range(3)]
    transpose = [[rotation[col][row] for col in range(3)] for row in range(3)]
    inverse_translation = [
        -sum(transpose[row][col] * translation[col] for col in range(3))
        for row in range(3)
    ]
    return [transpose[row] + [inverse_translation[row]] for row in range(3)] + [[0.0, 0.0, 0.0, 1.0]]


def matmul4(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    return [[sum(a[row][k] * b[k][col] for k in range(4)) for col in range(4)] for row in range(4)]


def require_valid(path: Path, document: Mapping[str, Any], kind: str) -> None:
    if kind == "stereo":
        errors = list(validate_stereo(document))
    else:
        errors = [
            f"{item.path}: {item.message}"
            for item in artifact_validator.validate(document)
            if getattr(item, "severity", "error") == "error"
        ]
    if errors:
        raise KimeraTranslationError(f"{path}: invalid {kind} artifact: " + "; ".join(errors))


def same_device(stereo: Mapping[str, Any], imu: Mapping[str, Any], camera_imu: Mapping[str, Any]) -> None:
    identities = [
        (document.get("device", {}).get("model"), document.get("device", {}).get("serial"))
        for document in (stereo, imu, camera_imu)
    ]
    if identities[1] != identities[2]:
        raise KimeraTranslationError("IMU and camera-IMU artifacts do not identify the same device")
    # Stereo may carry a logical device-model label different from the inertial
    # toolchain; the specimen serial still must agree.
    if identities[0][1] != identities[1][1]:
        raise KimeraTranslationError("stereo and inertial artifacts do not share the same device serial")


def kimera_camera(document: Mapping[str, Any], camera_key: str, body_pose: list[list[float]]) -> dict[str, Any]:
    camera_model = document["camera_model"]
    if camera_model.get("projection") != "pinhole":
        raise KimeraTranslationError("pinned Kimera translation accepts promoted pinhole stereo.v1 only")
    distortion = camera_model.get("distortion")
    if distortion not in {"opencv5", "opencv-rational"}:
        raise KimeraTranslationError(f"unsupported stereo.v1 distortion for pinned Kimera translation: {distortion!r}")
    camera = document["cameras"][camera_key]
    K = camera["K"]
    D = camera["D"]
    if distortion == "opencv5" and len(D) != 5:
        raise KimeraTranslationError(f"{camera_key}: opencv5 must preserve exactly 5 coefficients")
    if distortion == "opencv-rational" and len(D) not in {8, 12, 14}:
        raise KimeraTranslationError(
            f"{camera_key}: opencv-rational must preserve an OpenCV coefficient vector of length 8, 12, or 14"
        )
    return {
        "camera_id": "left_cam" if camera_key == "camera_a" else "right_cam",
        "source_camera": camera_key,
        "camera_model": "pinhole",
        "distortion_model": "radtan",
        "distortion_source_model": distortion,
        "distortion_coefficients": [float(item) for item in D],
        "intrinsics": [float(K[0][0]), float(K[1][1]), float(K[0][2]), float(K[1][2])],
        "resolution": [int(document["image"]["width"]), int(document["image"]["height"])],
        "T_BS_body_Pose_cam": body_pose,
        "rate_hz": {
            "status": "UNRESOLVED_NOT_IN_STEREO_V1",
            "value": None,
            "note": "Kimera CameraParams requires rate_hz; stereo.v1 does not carry camera rate and this tool does not invent one.",
        },
    }


def imu_rate(imu: Mapping[str, Any]) -> tuple[float, str]:
    imu_section = imu.get("imu", {})
    timing = imu.get("timing", {})
    for path, value in (
        ("imu.sample_rate_hz_measured", imu_section.get("sample_rate_hz_measured")),
        ("timing.effective_rate_hz", timing.get("effective_rate_hz")),
        ("imu.sample_rate_hz_nominal", imu_section.get("sample_rate_hz_nominal")),
    ):
        if finite(value) and float(value) > 0.0:
            return float(value), path
    raise KimeraTranslationError("IMU artifact lacks an explicit positive sample-rate field")


def kimera_imu(imu: Mapping[str, Any]) -> dict[str, Any]:
    noise = imu.get("noise")
    if not isinstance(noise, Mapping):
        raise KimeraTranslationError("IMU noise evidence is required; defaults are forbidden")
    fields = {
        "gyroscope_noise_density": "gyroscope_noise_density_rad_s_sqrt_hz",
        "accelerometer_noise_density": "accelerometer_noise_density_m_s2_sqrt_hz",
        "gyroscope_random_walk": "gyroscope_bias_random_walk_rad_s2_sqrt_hz",
        "accelerometer_random_walk": "accelerometer_bias_random_walk_m_s3_sqrt_hz",
    }
    mapped: dict[str, float] = {}
    sources: dict[str, str] = {}
    for output, source in fields.items():
        value = noise.get(source)
        if not finite(value) or float(value) <= 0.0:
            raise KimeraTranslationError(f"IMU noise field {source} is required and must be > 0")
        mapped[output] = float(value)
        sources[output] = f"noise.{source}"
    rate, rate_source = imu_rate(imu)
    return {
        "T_BS_body_Pose_imu": identity4(),
        "body_frame": imu["imu"]["frame"],
        "rate_hz": rate,
        "rate_source": rate_source,
        **mapped,
        "field_sources": sources,
    }


def build_plan(stereo_path: Path, imu_path: Path, camera_imu_path: Path) -> dict[str, Any]:
    paths = {
        "stereo": stereo_path.resolve(),
        "imu": imu_path.resolve(),
        "camera_imu": camera_imu_path.resolve(),
    }
    documents = {name: load(path) for name, path in paths.items()}
    require_valid(paths["stereo"], documents["stereo"], "stereo")
    require_valid(paths["imu"], documents["imu"], "imu")
    require_valid(paths["camera_imu"], documents["camera_imu"], "camera-imu")

    stereo = documents["stereo"]
    imu = documents["imu"]
    camera_imu = documents["camera_imu"]
    same_device(stereo, imu, camera_imu)

    referenced_imu = camera_imu["imu_reference"].get("imu_calibration_id")
    if referenced_imu is not None and referenced_imu != imu["calibration_id"]:
        raise KimeraTranslationError("camera-IMU artifact references a different IMU calibration id")
    if camera_imu["camera_reference"].get("camera_id") != stereo["capture"].get("camera_a_identity"):
        raise KimeraTranslationError("camera-IMU reference camera does not match stereo camera_a identity")
    if [camera_imu["camera_reference"].get("width"), camera_imu["camera_reference"].get("height")] != [
        stereo["image"]["width"], stereo["image"]["height"]
    ]:
        raise KimeraTranslationError("camera-IMU reference geometry does not match stereo artifact")

    t_cam_a_from_body = matrix4(camera_imu["transform"]["matrix"], "camera_imu.transform.matrix")
    t_body_from_cam_a = rigid_inverse(t_cam_a_from_body)
    rotation = stereo["stereo"]["R_camera_b_from_camera_a"]
    translation = stereo["stereo"]["T_camera_b_from_camera_a_m"]
    t_cam_b_from_cam_a = [
        [float(rotation[row][0]), float(rotation[row][1]), float(rotation[row][2]), float(translation[row])]
        for row in range(3)
    ] + [[0.0, 0.0, 0.0, 1.0]]
    t_body_from_cam_b = matmul4(t_body_from_cam_a, rigid_inverse(t_cam_b_from_cam_a))

    time_offset = camera_imu.get("time_offset")
    if not isinstance(time_offset, Mapping):
        raise KimeraTranslationError("camera-IMU time_offset evidence is required")
    if time_offset.get("definition") != TIME_OFFSET_DEFINITION:
        raise KimeraTranslationError(f"camera-IMU time offset must use exactly: {TIME_OFFSET_DEFINITION}")
    offset = time_offset.get("offset_s")
    if not finite(offset):
        raise KimeraTranslationError("camera-IMU time_offset.offset_s must be finite")

    sources = {
        name: {
            "path": str(path),
            "sha256": sha256_file(path),
            "schema": documents[name]["schema"],
            "calibration_id": documents[name]["calibration_id"],
            "provenance_kind": documents[name].get("provenance", {}).get("kind"),
        }
        for name, path in paths.items()
    }

    return {
        "schema": SCHEMA,
        "tool": COMPATIBILITY_TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "status": "CALIBRATION_TRANSLATION_PLAN_READY_NOT_BACKEND_ADOPTION",
        "upstream": {
            "repository": KIMERA_REPOSITORY,
            "revision": KIMERA_REVISION,
            "revision_is_exact_40_hex": bool(REVISION_RE.fullmatch(KIMERA_REVISION)),
            "provenance": list(UPSTREAM_PROVENANCE),
        },
        "sources": sources,
        "frame_convention": {
            "body_frame": imu["imu"]["frame"],
            "body_definition": "Bividi VIO body frame is the calibrated IMU frame.",
            "matrix_notation": "T_X_from_Y maps homogeneous points expressed in Y into frame X.",
            "camera_a_source": "camera_imu.transform.matrix = T_camera_a_from_body",
            "camera_a_kimera": "T_BS(camera_a) = T_body_from_camera_a = inverse(T_camera_a_from_body)",
            "stereo_source": "T_camera_b_from_camera_a is built from #8 R_camera_b_from_camera_a and T_camera_b_from_camera_a_m",
            "camera_b_kimera": "T_BS(camera_b) = T_body_from_camera_a * inverse(T_camera_b_from_camera_a)",
        },
        "kimera_camera_params": {
            "left": kimera_camera(stereo, "camera_a", t_body_from_cam_a),
            "right": kimera_camera(stereo, "camera_b", t_body_from_cam_b),
        },
        "kimera_imu_params": kimera_imu(imu),
        "time_alignment": {
            "bividi_definition": TIME_OFFSET_DEFINITION,
            "bividi_camera_time_reference": time_offset.get("camera_time_reference"),
            "bividi_offset_s": float(offset),
            "kimera_definition": "t_imu = t_cam + imu_time_shift",
            "kimera_imu_time_shift_s": float(offset),
            "mapping": "direct_same_sign_no_negation",
            "source_field": "camera_imu.time_offset.offset_s",
            "upstream_symbol": "TimeAlignerBase::Result::imu_time_shift",
        },
        "runtime_unresolved": {
            "camera_rate_hz": "not carried by stereo.v1; the later runtime spike must supply it explicitly",
            "frontend_backend_lcd_display_params": "not generated; tuning/policy remains outside this translation contract",
            "pipeline_lifecycle": "VioResetDirective::reinitialize maps to recreate_pipeline_before_feed in the C++ feed contract",
        },
        "guardrails": [
            "No Kimera/GTSAM/OpenCV dependency is required to produce this plan.",
            "No calibration/noise/rate defaults are injected.",
            "No backend adoption or AR0234 accuracy claim is made.",
            "The exact upstream revision is pinned; floating branches are invalid evidence.",
        ],
    }


def validate_plan(plan: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(plan, Mapping):
        return ["plan must be an object"]
    if plan.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    upstream = plan.get("upstream")
    if not isinstance(upstream, Mapping) or upstream.get("repository") != KIMERA_REPOSITORY or upstream.get("revision") != KIMERA_REVISION:
        errors.append("pinned Kimera repository/revision mismatch")
    elif not REVISION_RE.fullmatch(str(upstream.get("revision"))):
        errors.append("Kimera revision must be exact lowercase 40-hex")
    sources = plan.get("sources")
    if not isinstance(sources, Mapping) or set(sources) != {"stereo", "imu", "camera_imu"}:
        errors.append("sources must contain stereo, imu, and camera_imu")
    else:
        for name, source in sources.items():
            if not isinstance(source, Mapping) or not re.fullmatch(r"[0-9a-f]{64}", str(source.get("sha256", ""))):
                errors.append(f"sources.{name}.sha256 invalid")
    alignment = plan.get("time_alignment")
    if not isinstance(alignment, Mapping) or alignment.get("mapping") != "direct_same_sign_no_negation" or alignment.get("bividi_offset_s") != alignment.get("kimera_imu_time_shift_s"):
        errors.append("time offset sign mapping is not frozen as direct")
    return errors


def self_test() -> int:
    transform = [[1.0, 0.0, 0.0, 0.03], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.01], [0.0, 0.0, 0.0, 1.0]]
    inverse = rigid_inverse(transform)
    assert abs(inverse[0][3] + 0.03) < 1e-12
    assert abs(inverse[2][3] + 0.01) < 1e-12
    assert matmul4(transform, inverse) == identity4()
    assert REVISION_RE.fullmatch(KIMERA_REVISION)
    print("Kimera VIO translation-plan self-test: PASS")
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--stereo", type=Path)
    result.add_argument("--imu", type=Path)
    result.add_argument("--camera-imu", type=Path)
    result.add_argument("--output", type=Path)
    result.add_argument("--self-test", action="store_true")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.self_test:
        return self_test()
    if args.stereo is None or args.imu is None or args.camera_imu is None or args.output is None:
        print("kimera-translation: error: --stereo, --imu, --camera-imu and --output are required", file=sys.stderr)
        return 2
    try:
        plan = build_plan(args.stereo, args.imu, args.camera_imu)
        errors = validate_plan(plan)
        if errors:
            raise KimeraTranslationError("generated plan invalid: " + "; ".join(errors))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (KimeraTranslationError, OSError) as exc:
        print(f"kimera-translation: error: {exc}", file=sys.stderr)
        return 2
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
