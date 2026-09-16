# Bividi Web UI

Status: **lightweight engineering console with synthetic and optional live Nori sources — Issues #35 / #42**

`bividi-web` is the browser-based engineering control surface for Bividi. It keeps the sensor hot path native while exposing low-rate status, controls, snapshots, and engineering previews over HTTP.

## Boundary

```text
Synthetic source / Live Nori backend
            ↓
      CaptureSession
            ↓
       bividi-web
     C++17 + OpenCV
            ↓
      HTTP / MJPEG
            ↓
        Browser
```

The web server does not call DECXIN/Nori, V4L2, Media Foundation, or other vendor/platform APIs directly. Live hardware control and preview use the same shared session/backend boundary as the local viewer.

## Sources

The default source is synthetic:

```bash
bividi-web
# equivalent to:
bividi-web --source synthetic
```

When built with the supplied Nori SDK, the server can use the live session:

```bash
bividi-web --source nori --device 0 --mode 0
```

Optional timeout and port selection:

```bash
bividi-web \
  --source nori \
  --device 0 \
  --mode 0 \
  --timeout-ms 2000 \
  --port 8080
```

Use `bividi-nori-probe` to establish the real device/mode index. Mode `0` in the examples is not a claim about the delivered AR0234 unit.

## Live preview path

For the Nori source:

```text
Nori pull buffer
      ↓
owned transport normalization
      ↓
DECXIN decode
      ↓
NoriCaptureSession
      ↓
latest StereoPreviewFrame
      ↓
resize / JPEG encode at request time
      ↓
HTTP snapshot / MJPEG
```

The browser preview is intentionally decoupled from acquisition fidelity. Live acquisition may run at the sensor transport resolution/rate while browser delivery remains a lower-rate engineering preview.

Current browser preview target:

```text
640 × 400
20 fps
JPEG / MJPEG
```

> Browser preview quality must never redefine the sensor acquisition contract.

The session retains an owned normalized frame for asynchronous preview, so browser clients do not pin the vendor capture-buffer pool.

## Routes

```text
GET  /
GET  /app.js
GET  /style.css
GET  /api/status
POST /api/capture/toggle
POST /api/trigger/cycle
POST /api/reconnect
POST /api/exposure?value=<us>
POST /api/gain?value=<x10>
GET  /stream/a.mjpg
GET  /stream/b.mjpg
GET  /snapshot/a.jpg
GET  /snapshot/b.jpg
```

`/api/status` reports:

- source and capture state;
- frame/drop/duplicate/out-of-order counters;
- nominal and measured acquisition FPS;
- browser preview geometry/rate;
- shutter/gain state;
- trigger mode;
- embedded exposure start/end timestamps;
- decoded IMU cadence;
- latest backend action/error text.

Configured shutter remains distinct from the embedded `EE - ES` timing interval.

## Controls

The browser controls submit requests through `CaptureSession`:

```text
Pause / Resume
Trigger-mode cycle
Reconnect
Exposure (microseconds)
Gain (x0.1 UI representation)
```

For the live Nori source, vendor calls are serialized on the session worker thread. The HTTP client threads do not call the SDK directly.

Trigger-mode selection alone does not generate hardware/command triggers. Software-trigger frequency and explicit command-trigger actions remain live-hardware follow-up items under #35; a non-free-run mode may therefore stop producing frames until a trigger source is configured.

## Frontend

The frontend is deliberately small:

```text
web/
├── index.html
├── app.js
└── style.css
```

There is no npm, React, Vue, bundler, or frontend package manager.

## Build

`bividi-web` requires OpenCV:

```text
core
imgproc
imgcodecs
```

Synthetic-capable build:

```bash
cmake -S . -B build -DBIVIDI_BUILD_WEB=ON
cmake --build build --config Release
```

To include the live Nori source:

```bash
cmake -S . -B build-nori \
  -DBIVIDI_BUILD_WEB=ON \
  -DBIVIDI_WITH_NORI_SDK=ON \
  -DBIVIDI_NORI_SDK_ROOT=/path/to/Nori-sdk
cmake --build build-nori --config Release
```

Default endpoint:

```text
http://127.0.0.1:8080
```

## Security posture

The default bind address is loopback only:

```text
127.0.0.1
```

Remote/LAN exposure requires an explicit override, for example:

```bash
bividi-web --listen 0.0.0.0
```

There is currently no authentication layer. Do not expose the engineering control surface to an untrusted network. A non-loopback bind prints a warning.

## Headless self-test

CI can validate the web path without opening a browser or persistent listener:

```bash
bividi-web --self-test
```

The test covers:

- synthetic status generation;
- control-state mutation;
- JPEG encoding for both previews;
- presence of the static HTML/CSS/JavaScript assets.

The live Nori session itself still requires the proprietary SDK at build time and the physical device for runtime validation.

## Relationship to HighGUI

```text
bividi-viewer  → local bring-up / diagnostic UI
bividi-web     → browser engineering console
```

Both consume the same `CaptureSession` boundary and neither is part of the final Bividi Core observation contract.

## Physical AR0234 validation

The software route to the browser is connected. Issue #35 still requires physical evidence for the delivered module: actual transport mode, camera A/B physical mapping, live timestamp semantics, sustained throughput/jitter, sequence continuity, trigger support, reconnect recovery, memory stability, and optics/firmware behavior.

Related: #35, #40, #41, #42.
