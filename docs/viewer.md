# Bividi Viewer

Status: **minimal engineering UI with synthetic and optional live Nori sources — Issues #35 / #41**

`bividi-viewer` is a small OpenCV HighGUI application for sensor bring-up, timing inspection, and basic control work. It is intentionally an engineering tool rather than a product GUI.

## Boundary

```text
Synthetic source / Live Nori backend
                ↓
          CaptureSession
                ↓
          bividi-viewer
          OpenCV HighGUI
```

The viewer does not call DECXIN/Nori, V4L2, Media Foundation, or other vendor/platform APIs directly. Live controls and frame delivery go through the shared session/backend boundary.

OpenCV/HighGUI stays outside the Bividi core data contract.

## Sources

The default source remains synthetic so UI behavior and CI self-tests do not require hardware:

```bash
bividi-viewer
# equivalent to:
bividi-viewer --source synthetic
```

When Bividi is built with the supplied Nori SDK, the same viewer can select the live session:

```bash
bividi-viewer --source nori --device 0 --mode 0
```

Optional acquisition timeout:

```bash
bividi-viewer --source nori --device 0 --mode 0 --timeout-ms 2000
```

The actual device and mode indices must be established with `bividi-nori-probe`; do not assume mode `0` is the desired 4000×1200 profile on the delivered unit.

## Live preview path

For the Nori source:

```text
Nori pull buffer
      ↓
transport normalization
      ↓
DECXIN decode
      ↓
NoriCaptureSession
      ↓
StereoPreviewFrame
 Camera A / Camera B
      ↓
viewer resize / letterbox
```

`StereoPreviewFrame` is only an engineering preview boundary. The viewer still does not own or define the final #11 sensor-observation contract.

The live status panel reports:

- capture state;
- measured FPS;
- frame/drop/duplicate/out-of-order counters;
- shutter/gain control state;
- trigger mode;
- embedded exposure start/end timestamps;
- IMU rate estimated from decoded timestamps;
- latest backend action/error text.

The live session uses owned normalized frames for asynchronous preview, so retaining the latest display frame does not pin a Nori SDK buffer from the capture pool.

## Controls

| Control | Synthetic source | Nori source |
|---|---|---|
| `SPACE` | pause / resume | `VideoStop` / `VideoStart` through the session worker |
| `T` | cycle trigger display | request Free Run / Software / Hardware / Command mode |
| `C` | reset counters/state | tear down and reconnect the Nori stream |
| `S` | save current canvas | save current live/status canvas |
| `Q` or `Esc` | quit | quit |
| Exposure trackbar | synthetic value | sensor shutter request in microseconds |
| Gain trackbar | synthetic value | sensor gain request, quantized to the SDK-reported multiplier range/step |

The live control path is serialized on the Nori session worker; the UI thread does not call vendor APIs directly.

Trigger-mode selection alone does not create a hardware/command trigger source. Software-trigger frequency and explicit command-trigger actions remain live-hardware follow-up work under #35, so non-free-run modes may legitimately stop producing frames until their trigger source is configured.

Snapshot files use the form:

```text
bividi_snapshot_<frame>.png
```

## Build

The viewer requires OpenCV components:

```text
core
highgui
imgproc
imgcodecs
```

Synthetic-capable build:

```bash
cmake -S . -B build -DBIVIDI_BUILD_VIEWER=ON
cmake --build build --config Release
```

To include the live Nori source, also provide the vendor SDK:

```bash
cmake -S . -B build-nori \
  -DBIVIDI_BUILD_VIEWER=ON \
  -DBIVIDI_WITH_NORI_SDK=ON \
  -DBIVIDI_NORI_SDK_ROOT=/path/to/Nori-sdk
cmake --build build-nori --config Release
```

On multi-config Windows generators the executable is typically under `build/Release/`.

## Headless self-test

CI and headless environments can validate the viewer without opening a window:

```bash
bividi-viewer --self-test
```

The self-test renders one synthetic stereo/status canvas and PNG-encodes it in memory. This validates the OpenCV processing/imgcodecs path without requiring a display server or vendor hardware.

## Physical AR0234 validation

The software path is now connected, but the following remain unverified until the actual unit is measured:

- which advertised mode corresponds to the intended 4000×1200 transport;
- actual MJPEG/YUYV/BGR24 behavior;
- camera A/B → physical left/right mapping;
- live ES/EE and IMU timestamp behavior;
- drop/duplicate/out-of-order behavior under sustained capture;
- exact trigger-mode support on the delivered firmware;
- reconnect/recovery behavior;
- optics and image quality.

The viewer must continue to label the channels Camera A/B until physical orientation is established.

Related: #35, #40, #41.
