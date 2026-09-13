# USB / UVC Characterization Test Plan

Owner: Issue #4  
Status: pre-hardware protocol  
Last reviewed: 2026-09-14

## Objective

Determine the **actual host-visible contract** of the reference camera before writing a device backend.

The test must distinguish:

```text
requested mode
!= advertised mode
!= negotiated mode
!= stable captured behavior
```

External implementations suggest a single UVC stream and MJPG `2560x720`, but those remain hypotheses until this plan is executed on our device.

## Evidence to retain

Keep small text artifacts in Git where practical:

- USB tree / descriptor dump;
- UVC format and frame-interval listing;
- control listing;
- negotiated/read-back mode;
- host OS and tool versions;
- capture summary: requested mode, actual dimensions, actual FPS, drops/failures;
- hashes/metadata for any larger external capture artifacts.

A characterization session should include a timestamp/session label and host identity sufficient for reproduction.

## Linux protocol

### 1. Enumerate USB topology

```bash
lsusb
lsusb -t
v4l2-ctl --list-devices
```

Record:

- VID/PID;
- product/manufacturer strings;
- USB bus/port path;
- negotiated USB speed;
- every `/dev/video*` node associated with the device.

### 2. Dump descriptors and controls

After identifying VID/PID and video nodes:

```bash
lsusb -v -d <VID:PID>
v4l2-ctl --device=/dev/videoN --all
v4l2-ctl --device=/dev/videoN --list-formats-ext
v4l2-ctl --device=/dev/videoN --list-ctrls-menus
```

If a media graph exists:

```bash
media-ctl -p
```

### 3. Probe candidate mode

External prior evidence suggests:

```text
MJPG
2560x720
30 FPS
```

Do not assume support. First confirm that the descriptor advertises the mode.

If advertised, request it through the native V4L2 path:

```bash
v4l2-ctl \
  --device=/dev/videoN \
  --set-fmt-video=width=2560,height=720,pixelformat=MJPG
```

Then read back actual state:

```bash
v4l2-ctl --device=/dev/videoN --get-fmt-video
v4l2-ctl --device=/dev/videoN --get-parm
```

If frame interval must be set explicitly, record the exact command and read it back afterwards.

### 4. Capture without hiding negotiation

Use at least one native or transparent path before relying on OpenCV.

Candidate tools:

```text
v4l2-ctl
ffmpeg
GStreamer
```

Record:

- first decoded frame dimensions;
- requested/actual pixel format;
- timestamp behavior if exposed;
- short-run delivered FPS;
- read failures;
- duplicate/drop indications where observable.

### 5. OpenCV comparison

Only after native enumeration/negotiation is recorded, open the same node through OpenCV and compare:

```text
requested width/height/FourCC/FPS
vs
OpenCV read-back
vs
V4L2 read-back
vs
actual frame shape
```

This explicitly tests the external warning that `VideoCapture.set()` may silently fall back.

## Windows protocol

### 1. Enumerate device identity/topology

Record using a USB descriptor viewer and Windows device enumeration:

- VID/PID;
- product/manufacturer strings;
- USB speed;
- interface/endpoints where visible;
- camera device name(s).

Useful host evidence may include:

```powershell
Get-PnpDevice -Class Camera
Get-PnpDevice -Class Image
```

A USB tree/descriptor tool may provide the authoritative USB-side detail that DirectShow does not expose clearly.

### 2. Enumerate DirectShow modes

With FFmpeg available:

```powershell
ffmpeg -list_devices true -f dshow -i dummy
```

Then for the exact camera name:

```powershell
ffmpeg -f dshow -list_options true -i video="<camera name>"
```

Record every advertised format/resolution/frame-rate combination relevant to Bividi.

### 3. Candidate-mode capture

Request candidate modes explicitly and verify the resulting decoded frame geometry and observed frame rate.

The same evidence rule applies:

```text
request success != negotiated-mode proof
```

Where Windows APIs do not provide a clean read-back path, use independent evidence from the actual decoded frame and USB/DirectShow enumeration.

## Cross-platform comparison

If both Windows and Linux are available, compare:

- number of exposed video devices;
- advertised modes;
- default mode;
- control set;
- actual selected mode;
- delivered FPS;
- any backend-specific fallback.

Platform disagreement is evidence to preserve, not normalize away.

## Minimum session record

```text
session_id
host_os
host_version
tool_versions
usb_vid_pid
usb_speed
video_nodes_or_names
requested_mode
advertised_mode_present
negotiated_or_readback_mode
first_frame_shape
measured_fps_window
read_failures
notes
```

## Acceptance criteria for #4 execution

A characterization run is complete only when:

- the camera's USB identity and speed are recorded;
- every host-visible video node/interface is mapped;
- supported formats/resolutions/frame intervals are captured from the host interface;
- controls are enumerated;
- at least the selected Bividi mode has requested, read-back, and captured evidence;
- silent fallback can be detected;
- output is sufficient for #5 to reason about stereo packing without guessing.

## Output into #5

#4 should hand #5 an exact transport observation such as:

```text
node/device: ...
format: ...
width x height: ...
frame interval: ...
decoded frame shape: ...
```

It must **not** hand over an assumed left/right interpretation. That belongs to #5.
