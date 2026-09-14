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
│ encoded data │ camera image A     │ camera image B     │
└──────────────┴────────────────────┴────────────────────┘
```

The 160-column encoded region is a transport detail. Logical left/right ordering of camera A/B must be verified on the real device or from stronger vendor mapping evidence.

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

The adapter therefore preserves the raw 32-bit value and separately maintains an extended timeline for long-running capture.

## Encoded groups

Each encoded group is **16 bytes**.

The guide illustrates the ICM42688 case as one header group plus 11 IMU groups. The supplied V010002 decoder is more general: the current protocol header carries up to five device-type/group-count descriptors and derives the total group count from the header.

Therefore Bividi must **not** make `11 IMU samples per frame` part of its core schema.

### Group 0

For the current protocol:

```text
16 bytes total

protocol / device-group descriptors : 8 bytes
exposure start timestamp             : 4 bytes
exposure end timestamp               : 4 bytes
```

The vendor decoder also retains a legacy protocol path in which the first and second 8-byte halves contain duplicated exposure timing data and the ICM42688 path is treated as 11 groups.

### ICM42688 data group

For an ICM42688 group, the supplied decoder uses:

```text
IMU timestamp : 4 bytes, big-endian
Accel X       : 2 bytes, signed big-endian
Accel Y       : 2 bytes, signed big-endian
Accel Z       : 2 bytes, signed big-endian
Gyro X        : 2 bytes, signed big-endian
Gyro Y        : 2 bytes, signed big-endian
Gyro Z        : 2 bytes, signed big-endian
```

The supplied demo converts raw values using defaults corresponding to:

```text
accelerometer range: ±4 g
gyroscope range:     ±1000 dps
```

Those conversion settings are properties of the supplied decoder example and must not be assumed to be immutable device configuration without verification.

The vendor decoder also defines an invalid-sample sentinel:

```text
Accel X/Y/Z all == -1
OR
Gyro X == -32768
```

When this condition occurs, the vendor implementation clears the sensor values while preserving the timestamp. Bividi mirrors the invalid state explicitly rather than treating the cleared values as a valid zero-motion measurement.

## Encoding extraction

The vendor sample decoder scans the encoded pixel area using 8×8 coding cells and reconstructs byte groups from image pixels. The code uses the middle byte of each BGR pixel and applies vendor thresholds to recover 0/1 bits. Blank/alignment pixels are high-valued and terminate encoded data for the line.

Bividi treats this as a DECXIN transport-decoder responsibility:

```text
composite image
    ↓
encoded-pixel decoder
    ↓
protocol bytes
    ↓
ES / EE + device groups
    ↓
ICM42688 samples where declared
```

The Bividi core must not know about 8×8 coding cells or the 160-column metadata region.

## Golden vendor sample checkpoint

The repository keeps only a compact derived vector and hashes for the vendor sample; the 14.4 MB BMP remains external project-source material.

Source:

```text
4000x1200_0_0_10.bmp
SHA-256: 62cf01e57c0bc36e68f2f355079295947643bff02ccab5abe4d2af17ab939ebe
```

The implemented decoder reproduces the supplied vendor decoder semantics:

```text
Protocol type       : 1
ICM42688 groups     : 11
Exposure Start (ES) : 28,117,353 us
Exposure End   (EE) : 28,124,847 us
Exposure duration   : 7,494 us
First IMU timestamp : 28,108,131 us
Last IMU timestamp  : 28,124,771 us
IMU timestamp step  : 1,664 us in this sample
```

The decoded 192-byte group payload has:

```text
SHA-256: ef9ab743f58737529c9612f0cf8f0037ef2b9fa6ba616d8764e09031a681cfd4
```

After normalizing BMP row order to top-down BGR24, the observed transport regions hash to:

```text
metadata 160×1200 : 7619ddf0cda17900de48a1aba55f3d6bf0da70b900a2e3973c9a9b4fd961eeed
camera A 1920×1200 : 3b6955bcf39e92e463acb4c49df54364204d387dbd9faedac99a3cd2d4c91822
camera B 1920×1200 : a912793ac9124ee226eec9092af13a7b41302363e771815f5a93f3f68353868b
```

These hashes are regression evidence for the supplied sample only. They do not establish the physical left/right identity of camera A/B.

The compact vector is stored at:

- `tests/fixtures/decxin_ar0234_sample_vector.json`

The external BMP can be rechecked with:

```bash
python tools/verify_decxin_vendor_sample.py /path/to/4000x1200_0_0_10.bmp
```

## Synchronization specifications

The Nori guide declares the following synchronization performance:

```text
multiple sensors in one USB camera : < 1 µs
multiple USB cameras               : < 100 µs
IMU ↔ camera frame                  : < 30 µs
```

These are vendor specifications and remain unmeasured by Bividi until hardware characterization is completed.

Seller/marketing material supplied for the device family may quote `<10 µs` for camera/IMU synchronization. Bividi preserves that discrepancy rather than silently choosing the more favorable value.

## Rollover handling requirement

A correct adapter produces both:

```text
raw_device_time_32
extended_device_time
```

Example:

```text
0xfffffff0
0xfffffffe
0x00000020   ← wrap
```

The extension logic treats a large backward jump across half the 32-bit range as a wrap. Small backward movement remains visible as reordering rather than being silently rewritten into another epoch.

Raw timestamp values are preserved after extension.

## Validation strategy

The offline path now covers:

- composite BMP parsing;
- metadata/camera-region separation;
- encoded-pixel extraction;
- group/header parsing;
- exposure start/end decoding;
- ICM42688 sample decoding;
- vendor invalid-sample handling;
- 32-bit timestamp rollover tests;
- compact golden vectors and hashes;
- CLI inspection of the external vendor sample.

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
platform-independent DECXIN decoder
        ↓
normalized camera + IMU + timing values
        ↓
Bividi core / observation boundary
```

The protocol is implementation evidence, not a public Bividi schema.

Related: #32, #35.
