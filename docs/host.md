# Bividi Host Reference Stack

Status: platform-independent host foundation — Issues #28 and #38

The Bividi host layer is the boundary shared by command-line tools, AI/robotics adapters, replay tooling, and future physical-camera backends.

## 1. Current structure

```text
CLI / MCP / ROS / future adapters
            ↓
        BividiHost
            ↓
   source-provider compatibility API
            ↓
     SensorCapabilities
```

The data-plane architecture underneath a physical provider is:

```text
Platform Backend
        ↓
Device Adapter
        ↓
Capability Discovery
        ↓
Bividi Core
```

`PlatformBackend` and `DeviceAdapter` are separate contracts. The first owns OS/API mechanics; the second owns device-family interpretation.

## 2. Runtime capability model

`SensorCapabilities` is platform-independent and dependency-light.

It can represent:

```text
camera streams[]
explicit stereo_pairs[]
RGB / MONO / RAW encoding
visible / infrared / unknown modality
optional IMU
optional audio
device / exposure timestamps
hardware sync
trigger modes
```

Topology is discovered at runtime. It is not selected by Makefile/CMake product switches.

## 3. Provider compatibility

`StereoSourceProvider` remains as the existing discovery/control compatibility surface while Issue #11 owns the final observation contract.

Providers now expose:

```text
get_capabilities(source_id)
```

so callers do not infer topology from source names or provider-specific conventions.

## 4. Platform and device separation

```text
Platform Backend
    owns:
      OS/API discovery
      platform handles
      platform errors

Device Adapter
    owns:
      device identification/profile
      packet/metadata decoding
      timestamp behavior
      device controls
      normalized capability discovery
```

This prevents a platform × device class explosion such as separate Windows/Linux/macOS implementations for every camera family.

## 5. Dependency policy

The base package intentionally remains standard-library-only.

Optional platform/vendor dependencies belong to optional backends. A backend being installed means only that the binary/package *can* use it; the attached rig and its sensor topology remain runtime facts.

## 6. Tests

Hardware-independent tests use Python's standard library:

```bash
python -m unittest discover -s tests
```

The capability tests cover mono, stereo+IMU, and multi-camera/auxiliary-modality rigs without importing any OS or vendor SDK.
