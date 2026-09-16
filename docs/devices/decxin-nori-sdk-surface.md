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

Bividi isolates this dependency in an optional capture backend rather than making the base host package depend on the vendor SDK.

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

The Linux header describes the returned frame as a buffer from an internal queue and `FreeFrameBuff` as returning that frame to the internal pool. `FRAME_BUFFER_DATA` contains at least:

```text
PixFormat       VIDEO_INFO
Frame_Time      timeval32 { int32 sec, int32 usec }
pBufAddr        void*
buff_Length     uint32
buff_Offset     uint32
index           uint32
buffer          vendor-exposed v4l2_buffer state
```

The supplied `grab_image` sample follows the lifecycle:

```text
GetFrameBuff(...)
    ↓
use pBufAddr / PixFormat / buffer metadata / buff_Length
    ↓
FreeFrameBuff(...)
```

For continuity accounting, Bividi uses Linux `buffer.sequence` as the frame sequence. `FRAME_BUFFER_DATA::index` is treated as a buffer-pool index and is preserved separately; using it as a frame number would create false duplicate/drop results as buffers are recycled.

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

Bividi uses Windows `u_FrameNum` as the normalized frame sequence.

The Windows API documentation also states that every successfully acquired frame resource must be returned through `Nori_Xvision_FreeFrameBuff` after use.

This maps directly onto Bividi's native lifetime boundary:

```text
vendor frame pointer
        ↓
FrameLease(deleter = Nori_Xvision_FreeFrameBuff)
        +
frame bytes / sequence / host receive time
        ↓
transport normalization / DECXIN decode
        ↓
last vendor-buffer lease released
        ↓
Nori_Xvision_FreeFrameBuff
```

The vendor frame structs and the Linux/Windows ABI differences remain private to backend translation units. They do not appear in Bividi's public capture/core headers.

The first live backend uses this pull-buffer path rather than callback acquisition because ownership and backpressure are explicit and directly testable. Callback mode remains optional until profiling or device behavior demonstrates a need for it.

### Transport-format consequence

The SDK returns transport-dependent payloads, not necessarily the top-down BGR24 image required by the DECXIN encoded-pixel decoder.

The Linux sample explicitly handles:

```text
VIDEO_MEDIA_TYPE_MJPG
VIDEO_MEDIA_TYPE_YUYV
```

The Windows public surface includes MJPEG/YUY2 and SDK-decoded BGR24 variants. The Windows documentation for the BGR24 conversion modes describes the image memory as **bottom-up**. Bividi's `ImageView` uses a positive row stride and the DECXIN decoder addresses the encoded image top-down, so the Windows bottom-up representation must not be passed into the decoder unchanged.

Implemented normalization rule:

```text
vendor transport frame
        ↓
explicit transport normalization
        ↓
top-down BGR24 4000×1200
        ↓
DECXIN encoded-pixel decoder
```

For correctness-first bring-up, an explicit normalization copy is acceptable. For asynchronous viewer/web use, Bividi intentionally requests owned normalized output so retaining the latest preview does not pin a vendor SDK buffer. Optimization remains evidence-driven after live profiling.

## Trigger surface

Both supplied SDK revisions define trigger modes including:

```text
NON_TRIIGER_MODE
SOFTWARE_TRIIGER_MODE
HARDWARE_TRIGGER_MODE
COMMAND_TRIGGER_MODE
```

Both expose:

```text
Nori_Xvision_GetTriggerMode
Nori_Xvision_SetTriggerMode
```

Software-trigger frequency exists on both supplied revisions but the API name differs:

```text
Linux 10.00.06:
  Nori_Xvision_GetSoftTriggerFrequency
  Nori_Xvision_SetSoftTriggerFrequency

Windows 10.00.10:
  Nori_Xvision_GetTriggerFrequency
  Nori_Xvision_SetTriggerFrequency
```

The Chinese SDK comments describe the frequency unit as Hz; the English comments also warn that the value may be implementation-specific. This must therefore be measured on the delivered firmware before Bividi treats it as a stable normalized control.

The SDK also exposes command-trigger operations where one call requests one frame after selecting command-trigger mode.

The current Bividi session normalizes trigger-mode selection only. It does **not** yet manufacture software-trigger frequency or command-trigger events. Selecting a non-free-run mode can therefore legitimately stop continuous output until the appropriate trigger source is configured/exercised.

The presence of generic SDK support does not prove that every trigger mode is enabled by the purchased DECXIN AR0234 module/firmware; this must be verified on the device.

## Shutter / gain control surface

Both supplied SDK revisions expose sensor-level shutter and gain controls:

```text
Nori_Xvision_GetSensorShutter
Nori_Xvision_SetSensorShutter
Nori_Xvision_GetSensorGain
Nori_Xvision_SetSensorGain
```

The supplied documentation describes sensor shutter in microseconds. `GetSensorGain` returns current/minimum/maximum/step values, so Bividi treats the UI gain request as a requested multiplier and quantizes it to the SDK-reported range/step rather than assuming an arbitrary continuous scale.

Before changing shutter/gain, both SDKs require manual exposure mode, but the platform API differs.

Windows 10.00.10 uses camera-terminal control:

```text
Nori_Xvision_GetCameraTerminalControl(CameraControl_Exposure, ...)
Nori_Xvision_SetCameraTerminalControl(
    CameraControl_Exposure,
    current_value,
    CameraControl_Flags_Manual)
```

Linux 10.00.06 uses processing-unit/V4L2 control:

```text
Nori_Xvision_GetProcessingUnitControl(V4L2_CID_EXPOSURE_AUTO, ...)
Nori_Xvision_SetProcessingUnitControl(
    V4L2_CID_EXPOSURE_AUTO,
    V4L2_EXPOSURE_MANUAL)
```

These platform-specific prerequisites remain inside the Nori backend. The public session surface only speaks in normalized shutter/gain requests.

Configured/read-back shutter must not be conflated with DECXIN embedded exposure timing. Bividi therefore keeps:

```text
control domain:
  shutter_us

embedded device timing domain:
  ES
  EE
  EE - ES
```

as distinct evidence.

## Other RAW / image-control surface

Both SDK archives contain a `device_raw_output_control` example. The SDK surface also includes examples for:

- white-balance gain control;
- 3A control;
- processing-unit controls;
- mirror/flip controls on Windows;
- GPIO control;
- user data / ESN controls;
- firmware-related operations.

These are capabilities of the vendor SDK surface, not requirements for Bividi's normalized observation API.

Bividi initially uses only the minimal subset needed for reliable capture, timing, identification, and required engineering controls.

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
 shared capture/session boundary
            ↓
 viewer / web / calibration / recording
```

Offline fixtures and live capture share the same DECXIN decode/normalization logic. The SDK is responsible for acquiring frames and operating device controls, not for defining Bividi's public observation model.

## Bring-up checks after hardware arrival

Verify, in order:

1. device enumeration and stable identity;
2. reported modes versus the approval sheet;
3. 4000×1200 MJPEG/YUYV/BGR24 live behavior;
4. presence and location of the encoded timestamp/IMU region;
5. frame numbering and SDK `Frame_Time` behavior;
6. embedded ES/EE timestamp continuity;
7. IMU cadence and continuity;
8. free-run/software/hardware/command trigger behavior on this exact firmware;
9. shutter/gain readback and response;
10. disconnect/reconnect behavior;
11. sustained capture, drop rate, jitter, and memory stability.

Firmware-update APIs are intentionally out of the initial Bividi bring-up path unless a verified backup/recovery procedure is established.

Related: #32, #35.
