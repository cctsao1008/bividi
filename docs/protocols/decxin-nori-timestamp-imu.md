# DECXIN Nori Timestamp and IMU Encoding

Status: **vendor protocol note for Issue #35; live hardware verification pending**

This document captures only the protocol details needed to implement the DECXIN adapter and deterministic offline tests.

## Source basis

- DECXIN `Nori 3D Camera User Guide V1.0`.
- DECXIN `TimeStamp_Data_Decode_DemoCode_V010002` package.
- Included `4000x1200_0_0_10.bmp` sample.
- Included `icm_decode.cpp` and `inc/icm42688_decode.h`.

No vendor binary or large sample frame is copied into normal Git history.

## Frame-level model

The Nori guide states that video output resolution consists of effective image data plus an encoded-data region.

The supplied sample is 4000×1200. With two 1920×1200 eye images, the observed transport geometry is:

```text
4000 × 1200 composite frame

┌──────────────┬────────────────────┬────────────────────┐
│ 160 columns  │ 1920 × 1200       │ 1920 × 1200       │
│ encoded data │ eye image A        │ eye image B        │
└──────────────┴────────────────────┴────────────────────┘
```

The 160-column encoded region is a transport detail. Logical left/right ordering of eye A/B must be verified on the real device or from stronger vendor mapping evidence.

## Timestamp semantics

The Nori guide defines the synchronized video-frame timestamp as **exposure end (`EE`)**.

The encoded frame also carries both exposure start and exposure end values:

```text
Exposure Start (ES)
Exposure End   (EE)
```

The guide declares:

- timestamp unit: `µs`;
- timestamp width: `32 bit`;
- timestamp accuracy: `50 ppm`;
- IMU timestamp: time when the IMU measurement has completed.

A 32-bit microsecond counter wraps after:

```text
2^32 µs = 4294.967296 s ≈ 71.58 min
```

The adapter must therefore preserve the raw 32-bit value and separately maintain an extended monotonic time for long-running capture.

## Encoded groups

The guide specifies **12 groups per video frame**, each **16 bytes**.

### Group 0

```text
16 bytes total

header / protocol information : 8 bytes
exposure start timestamp       : 4 bytes
exposure end timestamp         : 4 bytes
```

The vendor decoder supports protocol/header interpretation before determining the total payload group count.

### Groups 1 through 11

For the ICM42688 path, each 16-byte IMU group is decoded as:

```text
IMU timestamp : 4 bytes
Accel X       : 2 bytes
Accel Y       : 2 bytes
Accel Z       : 2 bytes
Gyro X        : 2 bytes
Gyro Y        : 2 bytes
Gyro Z        : 2 bytes
```

The supplied decoder uses default conversion settings corresponding to:

```text
accelerometer range: ±4 g
gyroscope range:     ±1000 dps
```

Those conversion settings are properties of the supplied decoder example and must not be assumed to be immutable device configuration without verification.

## Encoding extraction

The vendor sample decoder scans the encoded pixel area using 8×8 coding cells and reconstructs byte groups from image pixels. The guide notes that blank pixels in the encoded region are invalid-data buffer space and have grayscale values above 210.

Bividi should treat this as a DECXIN transport decoder responsibility:

```text
composite image
    ↓
encoded-pixel decoder
    ↓
protocol bytes
    ↓
ES / EE + IMU samples
```

The Bividi host-facing observation must not expose 8×8 code-cell details.

## Synchronization specifications

The Nori guide declares the following synchronization performance:

```text
multiple sensors in one USB camera : < 1 µs
multiple USB cameras               : < 100 µs
IMU ↔ camera frame                  : < 30 µs
```

These are vendor specifications and remain unmeasured by Bividi until hardware characterization is completed.

Seller/marketing material seen earlier may quote different numbers. Bividi must preserve such discrepancies instead of silently choosing the most favorable claim.

## Rollover handling requirement

A correct adapter should conceptually produce both:

```text
raw_device_time_32
extended_device_time
```

Example:

```text
0xfffffff0
0xfffffffe
0x00000620   ← wrap
```

The extension logic must be deterministic and covered by unit tests. Raw timestamp values must not be discarded after extension.

## Validation strategy

Before live hardware is available, Issue #35 should use the vendor sample and decoder as a golden reference for:

- composite dimensions;
- encoded-region extraction;
- group/header parsing;
- exposure start/end decoding;
- ICM42688 sample decoding;
- malformed-frame handling;
- timestamp rollover behavior using synthetic vectors.

After hardware arrival, add live checks for:

- timestamp continuity;
- IMU cadence;
- frame/IMU gaps;
- duplicate/out-of-order frames;
- sustained timing behavior;
- independent trigger/strobe timing where measurement equipment allows it.

## Adapter boundary

```text
DECXIN/Nori encoded transport
        ↓
protocol decoder
        ↓
normalized image + IMU + timing values
        ↓
Bividi observation stream
```

The protocol is implementation evidence, not a public Bividi schema.

Related: #32, #35.