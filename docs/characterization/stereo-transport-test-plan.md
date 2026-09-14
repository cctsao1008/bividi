# AR0234 Stereo Transport Characterization Plan

Owner: Issue #35  
Reference device: DECXIN AR0234 stereo + ICM-42688-P  
Status: live-hardware plan

## Objective

Verify how the delivered AR0234 transport maps to the two physical cameras and confirm that the live path matches the already decoded vendor sample without promoting unverified left/right assumptions into the core contract.

## Offline facts already established

The vendor sample used by the offline decoder has this decoded geometry:

```text
4000 × 1200 transport frame
= 160 × 1200 encoded metadata region
+ 1920 × 1200 camera A
+ 1920 × 1200 camera B
```

The current decoder intentionally exposes `camera_a` and `camera_b` rather than guessing physical left/right identity.

The metadata region carries exposure timing and bundled ICM-42688 samples; those details remain device-adapter responsibilities.

## Live questions to answer

- does the delivered unit expose the same 4000×1200 layout in the selected mode?
- is the 160-column metadata region stable and located as expected?
- which decoded region is the physical left camera?
- which decoded region is the physical right camera?
- is ordering stable across reopen/reconnect?
- do MJPEG and YUYV expose equivalent logical camera ordering?
- are there mode-dependent crop, scale, padding, border, or metadata differences?
- do live timestamps and IMU groups decode through the same implementation as the offline sample?

## 1. Preserve untouched transport evidence

For every mode under test, record before applying semantic mapping:

- transport pixel format;
- decoded width/height/channels;
- representative hashes/metadata;
- metadata-region geometry;
- camera-region geometry;
- whether dimensions/order remain stable over a capture run.

Do not rewrite camera A/B as left/right until physical mapping has been measured.

## 2. Prove physical left/right mapping

Use one-lens-at-a-time occlusion:

```text
cover physical left lens
→ identify whether camera A or camera B changes

cover physical right lens
→ identify whether camera A or camera B changes
```

Repeat after close/open and USB reconnect.

A mapping is accepted only if it is reproducible. Variable names in vendor/demo code are not sufficient evidence.

## 3. Verify transport regions

For the selected mode confirm:

```text
metadata region
camera A region
camera B region
```

Check boundaries for:

- padding;
- duplicated columns;
- crop/scale behavior;
- black borders;
- mode-specific offset changes;
- malformed frames.

The live backend should hand the raw decoded frame to the same DECXIN adapter logic used offline rather than reimplementing the split.

## 4. Mode-by-mode verification

At minimum test every mode Bividi intends to support on the delivered device.

Record:

```text
transport format
transport dimensions
metadata geometry
camera A geometry
camera B geometry
physical left mapping
physical right mapping
crop / scale / padding notes
```

A mapping proven for one format must not be assumed for another format without verification.

## 5. Timing and IMU continuity

Using the existing DECXIN decoder, record:

- exposure start/end continuity;
- extended 32-bit timestamp continuity;
- IMU sample count per frame;
- IMU timestamp cadence;
- gaps, duplicates, or out-of-order samples;
- frame-to-frame anomalies.

Vendor synchronization numbers remain vendor claims until separately measured with appropriate trigger/strobe instrumentation.

## 6. Pair integrity

Record explicit failures such as:

- one camera region frozen while the other changes;
- duplicated camera regions;
- malformed metadata/camera boundary;
- intermittent geometry change;
- one-camera corruption;
- missing or invalid metadata decode.

These states must be observable rather than silently accepted as valid stereo data.

## Core boundary

The adapter may know the DECXIN layout. Bividi Core must not.

```text
4000×1200 DECXIN transport
        ↓
DECXIN adapter
        ↓
camera streams + IMU + timing + status
        ↓
Bividi Core
```

The final consumer-facing observation schema remains owned by Issue #11.

## Acceptance criteria

The stereo-transport characterization slice of #35 is complete when:

- live transport geometry is measured for the selected AR0234 modes;
- physical camera A/B → left/right mapping is proven and repeatable;
- metadata and camera boundaries are exact;
- mode-specific differences are documented;
- live frames use the same DECXIN decoder path as offline fixtures;
- timing/IMU continuity and malformed-frame behavior are observable;
- no DECXIN packing assumption leaks into the platform-independent Bividi Core.
