# Calibration command behavior contract

Status: frozen from the package-native stereo leaves implemented under Issue #60 and extended incrementally to package-native IMU leaves under Issues #89, #91, #93, #95, #97, and #99.

This document defines the command-level behavior that `bividi-calib` must preserve while implementations move between compatibility scripts and installed package modules. It does **not** define calibration math, artifact schemas, or product/lab thresholds.

## Exit-code vocabulary

| Exit code | Meaning |
|---:|---|
| `0` | Command completed successfully, or an evidence evaluator produced a non-failing disposition/status. |
| `2` | Usage, malformed input, schema/input-domain error, or other command-domain error. |
| `3` | A command successfully evaluated evidence and the resulting quality/disposition is explicitly `FAIL`. |

`3` is therefore not a parser/runtime error. It means the evaluation itself completed and found failing evidence. Presentation/orchestration/analysis commands that do not own a quality disposition do not manufacture an exit-3 state.

The package-native `imu timing-audit`, `imu stationary`, `imu allan`, `imu six-position`, and `imu gyro-rotation` commands are analysis leaves. They return `0` for a completed analysis and `2` for usage/input/domain failures; they do not own a PASS/FAIL evidence disposition and therefore do not use exit `3`.

`imu config-consistency` differs: it remains evidence-only when no thresholds are supplied, but explicit operator thresholds can produce PASS/FAIL. A completed `FAIL` is exit `3`; malformed input, schema/hash errors, missing required evidence, or other command-domain failures are exit `2`.

`imu provenance` is a structural/hash gate. A completed verification with one or more gate findings returns `3`; parser/input/read/domain errors return `2`; PASS returns `0`.

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
| `imu provenance` | `tools/imu_calibration_provenance.py` | `1` |

`stereo report` is presentation-only Markdown and does not create a new versioned evidence artifact merely to attach provenance.

The existing `bividi.calibration.camera_imu_timing_audit.v1`, `bividi.calibration.imu_stationary_analysis.v1`, `bividi.calibration.imu_allan_analysis.v1`, `bividi.calibration.imu_six_position_analysis.v1`, `bividi.calibration.imu_gyro_rotation_analysis.v1`, and `bividi.calibration.imu_config_consistency.v1` reports predate package migration and do not carry a top-level versioned `provenance` object. Package migration preserves those schemas rather than injecting new fields merely to make metadata uniform. The stationary and Allan reports keep explicit conversion provenance under `scale_conversion.source` when operator-supplied SI scales are used.

## Policy-source semantics

There is no universal calibration threshold hidden in the CLI.

For package-native stereo evidence producers/reviewers:

- `target-scale`, `geometry-review`, and `repeatability` may operate without numeric gates. In that case their machine-readable status remains `EVIDENCE_ONLY_NO_THRESHOLDS`.
- If explicit numeric gates are supplied, a named `policy_source` is required before the result can become `PASS` or `FAIL`.
- `promote` owns no numeric thresholds. Promotion instead requires the manifest policy source and the already-generated quality evidence to carry explicit PASS/gates/policy information, in addition to measured provenance and source-integrity requirements.
- `report` only renders existing status/policy information. It cannot promote, downgrade, or invent evidence.
- `campaign` may record a policy source as orchestration metadata, but its presence/schema audit does not perform quality/hash/policy verification.

For package-native IMU leaves:

