# AR0234 Host / USB Characterization Plan

Owner: Issue #35  
Reference device: DECXIN AR0234 stereo + ICM-42688-P  
Status: live-hardware plan

## Objective

Determine the **actual host-visible contract** of the delivered AR0234 module on each supported host path before treating vendor declarations as implemented behavior.

Keep these distinct:

```text
vendor-declared mode
!= host-advertised mode
!= requested mode
!= negotiated/read-back mode
!= stable captured behavior
```

The vendor documentation currently declares, among other modes:

```text
4000 × 1200 @ 60 fps MJPEG
4000 × 1200 @ 30 fps YUYV
```

Those values remain declarations until the delivered unit is measured.

## Evidence to retain

For each characterization session record small, reviewable artifacts where practical:

- host OS/version and tool versions;
- USB identity, speed, product/manufacturer strings, serial behavior;
- host-visible video/audio nodes or device names;
- advertised formats/resolutions/frame intervals;
- controls and trigger-related surfaces exposed by the chosen backend;
- requested and read-back mode;
- actual decoded frame dimensions and format;
- sustained FPS window;
- drops, duplicates, out-of-order observations, read failures, and reconnect behavior;
- hashes/metadata for larger external captures.

A session should have a stable identifier and enough context to reproduce it.

## Linux path

Start with native UVC/V4L2 evidence before adding higher-level wrappers:

```bash
lsusb
lsusb -t
v4l2-ctl --list-devices
v4l2-ctl --device=/dev/videoN --all
v4l2-ctl --device=/dev/videoN --list-formats-ext
v4l2-ctl --device=/dev/videoN --list-ctrls-menus
```

If a media graph exists:

```bash
media-ctl -p
```

Record VID/PID, USB speed, all associated nodes, every relevant advertised mode, and actual read-back state after requesting the target mode.

The optional Nori Linux SDK may be evaluated separately, but SDK behavior must not be used to hide what the underlying host interface actually exposes.

## Windows path

Record device identity/topology and enumerate camera modes using native/transparent tooling before relying on application wrappers.

Useful evidence may include:

```powershell
Get-PnpDevice -Class Camera
Get-PnpDevice -Class Image
```

When FFmpeg DirectShow enumeration is available:

```powershell
ffmpeg -list_devices true -f dshow -i dummy
ffmpeg -f dshow -list_options true -i video="<camera name>"
```

The Nori Windows SDK may provide additional device controls. Treat those as a separate backend surface, not as proof that generic UVC exposes the same controls.

## macOS path

Vendor material declares UVC compatibility on macOS, but no Nori macOS SDK has been established in the project sources.

Characterization should therefore focus on the native UVC/AVFoundation-visible device and modes. Do not assume vendor-specific trigger/control parity with Windows/Linux.

## Cross-platform comparison

Compare at least:

- device enumeration identity;
- number of video/audio interfaces;
- supported modes;
- default/negotiated mode;
- control set;
- delivered FPS;
- frame dimensions and format;
- timestamp availability;
- reconnect behavior.

Platform disagreement is evidence to preserve, not normalize away.

## Runtime stability

For the mode selected for Bividi, measure:

- sustained FPS;
- frame-number continuity where available;
- duplicate/out-of-order frames;
- timestamp continuity;
- memory growth over a long run;
- disconnect/reconnect behavior;
- explicit error state on malformed or failed capture.

## Minimum session record

```text
session_id
host_os
host_version
backend
tool_versions
usb_vid_pid
usb_speed
video_nodes_or_names
audio_nodes_or_names
requested_mode
advertised_mode_present
negotiated_or_readback_mode
first_frame_shape
measured_fps_window
drops_or_duplicates
read_failures
reconnect_result
notes
```

## Acceptance criteria

The live host characterization slice of #35 is complete only when:

- the delivered AR0234 device identity and USB speed are recorded;
- host-visible interfaces are mapped;
- target formats/resolutions/frame intervals are enumerated and tested;
- requested vs actual mode is distinguishable;
- sustained capture and recovery behavior are measured;
- results are sufficient to connect the live backend to the existing platform-independent DECXIN decoder without inventing transport behavior.
