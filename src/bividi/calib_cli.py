"""Discoverable calibration CLI over installed and compatibility implementations.

Reusable calibration/evidence implementations move from the source-tree
``tools/`` compatibility surface into installed package modules incrementally.
Commands already migrated execute from the installed package; remaining commands
continue to delegate to the existing source-tree tools without copying their
algorithms into a parallel implementation.
"""

from __future__ import annotations

import importlib.metadata
import os
from dataclasses import dataclass
from pathlib import Path
import shlex
import subprocess
import sys
from collections.abc import Sequence


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


_COMMANDS: tuple[CalibrationCommand, ...] = (
    # Stereo / #8
    CalibrationCommand("stereo", "target", "stereo_calibration_workbench.py", ("target",), "generate a calibration target contract/render"),
    CalibrationCommand("stereo", "session", "stereo_calibration_workbench.py", ("session",), "build a paired stereo session manifest"),
    CalibrationCommand("stereo", "session-recorder", "stereo_calibration_workbench.py", ("session-recorder",), "import a recorder-backed stereo session"),
    CalibrationCommand("stereo", "inspect", "stereo_calibration_workbench.py", ("inspect",), "inspect target detection and dataset quality"),
    CalibrationCommand("stereo", "solve", "stereo_calibration_workbench.py", ("solve",), "solve mono/stereo calibration"),
    CalibrationCommand("stereo", "validate", "stereo_calibration_workbench.py", ("validate",), "validate a stereo calibration artifact"),
    CalibrationCommand("stereo", "rectify", "stereo_calibration_workbench.py", ("rectify",), "render a rectification inspection view"),
    CalibrationCommand(
        "stereo",
        "target-scale",
        None,
        summary="review measured target print scale",
        module="bividi.calibration.target_scale",
    ),
    CalibrationCommand(
        "stereo",
        "geometry-review",
        None,
        summary="review physical stereo geometry evidence",
        module="bividi.calibration.stereo_geometry",
    ),
    CalibrationCommand(
        "stereo",
        "repeatability",
        None,
        summary="compare independent stereo calibrations",
        module="bividi.calibration.stereo_repeatability",
    ),
    CalibrationCommand(
        "stereo",
        "promote",
        None,
        summary="run stereo evidence/promotion gate",
        module="bividi.calibration.stereo_provenance",
    ),
    CalibrationCommand(
        "stereo",
        "report",
        None,
        summary="render a human stereo calibration report",
        module="bividi.calibration.stereo_report",
    ),
    CalibrationCommand(
        "stereo",
        "campaign",
        None,
        summary="plan/audit a physical stereo campaign",
        module="bividi.calibration.stereo_campaign",
    ),

    # IMU / #47
    CalibrationCommand(
        "imu",
        "timing-audit",
        None,
        summary="audit device-time cadence and camera/IMU timing",
        module="bividi.calibration.imu_timing",
    ),
    CalibrationCommand(
        "imu",
        "stationary",
        None,
        summary="analyze stationary bias/statistics",
        module="bividi.calibration.imu_stationary",
    ),
    CalibrationCommand(
        "imu",
        "allan",
        None,
        summary="analyze Allan deviation/noise evidence",
        module="bividi.calibration.imu_allan_command",
    ),
    CalibrationCommand(
        "imu",
        "six-position",
        None,
        summary="analyze six-position accelerometer evidence",
        module="bividi.calibration.imu_six_position_command",
    ),
    CalibrationCommand(
        "imu",
        "gyro-rotation",
        None,
        summary="analyze controlled gyro rotations",
        module="bividi.calibration.imu_gyro_rotation_command",
    ),
    CalibrationCommand(
        "imu",
        "config-consistency",
        None,
        summary="compare declared configuration with measured response",
        module="bividi.calibration.imu_config_consistency_command",
    ),
    CalibrationCommand(
        "imu",
        "provenance",
        None,
        summary="run IMU provenance/promotion gate",
        module="bividi.calibration.imu_provenance_command",
    ),
    CalibrationCommand(
        "imu",
        "export-kalibr",
        None,
        summary="export measured IMU parameters for Kalibr",
        module="bividi.calibration.kalibr_imu_export_command",
    ),

    # Camera/IMU / #47
    CalibrationCommand(
        "camera-imu",
        "prepare",
        None,
        summary="prepare a hash-bound Kalibr dynamic session",
        module="bividi.calibration.kalibr_dynamic_session_command",
    ),
    CalibrationCommand(
        "camera-imu",
        "excitation",
        None,
        summary="review dynamic motion excitation evidence",
        module="bividi.calibration.camera_imu_excitation_command",
    ),
    CalibrationCommand(
        "camera-imu",
        "target-observations",
        None,
        summary="export pinned-Kalibr target observations",
        module="bividi.calibration.kalibr_target_observations_command",
    ),
    CalibrationCommand(
        "camera-imu",
        "target-coverage",
        None,
        summary="analyze AprilGrid/image-plane coverage",
        module="bividi.calibration.kalibr_target_coverage_command",
    ),
    CalibrationCommand("camera-imu", "ros1-bag", "write_kalibr_rosbag.py", (), "write legacy ROS1 bag for upstream Kalibr"),
    CalibrationCommand("camera-imu", "ros2-mcap", "write_ros2_calibration_mcap.py", (), "write ROS2/MCAP interoperability transport"),
    CalibrationCommand(
        "camera-imu",
        "import-kalibr",
        None,
        summary="import Kalibr T_cam_imu/time shift candidate",
        module="bividi.calibration.kalibr_camera_imu_import_command",
    ),
    CalibrationCommand("camera-imu", "solver-quality", "analyze_kalibr_solver_quality.py", (), "review exact Kalibr solver residuals"),
    CalibrationCommand("camera-imu", "temporal-review", "review_camera_imu_time_offset.py", (), "review device-time offset evidence"),
    CalibrationCommand("camera-imu", "repeatability", "compare_camera_imu_calibrations.py", (), "compare repeated camera/IMU solves"),
    CalibrationCommand("camera-imu", "promote", "camera_imu_calibration_provenance.py", (), "run camera/IMU evidence promotion gate"),
    CalibrationCommand("camera-imu", "campaign", "plan_camera_imu_physical_campaign.py", (), "plan/audit a physical camera/IMU campaign"),
)

