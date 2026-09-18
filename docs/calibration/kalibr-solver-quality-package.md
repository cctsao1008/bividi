# Package-native Kalibr IMU-camera solver-quality evidence

Owner: Issue #111 under #47  
Upstream: prepared dynamic session + external ETH Kalibr solve  
Adjacent: candidate import (#109), temporal review, repeatability, promotion  
Status: package migration only; residual fit remains one evidence class

## Command surface

The solver-quality evaluator is package-native:

```bash
bividi-calib camera-imu solver-quality --self-test
```

Installed routing is:

```text
bividi.calibration.kalibr_solver_quality_command
        ↓
bividi.calibration.kalibr_solver_quality
```

The historical source-tree entry point remains a thin compatibility wrapper:

```text
tools/analyze_kalibr_solver_quality.py
```

No Kalibr or ROS runtime is required to analyze an already produced solver text report.

## Source contract

The parser remains tied to the reviewed ETH Zurich Kalibr error-statistics output:

```text
backend: ethz-asl/kalibr
revision: 1f60227442d25e36365ef5f72cd80b9666d73467
source: aslam_offline_calibration/kalibr/python/kalibr_imu_camera_calibration/IccUtil.py::printErrorStatistics
```

A different session revision is rejected unless the operator explicitly passes:

```bash
--allow-backend-revision-mismatch
```

That flag records an explicit parser-contract review exception; it is not silent compatibility.

## Preserved residual semantics

The report schema remains:

```text
bividi.calibration.kalibr_solver_quality.v1
```

The evaluator preserves normalized and physical residuals separately for:

```text
camera reprojection
imu0 gyroscope
imu0 accelerometer
```

Physical units remain:

```text
camera: px
gyroscope: rad/s
accelerometer: m/s^2
```

For each parsed residual norm distribution Kalibr provides mean, median, and population standard deviation. Bividi preserves those values and derives:

```text
derived_rms = sqrt(mean^2 + std^2)
```

The prepared session determines the expected Kalibr stereo camera names. Missing expected camera/IMU residuals and `no corners` are structural findings rather than silently ignored data.

## Assessment policy

With structurally complete input and no explicit gates, the report remains:

```text
EVIDENCE_ONLY_NO_THRESHOLDS
```

Numeric limits are operator supplied only. Existing gate surfaces cover physical and normalized reprojection/gyro/accelerometer mean/RMS evidence. No default solver-residual acceptance threshold is added by package migration.

A structural error or an explicit gate violation produces a completed report status:

```text
FAIL
```

Passing supplied gates produces:

```text
PASS
```

## Exit-code contract

The package adapter maps the historical process exits onto the frozen calibration vocabulary:

```text
0  evidence-only or PASS completion
2  usage/input/schema/parser/revision/domain/write failure
3  completed structural or explicit-gate FAIL
```

The historical implementation returned `3` for domain/parser failures and `7` for completed report FAIL. Only this process-level collision is normalized; report schema, residual values, findings, gates, and assessment status are unchanged.

## Provenance

The report continues to bind both source files by SHA-256:

```text
prepared dynamic session
Kalibr results-imucam text report
```

Historical provenance remains:

```text
tool = analyze_kalibr_solver_quality.py
tool_version = 1
```

## Interpretation boundary

Solver residuals characterize optimizer fit. They do not independently establish:

```text
physical T_cam_imu accuracy
camera↔IMU timestamp correctness
trajectory observability
independent-session stability
downstream VIO accuracy
promotion readiness
```

Therefore:

```text
low Kalibr residuals != calibration truth
```

Temporal review, repeated-session comparison, target/excitation evidence, protocol timing evidence, and downstream validation remain separate layers.

## CI boundary

Normal Ubuntu and Windows CI exercise the installed self-test and the direct compatibility wrapper. The synthetic fixture proves evidence-only output, derived RMS, explicit PASS, explicit gate FAIL, structural `no corners` FAIL, revision mismatch rejection and explicit override, malformed report rejection, and Markdown rendering.
