# DECXIN AR0234 Stereo + IMU Module

Status: **vendor-supplied facts normalized for Issues #32/#35; live hardware verification pending**

This document records the device-specific facts that matter to Bividi. It is not a copy of the vendor manuals, and it does not promote vendor or seller claims into measured behavior.

## Source basis

- DECXIN `DECXIN-3361V1 & DECXIN-3362V1` USB camera module sample approval sheet.
- DECXIN product-parameter / mechanical material supplied for the AR0234 family.
- DECXIN `Nori 3D Camera User Guide V1.0`.
- DECXIN `TimeStamp_Data_Decode_DemoCode_V010002` package and included 4000×1200 BMP sample.
- DECXIN Nori_Xvision Windows SDK `10.00.10`.
- DECXIN Nori_Xvision Linux SDK `10.00.06`.
- Seller/SKU material for the actual purchase.
- Purchased product option: **100° SKU**.

The vendor archives and large sample media remain project-source material and are not copied into normal Git history.

## Module identity

The purchased product is the DECXIN AR0234 stereo global-shutter camera family with a six-axis IMU.

Vendor product/specification material identifies:

```text
sensor family: AR0234
per-sensor image: 1920 × 1200
composite transport: 4000 × 1200
baseline: approximately 60 mm
USB: USB 3.0
```

The formal module family is shown as:

```text
DECXIN-3361V1 & DECXIN-3362V1
```

Exact PCB/module revision on the delivered specimen must still be read from the physical unit rather than inferred from family artwork.

## Vendor-documented image characteristics

The vendor material documents:

| Item | Vendor-documented value |
| --- | --- |
| Photosensitive chip | AR0234 family material |
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
| Family lens material | approximately 2.37 mm, F2.8 for one documented configuration |
| S/N ratio | 37 dB |
| Dynamic range | 70 dB |
| AEC / AWB / AGC | Supported |
| Storage temperature | -40 °C to 80 °C |
| Working temperature | 0 °C to 60 °C |

The material also lists Windows 10/11 and Linux with UVC support, plus macOS/Android UVC support. Vendor Nori SDK packages supplied to this project are Windows and Linux packages; UVC compatibility is not the same thing as availability of the Nori SDK on every OS.

## Purchased lens option

The actual shipped order is the **100° seller SKU**.

The AR0234 product page exposes lens/SKU labels including:

```text
100° / 130° / 160° / 175° / 195° / 200°
```

Separate vendor product-parameter material lists optical FOV rows such as:

| Vendor optical row | Diagonal | Horizontal | Vertical |
| --- | ---: | ---: | ---: |
| 1 | 92° | 82° | 57° |
| 2 | 132° | 121° | 92° |
| 3 | 165° | 135° | 75° |
| 4 | 178° | 156° | 98° |
| 5 | 195° | 195° | 111° |
| 6 | 200° | 200° | 200° |

These values are preserved as vendor material, including unusual entries. The documents currently available do **not** establish a rigorous one-to-one mapping from seller SKU label `100°` to one specific H/V/D row or define whether the seller label itself means horizontal, vertical, diagonal, or nominal lens angle.

Therefore Bividi records:

```text
purchased option: 100° seller SKU
exact horizontal FOV: pending exact SKU confirmation / measurement
exact vertical FOV:   pending exact SKU confirmation / measurement
exact diagonal FOV:   pending exact SKU confirmation / measurement
```

Do not silently substitute the 130°/132° family drawing or another lens table entry for the delivered 100° specimen.

## SKU-dependent audio

Seller material/confirmation indicates that microphone availability is SKU-dependent: the purchased **100° SKU does not include the microphone**, while a **130° SKU is offered with microphone capability**.

This is not yet a live-enumeration result. Bividi therefore treats audio as a runtime capability rather than an AR0234-family invariant.

```text
purchased 100° SKU: audio expected absent
130° seller SKU:    microphone offered
live USB/audio enumeration: pending
```

## Mechanical / synchronization connector

The vendor mechanical drawing and product images show a synchronization header with labels corresponding to:

```text
EXT_TRG / EXI_TRG
GND
EXO_STRB
EXT_FSYNC / EXI_FSYNC
```

Naming differs slightly across material. The labels strongly suggest external trigger, ground, exposure/strobe output, and external frame-sync input, but exact electrical levels, edge semantics, pulse-width requirements, and supported operating modes are **not yet established** by the material normalized here.

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

Seller/marketing material for the family also advertises camera/IMU synchronization `< 10 µs`. This discrepancy is preserved rather than reconciled without measurement.

All timing figures above are **vendor claims/specifications**, not Bividi measurements.

The Nori guide lists TDK ICM42688 as an optional sensor and the supplied decoder material explicitly contains ICM42688 decoding logic. The supplied 4000×1200 vendor sample decodes to 11 ICM42688 groups for that frame; the protocol decoder itself supports variable device-group counts and Bividi does not hardcode 11 samples into its core model.

## Transport shape

For the supplied 4000×1200 sample used by Issue #35:

```text
4000 total columns
= 160-column encoding region
+ 1920-pixel camera image A
+ 1920-pixel camera image B
```

The 160-column region is visibly encoded data in the supplied sample image. The exact logical left/right ordering of the two 1920-pixel image regions must be verified rather than assumed from their position in the composite frame.

Transport packing is a DECXIN adapter detail and must not become a Bividi core contract.

## Current unknowns

The following remain open until the 100° hardware is available or the vendor provides stronger exact-SKU documentation:

- exact H/V/D field of view for the delivered 100° SKU;
- factory-provided stereo intrinsics/extrinsics;
- camera-to-IMU extrinsic calibration;
- exact electrical/timing characteristics of the synchronization header;
- whether all Nori SDK functions are enabled on this exact module/firmware;
- precise live-device enumeration identity, VID/PID, product string, serial behavior, and audio-device presence;
- sustained live FPS, jitter, frame-drop behavior, reconnect behavior, and long-run memory stability;
- independently measured sensor-to-sensor and camera-to-IMU timing error.

## Bividi boundary

The DECXIN adapter may know about `4000×1200`, the 160-column encoding region, Nori SDK calls, ICM42688 packet groups, and the DECXIN timestamp encoding. Bividi Core must not.

```text
Platform Backend
        ↓
DECXIN transport / SDK data
        ↓
DECXIN adapter / decoder
        ↓
normalized capabilities + sensor values
        ↓
Bividi Core
```

Related: #32, #35, #38.
