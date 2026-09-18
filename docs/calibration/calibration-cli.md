# Consolidated calibration CLI

Status: first Issue #60 routing layer.

`bividi-calib` is the discoverable operator entry point for the existing stereo, IMU, and camera-to-IMU evidence tools. This first slice deliberately delegates to the current `tools/*.py` implementations instead of copying calibration math into a second code path.

```text
bividi-calib
  stereo ...
  imu ...
  camera-imu ...
        ↓
current evidence/analysis implementation
        ↓
existing versioned artifacts and gates
```

## Architecture rule

CLI consolidation changes operator UX, not calibration semantics.

```text
one discoverable CLI
        !=
one opaque calibration algorithm
```

The underlying evidence concepts remain separate: target/session construction, inspection, solving, physical geometry review, repeatability, provenance/promotion, IMU noise/axis work, Kalibr export/import, solver quality, temporal review, and physical campaign planning.

Existing `tools/*.py` entry points remain compatibility surfaces during migration. Versioned artifacts remain readable independently of command naming.

## Entry point

Editable/source installation exposes:

```bash
python -m pip install -e ".[mcap]"
bividi-calib --help
bividi-calib --list
```

The router currently locates the source checkout containing `tools/`. Resolution order is:

1. explicit `--source-root PATH`;
2. `BIVIDI_SOURCE_ROOT`;
3. the package's editable-checkout location;
4. current directory and its parents.

If no checkout is found, the command fails explicitly instead of silently selecting another tool implementation. Moving the implementation modules fully under `src/bividi/` is a later #60 migration step.

## Command families

Representative stereo commands:

```bash
bividi-calib stereo target ...
bividi-calib stereo session ...
bividi-calib stereo session-recorder ...
bividi-calib stereo inspect ...
bividi-calib stereo solve ...
bividi-calib stereo validate ...
bividi-calib stereo rectify ...
bividi-calib stereo target-scale ...
bividi-calib stereo geometry-review ...
bividi-calib stereo repeatability ...
bividi-calib stereo promote ...
bividi-calib stereo report ...
bividi-calib stereo campaign ...
```

Representative IMU commands:

```bash
bividi-calib imu timing-audit ...
bividi-calib imu stationary ...
bividi-calib imu allan ...
bividi-calib imu six-position ...
bividi-calib imu gyro-rotation ...
bividi-calib imu config-consistency ...
bividi-calib imu provenance ...
bividi-calib imu export-kalibr ...
```

Representative camera-to-IMU commands:

```bash
bividi-calib camera-imu prepare ...
bividi-calib camera-imu excitation ...
bividi-calib camera-imu target-observations ...
bividi-calib camera-imu target-coverage ...
bividi-calib camera-imu ros1-bag ...
bividi-calib camera-imu ros2-mcap ...
bividi-calib camera-imu import-kalibr ...
bividi-calib camera-imu solver-quality ...
bividi-calib camera-imu temporal-review ...
bividi-calib camera-imu repeatability ...
bividi-calib camera-imu promote ...
bividi-calib camera-imu campaign ...
```

Use a leaf command's normal `--help` to see the exact arguments owned by the existing implementation:

```bash
bividi-calib stereo solve --help
bividi-calib imu allan --help
```

The delegated process exit code is preserved.

## Migration map

| Consolidated command | Compatibility implementation |
|---|---|
| `stereo target/session/session-recorder/inspect/solve/validate/rectify` | `tools/stereo_calibration_workbench.py` |
| `stereo target-scale` | `tools/review_calibration_target_scale.py` |
| `stereo geometry-review` | `tools/review_stereo_geometry.py` |
| `stereo repeatability` | `tools/compare_stereo_calibrations.py` |
| `stereo promote` | `tools/stereo_calibration_provenance.py` |
| `stereo report` | `tools/render_stereo_calibration_report.py` |
| `stereo campaign` | `tools/plan_stereo_calibration_campaign.py` |
| `imu timing-audit` | `tools/audit_imu_timing.py` |
| `imu stationary/allan/six-position/gyro-rotation/config-consistency` | corresponding `tools/analyze_imu_*.py` |
| `imu provenance` | `tools/imu_calibration_provenance.py` |
| `imu export-kalibr` | `tools/export_kalibr_imu.py` |
| `camera-imu prepare` | `tools/prepare_kalibr_dynamic_session.py` |
| `camera-imu excitation` | `tools/analyze_camera_imu_excitation.py` |
| `camera-imu target-observations/target-coverage` | Kalibr target observation/coverage tools |
| `camera-imu ros1-bag` | `tools/write_kalibr_rosbag.py` |
| `camera-imu ros2-mcap` | `tools/write_ros2_calibration_mcap.py` |
| `camera-imu import-kalibr` | `tools/import_kalibr_camera_imu.py` |
| `camera-imu solver-quality` | `tools/analyze_kalibr_solver_quality.py` |
| `camera-imu temporal-review` | `tools/review_camera_imu_time_offset.py` |
| `camera-imu repeatability` | `tools/compare_camera_imu_calibrations.py` |
| `camera-imu promote` | `tools/camera_imu_calibration_provenance.py` |
| `camera-imu campaign` | `tools/plan_camera_imu_physical_campaign.py` |

## Dependency and evidence boundaries

The router itself uses only the Python standard library. Optional dependencies remain owned by the leaf implementation that needs them. In particular, OpenCV, ROS1/Kalibr, ROS2/rosbag2, and MCAP are not pulled into unrelated calibration commands by the router.

`synthetic`, `measured`, and `imported` provenance, named policy sources, SHA-256 evidence binding, and explicit unknown/unmeasured fields remain semantics of the existing tools and artifacts. The router does not rewrite their outputs or normalize their thresholds.

## Current limitations / next #60 slices

This first slice still dispatches into source-tree scripts. The remaining consolidation work is to migrate reusable implementation modules under the installed package without forking their logic, centralize command/self-test contracts, and reduce the long per-tool GitHub Actions YAML list. Direct legacy scripts should remain thin compatibility wrappers during that migration.
