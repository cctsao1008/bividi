# Calibration command behavior contract

Status: frozen from the package-native stereo leaves implemented under Issue #60 and extended incrementally to package-native IMU leaves under Issues #89, #91, and #93.

This document defines the command-level behavior that `bividi-calib` must preserve while implementations move between compatibility scripts and installed package modules. It does **not** define calibration math, artifact schemas, or product/lab thresholds.

## Exit-code vocabulary

| Exit code | Meaning |
|---:|---|
| `0` | Command completed successfully, or an evidence evaluator produced a non-failing disposition/status. |
| `2` | Usage, malformed input, schema/input-domain error, or other command-domain error. |
| `3` | A command successfully evaluated evidence and the resulting quality/disposition is explicitly `FAIL`. |

`3` is therefore not a parser/runtime error. It means the evaluation itself completed and found failing evidence. Presentation/orchestration/analysis commands that do not own a quality disposition do not manufacture an exit-3 state.

The package-native `imu timing-audit`, `imu stationary`, `imu allan`, and `imu six-position` commands are analysis leaves. They return `0` for a completed analysis and `2` for usage/input/domain failures; they do not currently own a PASS/FAIL evidence disposition and therefore do not use exit `3`.

## Provenance identity

When a migrated command emits a versioned machine-readable artifact with a `provenance` object, package migration preserves the **historical compatibility tool name** rather than substituting the Python package-module filename.

Current frozen identities:

| Command | Historical `provenance.tool` | Version |
|---|---|---:|
| `stereo target-scale` | `review_calibration_target_scale.py` | `1` |
| `stereo geometry-review` | `review_stereo_geometry.py` | `1` |
| `stereo repeatability` | `compare_stereo_calibrations.py` | `1` |
| `stereo promote` | `stereo_calibration_provenance.py` | `1` |
| `stereo campaign` | `plan_stereo_calibration_campaign.py` | `1` |

`stereo report` is presentation-only Markdown and does not create a new versioned evidence artifact merely to attach provenance.

The existing `bividi.calibration.camera_imu_timing_audit.v1`, `bividi.calibration.imu_stationary_analysis.v1`, `bividi.calibration.imu_allan_analysis.v1`, and `bividi.calibration.imu_six_position_analysis.v1` reports predate package migration and do not carry a top-level versioned `provenance` object. Package migration preserves those schemas rather than injecting new fields merely to make metadata uniform. The stationary and Allan reports keep explicit conversion provenance under `scale_conversion.source` when operator-supplied SI scales are used.

## Policy-source semantics

There is no universal calibration threshold hidden in the CLI.

For package-native stereo evidence producers/reviewers:

- `target-scale`, `geometry-review`, and `repeatability` may operate without numeric gates. In that case their machine-readable status remains `EVIDENCE_ONLY_NO_THRESHOLDS`.
- If explicit numeric gates are supplied, a named `policy_source` is required before the result can become `PASS` or `FAIL`.
- `promote` owns no numeric thresholds. Promotion instead requires the manifest policy source and the already-generated quality evidence to carry explicit PASS/gates/policy information, in addition to measured provenance and source-integrity requirements.
- `report` only renders existing status/policy information. It cannot promote, downgrade, or invent evidence.
- `campaign` may record a policy source as orchestration metadata, but its presence/schema audit does not perform quality/hash/policy verification.

For package-native IMU analysis leaves:

