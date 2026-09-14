# Native Runtime

Status: **production data-path direction — Issue #40**

Bividi uses a native runtime for camera acquisition and hot image-path work, while Python remains the reference/oracle layer for protocol verification, characterization, and high-level tooling.

## Runtime stack

```text
C++17 + CMake
      ↓
Platform Backend
      ↓
Device Adapter / Decoder
      ↓
Bividi Core
      ↓
optional OpenCV views / processing
```

The current active physical reference is stereo AR0234 + IMU, but the native core remains platform/device independent.

## Why C++ + OpenCV

The high-rate camera path is dominated by buffer movement, image decoding, color conversion, and image processing. These operations should stay in native code and use existing native libraries rather than per-pixel Python loops.

OpenCV is useful for image views and CV operations, but it is not the Bividi core schema. Core image data is represented with a small stride-aware `ImageView`; OpenCV wraps that view only when needed.

```text
ImageView
  data
  width / height
  row_stride
  pixel format
       ↓ optional zero-copy bridge
cv::Mat
```

The zero-copy bridge borrows the source buffer. Buffer lifetime remains owned by the capture/backend layer.

## Python role

The existing Python implementation remains intentionally useful:

- DECXIN/Nori reference decoder;
- golden-vector oracle;
- characterization scripts;
- analysis and plotting;
- optional high-level inspection tooling.

Native and Python decoders should agree on the same source-derived golden vectors. Python is not required to sit in the production frame hot path.

## Build-time versus runtime

CMake controls which native capabilities are compiled and available, for example:

```text
BIVIDI_WITH_OPENCV
future vendor-SDK/backend options
BIVIDI_BUILD_TESTS
```

It does **not** select the attached sensor topology.

```text
mono / stereo
RGB / MONO / IR
IMU present / absent
audio present / absent
camera model / SKU
```

Those remain runtime-discovered device capabilities.

## Performance rules

1. Avoid unnecessary full-frame copies.
2. Preserve buffer stride and ownership explicitly.
3. Prefer views/ROIs over duplication.
4. Keep vendor packet decoding deterministic and small.
5. Profile live hardware before adding GPU/CUDA or more languages.
6. Keep platform/vendor APIs outside the Bividi core contract.

## Current native targets

`bividi_core`
: dependency-light C++17 core containing the platform-independent DECXIN/Nori decoder and image-view types.

`bividi_opencv`
: optional OpenCV bridge built only when OpenCV is available.

`bividi_native_tests`
: hardware-independent golden-vector and rollover tests.

`bividi_opencv_tests`
: validates that a stride-aware `ImageView` becomes a borrowed `cv::Mat` header without copying and that unsupported pixel formats are rejected explicitly.

## Build

Without requiring OpenCV:

```bash
cmake -S . -B build -DBIVIDI_WITH_OPENCV=OFF
cmake --build build
ctest --test-dir build --output-on-failure
```

With OpenCV installed, the default configuration attempts to build the OpenCV bridge:

```bash
cmake -S . -B build
cmake --build build
ctest --test-dir build --output-on-failure
```

## Continuous validation

`.github/workflows/native.yml` validates the native path on every push to `main` and on pull requests:

```text
Ubuntu   → C++17 core build + tests
Windows  → C++17 core build + tests
Ubuntu + libopencv-dev
         → core + OpenCV bridge build + zero-copy bridge tests
```

The first CI run for Issue #40 completed successfully across all three jobs. This gives the OpenCV bridge a real compile/link/test check instead of treating it as an unverified optional header path.

Live camera acquisition remains intentionally outside this checkpoint; it belongs to the hardware/backend phase after the reference device is available.

Related: #35, #38, #40.
