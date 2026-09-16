# DECXIN Nori_Xvision SDK Surface

Status: **vendor SDK/API inventory for Issue #35; exact module support still requires live verification**

This document records the host-facing SDK capabilities that are relevant to Bividi. It intentionally does not reproduce the vendor API manual or redistribute vendor binaries.

## Source basis

- Nori_Xvision Windows Development Kit User Guide `Ver.10.00.10`.
- Windows headers, libraries, and C++/C# samples from the supplied SDK archive.
- Nori_Xvision Linux Development Kit User Guide `V10.00.06`.
- Linux headers, libraries, Makefile, and C++ samples from the supplied SDK archive.

## Version / platform matrix

| Platform | Supplied SDK | Binary library coverage | Sample source |
| --- | --- | --- | --- |
| Windows | 10.00.10 | Win32 and Win64 DLL/import libraries | C++ and C# |
| Linux | 10.00.06 | x86, x64, ARM32, ARM64 shared libraries | C++ |

The Windows and Linux packages are different revisions; Bividi must not assume perfect API/behavior parity without checking the exact functions used.

## Binary dependency

The supplied SDK is not a fully open implementation.

Windows links against vendor binaries such as:

```text
Nori_Xvision_API.dll
Nori_Xvision_API_x64.dll
```

Linux links against:

```text
libNori_Xvision_Std.so
```

The Linux package supplies shared objects for x86, x64, ARM32, and ARM64.

Therefore:

```text
sample source available      = yes
public API headers available = yes
vendor binary dependency     = yes
fully open device protocol   = not established
```

Bividi should isolate this dependency in an optional capture backend rather than make the base host package depend on the vendor SDK.

## Frame acquisition surface

The SDK packages include examples for:

- device discovery/check;
- image grabbing;
- callback-based grabbing;
- asynchronous grabbing;
- OpenCV display in sample code;
- device/version printing.

The Linux frame structure contains a `Frame_Time` represented by a 32-bit seconds/microseconds timeval-like structure. The Windows frame structure exposes `Frame_Time` as `FILETIME` and also carries frame-number information in the vendor public types.

These SDK frame timestamps are host-SDK fields and must not be conflated with the Nori embedded exposure timestamps until live behavior is compared.

### Pull-buffer ABI and ownership

The supplied Linux and Windows SDK revisions expose the same conceptual pull-buffer operation but **not the same ABI**.

Linux 10.00.06 returns the vendor frame pointer directly:

```cpp
FRAME_BUFFER_DATA* Nori_Xvision_GetFrameBuff(
    uint32_t device_id,
    bool block,
    uint32_t timeout_ms);

uint32_t Nori_Xvision_FreeFrameBuff(
    uint32_t device_id,
    FRAME_BUFFER_DATA* frame);
```

The Linux header explicitly describes the returned frame as a buffer from an internal queue and `FreeFrameBuff` as returning that frame to the internal pool. `FRAME_BUFFER_DATA` contains at least:

```text
PixFormat       VIDEO_INFO
Frame_Time      timeval32 { int32 sec, int32 usec }
pBufAddr        void*
buff_Length     uint32
buff_Offset     uint32
index           uint32
v4l2_buffer     vendor-exposed V4L2 buffer state
```

The supplied `grab_image` sample follows the exact lifecycle:

```text
GetFrameBuff(...)
    ↓
use pBufAddr / PixFormat / index / buff_Length
    ↓
FreeFrameBuff(...)
```

Windows 10.00.10 instead returns a status code and fills an output frame pointer:

```cpp
uint32_t Nori_Xvision_GetFrameBuff(
    uint32_t device_id,
    FRAME_BUFFER_OUT** frame,
    uint32_t timeout_ms);

uint32_t Nori_Xvision_FreeFrameBuff(
    uint32_t device_id,
    FRAME_BUFFER_OUT* frame);
```

`FRAME_BUFFER_OUT` contains at least:

```text
pBufAddr      BYTE*
u_FrameLen    uint32
u_FrameNum    uint64
Frame_Time    FILETIME
PixFormat     fps / format / width / height
capacity      uint32
```

The Windows API documentation also states that every successfully acquired frame resource must be returned through `Nori_Xvision_FreeFrameBuff` after use.

This maps directly onto Bividi's native lifetime boundary:

```text
vendor frame pointer
        ↓
FrameLease(deleter = Nori_Xvision_FreeFrameBuff)
        +
frame bytes / sequence / host receive time
        ↓
DECXIN decode / downstream consumers
        ↓
last lease released
        ↓
Nori_Xvision_FreeFrameBuff
```

The vendor frame structs and the Linux/Windows ABI differences must remain private to platform-specific backend translation units. They must not appear in Bividi's public capture/core headers.

