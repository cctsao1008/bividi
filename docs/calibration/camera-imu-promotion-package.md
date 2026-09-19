# Package-native camera↔IMU evidence promotion gate

Owner: Issue #117 under #47  
Upstream: dynamic-session staging (#103), excitation (#105), target evidence (#107), candidate import (#109), solver quality (#111), temporal review (#113), repeatability (#115)  
Status: final evidence-manifest/policy boundary; no calibration solver or threshold invention is added here

## Command surface

The consolidated promotion command is package-native:

```bash
bividi-calib camera-imu promote --self-test
```

It routes through:

```text
bividi.calibration.camera_imu_provenance_command
        ↓
bividi.calibration.camera_imu_calibration_provenance
        ↓
bividi.calibration.artifact_validator
```

The historical source-tree entry point remains a thin compatibility wrapper:

```text
tools/camera_imu_calibration_provenance.py
```

No source checkout is required by the installed command. The historical sibling import of `tools/validate_calibration_artifact.py` is replaced with package-native artifact validation.

The implementation module deliberately keeps the basename `camera_imu_calibration_provenance.py` because versioned manifest/verification provenance records `Path(__file__).name`.

## Manifest boundary

The gate creates and verifies:

```text
bividi.calibration.camera_imu_evidence_manifest.v1
```

and verification reports use:

```text
bividi.calibration.camera_imu_evidence_verification.v1
```

Manifest provenance remains:

```text
tool = camera_imu_calibration_provenance.py
tool_version = 1
```

The promotion layer does not modify any camera↔IMU transform, time offset, IMU parameter, detector output, residual statistic, or repeatability value.

## Exact evidence role set

A manifest freezes this complete role set:

```text
dynamic_session
excitation
target_observations
target_coverage
solver_quality
import_manifest
candidate
time_review
repeatability
```

with the existing schemas:

```text
dynamic_session      bividi.calibration.kalibr_dynamic_session.v1
excitation           bividi.calibration.camera_imu_excitation.v1
target_observations  bividi.calibration.kalibr_target_observations.v1
target_coverage      bividi.calibration.kalibr_target_coverage.v1
solver_quality       bividi.calibration.kalibr_solver_quality.v1
import_manifest      bividi.calibration.kalibr_camera_imu_import.v1
candidate            bividi.calibration.camera_imu.v1
time_review          bividi.calibration.camera_imu_time_review.v1
repeatability        bividi.calibration.camera_imu_repeatability.v1
```

`target_observations` is intentionally discovered through the SHA-bound `target_coverage.source` reference rather than supplied independently on the create CLI. This preserves the existing chain of custody.

## Supporting files

Manifest creation also discovers and freezes supporting solver files:

```text
kalibr_result_yaml
kalibr_results_imucam_txt
```

and, when present:

```text
import_solver_report
```

Each evidence/supporting-file record preserves a manifest-relative path when possible, SHA-256, byte size, and schema where applicable. Verification re-hashes every bound file.

## Cross-link verification

Before any policy disposition is considered, the gate re-verifies the evidence graph. The preserved checks include:

- every dynamic-session source reference still hashes correctly;
- the candidate is a valid `bividi.calibration.camera_imu.v1` artifact;
- candidate provenance binds exactly to the supplied dynamic session and Kalibr backend/revision;
- transform source/destination frames still match the candidate IMU/camera frames;
- specimen serial, camera topology, frame/axis declarations, and exact timestamp semantic remain compatible;
- the frozen time definition remains `t_imu_s = t_camera_reference_s + offset_s`;
- excitation, target observations, target coverage, solver quality, import manifest, and time review all link to the same session/result/candidate identities;
- the reviewed time-offset value equals the candidate time offset;
- repeatability references at least two distinct validated candidate artifacts, includes the candidate being considered exactly once, and uses the same camera/device/frame/time compatibility contract;
- repeatability backend revision identities remain consistent with the staged/candidate Kalibr revision.

A broken hash, missing role, schema mismatch, cross-link mismatch, duplicate evidence identity, or incompatible candidate is a command-domain failure. It is not a completed quality-policy FAIL.

## Three profile semantics

The profile names are intentionally not synonyms.

### `integrity`

`integrity` proves only:

```text
hashes + schemas + file identities + nested cross-links + compatibility
```

Component quality status does not gate this profile. Non-PASS component reports are surfaced as warnings.

Therefore:

```text
INTEGRITY_VERIFIED != calibration quality PASS
```

### `review`

`review` requires the integrity checks and blocks if any quality report is `FAIL`.

A component that remains:

```text
EVIDENCE_ONLY_NO_THRESHOLDS
```

is still allowed for review and produces a warning. This supports engineering review before final acceptance policy has been applied.

Therefore:

```text
REVIEW_READY != PROMOTION_READY
```

### `promotion`

`promotion` requires all integrity/review conditions plus the existing explicit policy conditions:

```text
policy_source is a non-placeholder named acceptance basis
all quality roles are PASS
all PASS quality roles carry explicit gate evidence
target-observation Kalibr revision is marked reviewed
solver-quality parser/backend revision mismatch was not allowed
target-observation revision equals the reviewed pinned Kalibr revision
```

The pinned revision remains:

```text
1f60227442d25e36365ef5f72cd80b9666d73467
```

Only then can disposition become:

```text
PROMOTION_READY
```

## Quality roles and threshold ownership

The quality roles are exactly:

```text
excitation
target_coverage
solver_quality
time_review
repeatability
```

The promotion layer reads their existing PASS/FAIL/evidence-only status and verifies that a PASS used for promotion was backed by explicit gates.

It does **not** assign numeric limits to those gates. Numeric acceptance values remain owned by the individual evidence leaves and the named product/lab policy.

In particular:

```text
promotion gate
    != universal threshold registry
    != hidden vendor-threshold adapter
    != auto-tuning layer
```

A non-placeholder `policy_source` is mandatory for promotion so the final acceptance basis is auditable rather than implied.

## Placeholder policy sources

The existing placeholder vocabulary remains rejected for promotion:

```text
""
unknown
n/a
na
tbd
unset
none
?
```

Manifest creation may still record an unset/placeholder policy source for integrity/review workflows; it simply cannot satisfy the promotion profile.

## Exit-code contract

The historical tool used process code `3` for domain/hash/write failures and `4` for a completed policy FAIL. The package command adapter normalizes the process surface to the frozen calibration vocabulary:

```text
0  successful manifest creation or non-failing verification
2  usage/input/schema/hash/cross-link/domain/read/write failure
3  completed verification/profile FAIL
```

This mapping does not alter manifest content, assessment status, disposition, failures, warnings, or evidence semantics.

## Interpretation boundary

A promotion-ready manifest means that the intended evidence graph is intact and each required evidence class passed explicit, recorded operator/product gates under a named policy source.

It does not independently prove physical truth. Specifically:

```text
PROMOTION_READY
    != mathematical proof of observability
    != independently measured ground-truth extrinsics
    != downstream VIO accuracy certification
    != replacement for physical campaign execution
```

The gate intentionally keeps independent evidence classes separate rather than allowing one good metric to stand in for another.

## CI boundary

Normal Ubuntu and Windows CI exercise both:

```bash
bividi-calib camera-imu promote --self-test
python tools/camera_imu_calibration_provenance.py --self-test
```

without Kalibr, ROS, OpenCV, or numpy. The existing synthetic self-test builds a complete evidence graph, proves `INTEGRITY_VERIFIED`, proves `REVIEW_READY` with evidence-only warnings, proves promotion is blocked before explicit PASS gates, proves hash tampering is rejected, rebuilds explicit passing evidence, and finally proves `PROMOTION_READY`.

Package regression additionally verifies installed routing outside a checkout, package-native artifact validation, the exact role sets, historical provenance identity, policy-source semantics, process-exit normalization, and frozen command-contract metadata.
