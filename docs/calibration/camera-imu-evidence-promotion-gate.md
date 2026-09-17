# Camera↔IMU Calibration Evidence Promotion Gate

Owner: Issue #47  
Input: one candidate `bividi.calibration.camera_imu.v1` plus its independent evidence reports  
Output: `bividi.calibration.camera_imu_evidence_manifest.v1` + verification report  
Status: hardware-independent tooling implemented; measured AR0234 campaign still pending

## Purpose

A numerically valid Kalibr result is not enough to release a camera↔IMU calibration to #46 VIO. Bividi keeps the independent evidence classes separate until a final provenance gate verifies that they all refer to the same session, candidate, backend revision, frame convention, and timestamp semantic.

```text
prepared dynamic session
        |
        +-- motion excitation evidence
        +-- exact Kalibr AprilGrid observations
        +-- target/image-plane coverage evidence
        +-- Kalibr solver residual evidence
        +-- imported T_cam_imu + time offset candidate
        +-- device-time temporal review
        +-- independent-session repeatability
        |
        v
camera_imu_calibration_provenance.py
        |
        +-- integrity profile
        +-- review profile
        +-- promotion profile
        |
        v
hash-bound evidence manifest
```

The gate **does not solve calibration again** and does not rewrite any threshold. It verifies identity, hashes, schemas, cross-links, and the policy disposition already established by the component reports.

## Three profiles

### `integrity`

Checks file identity, schemas, nested source hashes, candidate/session compatibility, Kalibr revision, camera mapping, frame direction, timestamp semantics, imported result identity, and repeatability membership.

Quality reports are not required to pass under this profile. The result is `INTEGRITY_VERIFIED` when the evidence graph is internally consistent.

### `review`

Adds the requirement that no quality report is `FAIL`. Reports that remain `EVIDENCE_ONLY_NO_THRESHOLDS` are allowed but surfaced as warnings.

This profile is useful before a product/lab acceptance policy has been frozen. A successful result is `REVIEW_READY`, not a production release claim.

### `promotion`

Requires all of the following:

- every quality report is explicit `PASS`;
- each `PASS` is backed by explicit gates in that report;
- `policy_source` is non-placeholder and names the lab/product acceptance basis;
- target observations use the reviewed pinned Kalibr detector revision;
- solver-quality parsing did not allow a backend/parser revision mismatch;
- all hashes, session/candidate links, frame conventions, timestamp semantics, and repeatability membership remain consistent.

A successful result is `PROMOTION_READY`.

`PROMOTION_READY` means the evidence bundle satisfies the recorded acceptance policy. It is **not** an independent proof of physical truth and does not replace #8 stereo calibration or downstream #46 VIO validation.

## Bound evidence roles

The manifest freezes these JSON artifacts by path, SHA-256, byte size, and schema:

```text
dynamic_session
excitation               (camera_imu_excitation)
target_observations      (exact pinned-Kalibr detections)
target_coverage
solver_quality
import_manifest
candidate                (camera_imu.v1)
time_review
repeatability
```

The manifest also freezes the external Kalibr result YAML and `*-results-imucam.txt`. If an import-side solver report is present, that file is bound too.

## Cross-link rules

Verification rejects, among other cases:

```text
candidate source_hash != dynamic-session SHA-256
candidate backend/revision != dynamic session
candidate camera timestamp semantic != dynamic session
candidate transform frames != declared camera/IMU frames
excitation report references another session
target coverage references another observation manifest
solver report references another session or residual text
import manifest references another result YAML or candidate
time review references another candidate or offset
repeatability report does not contain the candidate exactly once
repeatability artifacts differ in physical/frame/timing contract
bound evidence file changed after manifest creation
```

This is deliberately stronger than checking that filenames happen to match.

## Create a manifest

```bash
python tools/camera_imu_calibration_provenance.py create \
  --dynamic-session run01/session.json \
  --excitation run01/excitation.json \
  --target-coverage run01/target-coverage.json \
  --solver-quality run01/solver-quality.json \
  --import-manifest run01/camimu.json.import.json \
  --candidate run01/camimu.json \
  --time-review run01/time-review.json \
  --repeatability campaign/repeatability.json \
  --policy-source "AR0234 camera-IMU calibration acceptance policy rev A" \
  --output campaign/camimu-evidence.json
```

`target_observations` is discovered from the hash-bound `target_coverage.source` reference so the operator cannot accidentally supply a different observations file independently.

Creation validates the complete cross-link graph before writing the manifest.

## Verify

Integrity only:

```bash
python tools/camera_imu_calibration_provenance.py verify \
  campaign/camimu-evidence.json \
  --profile integrity
```

Review readiness:

```bash
python tools/camera_imu_calibration_provenance.py verify \
  campaign/camimu-evidence.json \
  --profile review \
  --output-prefix campaign/camimu-review
```

Promotion readiness:

```bash
python tools/camera_imu_calibration_provenance.py verify \
  campaign/camimu-evidence.json \
  --profile promotion \
  --output-prefix campaign/camimu-promotion
```

The optional output prefix writes:

```text
<prefix>.verification.json
<prefix>.verification.md
```

A blocked profile returns a non-zero exit status.

## Threshold ownership

The final gate intentionally has no switches such as `--max-reprojection-px` or `--max-time-offset-us`.

Those requirements belong to the evidence-producing tools:

```text
motion/coverage limits       -> analyze_camera_imu_excitation.py
target coverage limits       -> analyze_kalibr_target_coverage.py
solver residual limits       -> analyze_kalibr_solver_quality.py
temporal sanity limits       -> review_camera_imu_time_offset.py
repeatability limits         -> compare_camera_imu_calibrations.py
```

The promotion gate checks that explicit gates existed and passed. This avoids creating two competing sources of truth for acceptance limits.

## Physical evidence boundary

Normal CI uses synthetic fixtures to prove the manifest and cross-link mechanics on Windows and Linux. It cannot prove:

- AR0234/IMU physical axis mapping;
- the true camera↔IMU extrinsic;
- the true time offset;
- AprilGrid quality in the real optics;
- repeatability on a physical specimen;
- downstream VIO accuracy.

Those remain live-hardware work under #47 after #35 capture qualification and #8 camera geometry are available.

## Promotion to #46

The intended release chain is:

```text
#35 qualified acquisition
        +
#8 measured stereo calibration
        +
#47 camera↔IMU PROMOTION_READY evidence manifest
        v
frozen calibration revision
        v
#46 VIO measured validation
```

A VIO implementation may consume the promoted numerical artifact; it should not consume Kalibr-native files or infer missing calibration assumptions itself.
