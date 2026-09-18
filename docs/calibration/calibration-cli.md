# Consolidated calibration CLI

Status: Issue #60 consolidation in progress.

`bividi-calib` is the discoverable operator entry point for the stereo, IMU, and camera-to-IMU evidence tools. Reusable implementations are being migrated under the installed `bividi` package incrementally; direct `tools/*.py` entry points remain compatibility surfaces while that migration proceeds.

```text
bividi-calib
  stereo ...
  imu ...
  camera-imu ...
        ↓
installed implementation module where migrated
        OR
legacy source-tree compatibility implementation
        ↓
existing versioned artifacts and gates
```

## Architecture rule

CLI consolidation changes operator UX and packaging, not calibration semantics.

```text
one discoverable CLI
        !=
one opaque calibration algorithm
```

The underlying evidence concepts remain separate: target/session construction, inspection, solving, physical geometry review, repeatability, human-readable rendering, provenance/promotion, IMU noise/axis work, Kalibr export/import, solver quality, temporal review, and physical campaign planning.

Existing `tools/*.py` entry points remain compatibility surfaces during migration. Versioned artifacts remain readable independently of command naming.

## Entry point

Editable/source installation exposes:

```bash
python -m pip install -e ".[mcap]"
bividi-calib --help
bividi-calib --list
```

Commands already migrated under `src/bividi/` execute from the installed package and do not require a source checkout. For example:

```bash
bividi-calib stereo target-scale --help
bividi-calib stereo geometry-review --help
bividi-calib stereo repeatability --help
bividi-calib stereo promote --help
bividi-calib stereo report --help
bividi-calib stereo campaign --help
```

Remaining compatibility-routed commands still locate the source checkout containing `tools/`. Their resolution order is:

1. explicit `--source-root PATH`;
2. `BIVIDI_SOURCE_ROOT`;
3. the package's editable-checkout location;
4. current directory and its parents.

If a legacy-routed command cannot find a checkout, it fails explicitly instead of silently selecting another implementation. `--source-root` is therefore transitional and only relevant to commands that have not yet moved into the installed package.

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

Use a leaf command's normal `--help` to see the exact arguments owned by the implementation:

```bash
bividi-calib stereo solve --help
bividi-calib imu allan --help
```

The leaf implementation exit code is preserved by the router.

## Migration map

| Consolidated command | Implementation / compatibility surface |
|---|---|
| `stereo target/session/session-recorder/inspect/solve/validate/rectify` | `tools/stereo_calibration_workbench.py` |
| `stereo target-scale` | installed `bividi.calibration.target_scale`; legacy wrapper `tools/review_calibration_target_scale.py` |
| `stereo geometry-review` | installed `bividi.calibration.stereo_geometry`; legacy wrapper `tools/review_stereo_geometry.py` |
| `stereo repeatability` | installed `bividi.calibration.stereo_repeatability`; legacy wrapper `tools/compare_stereo_calibrations.py` |
| `stereo promote` | installed `bividi.calibration.stereo_provenance`; legacy wrapper `tools/stereo_calibration_provenance.py` |
| `stereo report` | installed `bividi.calibration.stereo_report`; legacy wrapper `tools/render_stereo_calibration_report.py` |
| `stereo campaign` | installed `bividi.calibration.stereo_campaign`; legacy wrapper `tools/plan_stereo_calibration_campaign.py` |
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

The `target-scale`, `geometry-review`, `repeatability`, `promote`, `report`, and `campaign` migrations are package-native stereo leaves. Their legacy wrappers delegate to installed modules while preserving existing evidence schemas/semantics and historical command behavior.

The promotion gate remains a gate rather than a calibration algorithm. It preserves the existing `integrity` / `review` / `promotion` profiles and `INTEGRITY_OK` / `REVIEWABLE` / `PROMOTION_READY` dispositions; verifies SHA-256 evidence bindings and cross-links; and, for promotion, requires measured provenance, immutable acquisition evidence, verified camera mapping, explicit PASS quality evidence with gates, and named policy sources. It still owns no numeric calibration thresholds.

The campaign planner still does not invent numeric limits: it only defines workflow/dependency/evidence expectations and a presence/schema audit; quality/hash/policy verification remains owned by the evidence tools.

## Central self-test manifest

Calibration command regression is registered once in `bividi.calib_selftests` rather than duplicated as a long list of GitHub Actions steps. The manifest still invokes every focused leaf self-test; consolidation changes orchestration, not the tests themselves.

```bash
python -m bividi.calib_selftests --list
python -m bividi.calib_selftests
python -m bividi.calib_selftests --only stereo-workbench --only imu-allan
```

The runner validates that every registered compatibility source tool exists, preserves each leaf process exit code as failure evidence, runs from the repository root, reports all failures by default, and supports `--fail-fast` for local diagnosis. Ubuntu and Windows execute the same manifest in CI. The OpenCV synthetic stereo solver remains in the OpenCV job because it intentionally exercises a heavier optional dependency surface.

Characterization/qualification self-tests for #35 remain separate from this calibration manifest; they are not calibration commands and should not be pulled into #60 merely to shorten YAML.

## Dependency and evidence boundaries

The router and self-test manifest use only the Python standard library. Optional dependencies remain owned by the leaf implementation that needs them. In particular, OpenCV, ROS1/Kalibr, ROS2/rosbag2, and MCAP are not pulled into unrelated calibration commands by the router.

`synthetic`, `measured`, and `imported` provenance, named policy sources, SHA-256 evidence binding, and explicit unknown/unmeasured fields remain semantics of the existing tools and artifacts. Package migration must preserve those meanings; command routing does not normalize or reinterpret thresholds. Human-readable rendering is downstream of those machine-readable artifacts and never upgrades their evidence disposition. Campaign planning is orchestration metadata, not a substitute for generated evidence.

## Current limitations / next #60 slices

Six dependency-light stereo implementations (`stereo target-scale`, `stereo geometry-review`, `stereo repeatability`, `stereo promote`, `stereo report`, and `stereo campaign`) have moved under the installed package. The OpenCV stereo workbench commands remain intentionally heavier and still use the compatibility source-tree route.

With package-native evidence review, repeatability, promotion, rendering, and orchestration now represented, the next #60 structural step is to freeze the common command behavior contract: exit-code vocabulary, stable historical tool/version provenance, policy-source semantics, and machine-readable versus human-readable output roles. That contract should be extracted only from behavior already demonstrated by the migrated leaves; it must not change artifact schemas, gate semantics, or optional-dependency boundaries. Heavier OpenCV/ROS-facing implementations should remain isolated from unrelated commands.
