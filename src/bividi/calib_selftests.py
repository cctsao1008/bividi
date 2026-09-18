"""Central calibration tool self-test manifest/runner for Issue #60.

The runner deliberately invokes the existing compatibility entry points rather
than importing their optional dependencies into the base Bividi package. It is
therefore a CI/developer contract runner, not a calibration algorithm surface.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
from collections.abc import Sequence

from .calib_cli import find_source_root


@dataclass(frozen=True)
class CalibrationSelfTest:
    name: str
    script: str
    args: tuple[str, ...]
    summary: str = ""


_SELF_TESTS: tuple[CalibrationSelfTest, ...] = (
    CalibrationSelfTest("artifact-validator", "validate_calibration_artifact.py", ("--self-test",), "calibration artifact validator contract"),
    CalibrationSelfTest("example-imu-v1", "validate_calibration_artifact.py", ("calibration/examples/imu-synthetic-v1.json",), "validate synthetic IMU example"),
    CalibrationSelfTest("example-camera-imu-v1", "validate_calibration_artifact.py", ("calibration/examples/camera-imu-synthetic-v1.json",), "validate synthetic camera/IMU example"),
    CalibrationSelfTest("stereo-workbench", "stereo_calibration_workbench.py", ("--self-test",), "stereo workbench dependency-light contract"),
    CalibrationSelfTest("stereo-target-scale", "review_calibration_target_scale.py", ("--self-test",), "printed-target scale review"),
    CalibrationSelfTest("stereo-geometry", "review_stereo_geometry.py", ("--self-test",), "stereo geometry review"),
    CalibrationSelfTest("stereo-repeatability", "compare_stereo_calibrations.py", ("--self-test",), "stereo repeatability"),
    CalibrationSelfTest("stereo-promotion", "stereo_calibration_provenance.py", ("--self-test",), "stereo evidence promotion"),
    CalibrationSelfTest("stereo-report", "render_stereo_calibration_report.py", ("--self-test",), "stereo human report"),
    CalibrationSelfTest("stereo-campaign", "plan_stereo_calibration_campaign.py", ("--self-test",), "stereo physical campaign planner"),
    CalibrationSelfTest("imu-export-kalibr", "export_kalibr_imu.py", ("--self-test",), "Kalibr IMU export"),
    CalibrationSelfTest("imu-timing", "audit_imu_timing.py", ("--self-test",), "camera/IMU device-time audit"),
    CalibrationSelfTest("imu-stationary", "analyze_imu_stationary.py", ("--self-test",), "stationary IMU analysis"),
    CalibrationSelfTest("imu-allan", "analyze_imu_allan.py", ("--self-test",), "Allan deviation laboratory"),
    CalibrationSelfTest("imu-six-position", "analyze_imu_six_position.py", ("--self-test",), "six-position accelerometer laboratory"),
    CalibrationSelfTest("imu-gyro-rotation", "analyze_imu_gyro_rotation.py", ("--self-test",), "controlled gyro rotation laboratory"),
    CalibrationSelfTest("imu-provenance", "imu_calibration_provenance.py", ("--self-test",), "IMU provenance gate"),
    CalibrationSelfTest("imu-config-consistency", "analyze_imu_config_consistency.py", ("--self-test",), "declared-vs-measured IMU configuration review"),
    CalibrationSelfTest("camera-imu-prepare", "prepare_kalibr_dynamic_session.py", ("--self-test",), "Kalibr dynamic-session preparer"),
    CalibrationSelfTest("camera-imu-ros1-bag", "write_kalibr_rosbag.py", ("--self-test",), "legacy ROS1 Kalibr bag adapter"),
    CalibrationSelfTest("camera-imu-ros2-mcap", "write_ros2_calibration_mcap.py", ("--self-test",), "ROS2/MCAP calibration adapter"),
    CalibrationSelfTest("camera-imu-excitation", "analyze_camera_imu_excitation.py", ("--self-test",), "dynamic excitation laboratory"),
    CalibrationSelfTest("camera-imu-target-observations", "export_kalibr_target_observations.py", ("--self-test",), "pinned-Kalibr target observation adapter"),
    CalibrationSelfTest("camera-imu-target-coverage", "analyze_kalibr_target_coverage.py", ("--self-test",), "Kalibr target coverage analysis"),
    CalibrationSelfTest("camera-imu-import", "import_kalibr_camera_imu.py", ("--self-test",), "Kalibr camera/IMU result importer"),
    CalibrationSelfTest("camera-imu-solver-quality", "analyze_kalibr_solver_quality.py", ("--self-test",), "Kalibr solver quality evidence"),
    CalibrationSelfTest("camera-imu-temporal", "review_camera_imu_time_offset.py", ("--self-test",), "camera/IMU temporal review"),
    CalibrationSelfTest("camera-imu-repeatability", "compare_camera_imu_calibrations.py", ("--self-test",), "camera/IMU repeatability"),
    CalibrationSelfTest("camera-imu-promotion", "camera_imu_calibration_provenance.py", ("--self-test",), "camera/IMU evidence promotion"),
    CalibrationSelfTest("camera-imu-campaign", "plan_camera_imu_physical_campaign.py", ("--self-test",), "camera/IMU physical campaign planner"),
)


def self_tests() -> tuple[CalibrationSelfTest, ...]:
    return _SELF_TESTS


def validate_manifest(root: Path) -> list[str]:
    errors: list[str] = []
    names: set[str] = set()
    for case in _SELF_TESTS:
        if case.name in names:
            errors.append(f"duplicate self-test name: {case.name}")
        names.add(case.name)
        if not case.name or not case.script or not case.args:
            errors.append(f"malformed self-test entry: {case!r}")
        if not (root / "tools" / case.script).is_file():
            errors.append(f"missing self-test tool for {case.name}: tools/{case.script}")

    schema_dir = root / "calibration" / "schemas"
    schema_paths = sorted(schema_dir.glob("*.json")) if schema_dir.is_dir() else []
    if not schema_paths:
        errors.append("no calibration JSON schemas found under calibration/schemas")
    for path in schema_paths:
        try:
            with path.open("r", encoding="utf-8") as stream:
                value = json.load(stream)
            if not isinstance(value, dict):
                errors.append(f"calibration schema root must be an object: {path.relative_to(root)}")
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"cannot parse calibration schema {path.relative_to(root)}: {exc}")
    return errors


def select_tests(names: Sequence[str] | None) -> tuple[CalibrationSelfTest, ...]:
    if not names:
        return _SELF_TESTS
    requested = list(names)
    known = {case.name: case for case in _SELF_TESTS}
    unknown = [name for name in requested if name not in known]
    if unknown:
        raise KeyError("unknown calibration self-test(s): " + ", ".join(unknown))
    # Keep manifest order even when --only arguments arrive in another order.
    wanted = set(requested)
    return tuple(case for case in _SELF_TESTS if case.name in wanted)


def run_tests(
    cases: Sequence[CalibrationSelfTest],
    *,
    source_root: str | Path | None = None,
    fail_fast: bool = False,
) -> int:
    root = find_source_root(source_root)
    manifest_errors = validate_manifest(root)
    if manifest_errors:
        for error in manifest_errors:
            print(f"MANIFEST ERROR: {error}", file=sys.stderr)
        return 2

    failures: list[tuple[str, int]] = []
    for index, case in enumerate(cases, start=1):
        script = root / "tools" / case.script
        invocation = [sys.executable, str(script), *case.args]
        print(f"[{index}/{len(cases)}] {case.name}: {case.summary}", flush=True)
        completed = subprocess.run(invocation, cwd=root, check=False)
        if completed.returncode != 0:
            failures.append((case.name, int(completed.returncode)))
            print(f"FAIL {case.name}: exit {completed.returncode}", file=sys.stderr, flush=True)
            if fail_fast:
                break
        else:
            print(f"PASS {case.name}", flush=True)

    if failures:
        print("Calibration self-test failures:", file=sys.stderr)
        for name, returncode in failures:
            print(f"  {name}: exit {returncode}", file=sys.stderr)
        return 1

    print(f"Calibration self-test suite: PASS ({len(cases)} cases)")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, help="explicit Bividi source checkout")
    parser.add_argument("--list", action="store_true", help="list manifest test names without executing them")
    parser.add_argument("--only", action="append", default=[], metavar="NAME", help="run only a named manifest test; repeatable")
    parser.add_argument("--fail-fast", action="store_true", help="stop after the first failing leaf test")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parsed = _parser().parse_args(argv)
    if parsed.list:
        for case in _SELF_TESTS:
            print(f"{case.name:<34} {case.summary}")
        return 0

    try:
        cases = select_tests(parsed.only)
    except KeyError as exc:
        print(f"calibration-selftests: error: {exc.args[0]}", file=sys.stderr)
        return 2

    return run_tests(cases, source_root=parsed.source_root, fail_fast=parsed.fail_fast)


if __name__ == "__main__":
    raise SystemExit(main())
