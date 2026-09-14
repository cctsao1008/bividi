# DECXIN AR0234 Stereo + IMU Module

Status: **vendor-supplied facts normalized for Issue #35; live hardware verification pending**

This document records the device-specific facts that matter to Bividi. It is not a copy of the vendor manuals, and it does not promote vendor claims into measured behavior.

## Source basis

- DECXIN `DECXIN-3361V1 & DECXIN-3362V1` USB camera module sample approval sheet.
- DECXIN `Nori 3D Camera User Guide V1.0`.
- DECXIN `TimeStamp_Data_Decode_DemoCode_V010002` package and included 4000×1200 BMP sample.
- DECXIN Nori_Xvision Windows SDK `10.00.10`.
- DECXIN Nori_Xvision Linux SDK `10.00.06`.
- Purchased product option: **100° SKU**.

The vendor archives and large sample media remain project-source material and are not copied into normal Git history.

## Module identity

The purchased product is marketed as a DECXIN AR0234 stereo camera with a six-axis IMU. The formal approval sheet identifies the module family as:

```text
DECXIN-3361V1 & DECXIN-3362V1
```

The approval sheet itself does **not** print the sensor part number `AR0234`; therefore the AR0234 identity remains a product/vendor identification rather than a fact derived from that approval-sheet row alone.

## Vendor-documented image characteristics

The approval sheet documents:

| Item | Vendor-documented value |
| --- | --- |
| Sensor format | 1/2.6 inch |
| Effective pixels per sensor | 1920 × 1200 |
| Pixel size | 3.0 µm × 3.0 µm |
| Shutter | Global shutter |
| Output formats | MJPEG / YUV2 (YUYV) |
| Composite MJPEG mode | 4000 × 1200 @ 60 fps |
| Composite YUYV mode | 4000 × 1200 @ 30 fps |
| Interface | USB 3.0 |
| Focus | Fixed |
| Lens mount | M12 × P0.5 |
| Listed focal length | approximately 2.37 mm |
| Listed aperture | F2.8 |
| S/N ratio | 37 dB |
| Dynamic range | 70 dB |
| AEC / AWB / AGC | Supported |
| Storage temperature | -40 °C to 80 °C |
| Working temperature | 0 °C to 60 °C |

The document also lists Windows 10/11 and Linux with UVC support, plus macOS/Android UVC support.

## Purchased lens option

The actual order is the **100° product option**.

Do not interpret `100°` as an exact horizontal, vertical, or diagonal field of view until the vendor supplies the corresponding lens table or the device is measured.

```text
purchased option: 100° SKU
exact horizontal FOV: pending
exact vertical FOV:   pending
exact diagonal FOV:   pending
```

The approval-sheet mechanical drawing contains a lens/FOV table that appears to describe a wider-angle configuration; that table must not be silently substituted for the purchased 100° SKU.

## Mechanical / synchronization connector

The approval-sheet drawing shows a 4-pin synchronization header. The visible labels appear as:

```text
EXI_TRG
GND
EXO_STRB
EXI_FSYNC
```

The names strongly suggest external trigger, ground, exposure/strobe output, and external frame-sync input, but exact electrical levels, edge semantics, pulse-width requirements, and supported operating modes are **not yet established** by the material normalized here.

These pins are important because they provide a path to independent timing verification with a logic analyzer or oscilloscope after hardware arrival.

## Sensor timing and IMU

The Nori 3D Camera guide declares:

- same USB camera, multiple sensors: frame synchronization difference `< 1 µs`;
- multiple USB cameras: frame synchronization difference `< 100 µs`;
- IMU to camera-frame synchronization difference `< 30 µs`;
- timestamp unit: microseconds;
- timestamp width: 32 bit;
- timestamp accuracy: 50 ppm;
- synchronized frame timestamp semantic: exposure end (`EE`);
- IMU timestamp semantic: time when the IMU measurement has completed.

These are **vendor specifications**, not Bividi measurements.

The guide lists TDK ICM42688 as an optional sensor and the supplied decoder material explicitly contains ICM42688 decoding logic.

## Transport shape

For the supplied 4000×1200 sample used by Issue #35:

```text
4000 total columns
= 160-column encoding region
+ 1920-pixel eye image
+ 1920-pixel eye image
```

The 160-column region is visibly encoded data in the supplied sample image. The exact logical left/right ordering of the two 1920-pixel image regions must be verified rather than assumed from physical position in the composite frame.

Transport packing is a DECXIN adapter detail and must not become a Bividi core contract.

## Current unknowns

The following remain open until the 100° hardware is available or the vendor provides stronger documentation:

- exact H/V/D field of view for the purchased 100° SKU;
- factory-provided stereo intrinsics/extrinsics;
- camera-to-IMU extrinsic calibration;
- exact electrical/timing characteristics of the synchronization header;
- whether all Nori SDK functions are enabled on this exact module/firmware;
- precise live-device enumeration identity, VID/PID, product string, and serial behavior;
- sustained live FPS, jitter, frame-drop behavior, reconnect behavior, and long-run memory stability;
- independently measured sensor-to-sensor and camera-to-IMU timing error.

## Bividi boundary

The adapter may know about `4000×1200`, the 160-column encoding region, Nori SDK calls, and the DECXIN timestamp encoding. Consumers should not.

```text
DECXIN transport / SDK
        ↓
DECXIN adapter
        ↓
normalized stereo + IMU + timing + status
        ↓
Bividi host consumers
```

Related: #32, #35.