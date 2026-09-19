"""Discoverable calibration CLI over installed and compatibility implementations."""
from __future__ import annotations

import importlib.metadata
import os
import shlex
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CalibrationCommand:
    group: str
    name: str
    script: str | None
    prefix: tuple[str, ...] = ()
    summary: str = ""
    module: str | None = None

    def __post_init__(self) -> None:
        if (self.script is None) == (self.module is None):
            raise ValueError(
                f"calibration command {self.group} {self.name} must declare exactly one implementation target"
            )


def _pkg(group: str, name: str, module: str, summary: str, prefix: tuple[str, ...] = ()) -> CalibrationCommand:
    return CalibrationCommand(group, name, None, prefix, summary, module)


_COMMANDS: tuple[CalibrationCommand, ...] = (
    # Stereo / #8, #61
    _pkg("stereo", "target", "bividi.calibration.stereo_workbench_command", "generate a calibration target contract/render", ("target",)),
    _pkg("stereo", "session", "bividi.calibration.stereo_workbench_command", "build a paired stereo session manifest", ("session",)),
    _pkg("stereo", "session-recorder", "bividi.calibration.stereo_workbench_command", "import a recorder-backed stereo session", ("session-recorder",)),
    _pkg("stereo", "inspect", "bividi.calibration.stereo_workbench_command", "inspect target detection and dataset quality", ("inspect",)),
    _pkg("stereo", "solve", "bividi.calibration.stereo_workbench_command", "solve mono/stereo calibration", ("solve",)),
    _pkg("stereo", "validate", "bividi.calibration.stereo_workbench_command", "validate a stereo calibration artifact", ("validate",)),
    _pkg("stereo", "rectify", "bividi.calibration.stereo_workbench_command", "render a rectification inspection view", ("rectify",)),
    _pkg("stereo", "target-scale", "bividi.calibration.target_scale", "review measured target print scale"),
    _pkg("stereo", "geometry-review", "bividi.calibration.stereo_geometry", "review physical stereo geometry evidence"),
    _pkg("stereo", "repeatability", "bividi.calibration.stereo_repeatability", "compare independent stereo calibrations"),
    _pkg("stereo", "model-compare", "bividi.calibration.stereo_model_compare", "compare camera-model candidates on identical evidence"),
    _pkg("stereo", "fisheye-evaluate", "bividi.calibration.stereo_fisheye_candidate", "evaluate an OpenCV fisheye stereo candidate"),
    _pkg("stereo", "promote", "bividi.calibration.stereo_provenance", "run stereo evidence/promotion gate"),
    _pkg("stereo", "report", "bividi.calibration.stereo_report", "render a human stereo calibration report"),
    _pkg("stereo", "campaign", "bividi.calibration.stereo_campaign", "plan/audit a physical stereo campaign"),

    # IMU / #47
    _pkg("imu", "timing-audit", "bividi.calibration.imu_timing", "audit device-time cadence and camera/IMU timing"),
    _pkg("imu", "stationary", "bividi.calibration.imu_stationary", "analyze stationary bias/statistics"),
    _pkg("imu", "allan", "bividi.calibration.imu_allan_command", "analyze Allan deviation/noise evidence"),
    _pkg("imu", "six-position", "bividi.calibration.imu_six_position_command", "analyze six-position accelerometer evidence"),
    _pkg("imu", "gyro-rotation", "bividi.calibration.imu_gyro_rotation_command", "analyze controlled gyro rotations"),
    _pkg("imu", "config-consistency", "bividi.calibration.imu_config_consistency_command", "compare declared configuration with measured response"),
    _pkg("imu", "provenance", "bividi.calibration.imu_provenance_command", "run IMU provenance/promotion gate"),
    _pkg("imu", "export-kalibr", "bividi.calibration.kalibr_imu_export_command", "export measured IMU parameters for Kalibr"),

    # Camera/IMU / #47
    _pkg("camera-imu", "prepare", "bividi.calibration.kalibr_dynamic_session_command", "prepare a hash-bound Kalibr dynamic session"),
    _pkg("camera-imu", "excitation", "bividi.calibration.camera_imu_excitation_command", "review dynamic motion excitation evidence"),
    _pkg("camera-imu", "target-observations", "bividi.calibration.kalibr_target_observations_command", "export pinned-Kalibr target observations"),
    _pkg("camera-imu", "target-coverage", "bividi.calibration.kalibr_target_coverage_command", "analyze AprilGrid/image-plane coverage"),
    _pkg("camera-imu", "ros1-bag", "bividi.calibration.kalibr_rosbag_command", "write legacy ROS1 bag for upstream Kalibr"),
    _pkg("camera-imu", "ros2-mcap", "bividi.calibration.ros2_mcap_command", "write ROS2/MCAP interoperability transport"),
    _pkg("camera-imu", "import-kalibr", "bividi.calibration.kalibr_camera_imu_import_command", "import Kalibr T_cam_imu/time shift candidate"),
    _pkg("camera-imu", "solver-quality", "bividi.calibration.kalibr_solver_quality_command", "review exact Kalibr solver residuals"),
    _pkg("camera-imu", "temporal-review", "bividi.calibration.camera_imu_temporal_review_command", "review device-time offset evidence"),
    _pkg("camera-imu", "repeatability", "bividi.calibration.camera_imu_repeatability_command", "compare repeated camera/IMU solves"),
    _pkg("camera-imu", "promote", "bividi.calibration.camera_imu_provenance_command", "run camera/IMU evidence promotion gate"),
    _pkg("camera-imu", "campaign", "bividi.calibration.camera_imu_campaign_command", "plan/audit a physical camera/IMU campaign"),
)

