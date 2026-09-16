# Native Runtime

Status: **C++17/OpenCV runtime foundation, shared capture session, Nori pull-buffer acquisition boundary, and transport normalization implemented — physical AR0234 validation remains under Issue #35**

Bividi uses a native runtime for camera acquisition and hot image-path work, while Python remains the reference/oracle layer for protocol verification, characterization, and high-level tooling.

## Runtime stack

```text
C++17 + CMake
      ↓
Platform / vendor backend
      ↓
raw transport frame
      ↓
transport normalization
      ↓
Device Adapter / Decoder
      ↓
Bividi Core
      ↓
shared CaptureSession
      ↓
viewer / web / calibration / recording
```

The current active physical reference is stereo AR0234 + IMU, but the native core remains platform/device independent.

## Capture-buffer lifetime boundary

`ImageView` is deliberately non-owning. A live platform backend may receive a frame from a vendor-owned buffer pool whose lifetime ends only after an explicit release call.

The core capture boundary therefore carries ownership separately from image geometry:

```text
FrameLease
  owns/releases backing-buffer lifetime
       ↓
CapturedFrame
  FrameLease
  transport ImageView
  sequence
  host_receive_monotonic_ns
       ↓
Device Adapter / Decoder
```

This preserves zero-copy views without turning `ImageView` into a vendor-aware owning container. Copying a `CapturedFrame` shares the lease; the backing resource is released only after the final lease is destroyed.

Host receive time is explicitly a different clock domain from device/exposure/IMU timestamps. Device time is decoded later by the device adapter and must not be replaced by the host receive timestamp.

## Raw Nori transport versus normalized image

The Nori SDK may return compressed or packed transport payloads that are not honestly representable as an `ImageView`. Bividi therefore keeps a vendor-specific raw boundary below `CapturedFrame`:

```text
Nori_Xvision_GetFrameBuff
       ↓
nori::RawFrame
  FrameLease
  byte pointer / byte length
  actual VideoMode
  vendor sequence
  host monotonic receive time
  SDK timestamp representation
       ↓
normalize_to_bgr24()
       ↓
nori::NormalizedFrame
  CapturedFrame = top-down BGR24
  source-mode / SDK timing provenance
       ↓
decxin::Decoder::decode_frame(CapturedFrame)
```

`RawFrame` allows exactly one outstanding zero-copy vendor buffer in the first bring-up implementation. This mirrors the supplied vendor sample, keeps backpressure deterministic, and prevents accidental exhaustion of the SDK buffer pool while behavior is still being characterized.

The raw-frame lease also retains the private stream implementation. If the public stream object is destroyed while a raw frame is still in use, `VideoStop`, `DeviceVideoUnInit`, and SDK uninitialization are deferred until the final frame lease returns the buffer through `Nori_Xvision_FreeFrameBuff`.

### Transport normalization

The OpenCV-backed normalization layer is hardware-independent and does not require the vendor SDK to build or test.

Current behavior:

- top-down BGR24 can remain zero-copy;
- Windows-style bottom-up BGR24 is vertically normalized;
- YUYV/YUY2 is converted explicitly to BGR24;
- MJPEG is decoded explicitly and must match the advertised image geometry;
- malformed, truncated, unknown, or zero-sized transport data fails explicitly.

The normalized contract passed to the DECXIN encoded-pixel decoder is therefore:

```text
top-down BGR24
4000×1200 for the current DECXIN transport profile
positive row stride
explicit lifetime ownership
```

The 4000×1200 requirement itself remains owned by the DECXIN device decoder, not by the generic capture boundary.

## Shared capture session

Viewer and web applications no longer own separate synthetic state machines. They consume the same native capture-session model, which carries capture state/counters, FPS, controls, source identity, exposure timing, and IMU-rate status.

The synthetic source remains useful as a hardware-independent implementation of that path. A live source should replace the producer side of the session rather than create another UI-specific pipeline.

## Why C++ + OpenCV

The high-rate camera path is dominated by buffer movement, image decoding, color conversion, and image processing. These operations should stay in native code and use existing native libraries rather than per-pixel Python loops.

