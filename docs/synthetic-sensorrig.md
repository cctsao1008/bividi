# Deterministic Synthetic SensorRig

Status: hardware-independent test infrastructure for Issue #58. Synthetic output is never physical AR0234 evidence.

## Purpose

Provide compact stereo-inertial fixtures with explicit ground truth so the #11 observation contract, #31 replay, #9 depth, #46 VIO plumbing, and reliability regressions can be exercised before the physical camera arrives.

The generator is intentionally geometric rather than photorealistic:

```text
known rig / scene / trajectory / clocks
                ↓
tools/generate_synthetic_sensorrig.py
                ↓
replay-compatible session files
+
versioned ground_truth.json
```

## Generate a fixture

Static fronto-parallel plane:

```bash
python tools/generate_synthetic_sensorrig.py out/static \
  --scenario static-plane \
  --print-digest
```

Moving pure-translation trajectory:

```bash
python tools/generate_synthetic_sensorrig.py out/moving \
  --scenario moving-rig \
  --print-digest
```

The output directory must be absent or empty. The generator refuses to overwrite an existing non-empty directory.

## Output layout

```text
session/
├── capture.json
├── frames.csv
├── imu.csv
├── ground_truth.json
├── camera_a/
│   └── *.pgm
└── camera_b/
    └── *.pgm
```

`capture.json`, `frames.csv`, `imu.csv`, and the camera media deliberately match the first native replay adapter's existing Nori-session evidence layout. This is a **compatibility adapter shape**, not a claim that the synthetic source is a Nori/DECXIN device. `capture.json.provenance.kind` is always `synthetic`, the product/serial are synthetic, and `ground_truth.json` carries the independent generator contract.

The long-term source of truth remains `SensorObservation` / `SensorCapabilities`; storage layouts are adapters to that contract.

## Versioned ground truth

`ground_truth.json` uses:

```text
bividi.synthetic_sensor_rig.v1
```

It records:

- deterministic generator seed;
- explicit `synthetic` provenance;
- camera A/B pinhole K/D and image geometry;
- stereo R/T and baseline;
- camera↔IMU rotation/translation;
- coordinate-frame conventions;
- camera and IMU rate;
- exposure timing and 32-bit raw timestamp width;
- fronto-parallel plane depth;
- expected disparity from `fx * baseline / depth`;
- per-frame trajectory state;
- SHA-256 and byte count for each generated replay artifact/media file.

The current default static geometry is deliberately simple:

```text
fx = 80 px
baseline = 0.10 m
plane depth = 2.0 m
expected disparity = 4 px
```

These values are synthetic test parameters. They must never be substituted for seller nominal optics or measured AR0234 calibration.

## Image generation

Images are dependency-free binary PGM (`P5`) GRAY8 files. The texture uses a deterministic integer hash plus coarse checker structure. Camera B samples the same virtual plane with the known stereo offset, so the interior correspondence obeys the exact configured integer disparity.

The static scenario holds the rig fixed. The moving scenario applies a deterministic sinusoidal lateral translation while preserving the same stereo baseline and plane geometry.

## IMU model

The synthetic IMU frame is right-handed FLU:

```text
+X forward
+Y left
+Z up
```

Camera optical coordinates use the OpenCV convention:

```text
+X right
+Y down
+Z forward
```

`ground_truth.json` records the exact IMU→camera rotation.

The first moving fixture is pure translation, so gyro ground truth is exactly zero. Accelerometer raw counts are generated from the trajectory acceleration plus stationary +g specific force on IMU +Z using an explicitly synthetic counts-per-g value. This scale is part of the fixture definition only; it is not an ICM42688 configuration claim.

## Clock model

Three meanings remain distinct:

```text
device exposure / IMU time
host receive monotonic provenance
future replay scheduling time
```

The synthetic session stores device time in microseconds, finite-width raw evidence as 32-bit values, and independent host monotonic timestamps. It does not infer a physical camera↔host clock calibration.

## Determinism and CI

`tests/test_synthetic_sensorrig.py` regenerates independent copies and verifies that the full tree digest and canonical ground truth are identical. It also checks the exact stereo pixel shift, synthetic provenance, moving-image change, nonconstant inertial acceleration, and refusal to overwrite evidence.

The generator also provides:

```bash
python tools/generate_synthetic_sensorrig.py --self-test
```

Normal package unit tests already run on both Ubuntu and Windows CI, so the fixture semantics are cross-platform checked without OpenCV or physical hardware.

## Intended consumers

Near-term:

```text
#58 synthetic rig
      ↓
#31 ReplaySource
      ↓
#11 SensorObservation
      ↓
#9 rectification / disparity / metric depth / XYZ
```

Later, a richer moving scenario can add angular motion and more general 3D structure for #46 VIO adapter tests. The current pure-translation scenario is sufficient to establish timing/provenance plumbing and deterministic non-static inertial evidence without pretending to be a complete VIO benchmark.

## Guardrails

- Every generated artifact is synthetic evidence.
- Synthetic success is not AR0234 accuracy evidence.
- Camera A/B are not relabeled left/right as a physical-device claim.
- Host time is not substituted for device time.
- The synthetic raw IMU scale is not a vendor register/configuration claim.
- The Nori-shaped replay files are an adapter compatibility surface, not sensor identity.
- Physical synchronization, exposure behavior, optics, noise, depth range, and recovery remain owned by the measured #35/#8/#47 campaigns.