_COMMAND_INDEX = {(item.group, item.name): item for item in _COMMANDS}
_GROUPS = tuple(sorted({item.group for item in _COMMANDS}))


def commands() -> tuple[CalibrationCommand, ...]:
    return _COMMANDS


def _version() -> str:
    try:
        return importlib.metadata.version("bividi")
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0+source"


def _looks_like_checkout(root: Path) -> bool:
    return (root / "pyproject.toml").is_file() and (root / "tools").is_dir()


def find_source_root(explicit: str | Path | None = None) -> Path:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(Path(explicit))
    env = os.environ.get("BIVIDI_SOURCE_ROOT")
    if env:
        candidates.append(Path(env))
    here = Path(__file__).resolve()
    if len(here.parents) >= 3:
        candidates.append(here.parents[2])
    cwd = Path.cwd().resolve()
    candidates.extend((cwd, *cwd.parents))
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if _looks_like_checkout(resolved):
            return resolved
    raise RuntimeError(
        "cannot locate a Bividi source checkout containing tools/. "
        "Use --source-root PATH or set BIVIDI_SOURCE_ROOT."
    )


def resolve_command(group: str, name: str) -> CalibrationCommand:
    try:
        return _COMMAND_INDEX[(group, name)]
    except KeyError as exc:
        if group not in _GROUPS:
            raise KeyError(f"unknown calibration group: {group}") from exc
        raise KeyError(f"unknown {group} command: {name}") from exc


def build_invocation(
    group: str,
    name: str,
    tool_args: Sequence[str],
    *,
    source_root: str | Path | None = None,
) -> list[str]:
    command = resolve_command(group, name)
    if command.module is not None:
        return [sys.executable, "-m", command.module, *command.prefix, *tool_args]
    root = find_source_root(source_root)
    assert command.script is not None
    script = root / "tools" / command.script
    if not script.is_file():
        raise RuntimeError(f"calibration command {group} {name} expects missing tool: {script}")
    return [sys.executable, str(script), *command.prefix, *tool_args]


def _print_global_help() -> None:
    print("usage: bividi-calib [--source-root PATH] [--dry-run] <group> <command> [tool args...]")
    print()
    print("Calibration workflow router. Package-native commands run from the installed package.")
    print("Use '<group> --help' to list a group and '<group> <command> --help' for exact tool arguments.")
    print()
    print("groups:")
    for group in _GROUPS:
        print(f"  {group}")
    print()
    print("global options:")
    print("  -h, --help           show this help")
    print("  --list               list all routed commands")
    print("  --version            show Bividi package version")
    print("  --source-root PATH   compatibility source checkout when a legacy route exists")
    print("  --dry-run            print delegated command without executing it")


def _print_group_help(group: str) -> None:
    if group not in _GROUPS:
        raise KeyError(f"unknown calibration group: {group}")
    print(f"usage: bividi-calib {group} <command> [tool args...]")
    print()
    print("commands:")
    for command in _COMMANDS:
        if command.group == group:
            print(f"  {command.name:<20} {command.summary}")


def _print_command_list() -> None:
    for command in _COMMANDS:
        print(f"{command.group:<10} {command.name:<20} {command.summary}")


def _parse_globals(argv: list[str]) -> tuple[Path | None, bool, list[str]]:
    source_root: Path | None = None
    dry_run = False
    rest: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--source-root":
            if index + 1 >= len(argv):
                raise ValueError("--source-root requires PATH")
            source_root = Path(argv[index + 1])
            index += 2
            continue
        if token == "--dry-run":
            dry_run = True
            index += 1
            continue
        rest = argv[index:]
        break
    return source_root, dry_run, rest


def main(argv: Sequence[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if not raw or raw[0] in {"-h", "--help"}:
        _print_global_help()
        return 0
    if raw[0] == "--version":
        print(_version())
        return 0
    if raw[0] == "--list":
        _print_command_list()
        return 0
    try:
        source_root, dry_run, rest = _parse_globals(raw)
        if not rest:
            _print_global_help()
            return 2
        group = rest[0]
        if len(rest) == 1 or (len(rest) == 2 and rest[1] in {"-h", "--help"}):
            _print_group_help(group)
            return 0
        name = rest[1]
        invocation = build_invocation(group, name, rest[2:], source_root=source_root)
    except (KeyError, RuntimeError, ValueError) as exc:
        print(f"bividi-calib: error: {exc}", file=sys.stderr)
        return 2
    if dry_run:
        print(shlex.join(invocation))
        return 0
    completed = subprocess.run(invocation, check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
