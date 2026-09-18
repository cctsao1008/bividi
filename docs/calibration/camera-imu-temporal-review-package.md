# Package-native camera↔IMU temporal evidence review

Owner: Issue #113 under #47  
Upstream: package-native Kalibr candidate import (#109) and IMU timing foundation (#89)  
Adjacent evidence: solver quality (#111), target evidence (#107), dynamic excitation (#105)  
Status: package migration only; nearest-sample geometry remains sanity evidence, not an independent time-offset estimator

## Command surface

The consolidated temporal-review command is package-native:

```bash
bividi-calib camera-imu temporal-review --self-test
```

It routes through:

```text
bividi.calibration.camera_imu_temporal_review_command
        ↓
bividi.calibration.camera_imu_temporal_review
        ├─> bividi.calibration.imu_timing
        └─> bividi.calibration.artifact_validator
```

The historical source-tree entry point remains a thin compatibility wrapper:

```text
tools/review_camera_imu_time_offset.py
```

No source checkout is required by the installed command. The previous sibling-tool dependency on `tools/validate_calibration_artifact.py` is removed, and the timing parser/statistics are imported directly from the already package-native IMU timing foundation.

## Evidence boundary

The reviewer consumes:

```text
prepared bividi.calibration.kalibr_dynamic_session.v1 session
+
imported bividi.calibration.camera_imu.v1 candidate
+
SHA-bound raw DECXIN camera/IMU timing trace
```

It produces:

```text
bividi.calibration.camera_imu_time_review.v1
```

as JSON plus a human-readable Markdown rendering when an output prefix is supplied. Without an output prefix, both views are emitted to stdout.

The report is temporal **review evidence**. It does not solve a new camera↔IMU offset.

## Exact time semantics

The imported calibration artifact must use the frozen definition:

```text
t_imu_s = t_camera_reference_s + offset_s
```

The reviewer verifies that the artifact's camera timestamp semantic exactly matches the prepared session. Supported staged semantics remain:

```text
exposure_start
exposure_midpoint
exposure_end
```

The Kalibr offset is converted from seconds to microseconds and applied to that exact reference. No sign flip, zero-offset assumption, or alternate frame-timestamp interpretation is inferred.

The timing domain remains:

```text
DECXIN extended device microseconds
```

This is the same device-time domain used by the package-native IMU timing audit. Host arrival time is not substituted.

## Provenance and integrity checks

Before timing evidence is evaluated, the reviewer preserves these checks:

- the supplied session must be `bividi.calibration.kalibr_dynamic_session.v1`;
- the supplied candidate must be `bividi.calibration.camera_imu.v1`;
- the candidate is structurally validated with `bividi.calibration.artifact_validator`;
- `provenance.source_hash` in the candidate must equal the SHA-256 of the supplied dynamic-session manifest;
- the raw timing trace path and SHA-256 stored in `sources.raw_imu_csv` must still match;
- the session and candidate camera timestamp semantics must be identical;
- the time-offset value must be finite.

A failure of any of these checks is a command-domain error. It is not an evaluated temporal FAIL.

## Preserved measurements

The reviewer preserves the characterized statistics from the raw timing trace:

```text
camera frame count
valid/invalid IMU sample count
positive IMU interval distribution
exposure duration distribution
nearest IMU sample before applying the Kalibr shift
nearest IMU sample after applying the Kalibr shift
```

Nearest-sample distributions preserve signed and absolute forms. Camera exposure midpoint remains computed as:

```text
0.5 * (exposure_start_us + exposure_end_us)
```

The shifted reference is:

```text
camera_reference_us + kalibr_offset_us
```

and the nearest-sample delta remains:

```text
nearest_imu_us - shifted_camera_reference_us
```

## Nearest-sample interpretation guardrail

The nearest IMU sample is discrete sampling geometry. Therefore:

```text
small nearest-sample residual
    != independently estimated physical camera↔IMU offset
```

A small residual can help catch gross sign, unit, or timestamp-semantic mistakes, but sample-period aliases can make more than one shift appear locally plausible. The reviewer deliberately does not optimize an offset from nearest-sample distances.

Likewise:

```text
vendor synchronization claim
    != default Bividi temporal gate
```

No vendor `<30 us` claim, nominal sample period, or measured cadence is silently converted into an acceptance threshold.

## Explicit gates

With no gates supplied, status remains:

```text
EVIDENCE_ONLY_NO_THRESHOLDS
```

The existing optional gates remain:

```text
--max-abs-shift-us
--max-shifted-nearest-p95-us
```

If one or both gates are supplied and all pass, status is `PASS`. If an explicitly supplied gate fails, status is `FAIL`.

These gates remain operator policy. Package migration does not assign default values.

## Exit-code contract

The installed command follows the frozen calibration vocabulary:

```text
0  evidence-only or explicit-gate PASS
2  usage/input/schema/hash/validation/domain/read/write failure
3  completed explicit-gate FAIL
```

Exit `3` therefore means the temporal review completed and an operator-supplied gate failed. It is not used for a malformed artifact, timestamp-semantic mismatch, source-hash mismatch, invalid raw trace, or write failure.

The command adapter provides this process-level normalization without changing the report status or statistics.

## Relationship to other camera↔IMU evidence

Temporal review is independent from the adjacent evidence classes:

```text
dynamic excitation
AprilGrid target coverage
Kalibr solver residual quality
candidate artifact structural validity
independent-session repeatability
promotion/provenance completeness
```

In particular:

```text
small solver residuals
    != correct time offset

small shifted nearest-sample residuals
    != correct spatial transform

valid candidate artifact
    != calibration acceptance
```

A promotion or downstream VIO accuracy claim must therefore use the intended combination of evidence rather than upgrading any one report into a stronger claim.

## CI boundary

Normal Ubuntu and Windows CI run both:

```bash
bividi-calib camera-imu temporal-review --self-test
python tools/review_camera_imu_time_offset.py --self-test
```

without Kalibr, ROS, OpenCV, or numpy. The synthetic fixture preserves the characterized evidence-only path, a `250 us` imported shift, and an explicit max-shift FAIL path. Package-level regression also verifies installed routing outside a source checkout, package-native timing/validator imports, source-hash and timestamp-semantic domain failures, write-failure normalization, and command-contract metadata.
