# Bividi Web UI

Status: **lightweight engineering console — Issue #42**

`bividi-web` is the browser-based engineering control surface for Bividi. It keeps the sensor hot path native while exposing low-rate status, controls, snapshots, and engineering previews over HTTP.

## Boundary

```text
AR0234 / Replay / Synthetic Source
            ↓
      Platform Backend
            ↓
       Device Adapter
            ↓
        Bividi Core
            ↓
       bividi-web
     C++17 + OpenCV
            ↓
      HTTP / MJPEG
            ↓
        Browser
```

The web server does not call DECXIN/Nori, V4L2, Media Foundation, or other vendor/platform APIs directly. Live hardware control must bind through the same backend/control boundary used by the rest of Bividi.

## Current source

The current implementation uses a **synthetic stereo source** so the HTTP/UI layer can be built and tested before the physical AR0234 path is connected.

The browser therefore must not be interpreted as a measurement of:

- AR0234 image quality;
- real frame rate or drop behavior;
- exposure/gain response;
- trigger latency;
- IMU timing;
- camera A/B physical left/right mapping.

Those remain live-hardware characterization tasks under #35.

## Preview vs acquisition

The browser preview is intentionally decoupled from acquisition fidelity.

Current synthetic preview:

```text
640 × 400
20 fps
JPEG / MJPEG
```

A future live backend may acquire the AR0234 transport at its full supported mode while separately producing a lower-rate preview for browser display.

> Browser preview quality must never redefine the sensor acquisition contract.

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

`/api/status` reports the current synthetic source state, frame/drop counters, preview geometry/rate, exposure timing, IMU nominal rate, trigger mode, and control values.

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

Build with:

```bash
cmake -S . -B build -DBIVIDI_BUILD_WEB=ON
cmake --build build --config Release
```

Run locally:

```bash
bividi-web
```

Default endpoint:

```text
http://127.0.0.1:8080
```

Custom port:

```bash
bividi-web --port 8081
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

The first slice has no authentication layer. Do not expose it to an untrusted network. A non-loopback bind prints a warning.

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

## Relationship to HighGUI

`bividi-viewer` from #41 remains the minimum-dependency diagnostic viewer.

```text
bividi-viewer  → local bring-up / diagnostic UI
bividi-web     → normal browser engineering console
```

Neither is part of the Bividi Core contract.

Related: #35, #40, #41, #42.
