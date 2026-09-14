<p align="center">
  <img src="assets/bividi.svg" width="240" alt="Bividi mascot">
</p>

<h1 align="center">Bividi</h1>

<p align="center">
  <strong>Stereo-Inertial Sensor Research</strong>
</p>

<p align="center">
  <strong>Two eyes. One clock. Clean observations.</strong>
</p>

<p align="center">
  <em>Capture precisely. Synchronize correctly. Normalize simply.</em>
</p>

<p align="center">
  👀 Stereo &nbsp;·&nbsp; 🧭 IMU &nbsp;·&nbsp; ⏱️ Timing &nbsp;·&nbsp; 🔬 Validate
</p>

Bividi is a host-side stereo-inertial sensing project for acquiring camera and IMU data accurately, normalizing device-specific transport details, and delivering a compact observation stream to LSMM, robotics, CV/ML, recording, and other consumers.

The current engineering focus is intentionally narrow: **make the sensor path precise, efficient, stable, and easy to trust**.

> **Cute sensor. Serious timing.** Vendor quirks stay below the adapter boundary; consumers should see clean stereo images, IMU samples, timing, calibration identity, and capture status.

---

## 🧭 Architecture

```text
Physical SensorRig
      ↓
Capture Backend
      ↓
Device Adapter
      ↓
Observation Stream
      ↓
┌──────────┬──────────┬──────────┬──────────┐
│   LSMM   │ Robotics │  CV / ML │ Recorder │
└──────────┴──────────┴──────────┴──────────┘
```

The boundary is deliberately small:

- **SensorRig** — the physical cameras, IMU, trigger/sync wiring, and calibration relationship.
- **Capture Backend** — UVC, OS camera APIs, vendor SDKs, file/replay sources, or future transports.
- **Device Adapter** — owns packing, metadata decoding, timestamp quirks, left/right extraction, and device controls.
- **Observation Stream** — exposes normalized sensor information without leaking vendor transport layout.

Bividi does not try to become a semantic reasoning framework. It stops at clean sensor observations; interpretation belongs downstream.

## 📷 Reference sensor

The current reference hardware direction is the **DECXIN AR0234 stereo + ICM-42688-P IMU** module. The purchased unit is the **100° SKU**.

Current vendor-supplied facts and host-side material indicate:

```text
2 × AR0234 global-shutter cameras
1920 × 1200 per eye
USB 3 transport
4000 × 1200 composite transport mode
MJPEG up to 60 fps / YUYV up to 30 fps
ICM-42688-P IMU at about 600 Hz
external trigger / strobe / frame-sync signals
vendor timestamp + IMU metadata encoding
```

The exact H/V/D field of view for the purchased 100° lens, specimen calibration, and real synchronization performance remain hardware-verification items.

Durable device notes:

- [`docs/devices/decxin-ar0234.md`](docs/devices/decxin-ar0234.md)
- [`docs/protocols/decxin-nori-timestamp-imu.md`](docs/protocols/decxin-nori-timestamp-imu.md)
- [`docs/devices/decxin-nori-sdk-surface.md`](docs/devices/decxin-nori-sdk-surface.md)

Hardware evaluation is tracked in [#32](https://github.com/cctsao1008/bividi/issues/32).

## ⏱️ Transport and timing

The DECXIN/Nori material gives Bividi a useful first real adapter target:

```text
4000 × 1200 transport frame

┌──────────────┬────────────────────┬────────────────────┐
│ metadata     │ left camera        │ right camera       │
│ 160 px       │ 1920 × 1200        │ 1920 × 1200        │
└──────────────┴────────────────────┴────────────────────┘
```

The vendor decoder material describes exposure start/end timestamps plus bundled IMU samples. The device timestamps are 32-bit microsecond counters, so rollover handling is part of the adapter rather than something consumers should need to know about.

The rule is simple:

```text
transport payload != host observation
```

The adapter absorbs the transport oddities. The host-facing stream stays clean.

## 🧰 Host engineering

The current host foundation is hardware-independent and dependency-light. Discovery/status/mode inspection already exists; the real sensor path is now being implemented under [#35](https://github.com/cctsao1008/bividi/issues/35).

Current CLI:

```bash
bividi about
bividi sources
bividi status <source-id>
bividi modes <source-id>
bividi --json sources
```

The next sensor-side work is deliberately staged:

```text
vendor sample + decoder material
        ↓
offline DECXIN decoder
        ↓
golden tests
        ↓
inspection CLI
        ↓
live Nori/UVC backend
        ↓
long-run capture / timing / recovery validation
```

Offline and live paths should share the same decoding and normalization logic.

## 🔬 Engineering priorities

Bividi optimizes for four things before adding more features:

- **Precise** — preserve device timing, exposure timing, IMU cadence, sequence continuity, and calibration identity.
- **Efficient** — avoid unnecessary frame copies, conversions, and unbounded buffering.
- **Stable** — expose malformed frames, drops, duplicates, disconnects, and recovery state explicitly.
- **Simple** — keep the host-facing model small and keep device-specific behavior in the adapter.

A pretty depth map is not useful if the underlying capture timing is ambiguous or the stream quietly drops data.

## 🧪 Validation

The first useful tests are sensor tests, not perception demos.

```text
frame continuity
IMU continuity
exposure timestamp continuity
32-bit timestamp rollover
left/right extraction
malformed-payload rejection
sustained FPS / jitter
bounded memory use
disconnect / reconnect behavior
trigger / sync measurement
```

Vendor specifications remain vendor specifications until the physical unit is measured. Characterization results belong under [`docs/characterization/`](docs/characterization/).

## 🧱 Repository shape

```text
src/                    host core and adapters
tools/                  inspection / capture / validation tools
tests/                  deterministic and hardware integration tests
docs/devices/           durable device facts
docs/protocols/         device protocol notes
docs/characterization/  measurement plans and results
config/devices/          measured device profiles / quirks
calibration/             calibration metadata and references
data/                    artifact conventions; not a media dump
```

Large vendor SDK archives and raw captures do not belong in normal Git history. Source material stays outside the repository; durable engineering conclusions, code, tests, and measurements belong here.

## 📚 Documentation

- [`docs/architecture.md`](docs/architecture.md) — system boundary and dependency direction
- [`docs/host.md`](docs/host.md) — hardware-independent host layer
- [`docs/README.md`](docs/README.md) — documentation map
- [`docs/visual-identity.md`](docs/visual-identity.md) — mascot and README tone
- [`docs/devices/`](docs/devices/) — device facts and SDK surface
- [`docs/protocols/`](docs/protocols/) — transport/timestamp/IMU protocol notes
- [`docs/characterization/`](docs/characterization/) — measurement protocols and results

## 📏 Documentation principle

> **README explains the system. Issues explain the journey. Code proves the current state.**

README and durable documentation explain the sensor architecture, device boundaries, timing semantics, host interfaces, and verified hardware facts. GitHub Issues preserve experiments, implementation progress, unknowns, and measurement history. Code, configuration, tests, and characterization results remain the authoritative proof of implemented behavior.
