# Nori Live Characterization Harness

Owner: Issue #35  
Reference device: DECXIN AR0234 stereo + ICM-42688-P  
Tool: `bividi-nori-characterize`  
Status: implementation available; physical AR0234 measurements pending

## Purpose

`bividi-nori-characterize` is the first repeatable measurement harness for the live Nori capture path. It runs the same transport-normalization and DECXIN decode path used by the live session, but records per-frame evidence instead of rendering UI previews.

```text
Nori SDK pull buffer
        ↓
RawFrame
        ↓
MJPEG / YUYV / BGR24 normalization
        ↓
DECXIN decoder
        ↓
per-frame trace + statistical summary
```

The tool is deliberately evidence-oriented. It does not rename camera A/B to left/right, does not infer synchronization quality from host arrival time, and does not subtract timestamps from unrelated clock epochs.

## Build

The executable is built only when both the supplied Nori SDK and the OpenCV-backed transport-normalization path are available:

```bash
cmake -S . -B build-nori \
  -DBIVIDI_WITH_NORI_SDK=ON \
  -DBIVIDI_NORI_SDK_ROOT=/path/to/Nori-sdk
cmake --build build-nori --config Release
```

Normal CI does not require vendor binaries. The characterizer translation unit is nevertheless compile-checked in hardware-independent CI so public API/C++ drift is caught on both Linux and Windows.

## Recommended bring-up sequence

First enumerate the delivered device and mode indexes:

```bash
bividi-nori-probe
```

Then perform a short smoke run before longer characterization:

```bash
bividi-nori-characterize \
  --device 0 \
  --mode 0 \
  --duration-s 60 \
  --warmup-frames 30 \
  --output-prefix ar0234_smoke
```

`device=0` and `mode=0` are examples only. Use the actual indexes reported by `bividi-nori-probe`.

Useful staged runs after the first successful capture are:

```text
60 s   → basic continuity / decode sanity
10 min → sustained FPS / jitter / intermittent anomalies
1 h    → long-run continuity evidence
```

Long-run process-memory growth and deliberate disconnect/reconnect fault injection are still separate #35 checks; the first harness does not claim to automate them yet.

## Stop conditions

The default measurement window is 60 seconds. An optional decoded-frame limit can also be supplied:

```bash
bividi-nori-characterize --duration-s 600 --frames 36000
```

When both are supplied, the run stops at whichever condition is reached first.

Other useful options:

```text
--warmup-frames N
--timeout-ms N
--output-prefix PATH
--no-trigger-config
```

The default stream setup requests free-run unless `--no-trigger-config` is used.

## Output artifacts

Each run writes two small artifacts:

```text
<PREFIX>.csv   per-frame trace
<PREFIX>.json  run summary + distributions + provenance
```

### CSV trace

The trace currently records:

- sample index and platform-normalized frame sequence;
- host monotonic receive timestamp and frame interval;
- SDK frame-time representation, converted to microseconds when representable, plus same-domain interval;
- raw and extended DECXIN exposure-start/exposure-end timestamps;
- exposure-start and exposure-end frame intervals;
- exposure duration (`EE - ES`);
- total/valid IMU sample counts;
- first/last valid IMU timestamp and cross-frame IMU gap where available;
- raw transport byte length;
- actual returned transport format and geometry;
- vendor buffer index/offset provenance where exposed.

### JSON summary

The summary records device/firmware provenance and distributions including:

```text
host frame interval
SDK frame-time interval
embedded ES interval
embedded EE interval
exposure duration
IMU sample interval
IMU cross-frame gap
valid IMU samples per frame
raw frame byte size
```

Each distribution includes:

```text
count
min
max
mean
p50
p95
p99
```

The summary also records:

- decoded/raw frame counts;
- timeout and decode-error counts;
- selected-mode versus returned-mode mismatch count;
- measured FPS;
- frame-sequence drops, duplicates, out-of-order observations, and 32-bit wrap events where applicable;
- SDK timestamp-encoding changes.

## Clock-domain rule

Three time sources may be visible during a run:

```text
host_receive_monotonic_ns
SDK Frame_Time
embedded DECXIN ES / EE / IMU time
```

They are not assumed to share an epoch.

The first characterization harness therefore compares **intervals inside each domain** and preserves the raw/extended values. It intentionally does not report an absolute `host - device` offset.

Camera↔IMU spatial/temporal calibration remains owned by #47, where Kalibr or another proven external solver can operate on a deliberately prepared dataset.

## Sequence semantics

The backend already normalizes the vendor sequence source differently by platform:

```text
Linux   → v4l2_buffer.sequence (32-bit semantics)
Windows → Nori u_FrameNum
```

The characterizer applies explicit 32-bit wrap handling on Linux and records drops/duplicates/out-of-order observations separately.

Sequence gaps are stronger evidence of capture discontinuity than comparing decoded-frame count with nominal FPS alone. The JSON still reports nominal expected frames over the measured host interval as contextual information, not as the authoritative drop counter.

## What this tool does not prove

A clean run does not by itself prove:

- physical camera A/B → left/right identity;
- optical calibration quality;
- hardware synchronization error in microseconds;
- camera↔IMU temporal offset;
- generic UVC behavior outside the Nori backend;
- disconnect/reconnect recovery;
- long-run process-memory stability.

Those remain explicit characterization/calibration tasks under #35, #8, and #47.

## Suggested evidence retention

For each physical test session, retain the JSON summary and CSV trace with a stable session name that identifies at least host/platform, device, mode, and run purpose. Large raw video captures should remain outside normal Git history; keep hashes or external references when needed.

Related: #35, #8, #10, #47.