- `imu timing-audit --gap-threshold-us` is an explicit analysis parameter used only to count long intervals. It is **not** an acceptance gate and does not create PASS/FAIL evidence.
- `imu stationary` never infers sensor full-scale from the vendor demo. Supplying `--accel-g-per-count` and/or `--gyro-dps-per-count` requires an explicit `--scale-source`; that source identifies the conversion assumption/evidence and is not a product acceptance policy.
- `imu allan` derives its analysis rate from device timestamps unless `--sample-rate-hz` is explicitly supplied. It never silently assumes 600 Hz.
- `imu allan` never chooses Allan fit windows automatically. White-noise and random-walk fits exist only when `--white-window` / `--random-walk-window` are explicitly supplied.
- `imu allan` never reduces per-axis SI fits into Kalibr scalar candidates unless `--kalibr-axis-policy` is explicit, and that option additionally requires explicit SI conversion scales plus both fit windows.
- Allan/Kalibr fit outputs remain candidate analysis evidence; they are not automatically promoted into a Bividi calibration artifact.
- `imu six-position` owns no default pass/fail thresholds for cross-axis coupling, scale spread, pair-center residuals, matrix condition, or pose residuals. Its affine gravity model and signed axis mapping are candidate/sanity evidence.
- Static gravity can constrain accelerometer axis/sign mapping, but `imu six-position` explicitly does **not** claim to identify gyroscope axis/sign mapping. Controlled rotations remain required for that evidence.
- `imu gyro-rotation` owns no default pass/fail thresholds for cross-axis coupling, +/- pair symmetry, sensitivity condition, stationary-bias stability, or integrated-angle residuals. Its signed mapping and optional sensitivity matrix remain candidate evidence.
- Absolute gyroscope sensitivity is produced only when `--expected-angle-deg` is explicitly supplied; no nominal turn angle, sample rate, vendor-demo full-scale, or gyroscope sensitivity is inferred silently.
- When an accelerometer six-position report is supplied, accelerometer and gyroscope signed mappings are compared. A disagreement is evidence to investigate; neither mapping is silently preferred or auto-corrected.
- `imu config-consistency` owns no default acceptance tolerance. Without explicit thresholds its status remains `EVIDENCE_ONLY_NO_THRESHOLDS`.
- `imu config-consistency` may become an explicit gate only when the operator supplies `--max-accel-scale-error-pct`, `--max-gyro-scale-error-pct`, `--max-odr-error-pct`, and/or `--require-gyro-scale`.
- The characterized config-consistency format does **not** carry a separate named policy-source field. Package migration preserves that boundary rather than inventing one merely for uniformity.
- Config consistency is physical-response evidence, not sensor-register readback. Filter settings remain declared provenance with `physically_verified=false` unless a separate readback/transfer-function experiment is added.
- `imu provenance` has no numerical policy. Its `basic`, `full-imu`, and `promotion` profiles verify structure, role completeness, recorded compatibility, non-placeholder provenance, measured-vs-synthetic provenance, and file integrity.
- A current `imu provenance --profile promotion` PASS does **not** mean the underlying analysis values satisfy an accuracy requirement. It does not inspect the analysis reports' numerical status and does not currently require `config_consistency`; package migration intentionally preserves that boundary.

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
| `imu gyro-rotation` | Markdown stdout + optional run-summary CSV / machine JSON / Markdown files | Controlled-turn gyro axis/sign/symmetry evidence plus optional explicit-angle sensitivity model and accel↔gyro mapping comparison; candidate only. |
| `imu config-consistency` | Markdown stdout + optional machine JSON / Markdown files | SHA-bound declared-vs-measured range/ODR response consistency; explicit thresholds may gate, but this is not register readback or final promotion. |
| `imu provenance` | machine manifest JSON + gate result | SHA-bound structural/provenance compatibility and promotability evidence; not numerical quality acceptance. |

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

For `imu gyro-rotation`, the characterized controlled-turn implementation is `bividi.calibration.imu_gyro_rotation`; `bividi.calibration.imu_gyro_rotation_command` is likewise command-only. It does not alter device-time trapezoidal integration, signed-permutation inference, optional sensitivity estimation, accelerometer↔gyroscope mapping comparison, report content, or candidate-only interpretation.

For `imu config-consistency`, the characterized response-consistency implementation is `bividi.calibration.imu_config_consistency`; `bividi.calibration.imu_config_consistency_command` separates usage/domain failures from completed evaluated FAIL. This corrects the historical source-script exit-code collision (`3` for domain error, `2` for FAIL) without changing report status, thresholds, hashes, quantizer math, or evidence interpretation.

For `imu provenance`, the characterized implementation is `bividi.calibration.imu_provenance`; `bividi.calibration.imu_provenance_command` maps input/domain failures to exit `2` while preserving exit `3` for a completed failed gate. It does not change manifest schema, required roles, verification profiles, hashes, provenance fields, or the structural-vs-quality interpretation.

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

IMU axis/scale sanity laboratories:

- `imu six-position`
- `imu gyro-rotation`

IMU configuration consistency gate:

- `imu config-consistency`

IMU structural provenance gate:

- `imu provenance`

Heavier OpenCV workbench commands and the remaining camera↔IMU leaves can adopt this contract incrementally after their existing behavior is characterized. They should not be normalized by changing measurement or evidence semantics merely to make the table look uniform.
