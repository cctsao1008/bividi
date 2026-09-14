# Bividi Architecture

Status: **platform-independent sensor core — Issues #35 and #38**

Bividi turns host-visible sensor data into normalized observation streams while keeping operating-system mechanics, device-family quirks, and downstream interpretation outside the core.

## 1. Core rules

```text
platform != device
device transport != sensor topology
sensor topology != build configuration
transport payload != host observation
observation != meaning
```

The architecture is intentionally small. Bividi is a sensor subsystem, not a general perception ontology.

## 2. System boundary

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

Dependency direction is toward the core boundary. A downstream consumer must not need to know which operating system, SDK, packet layout, camera model, or lens SKU produced an observation.

## 3. Platform Backend

The platform backend owns host-API mechanics only.

Examples include:

```text
Windows   Media Foundation / UVC / optional vendor SDK
Linux     V4L2 / UVC / optional vendor SDK
macOS     AVFoundation / UVC
Replay    deterministic file-backed input
```

A backend may discover devices and eventually own platform-specific capture handles, buffers, callbacks, and error translation.

It must not define device-family semantics.

## 4. Device Adapter

A device adapter owns protocol/profile-specific behavior.

Typical responsibilities include:

- identifying whether the adapter supports a discovered device;
- decoding device-specific transport packing;
- extracting logical camera channels;
- decoding metadata and device timestamps;
- extending finite-width device clocks when required;
- interpreting trigger/control behavior;
- converting device-specific information into normalized capabilities and observations.

The adapter must not own operating-system policy.

## 5. Runtime capability discovery

Sensor topology is a runtime fact.

The compact core capability model can describe:

```text
camera streams[]
stereo_pairs[]
camera encoding
camera modality
IMU present / absent
audio present / absent
device timestamp support
exposure timestamp support
hardware synchronization support
trigger modes[]
```

Camera encoding and physical modality are separate concepts. For example, an infrared camera may expose a monochrome image representation.

Stereo relationships are explicit. The presence of two camera streams alone does not authorize Bividi to infer that they form a calibrated or synchronized stereo pair.

## 6. Bividi Core

The core is platform-independent.

It must not depend on:

```text
Windows / Linux / macOS APIs
Nori or another vendor SDK type
V4L2 / AVFoundation / Media Foundation objects
a particular USB packet layout
a fixed number of cameras
a fixed RGB / IR assumption
mandatory IMU or audio
a particular camera model or lens SKU
```

The core may depend only on normalized Bividi domain types and interfaces.

## 7. Build-time versus runtime

The rule is:

> **Build/install enables available backends; runtime discovers the attached sensor topology.**

Build/install configuration may enable optional dependencies such as a vendor SDK or native backend.

It must not be used to choose:

```text
mono vs stereo
RGB vs IR
IMU present vs absent
audio present vs absent
specific camera model
specific lens/SKU
```

Those are runtime device/capability facts.

## 8. Host/provider compatibility boundary

The current Python host facade predates this capability split and still exposes a stereo-oriented provider/mode API.

That compatibility surface remains usable while Issue #11 owns the final consumer observation-boundary freeze.

New code must not infer runtime topology from provider names or build flags. Providers expose normalized `SensorCapabilities` explicitly.

## 9. Timing and synchronization

Device timing and host timing are different domains.

Where available, Bividi preserves distinctions equivalent to:

```text
device timestamp
exposure start
exposure end
host receive / callback time
sequence continuity
synchronization status
```

Host arrival time must not silently replace a device/exposure timestamp when the latter exists.

## 10. Scope

Bividi owns:

- platform acquisition boundaries;
- device normalization;
- runtime capability discovery;
- timing/synchronization semantics;
- calibration identity;
- capture status and quality;
- normalized observation delivery.

Bividi does not own:

- semantic truth;
- object ontology;
- application decision authority;
- SLAM/VIO policy;
- LSMM reasoning;
- a generic multimodal framework.

## 11. Device-specific documentation

Device-family and SKU facts belong under focused documentation such as:

```text
docs/devices/
docs/protocols/
docs/characterization/
```

Vendor claims, documented protocol behavior, and measured specimen behavior must remain distinguishable.

The README and this architecture document should not track changing implementation progress or current-device development status.