OpenCV is useful for image views and CV operations, but it is not the Bividi core schema. Core image data is represented with a small stride-aware `ImageView`; OpenCV wraps or produces that view only when needed.

```text
ImageView
  data
  width / height
  row_stride
  pixel format
       ↓ optional bridge
cv::Mat
```

OpenCV-owned decoded buffers are kept alive through `FrameLease`; downstream core types still contain no `cv::Mat`.

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
BIVIDI_WITH_NORI_SDK
BIVIDI_NORI_SDK_ROOT
BIVIDI_BUILD_VIEWER
BIVIDI_BUILD_WEB
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
3. Prefer views/ROIs over duplication where the transport is already usable.
4. Accept an explicit correctness-first normalization copy when compressed/oriented transport requires it.
5. Keep vendor packet decoding deterministic and small.
6. Profile live hardware before adding GPU/CUDA or more languages.
7. Keep platform/vendor APIs outside the Bividi core contract.
8. Keep UI code outside core and backend implementations.

## Current native targets

`bividi_core`
: dependency-light C++17 core containing the DECXIN/Nori device decoder, image/capture boundary types, and shared capture-session model.

`bividi_opencv`
: optional OpenCV `ImageView` bridge.

`bividi_nori_opencv`
: optional, hardware-independent MJPEG/YUYV/BGR24 → top-down BGR24 normalization layer.

`bividi_nori`
: optional vendor-SDK probe and pull-buffer stream backend, built only with `BIVIDI_WITH_NORI_SDK=ON` and a supplied SDK root/library.

`bividi-nori-probe`
: enumerates Nori devices, identity/version information, and advertised video modes.

`bividi-nori-grab`
: minimal pull-buffer bring-up CLI that starts a selected mode and reports raw frame sequence, byte length, host receive time, SDK timestamp representation, and actual returned format.

`bividi-viewer` / `bividi-web`
: engineering UIs using the shared session model. Their current producer is synthetic; the next live slice connects the Nori-normalized DECXIN path to that same session.

Hardware-independent tests cover DECXIN decoding/rollover, buffer lifetime, shared session behavior, the generic OpenCV bridge, Nori transport normalization, and viewer/web self-tests.

## Build

Without requiring OpenCV or the viewer:

```bash
cmake -S . -B build \
  -DBIVIDI_WITH_OPENCV=OFF \
  -DBIVIDI_BUILD_VIEWER=OFF \
  -DBIVIDI_BUILD_WEB=OFF
cmake --build build
ctest --test-dir build --output-on-failure
```

With OpenCV installed, the default configuration also builds the OpenCV bridge, transport normalizer, viewer, and web console:

```bash
cmake -S . -B build
cmake --build build
ctest --test-dir build --output-on-failure
```

With the supplied Nori SDK available:

```bash
cmake -S . -B build-nori \
  -DBIVIDI_WITH_NORI_SDK=ON \
  -DBIVIDI_NORI_SDK_ROOT=/path/to/Nori-sdk
cmake --build build-nori
```

The normal repository CI intentionally does not require vendor binaries or physical hardware.

## Continuous validation

`.github/workflows/native.yml` validates the native path on every push to `main` and on pull requests:

```text
Ubuntu   → C++17 core build + tests
Windows  → C++17 core build + tests
Ubuntu + libopencv-dev
         → core + OpenCV bridge + Nori transport normalization
           + viewer/web build/tests
```

The OpenCV job exercises MJPEG decode, YUYV conversion, bottom-up BGR24 normalization, malformed transport rejection, and the viewer/web self-tests without a camera.

## Next live vertical slice

The remaining connection is deliberately narrow:

```text
nori::Stream::next_frame()
        ↓
normalize_to_bgr24()
        ↓
decxin::Decoder::decode_frame(CapturedFrame)
        ↓
shared CaptureSession
        ↓
viewer / web / calibration capture
```

Physical hardware must still establish the real mode index, actual transport choice, camera A/B physical orientation, live timestamp behavior, frame continuity, trigger support, reconnect behavior, sustained throughput, and memory stability before Issue #35 can be closed.

Related: #35, #38, #40, #41.
