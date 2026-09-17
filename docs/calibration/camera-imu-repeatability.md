# Camera↔IMU Calibration Repeatability Laboratory

Owner: Issue #47  
Input: two or more validated `bividi.calibration.camera_imu.v1` artifacts  
Output: pairwise repeatability evidence  
Status: hardware-independent comparator implemented; physical AR0234 repeatability campaign pending

## Purpose

One successful Kalibr solve does not establish a stable physical calibration. Repeated dynamic sessions should converge to similar spatial and temporal results before the artifact is trusted by #46 VIO.

`tools/compare_camera_imu_calibrations.py` compares repeated imported Bividi camera↔IMU artifacts without inventing a consensus transform.

```text
session A -> Kalibr -> imported artifact A
session B -> Kalibr -> imported artifact B
session C -> Kalibr -> imported artifact C
                 ↓
compare_camera_imu_calibrations.py
                 ↓
pairwise Δtranslation / Δrotation / Δtime-offset
                 ↓
repeatability evidence
```

## Compatibility gate

Before numerical comparison, every artifact must describe the same calibration contract:

```text
device model + serial
camera id / frame / resolution / mode
IMU model / frame
transform from/to frames
right-handed frame declarations
camera and IMU axis conventions
camera timestamp semantic
time-offset sign definition
external backend identity
```

A mismatch is rejected instead of being averaged away.

Kalibr backend revision must also match by default. Mixing solver revisions confounds physical repeatability with algorithm/version changes. Use `--allow-backend-revision-mismatch` only when that comparison is intentional.

Duplicate artifact content is rejected so the report cannot claim artificial perfect repeatability by comparing a result with itself.

## Pairwise spatial metric

For each pair of transforms `T_i` and `T_j` (both IMU -> the same camera frame), the comparator forms:

```text
Delta_ij = T_i * inverse(T_j)
```

and reports:

```text
translation delta = norm(Delta_ij.translation)    [mm]
rotation delta    = angle(Delta_ij.rotation)      [deg]
```

All pairs are evaluated. The report contains P50/P95/P99/max distributions and each run's worst disagreement with any other run.

The tool does **not** average SO(3)/SE(3), choose a medoid, or declare one run the ground truth. Repeatability is not accuracy.

## Pairwise temporal metric

Artifacts must use the same Bividi/Kalibr convention:

```text
t_imu_s = t_camera_reference_s + offset_s
```

and the same `camera_time_reference` (`exposure_start`, `exposure_midpoint`, or `exposure_end`).

For every pair:

```text
time offset delta = abs(offset_i - offset_j)    [us]
```

This measures solve-to-solve temporal repeatability. It does not prove the absolute time offset is physically correct; use `review_camera_imu_time_offset.py` and protocol evidence for that.

## Usage

Evidence-only mode:

```bash
python tools/compare_camera_imu_calibrations.py \
  run01-camera-imu.json \
  run02-camera-imu.json \
  run03-camera-imu.json \
  --output-prefix ar0234-camA-imu-repeatability
```

Outputs:

```text
ar0234-camA-imu-repeatability.repeatability.json
ar0234-camA-imu-repeatability.repeatability.md
```

Without explicit limits, status is:

```text
EVIDENCE_ONLY_NO_THRESHOLDS
```

When requirements or measured baselines justify thresholds, they can be supplied explicitly:

```bash
--max-pairwise-translation-mm <LIMIT>
--max-pairwise-rotation-deg <LIMIT>
--max-pairwise-time-offset-us <LIMIT>
```

The repository deliberately does not ship arbitrary default limits.

## Recommended physical campaign

For one specimen/configuration, run at least several independent dynamic sessions. Reposition the rig/target between sessions so the test exercises complete target detection and optimization rather than replaying one trajectory.

Keep constant:

```text
specimen
camera mode
IMU calibration artifact
AprilGrid geometry
camera timestamp semantic
Kalibr revision/container
camera/IMU frame conventions
```

Then inspect both per-session solver quality and cross-session repeatability.

A stable but biased calibration can still repeat well, so final acceptance should combine:

```text
Kalibr reprojection / solver quality
protocol/timestamp review
spatial + temporal repeatability
physical sanity checks
VIO behavior
```

Related: #8, #35, #47, #46.
