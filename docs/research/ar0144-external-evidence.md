# AR0144 External Evidence Audit

Status: pre-hardware research note  
Issue: #25  
Last reviewed: 2026-09-14

## Purpose

This note records public AR0144/Waveshare implementations that can inform Bividi before the reference camera arrives.

The evidence rule is strict:

```text
third-party implementation
        -> working hypothesis

our UVC descriptor / captured frame / measurement
        -> Bividi measured fact
```

External code is useful for deciding **what to test first**. It is not allowed to silently become the device contract.

## Evidence classes

| Class | Meaning |
|---|---|
| THIRD-PARTY MODULE EVIDENCE | Code or notes that appear to use an AR0144 stereo USB module, preferably Waveshare-specific. |
| SENSOR-LEVEL REFERENCE | AR0144 sensor/ISP integration that does not exercise the Waveshare USB stereo bridge. |
| CORROBORATING PATTERN | The same behavior appears in more than one implementation, but independence/provenance may be uncertain. |
| BIVIDI MEASURED FACT | Reserved for our own device measurements. None yet. |

## High-value external references

### 1. `attu0/depth_camera`

Reference:

- https://github.com/attu0/depth_camera/blob/c5d2f3b79bbdf8b2da1fae501d7ee38a27738af1/stereo_split_node.py
- https://github.com/attu0/depth_camera/blob/main/README.md

Observed implementation assumptions:

- AR0144 stereo USB camera appears on one `/dev/video*` node.
- Requested mode is MJPG, `2560x720`.
- The captured frame is treated as a horizontal side-by-side image.
- Left and right images are extracted by splitting the frame at `width / 2`.
- A ROS 2 wrapper republishes the two halves as left/right image topics.

Evidence value: **THIRD-PARTY MODULE EVIDENCE**.

Important limitation: the repository is not an authoritative description of our exact hardware revision. Device-node number, ordering, format negotiation, and synchronization quality remain unverified.

### 2. `jaa-bah/AutonoBird`

Reference:

- https://github.com/jaa-bah/AutonoBird/blob/81c3ffc1bd8aeb8a5b2be1b0b21800c4340c0576/scripts/ar0144/basic_calibration.py
- https://github.com/jaa-bah/AutonoBird/blob/81c3ffc1bd8aeb8a5b2be1b0b21800c4340c0576/scripts/ar0144/guided_calibration.py

This is the most directly useful public implementation found so far because the code explicitly identifies the hardware as a **Waveshare AR0144 2MP Stereo USB Camera**.

Observed implementation assumptions:

- The module typically appears as a single USB camera.
- Stereo transport is expected to be a horizontally stitched side-by-side frame.
- The frame is split at the midpoint.
- Calibration uses paired checkerboard observations, per-eye calibration, stereo calibration, rectification, and a classical disparity/depth path.

Important bring-up warning found in this implementation:

> OpenCV `VideoCapture.set()` requests for MJPG `2560x720` may silently fall back to another mode on some UVC driver/firmware combinations.

The implementation therefore attempts to pre-configure the V4L2 device with `v4l2-ctl` before opening it through OpenCV.

Evidence value: **THIRD-PARTY MODULE EVIDENCE** plus a high-value host integration warning.

Bividi consequence: #4 must verify the **negotiated/read-back mode**, not merely whether an API call requesting `2560x720 MJPG` returned success.

### 3. `abrar-nazib/StereoLite`

Reference:

- https://github.com/abrar-nazib/StereoLite/blob/80f0bed308fb7c77bffbf7bb53f1a53559596a87/model/scripts/capture_interactive.py

Observed implementation assumptions:

- AR0144 capture from `/dev/video2`.
- MJPG `2560x720`.
- Captured data is handled as a stereo pair and stored as separate left/right images.

Evidence value: **CORROBORATING PATTERN**.

This supports the same general host-side topology seen above, but it is not enough to prove implementation independence from other public examples.

### 4. `nxp-imx-support/meta-imx8mp-isp-ar0144`

Reference:

- https://github.com/nxp-imx-support/meta-imx8mp-isp-ar0144/blob/LF6.1.22_P22/README

NXP's reference layer enables AR0144 on i.MX8MP through MIPI CSI and demonstrates a GStreamer path using:

```text
YUY2
1280x800
```

Evidence value: **SENSOR-LEVEL REFERENCE**.

This is useful context for the AR0144 sensor's image geometry and host processing, but it is **not evidence for the Waveshare stereo USB transport**. The Waveshare product includes additional stereo synchronization/bridge/UVC behavior that this reference does not exercise.

