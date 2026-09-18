# Kalibr IMU export adapter

Owner: Issue #47  
Packaging slice: Issue #101  
Status: dependency-free adapter; Kalibr remains external/optional

## Purpose

`bividi-calib imu export-kalibr` converts an already validated Bividi IMU calibration artifact into the `imu.yaml` shape expected by ETH Zurich Kalibr. It is an interoperability adapter, not a calibration solver, not an IMU promotion gate, and not a source of default sensor parameters.

The durable source contract remains `bividi.calibration.imu.v1`. Kalibr YAML is downstream adapter output.

```text
bividi.calibration.imu.v1
        ↓ validate
package-native artifact validator
        ↓ strict field mapping
bividi-calib imu export-kalibr
        ↓
imu.yaml
+ optional bividi.kalibr.imu_export.v1 sidecar
        ↓
external Kalibr workflow
```

## Package mapping

Installed implementation:

```text
bividi.calibration.artifact_validator
bividi.calibration.kalibr_imu_export
bividi.calibration.kalibr_imu_export_command
```

Compatibility surfaces:

```text
tools/validate_calibration_artifact.py
tools/export_kalibr_imu.py
```

The compatibility scripts are thin wrappers. `bividi-calib imu export-kalibr` executes through the installed package and does not require a Bividi source checkout.

## Required measured fields

The adapter requires these positive values in the Bividi artifact:

```text
noise.accelerometer_noise_density_m_s2_sqrt_hz
noise.accelerometer_bias_random_walk_m_s3_sqrt_hz
noise.gyroscope_noise_density_rad_s_sqrt_hz
noise.gyroscope_bias_random_walk_rad_s2_sqrt_hz
```

They map directly to:

```text
accelerometer_noise_density
accelerometer_random_walk
gyroscope_noise_density
gyroscope_random_walk
```

No datasheet or vendor-demo value is substituted when one of these fields is missing.

## Update-rate selection

Kalibr `update_rate` is selected only from measured cadence evidence, in this order:

```text
1. timing.effective_rate_hz
2. imu.sample_rate_hz_measured
```

`imu.sample_rate_hz_nominal` is never used as a silent fallback.

## Provenance behavior

Accepted Bividi provenance kinds are:

```text
measured
imported
synthetic
```

Synthetic input is rejected by default. `--allow-synthetic` is an explicit test-only opt-in so CI/synthetic fixtures can exercise the adapter without being mistaken for real calibration evidence.

When `--manifest-out` is requested, the sidecar uses schema:

```text
bividi.kalibr.imu_export.v1
```

and records the exact field mapping, selected update-rate source, source calibration identity/provenance, source artifact path/SHA-256, and best-effort exporter Git revision.

## Command behavior

Example:

```bash
bividi-calib imu export-kalibr \
  calibration/imu-unit01.json \
  --rostopic /imu0 \
  --output imu.yaml \
  --manifest-out imu.export.json
```

The ROS topic must be an absolute topic such as `/imu0`.

Frozen command exits:

```text
0  successful export
2  usage/input/schema/domain/read/write failure
```

The adapter does not use exit `3` because it does not own an evaluated PASS/FAIL disposition.

## Validation boundary

The packaged validator preserves the existing dependency-free checks for both:

```text
bividi.calibration.imu.v1
bividi.calibration.camera_imu.v1
```

including camera↔IMU rigid-transform invariants and frame/time-offset consistency. Packaging the validator is necessary because the historical exporter imported it as a sibling `tools/` module; moving only the exporter would leave a hidden source-checkout dependency.

## Non-goals

This adapter does not:

- run Kalibr;
- install ROS or Kalibr;
- estimate noise density or random walk;
- invent a nominal update rate;
- approve an IMU calibration for production use;
- convert Kalibr YAML into Bividi's public calibration schema.

Kalibr remains an optional external backend under Issue #47.
