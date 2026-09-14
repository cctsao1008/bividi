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
  👀 Cameras &nbsp;·&nbsp; 🧭 IMU &nbsp;·&nbsp; ⏱️ Timing &nbsp;·&nbsp; 🔬 Validate
</p>

Bividi is a sensor-acquisition system for turning device-specific camera and inertial data into clean, synchronized observation streams.

Its core is deliberately platform-independent: operating-system mechanics stay in platform backends, device-family quirks stay in device adapters, and the actual sensor topology is discovered at runtime.

> **Cute sensor. Serious timing.** Complexity stays below the core boundary; downstream consumers see compact, predictable observations.

---

## 🧭 Architecture

```text
Physical SensorRig
        ↓
Platform Backend
        ↓
Device Adapter
        ↓
Capability Discovery
        ↓
Bividi Core
  platform-independent
        ↓
Observation Streams
        ↓
LSMM · Robotics · CV / ML · Recorder
```

The architectural roles are intentionally small:

- **Platform Backend** — owns operating-system and host-API mechanics such as Windows, Linux, macOS, UVC, V4L2, AVFoundation, or an optional vendor SDK.
- **Device Adapter** — owns device-family protocol details, packing, metadata, timestamp behavior, channel ordering, and control quirks.
- **Capability Discovery** — describes the sensor rig that is actually present: camera streams, declared stereo pairs, modality/encoding, optional IMU/audio, timing, synchronization, and trigger support.
- **Bividi Core** — consumes normalized device information without depending on an OS API, vendor SDK type, camera model, lens SKU, or fixed mono/stereo topology.
- **Observation Streams** — expose normalized sensor data and context to downstream consumers.

The key boundaries are:

```text
platform != device
device transport != sensor topology
sensor topology != build configuration
transport payload != host observation
```

## 🧩 Runtime capability model

Bividi does not assume that every rig is the same.

A rig may expose:

```text
one or more camera streams
zero or more declared stereo pairs
RGB / MONO / RAW encoding
visible / infrared / unknown modality
optional IMU
optional audio
device / exposure timing
hardware synchronization
software / hardware / command trigger
```

Camera relationships are explicit. Two streams do not become a stereo pair merely because both exist.

## ⚙️ Build-time vs runtime

Bividi follows one durable rule:

> **Build/install enables available backends; runtime discovers the attached sensor topology.**

Build-time configuration may decide whether an optional backend or vendor SDK is available. It must not decide whether the current rig is mono or stereo, RGB or IR, or whether IMU/audio is present.

The production camera hot path is native **C++17/CMake**, with OpenCV used as an optional image-processing/view layer rather than as the Bividi core data model. Python remains the reference/oracle and characterization layer.

## 🔬 Engineering principles

Bividi is built around four durable priorities:

- **Precise** — preserve timing, sequence continuity, synchronization state, and calibration context.
- **Efficient** — avoid unnecessary copying, conversion, and buffering in the acquisition path.
- **Stable** — make malformed input, drops, disconnects, recovery, and long-run behavior explicit and diagnosable.
- **Simple** — keep the core boundary small and keep platform/device-specific behavior outside it.

These priorities apply regardless of which operating system or camera module is used underneath.

## 📐 Scope

Bividi owns the path from physical sensor acquisition to normalized observations.

```text
Bividi owns
───────────
platform acquisition boundary
device normalization
runtime capability discovery
synchronization / timing semantics
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

- [`docs/architecture.md`](docs/architecture.md) — core boundary and dependency direction
- [`docs/host.md`](docs/host.md) — host API and backend/adapter boundary
- [`docs/native-runtime.md`](docs/native-runtime.md) — C++/OpenCV runtime and Python reference split
- [`docs/viewer.md`](docs/viewer.md) — local OpenCV diagnostic viewer
- [`docs/web-ui.md`](docs/web-ui.md) — browser engineering console and HTTP/MJPEG boundary
- [`docs/README.md`](docs/README.md) — documentation map
- [`docs/devices/`](docs/devices/) — device-specific facts and integration notes
- [`docs/protocols/`](docs/protocols/) — transport and protocol details
- [`docs/characterization/`](docs/characterization/) — measurement methods and results

## 📏 Documentation principle

> **README explains the system. Issues explain the journey. Code proves the current state.**

README stays focused on durable project identity, scope, and architecture. Device choices, implementation progress, experiments, temporary constraints, and changing measurements belong in Issues and focused documentation. Code, configuration, tests, and characterization remain the authoritative proof of implemented behavior.