_COMMAND_INDEX = {(item.group, item.name): item for item in _COMMANDS}
_GROUPS = tuple(sorted({item.group for item in _COMMANDS}))


def commands() -> tuple[CalibrationCommand, ...]:
    """Return the immutable command registry for tests/documentation."""

    return _COMMANDS


def _version() -> str:
    try:
        return importlib.metadata.version("bividi")
    except importlib.metadata.PackageNotFoundError:  # source-only invocation
        return "0.0.0+source"


def _looks_like_checkout(root: Path) -> bool:
    return (root / "pyproject.toml").is_file() and (root / "tools").is_dir()


def find_source_root(explicit: str | Path | None = None) -> Path:
    """Find the checkout containing legacy calibration compatibility scripts.

    Installed package modules do not use this lookup. Explicit ``--source-root``
    and ``BIVIDI_SOURCE_ROOT`` keep the remaining compatibility dispatches
    deterministic while implementations migrate incrementally.
    """

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
        raise RuntimeError(
            f"calibration command {group} {name} expects missing tool: {script}"
        )
    return [sys.executable, str(script), *command.prefix, *tool_args]


def _print_global_help() -> None:
    print("usage: bividi-calib [--source-root PATH] [--dry-run] <group> <command> [tool args...]")
    print()
    print("Calibration workflow router. Migrated commands run from the installed package; remaining tools keep compatibility dispatch.")
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
    print("  --source-root PATH   source checkout for legacy-routed commands")
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
