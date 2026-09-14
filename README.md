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

Bividi is a host-side stereo-inertial sensor system for turning device-specific camera and IMU data into a clean, synchronized observation stream.

Its purpose is deliberately narrow: acquire sensor data accurately, preserve timing and calibration context, isolate hardware-specific quirks, and expose a small stable boundary to downstream consumers.

> **Cute sensor. Serious timing.** Complexity stays below the adapter boundary; the host-facing stream stays compact and predictable.

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
LSMM · Robotics · CV / ML · Recorder
```

The architectural roles are intentionally small:

- **SensorRig** — the physical cameras, optional inertial sensor, synchronization path, and calibration relationship.
- **Capture Backend** — obtains device-visible sensor data through an OS API, vendor SDK, replay source, or another transport.
- **Device Adapter** — absorbs device-specific packing, metadata, timestamp behavior, channel ordering, and control details.
- **Observation Stream** — presents normalized stereo, inertial, timing, calibration, and capture-status information without exposing transport quirks.

The key boundary is:

```text
transport payload != host observation
```

A transport format may change. A device may change. The host-facing observation boundary should not need to change with them.

## ⏱️ Sensor contract

Bividi keeps the sensor contract practical rather than broad:

```text
stereo image data
IMU samples when present
device and host timing
sequence / continuity
calibration identity
capture / synchronization status
```

The project does not assign semantic meaning to these observations. LSMM, robotics, CV/ML, and other consumers may interpret them downstream.

## 🔬 Engineering principles

Bividi is built around four durable priorities:

- **Precise** — preserve timing, sequence continuity, synchronization state, and calibration context.
- **Efficient** — avoid unnecessary copying, conversion, and buffering in the acquisition path.
- **Stable** — make malformed input, drops, disconnects, recovery, and long-run behavior explicit and diagnosable.
- **Simple** — keep the core boundary small and keep device-specific behavior inside adapters.

These priorities apply regardless of which stereo-inertial device is used underneath.

## 📐 Scope

Bividi owns the path from physical sensor acquisition to normalized observations.

```text
Bividi owns
───────────
acquisition
synchronization / timing semantics
device normalization
calibration identity
capture status / quality

Downstream owns
───────────────
semantic interpretation
perception policy
SLAM / VIO decisions
application behavior
```

This keeps Bividi useful to LSMM without coupling the sensor layer to LSMM internals.

## 📚 Documentation

- [`docs/architecture.md`](docs/architecture.md) — system boundary and dependency direction
- [`docs/host.md`](docs/host.md) — hardware-independent host layer
- [`docs/README.md`](docs/README.md) — documentation map
- [`docs/devices/`](docs/devices/) — device-specific facts and integration notes
- [`docs/protocols/`](docs/protocols/) — transport and protocol details
- [`docs/characterization/`](docs/characterization/) — measurement methods and results

## 📏 Documentation principle

> **README explains the system. Issues explain the journey. Code proves the current state.**

README stays focused on durable project identity, scope, and architecture. Device choices, implementation progress, experiments, temporary constraints, and changing measurements belong in Issues and focused documentation. Code, configuration, tests, and characterization remain the authoritative proof of implemented behavior.
