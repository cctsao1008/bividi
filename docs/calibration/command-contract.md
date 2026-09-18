# Calibration command behavior contract

Status: frozen from the package-native stereo leaves implemented under Issue #60.

This document defines the command-level behavior that `bividi-calib` must preserve while implementations move between compatibility scripts and installed package modules. It does **not** define calibration math, artifact schemas, or product/lab thresholds.

## Exit-code vocabulary

| Exit code | Meaning |
|---:|---|
| `0` | Command completed successfully, or an evidence evaluator produced a non-failing disposition/status. |
| `2` | Usage, malformed input, schema/input-domain error, or other command-domain error. |
| `3` | A command successfully evaluated evidence and the resulting quality/disposition is explicitly `FAIL`. |

`3` is therefore not a parser/runtime error. It means the evaluation itself completed and found failing evidence. Presentation/orchestration commands that do not own a quality disposition do not manufacture an exit-3 state.

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

## Policy-source semantics

There is no universal calibration threshold hidden in the CLI.

For package-native stereo evidence producers/reviewers:

- `target-scale`, `geometry-review`, and `repeatability` may operate without numeric gates. In that case their machine-readable status remains `EVIDENCE_ONLY_NO_THRESHOLDS`.
- If explicit numeric gates are supplied, a named `policy_source` is required before the result can become `PASS` or `FAIL`.
- `promote` owns no numeric thresholds. Promotion instead requires the manifest policy source and the already-generated quality evidence to carry explicit PASS/gates/policy information, in addition to measured provenance and source-integrity requirements.
- `report` only renders existing status/policy information. It cannot promote, downgrade, or invent evidence.
- `campaign` may record a policy source as orchestration metadata, but its presence/schema audit does not perform quality/hash/policy verification.

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

Machine-readable evidence and gate artifacts remain authoritative. Human-readable output is a view over that evidence, and orchestration output describes what should exist rather than proving that the evidence is acceptable.

## Package/compatibility rule

For a migrated command:

```text
bividi-calib
    -> installed bividi.calibration.* module

legacy tools/*.py
    -> thin compatibility wrapper
    -> same installed module
```

Both surfaces must preserve the same artifact schema, status/disposition semantics, provenance identity where applicable, and exit-code behavior.

## Frozen package-native stereo set

The contract currently covers:

- `stereo target-scale`
- `stereo geometry-review`
- `stereo repeatability`
- `stereo promote`
- `stereo report`
- `stereo campaign`

Heavier OpenCV workbench commands and camera/IMU/IMU leaves can adopt this contract incrementally after their existing behavior is characterized. They should not be normalized by changing semantics merely to make the table look uniform.
