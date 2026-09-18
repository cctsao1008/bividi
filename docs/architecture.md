# Bividi Architecture

Status: **platform-independent sensor core — Issues #35, #38, and #11**

Bividi turns host-visible sensor data into normalized observation streams while keeping operating-system mechanics, device-family quirks, and downstream interpretation outside the core.

## 1. Core rules

```text
platform != device
device transport != sensor topology
sensor topology != build configuration
transport payload != host observation
raw observation != derived product
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
  SensorCapabilities
  SensorObservation
        ↓
Derived pipelines / consumers
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

A backend may discover devices and own platform-specific capture handles, buffers, callbacks, and error translation.

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

The first concrete native normalization adapter is the DECXIN `DecodedFrame -> SensorObservation` bridge. It preserves raw IMU counts/timestamp evidence and does not invent SI scaling before an explicit calibration exists.

## 5. Runtime capability discovery

Sensor topology is a runtime fact.

The native `SensorCapabilities` contract describes:

```text
camera streams[]
stereo_pairs[]
image representation
camera modality
IMU present / absent
audio present / absent
host/device/exposure/IMU timing support
hardware synchronization support
trigger modes[]
```

Image representation and physical modality are separate concepts. For example, an infrared camera may expose a monochrome host representation.

Stereo relationships are explicit. The presence of two camera streams alone does not authorize Bividi to infer a stereo pair. A declared stereo pair also does not by itself imply physical left/right ordering, calibration quality, or a measured synchronization bound.

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
OpenCV ownership types
ROS / MCAP schemas
```

The core may depend only on normalized Bividi domain types and interfaces.

`ImageView` remains non-owning. `FrameLease` carries backing-buffer lifetime independently of image geometry.

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

## 8. Native observation boundary

Issue #11 defines the native consumer contract in:

```text
include/bividi/capabilities.hpp
include/bividi/observation.hpp
docs/observation-interface.md
```

`SensorObservation` carries source/evidence state, sequence/continuity state, explicit clock domains, calibration/configuration identity, camera observations, and IMU observations.

Raw camera/IMU observations stay distinct from downstream disparity/depth/XYZ/VIO products. Engineering preview structs used by viewer/web are intentionally smaller and do not define the stable observation ABI.

The legacy Python host/capability facade remains useful for control, experiments, and reference behavior, but the native C++ contract is authoritative for production runtime observation semantics.

## 9. Timing and synchronization

Device timing, host timing, and replay scheduling are different domains.

Bividi preserves distinctions equivalent to:

```text
host receive monotonic time
device/exposure time
IMU sample time
replay scheduling time
sequence continuity / epoch
```

There is deliberately no single generic `timestamp` field in the native contract.

Host arrival time must not silently replace a device/exposure timestamp when the latter exists. Replay scheduling time must not overwrite original producer timestamps. Finite-width raw timestamp evidence may be retained alongside extended device time for rollover/audit work.

## 10. Calibration and derived pipelines

Calibration identities are opaque references carried by observations. The corresponding versioned #8/#47 artifacts remain separate.

Derived products such as:

```text
disparity
metric depth
XYZ / point cloud
VIO pose / velocity
future SLAM outputs
```

are separate typed results. They may reference the source observation and calibration/configuration identity, but they are not captured sensor evidence.

## 11. Scope

Bividi owns:

- platform acquisition boundaries;
- device normalization;
- runtime capability discovery;
- timing/synchronization semantics;
- calibration/configuration identity;
- capture validity/continuity state;
- normalized observation delivery.

Bividi does not own:

- semantic truth;
- object ontology;
- application decision authority;
- SLAM/VIO policy;
- LSMM reasoning;
- a generic multimodal framework.

## 12. Device-specific documentation

Device-family and SKU facts belong under focused documentation such as:

```text
docs/devices/
docs/protocols/
docs/characterization/
```

Vendor claims, documented protocol behavior, and measured specimen behavior must remain distinguishable.

The README and this architecture document describe durable boundaries rather than tracking every changing implementation milestone.