The first live backend should prefer this pull-buffer path over callback acquisition because ownership and backpressure are explicit and directly testable. Callback mode can remain optional until profiling or device behavior demonstrates a need for it.

### Transport-format consequence

The SDK returns transport-dependent payloads, not necessarily the top-down BGR24 image currently required by the DECXIN encoded-pixel decoder.

The Linux sample explicitly handles:

```text
VIDEO_MEDIA_TYPE_MJPG
VIDEO_MEDIA_TYPE_YUYV
```

and uses a vendor helper to convert YUYV to BGR24 when needed.

The Windows public surface includes MJPEG/YUY2 and SDK-decoded BGR24 variants. The Windows documentation for the BGR24 conversion modes describes the image memory as **bottom-up**. Bividi's current `ImageView` uses a positive row stride and assumes the decoded DECXIN geometry is addressed top-down, so the Windows bottom-up representation must not be passed into the decoder unchanged.

Initial implementation rule:

```text
vendor transport frame
        ↓
explicit transport normalization
        ↓
top-down BGR24 4000×1200
        ↓
DECXIN encoded-pixel decoder
```

For correctness-first bring-up, MJPEG → normal image decode or an explicit YUYV/BGR normalization copy is acceptable. Zero-copy optimization must wait until the actual live mode, buffer orientation, and decode cost are measured. Do not complicate the public image contract merely to preserve a premature zero-copy claim.

## Trigger surface

Both supplied SDK revisions define trigger modes including:

```text
NON_TRIIGER_MODE
SOFTWARE_TRIIGER_MODE
HARDWARE_TRIGGER_MODE
COMMAND_TRIGGER_MODE
```

The API exposes trigger get/set operations, including:

```text
Nori_Xvision_GetTriggerMode
Nori_Xvision_SetTriggerMode
```

The SDKs also include software-trigger and command-trigger examples. Windows additionally contains a trigger-control sample project.

The presence of generic SDK support does not prove that every mode is enabled by the purchased DECXIN AR0234 module/firmware; this must be verified on the device.

## RAW / image-control surface

Both SDK archives contain a `device_raw_output_control` example. The SDK surface also includes examples for:

- shutter/gain control;
- white-balance gain control;
- 3A control;
- processing-unit controls;
- mirror/flip controls on Windows;
- GPIO control;
- user data / ESN controls;
- firmware-related operations.

These are capabilities of the vendor SDK surface, not requirements for Bividi's normalized observation API.

Bividi should initially use only the minimal subset needed for reliable capture, timing, identification, and required controls.

## Device/version information

The vendor public structures expose version fields including:

```text
SDK version
Device type
ISP version
FPGA version
```

The supplied sample applications print FPGA version information. This is useful provenance for bring-up and characterization because behavior can be tied to a concrete firmware/software combination.

A first live `probe/info` command should capture at least:

```text
platform
SDK version
device identity / serial when available
device type
ISP version
FPGA version
USB-visible mode information
```

Do not assume VID/PID or product strings until measured on the purchased unit.

## IMU relationship

The generic Nori_Xvision SDK headers/samples inspected here do not expose an obvious high-level IMU stream API comparable to the separate timestamp/IMU decoder package.

Current working interpretation:

```text
video acquisition         → Nori SDK / UVC/backend
embedded timestamp + IMU → encoded image region decoder
```

This is an implementation hypothesis supported by the supplied package structure, not yet a claim about every live transport path. Live capture must confirm that the encoded region is present and stable in the modes Bividi uses.

## Recommended Bividi boundary

Keep the vendor SDK behind a narrow optional backend:

```text
Nori SDK / UVC / file fixture
            ↓
      capture backend
            ↓
 transport normalization
            ↓
 top-down BGR24 frame
            ↓
      DECXIN decoder
            ↓
 normalized sensor observation
```

Offline fixtures and live capture should share the same DECXIN decode/normalization path. The SDK should only be responsible for acquiring frames and operating device controls, not defining Bividi's public data model.

## Bring-up checks after hardware arrival

Verify, in order:

1. device enumeration and stable identity;
2. reported modes versus the approval sheet;
3. 4000×1200 MJPEG/YUYV live behavior;
4. presence and location of the encoded timestamp/IMU region;
5. frame numbering and SDK `Frame_Time` behavior;
6. embedded ES/EE timestamp continuity;
7. IMU cadence and continuity;
8. trigger-mode support on this exact firmware;
9. disconnect/reconnect behavior;
10. sustained capture, drop rate, jitter, and memory stability.

Firmware-update APIs are intentionally out of the initial Bividi bring-up path unless a verified backup/recovery procedure is established.

Related: #32, #35.