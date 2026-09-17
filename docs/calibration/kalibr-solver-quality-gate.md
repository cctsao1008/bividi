# Kalibr IMU-Camera Solver Quality Gate

Owner: Issue #47  
Upstream: `bividi.calibration.kalibr_dynamic_session.v1` + external ETH Zurich Kalibr solve  
Input: Kalibr `*-results-imucam.txt`  
Output: `bividi.calibration.kalibr_solver_quality.v1` JSON + Markdown evidence  
Status: parser/gate implemented; physical AR0234 solver evidence pending

## Purpose

A completed optimizer run is not enough evidence to promote camera↔IMU calibration. Bividi therefore parses the residual statistics that Kalibr itself writes into `*-results-imucam.txt` and keeps them as a separate quality artifact.

```text
provenance-bound dynamic session
            +
Kalibr *-results-imucam.txt
            ↓
analyze_kalibr_solver_quality.py
            ↓
normalized residuals
physical residuals
structural findings
optional explicit gates
            ↓
solver-quality JSON + Markdown
```

This quality report complements, but does not replace:

```text
T_cam_imu / timeshift import
camera↔IMU temporal review
multi-session repeatability
motion/target observability review
downstream VIO validation
```

## Authoritative parser contract

The parser contract is pinned to Kalibr revision:

```text
1f60227442d25e36365ef5f72cd80b9666d73467
```

and specifically to:

```text
aslam_offline_calibration/kalibr/python/
kalibr_imu_camera_calibration/IccUtil.py::printErrorStatistics
```

At that revision Kalibr prints two sections.

### Normalized Residuals

For each camera it computes the norm of the normalized reprojection residual and prints:

```text
mean
median
std
```

For each IMU it does the same for gyroscope and accelerometer residuals.

### Residuals

Kalibr also prints physical residual norms:

```text
Reprojection error     [px]
Gyroscope error        [rad/s]
Accelerometer error    [m/s^2]
```

again with:

```text
mean
median
std
```

The tool preserves normalized and physical values separately. It does not convert one into the other.

Because Kalibr uses NumPy's population standard deviation, Bividi also reports the derived residual-norm RMS:

```text
RMS = sqrt(mean^2 + std^2)
```

This is a derived statistic from Kalibr's printed mean/std, not an independently sampled residual stream.

## Run

```bash
python tools/analyze_kalibr_solver_quality.py \
  ar0234_kalibr_001/session.json \
  kalibr_dynamic-results-imucam.txt \
  --output-prefix ar0234_kalibr_001/solver-quality
```

Outputs:

```text
solver-quality.json
solver-quality.md
```

The report hashes both the dynamic-session manifest and the exact Kalibr text report.

## Structural checks

The Bividi dynamic-session manifest defines the expected stereo mapping:

```text
camera_a -> cam0
camera_b -> cam1
```

The solver-quality tool therefore requires residual evidence for:

```text
cam0 reprojection
cam1 reprojection
imu0 gyroscope
imu0 accelerometer
```

in both normalized and physical sections.

For this stereo workflow, an expected camera reporting:

```text
no corners
```

is a structural **FAIL**. Missing expected camera/IMU residual records are also structural failures.

## Backend revision guard

The text format is verified against the pinned Kalibr revision. A different session revision is rejected by default instead of silently assuming the parser contract stayed stable.

A deliberate backend-format experiment may use:

```bash
--allow-backend-revision-mismatch
```

only after the operator reviews the new Kalibr output contract. The mismatch remains recorded in the result.

## Default assessment

With no numeric requirements supplied, a structurally complete report has status:

```text
EVIDENCE_ONLY_NO_THRESHOLDS
```

Bividi does **not** invent universal reprojection, gyro, accelerometer, or normalized-residual acceptance limits.

## Explicit requirement-based gates

When a product requirement, controlled baseline, or validated lab criterion exists, the operator may provide gates explicitly:

```bash
python tools/analyze_kalibr_solver_quality.py \
  ar0234_kalibr_001/session.json \
  kalibr_dynamic-results-imucam.txt \
  --max-reprojection-mean-px <LIMIT> \
  --max-reprojection-rms-px <LIMIT> \
  --max-gyro-mean-rad-s <LIMIT> \
  --max-gyro-rms-rad-s <LIMIT> \
  --max-accel-mean-m-s2 <LIMIT> \
  --max-accel-rms-m-s2 <LIMIT> \
  --output-prefix ar0234_kalibr_001/solver-quality
```

Optional normalized-residual gates are also available:

```text
--max-normalized-reprojection-mean
--max-normalized-gyro-mean
--max-normalized-accel-mean
```

Each gate records the observed worst source (`cam0`, `cam1`, or `imu0.*`), the explicit threshold, unit, and PASS/FAIL result.

## Interpretation boundary

A low residual means the optimizer fit its selected model/data well. It does **not** by itself prove:

```text
correct physical extrinsic
correct camera timestamp semantic
correct camera↔IMU time offset
sufficient motion excitation / observability
absence of local minima
repeatability across independent recordings
downstream VIO accuracy
```

Likewise, the DECXIN synchronization claim is not converted into a Kalibr residual threshold. Protocol timing evidence and solver fit are different evidence classes.

The intended review stack is therefore:

```text
Kalibr transform/time result
        +
solver residual quality
        +
temporal evidence review
        +
independent-session repeatability
        +
physical protocol/timestamp evidence
        +
downstream VIO behavior
```

## CI

The dependency-free self-test verifies:

```text
exact normalized/physical parser shape
derived RMS calculation
explicit PASS gate
explicit FAIL gate
stereo no-corners structural failure
backend revision mismatch rejection/override
malformed report rejection
Markdown rendering
```

No ROS/Kalibr installation is needed for this parser self-test.

Related: #8, #35, #47, #46.