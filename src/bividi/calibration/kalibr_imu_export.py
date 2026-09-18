#!/usr/bin/env python3
"""Export a validated Bividi IMU calibration artifact to Kalibr imu.yaml.

The exporter is intentionally strict: Kalibr noise parameters must come from
explicit artifact fields. It never substitutes datasheet/default values and
refuses synthetic artifacts unless the caller explicitly opts in for testing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

from . import artifact_validator as calibration_validator

EXPORT_SCHEMA = "bividi.kalibr.imu_export.v1"


def nested(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def positive_number(data: dict[str, Any], path: str) -> float:
    value = nested(data, path)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"required measured field {path!r} is missing or non-numeric")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"required measured field {path!r} must be finite and > 0")
    return result


def source_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_revision() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value or None


def select_update_rate(data: dict[str, Any]) -> tuple[float, str]:
    timing_rate = nested(data, "timing.effective_rate_hz")
    if isinstance(timing_rate, (int, float)) and not isinstance(timing_rate, bool):
        value = float(timing_rate)
        if math.isfinite(value) and value > 0.0:
            return value, "timing.effective_rate_hz"

    measured_rate = nested(data, "imu.sample_rate_hz_measured")
    if isinstance(measured_rate, (int, float)) and not isinstance(measured_rate, bool):
        value = float(measured_rate)
        if math.isfinite(value) and value > 0.0:
            return value, "imu.sample_rate_hz_measured"

    raise ValueError(
        "Kalibr update_rate requires measured cadence: provide timing.effective_rate_hz "
        "or imu.sample_rate_hz_measured; nominal rate is not substituted"
    )


def yaml_scalar(value: float) -> str:
    return format(value, ".12g")


def build_export(data: dict[str, Any], rostopic: str, *, allow_synthetic: bool) -> tuple[str, dict[str, Any]]:
    findings = calibration_validator.validate(data)
    errors = [item for item in findings if item.severity == "error"]
    if errors:
        details = "; ".join(f"{item.path or '<root>'}: {item.message}" for item in errors[:8])
        raise ValueError(f"invalid Bividi calibration artifact: {details}")
    if data.get("schema") != calibration_validator.IMU_SCHEMA:
        raise ValueError(f"expected {calibration_validator.IMU_SCHEMA!r} artifact")

    provenance_kind = nested(data, "provenance.kind")
    if provenance_kind == "synthetic" and not allow_synthetic:
        raise ValueError(
            "synthetic IMU calibration is not exportable for real Kalibr runs without --allow-synthetic"
        )
    if provenance_kind not in {"measured", "imported", "synthetic"}:
        raise ValueError("artifact provenance.kind is missing or unsupported")

    if not isinstance(rostopic, str) or not rostopic.strip() or not rostopic.startswith("/"):
        raise ValueError("--rostopic must be a non-empty absolute ROS topic such as /imu0")

    accel_noise = positive_number(data, "noise.accelerometer_noise_density_m_s2_sqrt_hz")
    accel_walk = positive_number(data, "noise.accelerometer_bias_random_walk_m_s3_sqrt_hz")
    gyro_noise = positive_number(data, "noise.gyroscope_noise_density_rad_s_sqrt_hz")
    gyro_walk = positive_number(data, "noise.gyroscope_bias_random_walk_rad_s2_sqrt_hz")
    update_rate, update_rate_source = select_update_rate(data)

    values = {
        "accelerometer_noise_density": accel_noise,
        "accelerometer_random_walk": accel_walk,
        "gyroscope_noise_density": gyro_noise,
        "gyroscope_random_walk": gyro_walk,
        "rostopic": rostopic.strip(),
        "update_rate": update_rate,
    }

    yaml_text = (
        "# Generated from a Bividi IMU calibration artifact.\n"
        "# No datasheet/default noise values are substituted by this exporter.\n"
        f"accelerometer_noise_density: {yaml_scalar(accel_noise)}\n"
        f"accelerometer_random_walk: {yaml_scalar(accel_walk)}\n"
        f"gyroscope_noise_density: {yaml_scalar(gyro_noise)}\n"
        f"gyroscope_random_walk: {yaml_scalar(gyro_walk)}\n"
        f"rostopic: {rostopic.strip()}\n"
        f"update_rate: {yaml_scalar(update_rate)}\n"
    )

    manifest = {
        "schema": EXPORT_SCHEMA,
        "source_calibration_id": data.get("calibration_id"),
        "source_artifact_schema": data.get("schema"),
        "source_provenance_kind": provenance_kind,
        "update_rate_source": update_rate_source,
        "kalibr_imu_yaml": values,
        "mapping": {
            "accelerometer_noise_density": "noise.accelerometer_noise_density_m_s2_sqrt_hz",
            "accelerometer_random_walk": "noise.accelerometer_bias_random_walk_m_s3_sqrt_hz",
            "gyroscope_noise_density": "noise.gyroscope_noise_density_rad_s_sqrt_hz",
            "gyroscope_random_walk": "noise.gyroscope_bias_random_walk_rad_s2_sqrt_hz",
            "update_rate": update_rate_source,
        },
        "exporter_revision": git_revision(),
    }
    return yaml_text, manifest


def self_test() -> int:
    artifact = calibration_validator.synthetic_imu()
    yaml_text, manifest = build_export(artifact, "/imu0", allow_synthetic=True)
    assert "accelerometer_noise_density: 0.002" in yaml_text
    assert "gyroscope_noise_density: 0.0002" in yaml_text
    assert "rostopic: /imu0" in yaml_text
    assert "update_rate: 599.8" in yaml_text
    assert manifest["update_rate_source"] == "timing.effective_rate_hz"

    no_timing = json.loads(json.dumps(artifact))
    no_timing.pop("timing")
    _, fallback_manifest = build_export(no_timing, "/imu0", allow_synthetic=True)
    assert fallback_manifest["update_rate_source"] == "imu.sample_rate_hz_measured"

    try:
        build_export(artifact, "/imu0", allow_synthetic=False)
    except ValueError as exc:
        assert "synthetic" in str(exc)
    else:
        raise AssertionError("synthetic export must require explicit opt-in")

    missing = json.loads(json.dumps(artifact))
    del missing["noise"]["gyroscope_noise_density_rad_s_sqrt_hz"]
    try:
        build_export(missing, "/imu0", allow_synthetic=True)
    except ValueError as exc:
        assert "gyroscope_noise_density" in str(exc)
    else:
        raise AssertionError("missing measured Kalibr noise value must fail")

    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "imu.json"
        path.write_text(json.dumps(artifact), encoding="utf-8")
        assert len(source_hash(path)) == 64

    print("Kalibr IMU exporter self-test: PASS")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export a Bividi IMU calibration artifact to Kalibr imu.yaml"
    )
    parser.add_argument("artifact", nargs="?", type=Path)
    parser.add_argument("--rostopic", default="/imu0")
    parser.add_argument("--output", type=Path, default=Path("imu.yaml"))
    parser.add_argument("--manifest-out", type=Path,
                        help="optional JSON sidecar recording exact field mapping/provenance")
    parser.add_argument("--allow-synthetic", action="store_true",
                        help="allow synthetic artifacts for test-only export")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.self_test:
        return self_test()
    if args.artifact is None:
        print("IMU calibration artifact path is required", file=sys.stderr)
        return 3

    try:
        data = calibration_validator.load(args.artifact)
        yaml_text, manifest = build_export(data, args.rostopic, allow_synthetic=args.allow_synthetic)
        manifest["source_artifact"] = str(args.artifact)
        manifest["source_sha256"] = source_hash(args.artifact)
    except ValueError as exc:
        print(f"export_kalibr_imu: {exc}", file=sys.stderr)
        return 2

    args.output.write_text(yaml_text, encoding="utf-8")
    if args.manifest_out is not None:
        args.manifest_out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote Kalibr IMU config: {args.output}")
    if args.manifest_out is not None:
        print(f"wrote export manifest: {args.manifest_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
