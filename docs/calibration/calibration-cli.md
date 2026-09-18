# Consolidated calibration CLI

Status: `bividi-calib` consolidation completed in Issue #60; package-native migration continues incrementally under focused follow-up issues such as #89, #91, #93, #95, #97, and #99.

`bividi-calib` is the discoverable operator entry point for the stereo, IMU, and camera-to-IMU evidence tools. Reusable implementations are migrated under the installed `bividi` package incrementally; direct `tools/*.py` entry points remain compatibility surfaces while that migration proceeds.

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

The underlying evidence concepts remain separate: target/session construction, inspection, solving, physical geometry review, repeatability, human-readable rendering, provenance/promotion, IMU noise/axis/configuration work, Kalibr export/import, solver quality, temporal review, and physical campaign planning.

Existing `tools/*.py` entry points remain compatibility surfaces during migration. Versioned artifacts remain readable independently of command naming.

The frozen package-native command behavior is documented in `docs/calibration/command-contract.md` and represented by `bividi.calibration.contract`. That contract captures exit-code vocabulary, historical provenance identity where artifacts already carry it, policy/parameter roles, and output authority boundaries without centralizing numerical calibration policy.

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
bividi-calib imu timing-audit --help
bividi-calib imu stationary --help
bividi-calib imu allan --help
bividi-calib imu six-position --help
bividi-calib imu gyro-rotation --help
bividi-calib imu config-consistency --help
bividi-calib imu provenance --help
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
bividi-calib imu provenance --help
```

Package-native leaves conform to the frozen command vocabulary: `0` success/non-failing evaluation, `2` usage/input/domain error, and `3` when a completed evidence/gate evaluation explicitly fails.

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
| `imu timing-audit` | installed `bividi.calibration.imu_timing`; legacy wrapper `tools/audit_imu_timing.py` |
| `imu stationary` | installed `bividi.calibration.imu_stationary`; legacy wrapper `tools/analyze_imu_stationary.py` |
| `imu allan` | installed estimator/report `bividi.calibration.imu_allan` via command adapter `bividi.calibration.imu_allan_command`; legacy wrapper `tools/analyze_imu_allan.py` |
| `imu six-position` | installed gravity/axis analyzer `bividi.calibration.imu_six_position` via command adapter `bividi.calibration.imu_six_position_command`; legacy wrapper `tools/analyze_imu_six_position.py` |
| `imu gyro-rotation` | installed controlled-turn analyzer `bividi.calibration.imu_gyro_rotation` via command adapter `bividi.calibration.imu_gyro_rotation_command`; legacy wrapper `tools/analyze_imu_gyro_rotation.py` |
| `imu config-consistency` | installed response-consistency analyzer `bividi.calibration.imu_config_consistency` via command adapter `bividi.calibration.imu_config_consistency_command`; legacy wrapper `tools/analyze_imu_config_consistency.py` |
| `imu provenance` | installed manifest/provenance gate `bividi.calibration.imu_provenance` via command adapter `bividi.calibration.imu_provenance_command`; legacy wrapper `tools/imu_calibration_provenance.py` |
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

The six dependency-light stereo leaves and the dependency-free IMU timing/stationary, Allan/noise, six-position, controlled gyro-rotation, configuration-consistency, and provenance leaves are package-native. Their legacy wrappers delegate to installed modules while preserving report/artifact schemas and evidence interpretation boundaries.

For the IMU foundation specifically, `imu stationary` imports timing analysis through `bividi.calibration.imu_timing`; it no longer depends on a sibling `tools/audit_imu_timing.py` implementation. The timing audit still stays entirely inside the DECXIN device-time domain, and nearest-sample deltas remain timing evidence rather than a calibrated camera↔IMU offset. Stationary analysis still reports raw counts first and performs SI conversion only when the operator supplies explicit per-count scale plus `--scale-source`.

For `imu allan`, the characterized implementation remains a streaming dyadic non-overlapping Allan estimator with O(log N) state. The default analysis rate comes from measured device timestamps, not a hard-coded 600 Hz assumption. SI conversion requires explicit scale provenance, fit windows are never chosen automatically, and Kalibr-style scalar candidates require an explicit axis-reduction policy. Candidate parameters are analysis evidence only and are not automatically promoted into the IMU calibration artifact. See `docs/calibration/imu-allan.md`.

For `imu six-position`, the characterized six stationary poses estimate an evidence-only affine accelerometer gravity model and best signed raw-axis permutation. Static gravity can establish accelerometer directional evidence, but it cannot establish gyroscope axis/sign mapping; controlled rotation remains a separate evidence requirement. No default thresholds are invented for cross-axis coupling, scale spread, matrix condition, pair-center disagreement, or pose residuals. See `docs/calibration/imu-six-position.md`.

For `imu gyro-rotation`, the characterized analyzer subtracts a measured stationary raw-count bias and trapezoidally integrates each controlled turn over extended device time. The six +/- target-frame right-hand-rule turns establish gyro signed-axis/symmetry/coupling evidence. Absolute 3x3 gyro sensitivity is produced only when the operator explicitly provides a common commanded angle; no nominal angle, sample rate, vendor full-scale, or sensitivity is inferred. An optional six-position report provides accelerometer↔gyro signed-mapping comparison, and disagreement is reported rather than auto-corrected. See `docs/calibration/imu-gyro-rotation.md`.

For `imu config-consistency`, the analyzer verifies SHA-256-bound six-position/gyro/stationary/Allan evidence against the session manifest and compares measured physical response with declared range/ODR. It is not register readback: filter settings remain declared configuration provenance unless separately verified. No tolerance is invented by default. Explicit operator thresholds may produce PASS/FAIL/INCOMPLETE; a completed FAIL is exit `3`, while schema/hash/input failures are exit `2`. See `docs/calibration/imu-config-consistency.md`.

For `imu provenance`, the characterized manifest gate binds recorder summaries, raw traces, analysis JSON, observed device/mode metadata, and operator-declared IMU configuration. The `basic`, `full-imu`, and `promotion` profiles are structural/provenance gates. `promotion` additionally requires measured provenance and non-placeholder specimen/configuration fields, but it does not currently inspect analysis numerical statuses or require the #97 config-consistency report. A promotion PASS is therefore evidence of a complete, compatible, immutable measured bundle—not product-accuracy approval. See `docs/calibration/imu-calibration-provenance-gate.md`.

The stereo promotion gate remains a gate rather than a calibration algorithm. It preserves the existing `integrity` / `review` / `promotion` profiles and `INTEGRITY_OK` / `REVIEWABLE` / `PROMOTION_READY` dispositions; verifies SHA-256 evidence bindings and cross-links; and, for promotion, requires measured provenance, immutable acquisition evidence, verified camera mapping, explicit PASS quality evidence with gates, and named policy sources. It still owns no numeric calibration thresholds.

The stereo campaign planner still does not invent numeric limits: it only defines workflow/dependency/evidence expectations and a presence/schema audit; quality/hash/policy verification remains owned by the evidence tools.

## Central self-test manifest

Calibration command regression is registered once in `bividi.calib_selftests` rather than duplicated as a long list of GitHub Actions steps. The manifest still invokes every focused leaf self-test through the compatibility surfaces; consolidation changes orchestration, not the tests themselves.

```bash
python -m bividi.calib_selftests --list
python -m bividi.calib_selftests
python -m bividi.calib_selftests --only imu-timing --only imu-stationary --only imu-allan --only imu-six-position --only imu-gyro-rotation --only imu-config-consistency --only imu-provenance
```

The runner validates that every registered compatibility source tool exists, preserves each leaf process exit code as failure evidence, runs from the repository root, reports all failures by default, and supports `--fail-fast` for local diagnosis. Ubuntu and Windows execute the same manifest in CI. Package-level unit tests additionally execute migrated modules outside a source checkout.

Characterization/qualification self-tests for #35 remain separate from this calibration manifest; they are not calibration commands and should not be pulled into the calibration migration merely to shorten YAML.

## Dependency and evidence boundaries

The router, contract metadata, package-native IMU timing/stationary/Allan/six-position/gyro-rotation/config-consistency/provenance leaves use only the Python standard library. Optional dependencies remain owned by the leaf implementation that needs them. In particular, OpenCV, ROS1/Kalibr, ROS2/rosbag2, and MCAP are not pulled into unrelated calibration commands by the router.

`synthetic`, `measured`, and `imported` provenance, named policy sources where already defined, SHA-256 evidence binding, explicit scale/angle sources, explicit operator gates, and explicit unknown/unmeasured fields remain semantics of the existing tools and artifacts. Package migration must preserve those meanings; command routing does not normalize or reinterpret thresholds. Human-readable rendering is downstream of machine-readable evidence/analysis and never upgrades an evidence disposition.

## Current migration state / next slices

Package-native dependency-light stereo commands:

```text
target-scale
geometry-review
repeatability
promote
report
campaign
```

Package-native dependency-free IMU commands:

```text
timing-audit
stationary
allan
six-position
gyro-rotation
config-consistency
provenance
```

The remaining IMU-facing `export-kalibr` adapter and the camera↔IMU/Kalibr-facing leaves should remain isolated until their own packaging and optional-dependency boundaries are explicitly characterized. Package migration must not be used to smuggle semantic changes into promotion criteria; any decision to make config-consistency or numerical analysis status mandatory for IMU promotion should be reviewed separately.