- `imu timing-audit --gap-threshold-us` is an explicit analysis parameter used only to count long intervals. It is **not** an acceptance gate and does not create PASS/FAIL evidence.
- `imu stationary` never infers sensor full-scale from the vendor demo. Supplying `--accel-g-per-count` and/or `--gyro-dps-per-count` requires an explicit `--scale-source`; that source identifies the conversion assumption/evidence and is not a product acceptance policy.
- `imu allan` derives its analysis rate from device timestamps unless `--sample-rate-hz` is explicitly supplied. It never silently assumes 600 Hz.
- `imu allan` never chooses Allan fit windows automatically. White-noise and random-walk fits exist only when `--white-window` / `--random-walk-window` are explicitly supplied.
- `imu allan` never reduces per-axis SI fits into Kalibr scalar candidates unless `--kalibr-axis-policy` is explicit, and that option additionally requires explicit SI conversion scales plus both fit windows.
- Allan/Kalibr fit outputs remain candidate analysis evidence; they are not automatically promoted into a Bividi calibration artifact.
- `imu six-position` owns no default pass/fail thresholds for cross-axis coupling, scale spread, pair-center residuals, matrix condition, or pose residuals. Its affine gravity model and signed axis mapping are candidate/sanity evidence.
- Static gravity can constrain accelerometer axis/sign mapping, but `imu six-position` explicitly does **not** claim to identify gyroscope axis/sign mapping. Controlled rotations remain required for that evidence.

## Output roles

The consolidated CLI intentionally does not force all leaves into one output shape.

| Command | Output role | Authority boundary |
|---|---|---|
| `stereo target-scale` | machine evidence JSON | Physical print-scale review evidence. |
| `stereo geometry-review` | machine evidence JSON | Physical baseline comparison evidence. |
| `stereo repeatability` | machine evidence JSON | Independent-session consistency evidence. |
| `stereo promote` | machine evidence JSON | Hash-bound evidence manifest and controlled disposition. |
| `stereo report` | human-readable Markdown | Downstream presentation only; machine evidence remains authoritative. |
| `stereo campaign` | orchestration JSON + Markdown runbook; audit JSON | Workflow/dependency/presence metadata, not quality proof. |
| `imu timing-audit` | Markdown stdout + optional machine JSON / Markdown files | Timing/continuity evidence in the DECXIN device-time domain; nearest-sample deltas are not a calibrated temporal offset. |
| `imu stationary` | Markdown stdout + optional machine JSON / Markdown files | Raw-count statistics plus optional explicitly sourced SI conversion; accelerometer stationary mean includes gravity. |
| `imu allan` | Markdown stdout + optional Allan curve CSV / machine JSON / Markdown files | Streaming Allan/noise analysis. Raw-count curves are always available; SI fits and Kalibr candidates require explicit operator inputs and remain analysis evidence. |
| `imu six-position` | Markdown stdout + optional pose-summary CSV / machine JSON / Markdown files | Six-pose accelerometer gravity/axis candidate model plus static gyro mean evidence; no gyro axis/sign claim and no automatic promotion. |

Machine-readable evidence and gate artifacts remain authoritative where a gate exists. Human-readable output is a view over the analysis/evidence, and orchestration output describes what should exist rather than proving that the evidence is acceptable.

## Package/compatibility rule

For a migrated command:

```text
bividi-calib
    -> installed bividi.calibration.* module

legacy tools/*.py
    -> thin compatibility wrapper
    -> same installed implementation
```

Both surfaces must preserve the same artifact/report schema, evidence/interpretation semantics, provenance identity where applicable, and command-level exit-code behavior.

For `imu allan`, the characterized estimator/report implementation is `bividi.calibration.imu_allan`; `bividi.calibration.imu_allan_command` is a thin package command adapter that only normalizes the historical domain-error exit `3` to the frozen command-contract exit `2`. It does not alter Allan math, fit semantics, or report content.

For `imu six-position`, the characterized gravity/axis implementation is `bividi.calibration.imu_six_position`; `bividi.calibration.imu_six_position_command` is likewise a command-only adapter. It does not alter the six-pose convention, affine model, signed-permutation inference, report content, or candidate-only interpretation.

## Frozen package-native set

Stereo:

- `stereo target-scale`
- `stereo geometry-review`
- `stereo repeatability`
- `stereo promote`
- `stereo report`
- `stereo campaign`

IMU foundation:

- `imu timing-audit`
- `imu stationary`

IMU noise laboratory:

- `imu allan`

IMU axis/scale sanity laboratory:

- `imu six-position`

Heavier OpenCV workbench commands and the remaining IMU/camera↔IMU leaves can adopt this contract incrementally after their existing behavior is characterized. They should not be normalized by changing measurement or evidence semantics merely to make the table look uniform.
