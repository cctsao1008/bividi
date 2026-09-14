# Bividi Viewer

Status: **minimal engineering UI — Issue #41**

`bividi-viewer` is a small OpenCV HighGUI application for sensor bring-up, timing inspection, and basic control work. It is intentionally an engineering tool rather than a product GUI.

## Boundary

```text
Platform Backend / Replay / Synthetic Source
                ↓
        Device Adapter / Core
                ↓
          bividi-viewer
          OpenCV HighGUI
```

The viewer does not call DECXIN/Nori, V4L2, Media Foundation, or other vendor/platform APIs directly. Live controls will be bound through the backend/control boundary when the AR0234 hardware path is connected.

OpenCV/HighGUI stays outside the Bividi core data contract.

## Current source

The first implementation uses a **synthetic stereo source** so that UI behavior can be developed and tested before physical hardware arrives.

The current preview therefore does **not** represent measured AR0234 image quality, timing, exposure, gain, IMU behavior, drops, or trigger behavior. The status panel labels the source explicitly as synthetic.

The synthetic path exists to validate:

- two-camera preview layout;
- status overlay and FPS accounting;
- control-surface behavior;
- OpenCV HighGUI integration;
- snapshot encoding;
- a future source/backend handoff without changing the viewer itself.

## Controls

| Control | Action |
|---|---|
| `SPACE` | pause / resume synthetic capture |
| `T` | cycle Free Run / Software / Hardware / Command trigger display |
| `C` | synthetic reconnect/reset |
| `S` | save the current viewer canvas as a PNG snapshot |
| `Q` or `Esc` | quit |
| Exposure trackbar | change synthetic exposure value |
| Gain trackbar | change synthetic gain value |

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

With OpenCV development files installed:

```bash
cmake -S . -B build -DBIVIDI_BUILD_VIEWER=ON
cmake --build build --config Release
```

Run interactively:

```bash
./build/bividi-viewer
```

On multi-config Windows generators the executable is typically under `build/Release/`.

## Headless self-test

CI and headless environments can validate the viewer without opening a window:

```bash
bividi-viewer --self-test
```

The self-test renders one synthetic stereo/status canvas and PNG-encodes it in memory. This validates the OpenCV processing/imgcodecs path without requiring a display server.

## Live AR0234 handoff

When the reference hardware is available, the intended change is at the source/control boundary:

```text
Synthetic source                 Live platform backend
       ↓                                  ↓
viewer state / observations  ← same viewer surface → device controls
```

The live backend should provide the same normalized camera/timing/status data already defined by Bividi rather than teaching the viewer DECXIN transport details.

Physical camera A/B → left/right mapping must remain unclaimed until characterized on the actual device.

Related: #35, #40, #41.
