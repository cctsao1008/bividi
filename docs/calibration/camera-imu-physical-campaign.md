# Camera↔IMU Physical Calibration Campaign

Owner: Issue #47  
Depends on: #35 stable acquisition + #8 measured stereo calibration  
Downstream: #46 VIO  
Status: hardware-independent campaign planner implemented; physical AR0234 campaign pending

## Purpose

The #47 toolchain now has independent evidence layers for IMU characterization, dynamic excitation, exact Kalibr AprilGrid observations, target coverage, solver residual quality, temporal review, repeatability, and final evidence promotion. The remaining gap is execution discipline on real hardware.

`tools/plan_camera_imu_physical_campaign.py` turns those independent tools into a specimen-specific physical campaign without pretending to automate the measurements themselves.

It creates:

```text
<campaign-root>/campaign.json
<campaign-root>/RUNBOOK.md
```

and can later audit whether the expected outputs exist and, for JSON artifacts, whether their top-level schema matches the planned evidence role.

## Why this exists

A successful Kalibr solve is only one step in a physical campaign. The delivered specimen must accumulate compatible evidence in the right order:

```text
stable #35 acquisition
        +
measured #8 stereo calibration
        ↓
IMU bias / noise / axis / scale evidence
        ↓
measured IMU artifact
        ↓
independent dynamic camera+IMU sessions
        ↓
excitation + target coverage
        ↓
external Kalibr solves
        ↓
solver quality + import + temporal review
        ↓
cross-session repeatability
        ↓
final #47 promotion gate
        ↓
#46 VIO may consume the frozen calibration
```

The planner prevents a campaign from becoming an informal pile of files with unclear specimen identity, missing stages, or one unreviewed solver result being treated as calibration truth.

## Create a campaign

Example:

```bash
python tools/plan_camera_imu_physical_campaign.py init ar0234-camimu-001 \
  --campaign-id ar0234-camimu-001 \
  --model DECXIN-AR0234 \
  --serial <physical-serial> \
  --device 0 \
  --mode 0 \
  --camera-time-reference exposure_midpoint \
  --dynamic-session-count 3
```

`--dynamic-session-count` is explicit. The tool only enforces `>= 2`, because a repeatability comparison mathematically requires more than one independent solve. It does not invent a universal requirement that every product must use exactly three sessions.

A policy source can be recorded when one exists:

```bash
--policy-source "AR0234 camera-IMU calibration acceptance rev A"
```

The planner does **not** create numeric acceptance limits. Those remain owned by the relevant evidence tools and the named lab/product policy.

## Planned evidence stages

The generated runbook covers four groups.

### 1. IMU intrinsic campaign

```text
short stationary capture
stationary analysis
long stationary capture
Allan/noise analysis
six-position capture + analysis
controlled +/-XYZ gyro capture + analysis
IMU session provenance gate
measured IMU artifact review/promotion
```

This phase must retain the real configured range/ODR/filter provenance. Vendor-demo conversion constants are not specimen calibration.

### 2. Independent dynamic sessions

Each dynamic session contains:

```text
stereo + raw-IMU capture
Kalibr staging bundle
dynamic excitation evidence
exact Kalibr AprilGrid target observations
image-plane / target-corner coverage
external Kalibr solve
solver residual quality
T_cam_imu + timeshift import
device-time temporal review
```

The exact target-observation adapter remains inside the pinned Kalibr runtime and reuses Kalibr's own `GridDetector` / `GridCalibrationTargetObservation` semantics. Bividi does not redetect AprilGrid corners with a second detector for acceptance evidence.

### 3. Repeatability

Independent candidate solves are compared for spatial and temporal consistency. Repeatability is evidence that separate sessions agree; it is not proof that they agree on the physically correct answer.

### 4. Final promotion boundary

The final stage uses `tools/camera_imu_calibration_provenance.py` to hash-bind all evidence classes and apply the requested integrity/review/promotion profile.

`PROMOTION_READY` means the evidence graph satisfies the recorded policy. It is not an independent metrology claim.

## Audit a campaign

```bash
python tools/plan_camera_imu_physical_campaign.py audit \
  ar0234-camimu-001/campaign.json \
  --output ar0234-camimu-001/audit.json
```

Every stage is reported as:

```text
complete  expected artifacts exist and declared JSON schemas match
ready     dependencies are complete, but this stage output is missing/incomplete
blocked   at least one dependency is incomplete
```

This is deliberately a **presence/schema audit** only. It does not replace:

- SHA-256 verification performed by the provenance tools;
- numerical quality checks performed by excitation/coverage/solver/time/repeatability tools;
- manual review of specimen configuration and physical procedure;
- the final promotion gate.

## Physical procedure notes

Use the same physical specimen, firmware/SDK configuration, camera mode, and reviewed IMU configuration across evidence that is intended to compose into one calibration campaign. If a reconnect, firmware change, range change, filter change, mount change, optical change, or mode change invalidates that assumption, start a new compatible campaign or explicitly re-run the affected evidence.

For dynamic AprilGrid collection, the operator should deliberately vary target position, image-plane coverage, apparent scale/distance, and rig orientation/motion while keeping the board detectable in both cameras. The target-coverage and excitation tools quantify the resulting evidence; the campaign planner does not replace the operator procedure with arbitrary numeric limits.

## Timing contract

The campaign keeps the existing Bividi sign rule:

```text
t_imu_s = t_camera_reference_s + offset_s
```

and requires one explicit camera timestamp semantic:

```text
exposure_start
exposure_midpoint
exposure_end
```

Do not mix timestamp semantics between export, Kalibr solve, import, temporal review, and final promotion.

## Runtime boundary

Most planning and evidence analysis runs in normal Bividi tooling. Two stages remain explicitly external:

```text
exact Kalibr AprilGrid observation extraction
external Kalibr camera-IMU optimization
```

ROS/Kalibr therefore remain laboratory dependencies and do not enter Bividi Core or the production capture runtime.

## Guardrails

- No universal calibration threshold is invented by the campaign planner.
- Camera A/B are not renamed left/right unless #35 physical evidence supports that mapping.
- Vendor camera↔IMU synchronization claims remain claims until measured/validated.
- A low solver residual does not prove good target coverage, good inertial excitation, correct time offset, or correct physical extrinsics.
- A campaign audit reporting every file present does not imply promotion readiness.
- #46 accuracy claims remain blocked until measured #8 + #47 artifacts are frozen for the actual specimen/mode.

Related: #8, #35, #46, #47.