## Cross-repository pattern

Several public implementations converge on the following host-side model:

```text
AR0144-L       AR0144-R
    \             /
     \           /
      synchronized pair
             |
             v
       camera bridge
             |
             v
       one UVC stream
       MJPG 2560x720
             |
             v
   +-------------------+
   | 1280x720 |1280x720|
   |  assumed | assumed|
   |   left   |  right |
   +-------------------+
```

This is now a **strong working hypothesis**, not a Bividi fact.

## Hypotheses carried into characterization

### H1 — Single UVC stream

Expected: the reference camera exposes one useful video stream containing both eyes.

Verification in #4:

- enumerate all UVC interfaces/nodes;
- record VID/PID/product strings;
- map interfaces/endpoints to host video nodes.

### H2 — MJPG `2560x720` is the main full-width 30 FPS mode

Expected: the practical full-width mode is MJPG `2560x720`, commonly requested at 30 FPS by external projects.

Verification in #4:

- inspect UVC descriptors / `v4l2-ctl --list-formats-ext`;
- request the mode;
- read back the actual negotiated format, resolution, and interval;
- capture enough frames to distinguish advertised capability from stable behavior.

Do not infer mode success from `VideoCapture.set()` alone.

### H3 — Horizontal side-by-side packing

Expected: a `2560x720` payload contains two `1280x720` images separated at the vertical midpoint.

Verification in #5:

- capture an unmodified decoded frame;
- inspect geometry at the midpoint;
- physically occlude one lens at a time to establish mapping;
- verify the layout in every supported mode Bividi intends to use.

### H4 — Left half is the physical left camera

External code commonly labels the first half as `left`, but this must remain untrusted until a physical occlusion test proves the orientation.

Verification in #5:

```text
cover physical L lens -> identify affected frame half
cover physical R lens -> identify affected frame half
```

### H5 — OpenCV mode negotiation can silently fall back

Expected risk: requested mode and actual mode may differ.

Verification in #4:

- enumerate first;
- configure through the native host interface where appropriate;
- read back negotiated mode;
- log the first captured frame's actual dimensions/format;
- compare OpenCV-reported values against V4L2/descriptor evidence.

### H6 — Sensor geometry and USB geometry are different layers

NXP sensor-level examples use `1280x800`, while several Waveshare/USB examples use `1280x720` per eye inside a `2560x720` host frame.

Possible explanations include cropping, scaling, firmware mode selection, or different module configuration. No explanation is accepted until measured/documented evidence supports it.

This distinction must remain explicit:

```text
AR0144 sensor capability
        !=
Waveshare module output mode
        !=
Bividi selected operating mode
```

## Calibration lessons worth carrying forward

Public implementations consistently use conventional stereo geometry rather than vendor-specific calibration machinery:

```text
capture paired target views
-> per-eye intrinsic calibration
-> stereo extrinsic calibration
-> stereoRectify / remap
-> disparity
-> depth
```

Useful lessons, not constants to copy:

- calibration must use paired observations from the same stereo frame;
- the printed target's actual square size must be measured;
- calibration should span positions, orientations, and distances;
- rectification quality must be measured after calibration;
- nominal 52 mm baseline must not replace estimated/measured extrinsics;
- third-party calibration matrices or matcher parameters are not transferable to our camera.

## What we deliberately do not copy

Bividi will not copy from external projects:

- device index such as `/dev/video2`;
- hard-coded left/right ordering;
- calibration matrices;
- SGBM/BM parameters;
- assumed focal length;
- assumed stable FPS;
- claims that a common timestamp assigned after capture proves exposure synchronization;
- ROS/OpenCV-specific types as the public Bividi interface.

## Pre-hardware work enabled by this audit

The camera does **not** need to be physically present for these tasks:

1. maintain this external-evidence ledger as new references are found;
2. refine #4 into an enumeration/negotiation measurement protocol;
3. refine #5 into a deterministic packing/orientation test protocol;
4. define what raw text artifacts from USB/UVC enumeration should be retained;
5. prepare platform-neutral acceptance criteria for capture status and mode read-back;
6. study calibration quality metrics and failure criteria before acquiring calibration data;
7. keep sensor-level AR0144 information separate from Waveshare bridge behavior.

Hardware arrival starts measurement. It does not start research.

## Current conclusion

The public evidence is strong enough to prioritize a likely path:

```text
single UVC
-> MJPG 2560x720
-> horizontal side-by-side
-> split into two 1280x720 views
```

But Bividi will continue to label this **external prior evidence** until #4/#5 reproduce it on our own device.
